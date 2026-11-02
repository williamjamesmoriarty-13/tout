"""Tests du tableau de bord (faux Postgres, vrai serveur HTTP local). Lancer : python3 test_dashboard.py"""
import http.client
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone

import dashboard as d

OK = True


def check(label, got, want):
    global OK
    good = got == want
    OK &= good
    print(("OK  " if good else "FAIL"), label, "->" if not good else "", got if not good else "")


T0 = datetime(2026, 10, 19, 6, 0, 0, tzinfo=timezone.utc)

# =====================================================================
# 1. Accès à la base
# =====================================================================
class FakeCursor:
    def __init__(self, db): self.db = db
    def execute(self, sql, params=()):
        if self.db.get("query_error"): raise RuntimeError("secret interne : mot de passe=hunter2")
        self.db["executed"].append((sql, params)); self.rows = self.db["answers"].pop(0)
    def fetchall(self): return self.rows

class FakeConn:
    def __init__(self, db): self.db, self.closed = db, False
    def cursor(self): return FakeCursor(self.db)
    def close(self): self.closed = True; self.db["closed"] += 1

def fake_store(answers, **extra):
    db = {"executed": [], "answers": list(answers), "closed": 0, **extra}
    def connect():
        if db.get("connect_error"): raise ConnectionError("password=hunter2 host=db")
        return FakeConn(db)
    return d.Store(d.DashConfig(), connect=connect), db

row = (7, T0, "Restart", "student-service", "DENY", "dry-run", 1, ["invariant6_cause_racine"], "refusé", "skipped",
       "Latence", "cause:postgres", "cause:postgres|1", "i1")
st, db = fake_store([[row]])
out = st.verdicts(limit=5)
check("verdicts : colonnes nommées, dates en ISO, listes conservées",
      (out[0]["id"], out[0]["recorded_at"], out[0]["invariants_violated"], out[0]["cause_key"]), (7, T0.isoformat(), ["invariant6_cause_racine"], "cause:postgres"))
check("verdicts : schéma, tri décroissant, limite passée en paramètre", ("moteur_schema.verdicts" in db["executed"][0][0], "ORDER BY id DESC" in db["executed"][0][0], db["executed"][0][1][1]), (True, True, 5))
check("connexion fermée après chaque requête", db["closed"], 1)
st, db = fake_store([[row]]); st.since(6)
check("since : seulement les lignes plus récentes, ordre croissant", ("id > %s" in db["executed"][0][0], "ASC" in db["executed"][0][0], db["executed"][0][1][0]), (True, True, 6))
st, db = fake_store([[(1,)]]); check("max_id", st.max_id(), 1)
st, db = fake_store([[]]); check("détail d'un verdict inconnu : None", st.detail(99), None)
full = row + ({"action": "Restart"}, {"invariant6": {}}, {"result": "skipped"}, [])
st, db = fake_store([[full]]); det = st.detail(7)
check("détail : proposition et preuves (JSON) conservées", (det["proposal"], det["evidence"]), ({"action": "Restart"}, {"invariant6": {}}))
grp = ("cause:postgres|1", "cause:postgres", T0, T0, 3, ["a", "b"], "sent", "Cause : postgres")
st, db = fake_store([[grp]]); g = st.groups()[0]
check("groupes : refus comptés, services, statut et texte de l'alerte", (g["denies"], g["targets"], g["notification_status"], g["notification_message"]), (3, ["a", "b"], "sent", "Cause : postgres"))
st, db = fake_store([[("ALLOW", 4), ("DENY", 9)], [("invariant6_cause_racine", 5)], [("sent", 1), ("disabled", 2)]])
check("résumé 24 h", st.summary(24), {"hours": 24, "verdicts": {"ALLOW": 4, "DENY": 9}, "invariants": {"invariant6_cause_racine": 5}, "notifications": {"sent": 1, "disabled": 2}})
for label, kw in (("base injoignable", {"connect_error": True}), ("requête en erreur", {"query_error": True})):
    st, db = fake_store([[row]], **kw)
    try: st.verdicts(); msg = None
    except d.StoreUnavailable as e: msg = str(e)
    check(f"{label} : StoreUnavailable sans fuite d'information", (msg is not None, "hunter2" in (msg or ""), "password" in (msg or "")), (True, False, False))
try: d.Store(d.DashConfig(schema="x; DROP TABLE v")); raised = False
except ValueError: raised = True
check("schéma dangereux refusé", raised, True)
check("mot de passe absent de repr(DashConfig)", "hunter2" in repr(d.DashConfig(db_password="hunter2")), False)

# =====================================================================
# 2. Page
# =====================================================================
check("page : jamais d'innerHTML, d'eval ni de ressource externe",
      (("innerHTML" in d.PAGE), ("eval(" in d.PAGE), bool(re.search(r"https?://", d.PAGE))), (False, False, False))
