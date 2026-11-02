"""
notifier.py — Alertes WhatsApp via Twilio
=========================================
Envoie le message d'alerte du premier refus de chaque cause racine (le
regroupement est fait par causes.py). Principes :
- jamais bloquant : l'envoi se fait dans un fil à part, le moteur n'attend pas ;
- jamais fatal : une panne de Twilio est journalisée et enregistrée (statut
  "failed"), elle ne touche ni les verdicts ni les actions ;
- garde-fou : au plus `notify_max_per_hour` envois par heure (statut "throttled"
  au-delà) pour qu'un incident ne produise ni déluge de messages ni facture ;
- sans identifiants Twilio, le message est quand même enregistré (statut
  "disabled") : le tableau de bord montre ce qui AURAIT été envoyé ;
- le jeton Twilio et l'identifiant du compte n'apparaissent jamais dans les
  logs ni dans l'historique (les textes d'erreur sont expurgés).

Limite de WhatsApp à connaître : sur le sandbox Twilio (et en général), un
message libre n'est livré que dans les 24 h qui suivent le dernier message
reçu de ton numéro ; au-delà il faut un modèle de message approuvé. Renvoie
« join <code> » au sandbox pour rouvrir la fenêtre.
"""

import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Callable

logger = logging.getLogger("moteur")

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
MAX_BODY = 1500


def _warn(msg: str) -> None:
    logger.warning(json.dumps(msg))


def _info(msg: str) -> None:
    logger.info(json.dumps(msg))


def _whatsapp(number: str) -> str:
    number = number.strip()
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


class WhatsAppNotifier:
    def __init__(self, cfg, on_result: Callable | None = None, http_post: Callable | None = None,
                 clock: Callable | None = None, sync: bool = False):
        """
        on_result(group_id, cause_key, status, message, services, error, provider_sid)
        est appelé une fois par alerte, avec status = disabled | throttled | sent | failed.
        """
        self.cfg = cfg
        self.on_result = on_result
        self._post = http_post or self._default_post
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sync = sync
        self._sent: list[datetime] = []
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    @property
    def configured(self) -> bool:
        c = self.cfg
        return bool(c.twilio_account_sid and c.twilio_auth_token and c.twilio_from and c.notify_to)

    @staticmethod
    def _default_post(url: str, data: dict, auth: tuple, timeout: int):
        import requests  # importé ici : inutile pour les tests
        r = requests.post(url, data=data, auth=auth, timeout=timeout)
        try:
            body = r.json()
        except ValueError:
            body = {}
        return r.status_code, body

    # ------------------------------------------------------------------
    def submit(self, message: str, group_id: str, cause_key: str, services: list[str]) -> str:
        """Demande l'envoi d'une alerte. Retourne tout de suite : disabled | throttled | queued."""
        if not self.configured:
            self._report(group_id, cause_key, "disabled", message, services, None, None)
            return "disabled"
        with self._lock:
            now = self._clock()
            self._sent = [t for t in self._sent if now - t < timedelta(hours=1)]
            if len(self._sent) >= self.cfg.notify_max_per_hour:
                throttled = True
            else:
                throttled = False
                self._sent.append(now)
        if throttled:
            _warn(f"Alerte WhatsApp non envoyée : plus de {self.cfg.notify_max_per_hour} par heure "
                  f"(groupe {group_id})")
            self._report(group_id, cause_key, "throttled", message, services, None, None)
            return "throttled"
        if self._sync:
            self._deliver(message, group_id, cause_key, services)
        else:
            t = threading.Thread(target=self._deliver, args=(message, group_id, cause_key, services),
                                 daemon=True)
            self._threads.append(t)
            t.start()
        return "queued"

    def wait(self, timeout: float = 5.0) -> None:
        """Attend la fin des envois en cours (appelé à l'arrêt du moteur)."""
        for t in list(self._threads):
            t.join(timeout)
        self._threads = [t for t in self._threads if t.is_alive()]

    # ------------------------------------------------------------------
    def _redact(self, text: str) -> str:
        for secret in (self.cfg.twilio_auth_token, self.cfg.twilio_account_sid):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _deliver(self, message: str, group_id: str, cause_key: str, services: list[str]) -> None:
        c = self.cfg
        status, error, sid = "failed", None, None
        try:
            code, body = self._post(
                TWILIO_URL.format(sid=c.twilio_account_sid),
                {"From": _whatsapp(c.twilio_from), "To": _whatsapp(c.notify_to),
                 "Body": message[:MAX_BODY]},
                (c.twilio_account_sid, c.twilio_auth_token), 5)
            if code in (200, 201):
                status, sid = "sent", body.get("sid")
            else:
                detail = body.get("message") or "réponse sans détail"
                error = self._redact(f"HTTP {code} (code Twilio {body.get('code', '?')}) : {detail}")
        except Exception as e:
            error = self._redact(f"{type(e).__name__}: {e}")
        if status == "sent":
            _info(f"Alerte WhatsApp envoyée (groupe {group_id})")
        else:
            _warn(f"Alerte WhatsApp en échec (groupe {group_id}) : {error}")
        self._report(group_id, cause_key, status, message, services, error, sid)

    def _report(self, *args) -> None:
        if self.on_result is None:
            return
        try:
            self.on_result(*args)
        except Exception as e:   # l'enregistrement ne doit jamais faire échouer l'alerte
            _warn(f"Alerte WhatsApp : enregistrement impossible ({type(e).__name__})")
