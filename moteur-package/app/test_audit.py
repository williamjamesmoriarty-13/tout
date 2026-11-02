"""Tests de l'historique durable (faux Postgres). Lancer : python3 test_audit.py"""
import io
import json
import logging
import threading
from datetime import datetime, timezone, timedelta

import audit as a
import moteur as m

OK = True


def check(label, got, want):
    global OK
    good = got == want
    OK &= good
    print(("OK  " if good else "FAIL"), label, "->", got if not good else "")


NOW = datetime(2026, 10, 19, 6, 0, 0, tzinfo=timezone.utc)
CFG = m.Config(audit_db_user="moteur_audit", audit_db_password="s3cret-audit")


class PgError(Exception):
    """Erreur renvoyée par le serveur (a un pgcode), comme psycopg2.DataError."""
    def __init__(self, pgcode, msg="invalid input"): super().__init__(msg); self.pgcode = pgcode


class FakeDb:
    def __init__(self):
        self.rows, self.connects, self.conns = [], 0, []
        self.connect_error = None        # exception levée par connect()
        self.exec_errors = {}            # n° d'insertion -> exception
        self.attempts = 0
        self._lock = threading.Lock()


class FakeCursor:
    def __init__(self, db): self.db = db
    def execute(self, sql, params):
        with self.db._lock:
            self.db.attempts += 1
            err = self.db.exec_errors.get(self.db.attempts)
            if err: raise err
            self.db.rows.append((sql, params))


class FakeConn:
    def __init__(self, db): self.db, self.closed = db, False
    def cursor(self): return FakeCursor(self.db)
    def commit(self): pass
    def rollback(self): pass
    def close(self): self.closed = True


def store(db, clock=None, cfg=CFG):
    def connect():
        db.connects += 1
        if db.connect_error: raise db.connect_error
        c = FakeConn(db); db.conns.append(c); return c
    return a.AuditStore(cfg, connect=connect, clock=clock or (lambda: NOW))


def verdict(action="Restart", target="student-service", decision="DENY", n=1):
    return {"timestamp": NOW.isoformat(), "mode": "dry-run", "verdict": decision,
            "proposal": {"timestamp": (NOW - timedelta(seconds=2)).isoformat(), "action": action,
                         "target": target, "details": {"attempt": n}},
            "incident": {"incident_id": "i1", "attempt": n, "max_attempts": 2},
            "invariant_violated": ["invariant6_cause_racine"] if decision == "DENY" else [],
            "justification": "refusé", "execution": {"executed": False, "result": "skipped"},
            "evidence": {"invariant6_cause_racine": {"causes_racines": ["postgres"]}}, "alerts": []}


# --- non configuré : rien ne se passe ---
db = FakeDb()
s = store(db, cfg=m.Config())
s.record_verdict(verdict(), "cause:x", "g1"); s.record_notification("g1", "cause:x", "sent", "m", [])
check("non configuré : aucune connexion, rien en attente", (db.connects, s.pending(), s.configured), (0, 0, False))

# --- enregistrement d'un verdict ---
db = FakeDb(); s = store(db)
s.record_verdict(verdict(), "cause:postgres", "cause:postgres|1")
sql, p = db.rows[0]
check("écrit dans le bon schéma et la bonne table", "INSERT INTO moteur_schema.verdicts" in sql, True)
check("autant de paramètres que de colonnes", sql.count("%s"), len(p))
check("horodatages convertis, champs principaux", (p[0], p[1], p[2], p[3], p[4], p[5]),
      (NOW - timedelta(seconds=2), NOW, "dry-run", "Restart", "student-service", "DENY"))
check("incident, tentative, invariants violés", (p[6], p[7], p[8]), ("i1", 1, ["invariant6_cause_racine"]))
check("exécution, proposition, preuves : du JSON relisible",
      (json.loads(p[10])["result"], json.loads(p[11])["target"], json.loads(p[12])["invariant6_cause_racine"]["causes_racines"]),
      ("skipped", "student-service", ["postgres"]))
check("cause et groupe", (p[14], p[15]), ("cause:postgres", "cause:postgres|1"))
check("connexion fermée après l'écriture", (db.conns[0].closed, s.pending()), (True, 0))

s.record_notification("cause:postgres|1", "cause:postgres", "sent", "Moteur de sûreté", ["student-service"], None, "SM123")
sql, p = db.rows[1]
check("notification : table et paramètres", ("moteur_schema.notifications" in sql, p),
      (True, ("cause:postgres|1", "cause:postgres", "whatsapp", "sent", "Moteur de sûreté", ["student-service"], None, "SM123")))