script = re.search(r"<script nonce=\"__NONCE__\">(.*?)</script>", d.PAGE, re.S).group(1)
if shutil.which("node"):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f: f.write(script)
    r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
    check("JavaScript : syntaxe valide (node --check)", (r.returncode, r.stderr[:200]), (0, ""))
else:
    print("SKIP JavaScript : node absent")

# =====================================================================
# 3. Serveur HTTP
# =====================================================================
class FakeStore:
    def __init__(self):
        self.rows = [self.make(i) for i in range(1, 6)]
        self.down, self.calls = False, []
    @staticmethod
    def make(i, verdict="DENY"):
        return {"id": i, "recorded_at": T0.isoformat(), "action": "Restart", "target": "student-service",
                "verdict": verdict, "mode": "dry-run", "attempt": 1, "invariants_violated": [], "justification": f"ligne {i}",
                "result": "skipped", "reason": "r", "cause_key": "cause:x", "cause_group": "g", "incident_id": "i"}
    def _chk(self):
        if self.down: raise d.StoreUnavailable("connexion : ConnectionError")
    def verdicts(self, limit=50, before_id=None):
        self._chk(); self.calls.append(("verdicts", limit, before_id))
        rows = [r for r in self.rows if before_id is None or r["id"] < before_id]
        return list(reversed(rows))[:limit]
    def since(self, last_id, limit=200):
        self._chk(); return [r for r in self.rows if r["id"] > last_id][:limit]
    def detail(self, i):
        self._chk(); return next((dict(r, proposal={"x": 1}, evidence={}, execution={}, alerts=[]) for r in self.rows if r["id"] == i), None)
    def max_id(self): self._chk(); return max((r["id"] for r in self.rows), default=0)
    def groups(self, limit=20): self._chk(); return [{"cause_group": "g", "cause_key": "cause:x", "denies": 5}]
    def summary(self, hours=24): self._chk(); return {"hours": hours, "verdicts": {"DENY": 5}}


def start(store, **kw):
    cfg = d.DashConfig(**{"port": 0, "poll_s": 0.05, "ping_s": 0.3, **kw})
    srv = d.make_server(store, cfg, host="127.0.0.1")
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return srv, t

def stop(srv, t):
    srv.stop_event.set(); srv.shutdown(); srv.server_close(); t.join(2)

def get(srv, path, method="GET", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=3)
    c.request(method, path, headers=headers or {})
    r = c.getresponse(); body = r.read()
    return r.status, dict(r.getheaders()), body

store = FakeStore(); srv, th = start(store)
status, h, body = get(srv, "/")
nonce = re.search(r"script-src 'nonce-([\w\-]+)'", h["Content-Security-Policy"]).group(1)
check("page : 200 HTML, nonce CSP repris dans le script et le style", (status, h["Content-Type"].startswith("text/html"), body.decode().count(f'nonce="{nonce}"')), (200, True, 2))
check("page : en-têtes de sécurité", (h["X-Frame-Options"], h["X-Content-Type-Options"], "default-src 'none'" in h["Content-Security-Policy"], h["Cache-Control"]), ("DENY", "nosniff", True, "no-store"))
check("un nonce différent à chaque requête", get(srv, "/")[1]["Content-Security-Policy"] != h["Content-Security-Policy"], True)
check("/healthz", get(srv, "/healthz")[::2], (200, b"ok"))

status, _, body = get(srv, "/api/verdicts?limit=2")
check("API verdicts : 2 lignes, la plus récente d'abord", (status, [r["id"] for r in json.loads(body)["verdicts"]]), (200, [5, 4]))
get(srv, "/api/verdicts?limit=99999&before_id=4")
check("limite bornée à 200, before_id transmis", store.calls[-1], ("verdicts", 200, 4))
check("paramètre invalide : 400", get(srv, "/api/verdicts?limit=abc")[0], 400)
status, _, body = get(srv, "/api/verdict?id=3")
check("détail d'un verdict", (status, json.loads(body)["proposal"]), (200, {"x": 1}))
check("verdict inconnu : 404", get(srv, "/api/verdict?id=999")[0], 404)
check("détail sans id : 404", get(srv, "/api/verdict")[0], 404)
check("groupes et résumé", (json.loads(get(srv, "/api/groups")[2])["groups"][0]["denies"], json.loads(get(srv, "/api/summary?hours=2")[2])["hours"]), (5, 2))
check("chemin inconnu : 404", get(srv, "/admin")[0], 404)
check("POST, PUT, DELETE : 405", [get(srv, "/api/groups", m)[0] for m in ("POST", "PUT", "DELETE")], [405] * 3)
store.down = True
status, _, body = get(srv, "/api/groups")
check("base indisponible : 503 générique, sans détail", (status, json.loads(body), b"ConnectionError" in body), (503, {"error": "base d'historique indisponible"}, False))
store.down = False
stop(srv, th)


def read_events(resp, n, timeout=3.0):
    events, cur, deadline = [], {}, time.time() + timeout
    while len(events) < n and time.time() < deadline:
        line = resp.readline().decode()
        if line == "": break
        line = line.rstrip("\n")
        if line == "":
            if cur: events.append(cur); cur = {}
        elif line.startswith(":"): events.append({"comment": line[1:].strip()})
        else:
            k, _, v = line.partition(": "); cur[k] = v
    return events

