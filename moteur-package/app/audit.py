"""
audit.py — Historique durable des verdicts et des notifications (Postgres)
=========================================================================
Chaque verdict (ALLOW comme DENY) et chaque notification est enregistré dans le
schéma `moteur_schema`, avec un rôle qui ne peut qu'INSERER et LIRE ces deux
tables (créé par scripts/setup_audit_db.sh). Les enregistrements ne sont jamais
modifiés ni supprimés par le moteur.

L'enregistrement ne doit JAMAIS gêner les décisions :
- si la base est injoignable, les lignes attendent dans une file mémoire
  (500 au maximum, les plus anciennes sont perdues au-delà) et on réessaie
  toutes les 30 s, sans bloquer le moteur à chaque verdict ;
- une ligne refusée par la base (erreur de données) est abandonnée au lieu de
  bloquer toutes les suivantes ;
- toute exception est avalée et journalisée une seule fois par panne.
"""

import collections
import json
import logging
import re
import threading
from datetime import datetime, timezone, timedelta
from typing import Callable

logger = logging.getLogger("moteur")

RETRY_AFTER_S = 30
MAX_PENDING = 500
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _warn(msg: str) -> None:
    logger.warning(json.dumps(msg))


def _info(msg: str) -> None:
    logger.info(json.dumps(msg))


def _ts(value) -> datetime | None:
    """Horodatage ISO -> datetime (None si illisible : jamais d'erreur côté base)."""
    try:
        ts = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


class AuditStore:
    def __init__(self, cfg, connect: Callable | None = None, clock: Callable | None = None):
        if not _IDENT.match(cfg.audit_schema):
            raise ValueError(f"nom de schéma invalide : {cfg.audit_schema!r}")
        self.cfg = cfg
        self._connect = connect or self._default_connect
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._pending: collections.deque = collections.deque(maxlen=MAX_PENDING)
        self._lock = threading.Lock()
        self._retry_at: datetime | None = None
        self._outage_warned = False
        self._overflow_warned = False
        schema = cfg.audit_schema
        self._sql_verdict = (
            f"INSERT INTO {schema}.verdicts (proposal_ts, verdict_ts, mode, action, target, "
            f"verdict, incident_id, attempt, invariants_violated, justification, execution, "
            f"proposal, evidence, alerts, cause_key, cause_group) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::text[], %s, %s::jsonb, %s::jsonb, "
            f"%s::jsonb, %s::jsonb, %s, %s)")
        self._sql_notification = (
            f"INSERT INTO {schema}.notifications (group_id, cause_key, channel, status, "
            f"message, services, error, provider_sid) "
            f"VALUES (%s, %s, %s, %s, %s, %s::text[], %s, %s)")

    @property
    def configured(self) -> bool:
        return bool(self.cfg.audit_db_user and self.cfg.audit_db_password)

    def _default_connect(self):
        import psycopg2  # importé ici : inutile pour les tests
        c = self.cfg
        return psycopg2.connect(
            host=c.db_host, port=c.db_port, dbname=c.db_name,
            user=c.audit_db_user, password=c.audit_db_password,
            connect_timeout=c.db_timeout_s,
            options=f"-c statement_timeout={c.db_timeout_s * 1000}")

    # ------------------------------------------------------------------
    def record_verdict(self, verdict: dict, cause_key: str | None = None,
                       cause_group: str | None = None) -> None:
        if not self.configured:
            return
        p = verdict.get("proposal", {})
        inc = verdict.get("incident", {}) or {}
        dump = lambda x: json.dumps(x, default=str)
        self._enqueue(self._sql_verdict, (
            _ts(p.get("timestamp")), _ts(verdict.get("timestamp")), verdict.get("mode"),
            p.get("action"), p.get("target"), verdict.get("verdict"),
            inc.get("incident_id"), inc.get("attempt"), list(verdict.get("invariant_violated", [])),
            verdict.get("justification"), dump(verdict.get("execution")), dump(p),
            dump(verdict.get("evidence")), dump(verdict.get("alerts", [])),
            cause_key, cause_group))

    def record_notification(self, group_id: str, cause_key: str, status: str, message: str,
                            services: list[str], error: str | None = None,
                            provider_sid: str | None = None) -> None:
        if not self.configured:
            return
        self._enqueue(self._sql_notification, (
            group_id, cause_key, "whatsapp", status, message, list(services), error, provider_sid))

    # ------------------------------------------------------------------
    def _enqueue(self, sql: str, params: tuple) -> None:
        with self._lock:
            if len(self._pending) == MAX_PENDING and not self._overflow_warned:
                self._overflow_warned = True
                _warn(f"Historique : file d'attente pleine ({MAX_PENDING}), les plus anciennes "
                      f"lignes sont perdues tant que la base est injoignable")
            self._pending.append((sql, params))
        self.flush()

    def pending(self) -> int:
        return len(self._pending)

    def flush(self) -> bool:
        """Écrit les lignes en attente. True si tout est écrit (ou rien à écrire)."""
        with self._lock:
            if not self._pending:
                return True
            if self._retry_at is not None and self._clock() < self._retry_at:
                return False
            try:
                conn = self._connect()
            except Exception as e:
                self._failed(e)
                return False
            try:
                cur = conn.cursor()
                while self._pending:
                    sql, params = self._pending[0]
                    try:
                        cur.execute(sql, params)
                        conn.commit()
                    except Exception as e:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        if getattr(e, "pgcode", None):
                            # La base a refusé CETTE ligne (donnée invalide) : on l'abandonne
                            # pour ne pas bloquer toutes les suivantes.
                            self._pending.popleft()
                            _warn(f"Historique : ligne refusée par la base et abandonnée "
                                  f"({getattr(e, 'pgcode', '?')}) : {str(e)[:160]}")
                            continue
                        self._failed(e)
                        return False
                    self._pending.popleft()
                if self._outage_warned:
                    _info("Historique : base de nouveau joignable, enregistrement repris")
                self._outage_warned = False
                self._overflow_warned = False
                self._retry_at = None
                return True
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def _failed(self, e: Exception) -> None:
        self._retry_at = self._clock() + timedelta(seconds=RETRY_AFTER_S)
        if not self._outage_warned:
            self._outage_warned = True
            _warn(f"Historique : base injoignable ({type(e).__name__}: {str(e)[:160]}). "
                  f"Les verdicts attendent en mémoire, nouvel essai dans {RETRY_AFTER_S} s.")