s.record_verdict(verdict(decision="ALLOW"), None, None)
check("un ALLOW est enregistré aussi (sans cause)", (db.rows[2][1][5], db.rows[2][1][14], db.rows[2][1][15]), ("ALLOW", None, None))
bad = verdict(); bad["proposal"]["timestamp"] = "pas une date"
s.record_verdict(bad, None, None)
check("horodatage illisible : NULL, pas d'erreur", db.rows[3][1][0], None)

# --- base injoignable : on attend, on réessaie, rien ne se perd ---
db = FakeDb(); db.connect_error = ConnectionError("connection refused")
clock = {"now": NOW}
s = store(db, clock=lambda: clock["now"])
logbuf = io.StringIO(); h = logging.StreamHandler(logbuf); a.logger.addHandler(h)
a.logger.setLevel(logging.INFO)   # le message de reprise est de niveau INFO
s.record_verdict(verdict(n=1), "cause:a", "g1")
check("1re tentative : en attente, aucune exception", (s.pending(), db.connects), (1, 1))
clock["now"] = NOW + timedelta(seconds=10)
s.record_verdict(verdict(n=2), "cause:a", "g1")
check("10 s plus tard : pas de nouvelle connexion (pas de blocage à chaque verdict)", (s.pending(), db.connects), (2, 1))
clock["now"] = NOW + timedelta(seconds=31)
s.flush()
check("31 s plus tard : nouvel essai", db.connects, 2)
db.connect_error = None
clock["now"] = NOW + timedelta(seconds=70)
s.record_verdict(verdict(n=3), "cause:a", "g1")
check("base revenue : tout est écrit, dans l'ordre", ([r[1][7] for r in db.rows], s.pending()), ([1, 2, 3], 0))
a.logger.removeHandler(h)
check("une seule alerte par panne (+ la reprise)", (logbuf.getvalue().count("injoignable"), logbuf.getvalue().count("repris")), (1, 1))
check("le mot de passe n'apparaît jamais dans les logs", "s3cret-audit" in logbuf.getvalue(), False)

# --- ligne refusée par la base : abandonnée, les autres passent ---
db = FakeDb(); db.exec_errors = {1: PgError("22P02")}
s = store(db)
s.record_verdict(verdict(n=1), None, None)
s.record_verdict(verdict(n=2), None, None)
check("ligne invalide abandonnée, la suivante écrite", ([r[1][7] for r in db.rows], s.pending()), ([2], 0))

# --- coupure pendant l'écriture : on garde la ligne et on réessaie ---
db = FakeDb(); db.exec_errors = {1: ConnectionError("server closed the connection")}
clock = {"now": NOW}; s = store(db, clock=lambda: clock["now"])
s.record_verdict(verdict(n=1), None, None)
check("coupure en cours d'écriture : ligne conservée", (s.pending(), len(db.rows), db.conns[0].closed), (1, 0, True))
clock["now"] = NOW + timedelta(seconds=40); s.flush()
check("nouvel essai réussi", (s.pending(), len(db.rows)), (0, 1))

# --- file bornée ---
db = FakeDb(); db.connect_error = ConnectionError("down")
s = store(db)
logbuf = io.StringIO(); h = logging.StreamHandler(logbuf); a.logger.addHandler(h)
for i in range(600): s.record_verdict(verdict(n=i), None, None)
a.logger.removeHandler(h)
check("file limitée à 500 lignes", s.pending(), 500)
check("les plus anciennes sont perdues", s._pending[0][1][7], 100)
check("alerte de débordement unique", logbuf.getvalue().count("file d'attente pleine"), 1)

# --- concurrence (le moteur et le notifieur écrivent en même temps) ---
db = FakeDb(); s = store(db)
threads = [threading.Thread(target=lambda k=k: [s.record_verdict(verdict(n=k * 100 + i), None, None) for i in range(25)]) for k in range(4)]
[t.start() for t in threads]; [t.join() for t in threads]
check("4 fils × 25 lignes : 100 lignes, aucune perdue ni doublée", (len(db.rows), len({r[1][7] for r in db.rows})), (100, 100))

# --- sécurité ---
try:
    a.AuditStore(m.Config(audit_schema="x; DROP TABLE verdicts"), connect=lambda: None); raised = False
except ValueError:
    raised = True
check("nom de schéma dangereux refusé", raised, True)
check("secrets absents de repr(Config)", ("s3cret" in repr(m.Config(audit_db_password="s3cret", twilio_auth_token="s3cret"))), False)
check("variables d'environnement lues", (lambda e: (e.audit_schema, e.notify_max_per_hour, e.cause_group_ttl_s))(m.Config.from_env()), ("moteur_schema", 10, 600))

print("\nTOUS LES TESTS PASSENT" if OK else "\nDES TESTS ÉCHOUENT")