def wait_until(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return True
        time.sleep(0.02)
    return cond()

def close_stream(conn, resp):
    """Ferme comme un navigateur : la réponse HTTP/1.0 garde le socket, conn.close() seul ne suffit pas."""
    resp.close(); conn.close()

def open_stream(srv, path="/api/stream", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=3)
    c.request("GET", path, headers=headers or {}); return c, c.getresponse()

# --- flux en direct ---
store = FakeStore(); srv, th = start(store)
conn, resp = open_stream(srv, "/api/stream?tail=2")
check("flux : en-têtes SSE", (resp.status, resp.getheader("Content-Type").startswith("text/event-stream"), resp.getheader("Cache-Control")), (200, True, "no-cache"))
ev = read_events(resp, 3)
check("flux : les 2 derniers verdicts dans l'ordre chronologique, puis « ready »",
      ([(e["event"], e.get("id")) for e in ev]), [("verdict", "4"), ("verdict", "5"), ("ready", None)])
check("flux : le contenu est du JSON complet", json.loads(ev[0]["data"])["justification"], "ligne 4")
store.rows.append(store.make(6, "ALLOW")); store.rows.append(store.make(7))
ev = read_events(resp, 2)
check("flux : les nouveaux verdicts arrivent en direct", [(e["event"], e["id"], json.loads(e["data"])["verdict"]) for e in ev], [("verdict", "6", "ALLOW"), ("verdict", "7", "DENY")])
ev = read_events(resp, 1)
check("flux : battement de cœur régulier", ev[0], {"comment": "ping"})
close_stream(conn, resp)

conn, resp = open_stream(srv, "/api/stream?tail=0")
ev = read_events(resp, 1)
check("flux sans historique (tail=0) : démarre à l'instant présent", (ev[0]["event"], json.loads(ev[0]["data"])["last_id"]), ("ready", 7))
close_stream(conn, resp)

conn, resp = open_stream(srv, "/api/stream", {"Last-Event-ID": "5"})
ev = read_events(resp, 3)
check("reprise après coupure (Last-Event-ID) : seulement ce qui a été manqué", [(e["event"], e.get("id")) for e in ev], [("verdict", "6"), ("verdict", "7"), ("ready", None)])
close_stream(conn, resp)

# --- panne puis reprise de la base pendant un flux ---
conn, resp = open_stream(srv, "/api/stream?tail=0"); read_events(resp, 1)
store.down = True
ev = read_events(resp, 1)
check("base en panne pendant le flux : un seul événement « problem »", [e["event"] for e in ev], ["problem"])
store.down = False; store.rows.append(store.make(8))
ev = read_events(resp, 2)
check("base revenue : « ready » puis les verdicts manqués", [(e["event"], e.get("id")) for e in ev], [("ready", None), ("verdict", "8")])
close_stream(conn, resp)

check("onglet fermé : la place est libérée en moins de 2 s (sans attendre le prochain battement)",
      wait_until(lambda: srv.stream_slots._value == srv.cfg.max_streams), True)
stop(srv, th)

# --- nombre de flux borné ---
store = FakeStore(); srv, th = start(store, max_streams=1)
c1, r1 = open_stream(srv, "/api/stream?tail=0"); read_events(r1, 1)
c2, r2 = open_stream(srv, "/api/stream?tail=0")
check("2e flux au-delà de la limite : 503", r2.status, 503); close_stream(c2, r2)
close_stream(c1, r1)
wait_until(lambda: srv.stream_slots._value == 1)
c3, r3 = open_stream(srv, "/api/stream?tail=0")
check("après fermeture du 1er, un nouveau flux est accepté", r3.status, 200); close_stream(c3, r3)
stop(srv, th)

# --- un onglet fermé libère sa place même sans aucun battement de cœur (ping toutes les 30 s) ---
store = FakeStore(); srv, th = start(store, max_streams=1, ping_s=30)
c1, r1 = open_stream(srv, "/api/stream?tail=0"); read_events(r1, 1)
check("1 flux ouvert : place prise", srv.stream_slots._value, 0)
close_stream(c1, r1)
check("onglet fermé, battement à 30 s : la place est quand même libérée en moins de 2 s",
      wait_until(lambda: srv.stream_slots._value == 1), True)
stop(srv, th)

# --- arrêt propre : les flux se terminent ---
store = FakeStore(); srv, th = start(store)
conn, resp = open_stream(srv, "/api/stream?tail=0"); read_events(resp, 1)
srv.stop_event.set()
t0 = time.time(); rest = resp.read()
check("arrêt du serveur : le flux se termine vite", time.time() - t0 < 2, True)
close_stream(conn, resp); srv.shutdown(); srv.server_close()

print("\nTOUS LES TESTS PASSENT" if OK else "\nDES TESTS ÉCHOUENT")
