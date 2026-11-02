"""
dashboard.py — Tableau de bord du moteur de vérification
========================================================
Petit serveur web (bibliothèque standard uniquement) qui lit l'historique
Postgres du moteur avec un rôle EN LECTURE SEULE (moteur_viewer) :
- un flux en temps réel des verdicts, comme `kubectl logs -f` (Server-Sent Events) ;
- les groupes de causes racines et le statut de leur alerte WhatsApp ;
- le détail d'un verdict (proposition, preuves) au clic.

Sécurité : le tableau de bord ne modifie rien et n'a aucun accès à l'API
Kubernetes. Il n'a PAS d'authentification : ne l'expose pas, accède-y avec
`kubectl port-forward -n university-moteur svc/moteur-dashboard 8088:80`.
Les données affichées viennent de logs applicatifs : la page n'insère jamais
de texte avec innerHTML et applique une politique CSP stricte.
"""

import json
import logging
import os
import re
import secrets
import select
import signal
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("dashboard")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _info(msg: str) -> None:
    logger.info(json.dumps(msg))


def _warn(msg: str) -> None:
    logger.warning(json.dumps(msg))


# ============================================================
# Configuration
# ============================================================
@dataclass
class DashConfig:
    port: int = 8080
    db_host: str = "postgres.university-app.svc.cluster.local"
    db_port: int = 5432
    db_name: str = "university_db"
    db_user: str = ""
    db_password: str = field(default="", repr=False)   # jamais affiché
    schema: str = "moteur_schema"
    db_timeout_s: int = 5
    poll_s: float = 2.0
    max_streams: int = 10
    ping_s: float = 15.0

    @classmethod
    def from_env(cls) -> "DashConfig":
        e = os.environ.get
        return cls(port=int(e("DASH_PORT", "8080")),
                   db_host=e("DB_HOST", cls.db_host), db_port=int(e("DB_PORT", "5432")),
                   db_name=e("DB_NAME", cls.db_name), db_user=e("DASH_DB_USER", ""),
                   db_password=e("DASH_DB_PASSWORD", ""), schema=e("AUDIT_SCHEMA", cls.schema),
                   db_timeout_s=int(e("DB_TIMEOUT_SECONDS", "5")),
                   poll_s=float(e("DASH_POLL_SECONDS", "2")),
                   max_streams=int(e("DASH_MAX_STREAMS", "10")))


class StoreUnavailable(Exception):
    """La base est injoignable ou la requête a échoué."""


# ============================================================
# Accès à la base (lecture seule)
# ============================================================
VERDICT_COLS = ["id", "recorded_at", "action", "target", "verdict", "mode", "attempt",
                "invariants_violated", "justification", "result", "reason",
                "cause_key", "cause_group", "incident_id"]
DETAIL_COLS = VERDICT_COLS + ["proposal", "evidence", "execution", "alerts"]
GROUP_COLS = ["cause_group", "cause_key", "first_seen", "last_seen", "denies", "targets",
              "notification_status", "notification_message"]


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


class Store:
    def __init__(self, cfg: DashConfig, connect: Callable | None = None):
        if not _IDENT.match(cfg.schema):
            raise ValueError(f"nom de schéma invalide : {cfg.schema!r}")
        self.cfg = cfg
        self._connect = connect or self._default_connect
        s = cfg.schema
        base = ("id, recorded_at, action, target, verdict, mode, attempt, invariants_violated, "
                "justification, execution->>'result', proposal->>'reason', cause_key, "
                "cause_group, incident_id")
        self._sql_verdicts = f"SELECT {base} FROM {s}.verdicts WHERE id < %s ORDER BY id DESC LIMIT %s"
        self._sql_since = f"SELECT {base} FROM {s}.verdicts WHERE id > %s ORDER BY id ASC LIMIT %s"
        self._sql_detail = (f"SELECT {base}, proposal, evidence, execution, alerts "
                            f"FROM {s}.verdicts WHERE id = %s")
        self._sql_max = f"SELECT coalesce(max(id), 0) FROM {s}.verdicts"
        self._sql_groups = (
            f"SELECT v.cause_group, v.cause_key, min(v.recorded_at), max(v.recorded_at), count(*), "
            f"array_agg(DISTINCT v.target), "
            f"(SELECT n.status FROM {s}.notifications n WHERE n.group_id = v.cause_group "
            f"ORDER BY n.id DESC LIMIT 1), "
            f"(SELECT n.message FROM {s}.notifications n WHERE n.group_id = v.cause_group "
            f"ORDER BY n.id DESC LIMIT 1) "
            f"FROM {s}.verdicts v WHERE v.verdict = 'DENY' AND v.cause_group IS NOT NULL "
            f"GROUP BY v.cause_group, v.cause_key ORDER BY max(v.recorded_at) DESC LIMIT %s")
        self._sql_summary = [
            ("verdicts", f"SELECT verdict, count(*) FROM {s}.verdicts "
                         f"WHERE recorded_at > now() - make_interval(hours => %s) GROUP BY verdict"),
            ("invariants", f"SELECT inv, count(*) FROM (SELECT unnest(invariants_violated) AS inv "
                           f"FROM {s}.verdicts WHERE recorded_at > now() - make_interval(hours => %s)) t "
                           f"GROUP BY inv ORDER BY 2 DESC"),
            ("notifications", f"SELECT status, count(*) FROM {s}.notifications "
                              f"WHERE recorded_at > now() - make_interval(hours => %s) GROUP BY status"),
        ]

    def _default_connect(self):
        import psycopg2  # importé ici : inutile pour les tests
        c = self.cfg
        return psycopg2.connect(
            host=c.db_host, port=c.db_port, dbname=c.db_name, user=c.db_user, password=c.db_password,
            connect_timeout=c.db_timeout_s,
            options=f"-c statement_timeout={c.db_timeout_s * 1000} -c default_transaction_read_only=on")

    def _rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        try:
            conn = self._connect()
        except Exception as e:
            raise StoreUnavailable(f"connexion : {type(e).__name__}") from e
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        except Exception as e:
            raise StoreUnavailable(f"requête : {type(e).__name__}") from e
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _as_dicts(cols: list[str], rows: list[tuple]) -> list[dict]:
        return [_jsonable(dict(zip(cols, r))) for r in rows]

    def verdicts(self, limit: int = 50, before_id: int | None = None) -> list[dict]:
        before = before_id if before_id is not None else 2 ** 62
        return self._as_dicts(VERDICT_COLS, self._rows(self._sql_verdicts, (before, limit)))

    def since(self, last_id: int, limit: int = 200) -> list[dict]:
        return self._as_dicts(VERDICT_COLS, self._rows(self._sql_since, (last_id, limit)))

    def detail(self, verdict_id: int) -> dict | None:
        rows = self._rows(self._sql_detail, (verdict_id,))
        return self._as_dicts(DETAIL_COLS, rows)[0] if rows else None

    def max_id(self) -> int:
        rows = self._rows(self._sql_max)
        return int(rows[0][0]) if rows else 0

    def groups(self, limit: int = 20) -> list[dict]:
        return self._as_dicts(GROUP_COLS, self._rows(self._sql_groups, (limit,)))

    def summary(self, hours: int = 24) -> dict:
        out = {"hours": hours}
        for name, sql in self._sql_summary:
            out[name] = {str(k): int(v) for k, v in self._rows(sql, (hours,))}
        return out


# ============================================================
# Page (une seule, sans dépendance ; tout texte via textContent)
# ============================================================
PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moteur de sûreté — tableau de bord</title>
<style nonce="__NONCE__">
:root{color-scheme:dark;--bg:#0f1419;--panel:#171d24;--line:#26303a;--txt:#d6dde5;--mut:#8493a3;--ok:#3fb950;--bad:#f85149;--warn:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.4 system-ui,sans-serif}
header{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:12px 18px;border-bottom:1px solid var(--line)}
h1{font-size:16px;margin:0}.pill{padding:2px 10px;border-radius:999px;background:var(--panel);border:1px solid var(--line);color:var(--mut)}
.pill b{color:var(--txt)}#conn.live{color:var(--ok)}#conn.down{color:var(--bad)}
main{display:grid;grid-template-columns:3fr 2fr;gap:14px;padding:14px 18px}@media(max-width:1000px){main{grid-template-columns:1fr}}
section{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-width:0}
section h2{font-size:13px;margin:0;padding:10px 14px;border-bottom:1px solid var(--line);color:var(--mut);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.tools{margin-left:auto;display:flex;gap:10px;align-items:center;font-weight:400}.tools input[type=text]{background:var(--bg);color:var(--txt);border:1px solid var(--line);border-radius:4px;padding:2px 6px}
button{background:var(--bg);color:var(--txt);border:1px solid var(--line);border-radius:4px;padding:3px 9px;cursor:pointer}
#feed{height:62vh;overflow:auto;font:12.5px/1.5 ui-monospace,Menlo,Consolas,monospace;padding:6px 0}
.row{padding:1px 14px;white-space:pre-wrap;word-break:break-word;cursor:pointer;border-left:3px solid transparent}.row:hover{background:#1d252e}
.row.ALLOW{border-left-color:var(--ok)}.row.DENY{border-left-color:var(--bad)}.row.new{background:#2a2412}
.v-ALLOW{color:var(--ok);font-weight:700}.v-DENY{color:var(--bad);font-weight:700}.mut{color:var(--mut)}.cause{color:var(--warn)}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top;font-size:12.5px}
th{color:var(--mut);font-weight:600}td.msg{white-space:pre-wrap;color:var(--mut);max-width:300px}
.st-sent{color:var(--ok)}.st-failed,.st-throttled{color:var(--bad)}.st-disabled{color:var(--mut)}
#detail{display:none;margin:0;padding:12px 14px;max-height:34vh;overflow:auto;border-top:1px solid var(--line);font:12px ui-monospace,Menlo,monospace;white-space:pre-wrap}
</style></head><body>
<header><h1>Moteur de sûreté</h1><span class="pill" id="conn">connexion…</span>
<span class="pill">24 h : <b id="n-allow">0</b> ALLOW · <b id="n-deny">0</b> DENY</span>
<span class="pill">alertes : <b id="n-notif">0</b></span><span class="pill mut" id="err"></span></header>
<main>
<section><h2>Flux en direct <span class="mut">(comme kubectl logs -f)</span>
<span class="tools"><label><input type="checkbox" id="f-allow" checked> ALLOW</label>
<label><input type="checkbox" id="f-deny" checked> DENY</label>
<input type="text" id="f-text" placeholder="filtrer (service, cause...)" size="22">
<label><input type="checkbox" id="scroll" checked> suivre</label>
<button id="bell" type="button">Notifications du navigateur</button></span></h2>
<div id="feed"></div><pre id="detail"></pre></section>
<section><h2>Causes racines</h2>
<table><thead><tr><th>Cause</th><th>Dernier refus</th><th>Refus</th><th>Alerte</th></tr></thead><tbody id="groups"></tbody></table></section>
</main>
<script nonce="__NONCE__">
"use strict";
const $ = (id) => document.getElementById(id);
const MAX_ROWS = 1500;
const seenGroups = new Set();
let live = false;                       // devient vrai après le premier lot reçu
let notify = false;
const hhmmss = (iso) => iso ? new Date(iso).toLocaleTimeString("fr-FR") : "--:--:--";
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };

function addRow(v, fromStream) {
  const row = el("div", "row " + v.verdict);
  row.dataset.id = v.id; row.dataset.verdict = v.verdict;
  row.append(el("span", "mut", hhmmss(v.recorded_at) + "  "), el("span", "v-" + v.verdict, v.verdict.padEnd(5) + " "),
             document.createTextNode(v.action + " " + v.target + " "), el("span", "mut", "t" + (v.attempt ?? "?") + " "));
  if (v.cause_key) row.append(el("span", "cause", "[" + v.cause_key + "] "));
  if (v.result && v.result !== "skipped") row.append(el("span", "mut", "(" + v.result + ") "));
  row.append(document.createTextNode("— " + (v.justification || "")));
  row.dataset.text = (row.textContent || "").toLowerCase();
  row.addEventListener("click", () => showDetail(v.id));
  const feed = $("feed");
  const stick = $("scroll").checked;
  feed.append(row);
  while (feed.children.length > MAX_ROWS) feed.removeChild(feed.firstChild);
  applyFilter(row);
  if (fromStream && live) { row.classList.add("new"); setTimeout(() => row.classList.remove("new"), 4000); }
  if (stick) feed.scrollTop = feed.scrollHeight;
  if (v.cause_group && v.verdict === "DENY" && !seenGroups.has(v.cause_group)) {
    seenGroups.add(v.cause_group);
    if (fromStream && live && notify && "Notification" in window && Notification.permission === "granted") {
      new Notification("Moteur : " + v.cause_key, { body: v.action + " " + v.target + " refusé — " + (v.justification || "") });
    }
  }
}
function applyFilter(row) {
  const okV = row.dataset.verdict === "ALLOW" ? $("f-allow").checked : $("f-deny").checked;
  const q = $("f-text").value.trim().toLowerCase();
  row.style.display = okV && (!q || row.dataset.text.includes(q)) ? "" : "none";
}
function refilter() { for (const r of $("feed").children) applyFilter(r); }
["f-allow", "f-deny", "f-text"].forEach((id) => $(id).addEventListener("input", refilter));

async function showDetail(id) {
  const box = $("detail");
  try {
    const r = await fetch("/api/verdict?id=" + encodeURIComponent(id));
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    box.textContent = JSON.stringify(d, null, 2);
    box.style.display = "block";
  } catch (e) { box.textContent = "Détail indisponible : " + e.message; box.style.display = "block"; }
}

async function refreshSide() {
  try {
    const [s, g] = await Promise.all([fetch("/api/summary").then((r) => r.json()), fetch("/api/groups").then((r) => r.json())]);
    $("n-allow").textContent = (s.verdicts && s.verdicts.ALLOW) || 0;
    $("n-deny").textContent = (s.verdicts && s.verdicts.DENY) || 0;
    $("n-notif").textContent = Object.values(s.notifications || {}).reduce((a, b) => a + b, 0);
    const body = $("groups"); body.replaceChildren();
    for (const x of g.groups || []) {
      const tr = el("tr");
      const cause = el("td"); cause.append(el("div", "cause", x.cause_key), el("div", "mut", (x.targets || []).join(", ")));
      const alert = el("td"); alert.append(el("div", "st-" + (x.notification_status || "none"), x.notification_status || "aucune"));
      if (x.notification_message) alert.append(el("div", "msg mut", x.notification_message));
      tr.append(cause, el("td", "", hhmmss(x.last_seen)), el("td", "", String(x.denies)), alert);
      body.append(tr);
    }
    $("err").textContent = "";
  } catch (e) { $("err").textContent = "résumé indisponible"; }
}

$("bell").addEventListener("click", async () => {
  if (!("Notification" in window)) { $("err").textContent = "notifications non prises en charge"; return; }
  const p = await Notification.requestPermission();
  notify = p === "granted";
  $("bell").textContent = notify ? "Notifications activées" : "Notifications refusées";
});

function connect() {
  const es = new EventSource("/api/stream?tail=50");
  es.addEventListener("open", () => { $("conn").textContent = "en direct"; $("conn").className = "pill live"; });
  es.addEventListener("verdict", (ev) => { addRow(JSON.parse(ev.data), true); });
  es.addEventListener("ready", () => { live = true; refreshSide(); });
  es.addEventListener("problem", () => { $("err").textContent = "base d'historique indisponible"; });
  es.addEventListener("error", () => { $("conn").textContent = "déconnecté, reconnexion…"; $("conn").className = "pill down"; });
}
connect(); refreshSide(); setInterval(refreshSide, 5000);
</script></body></html>
"""


# ============================================================
# Serveur HTTP
# ============================================================
class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, store: Store, cfg: DashConfig):
        super().__init__(addr, Handler)
        self.store, self.cfg = store, cfg
        self.stop_event = threading.Event()
        self.stream_slots = threading.BoundedSemaphore(cfg.max_streams)


def _clamp_int(raw: str | None, default: int, lo: int, hi: int) -> int:
    if raw is None:
        return default
    return max(lo, min(hi, int(raw)))   # ValueError si ce n'est pas un entier -> 400


class Handler(BaseHTTPRequestHandler):
    server_version = "moteur-dashboard"

    def log_message(self, fmt, *args):   # pas de journal d'accès bavard
        pass

    # ---- réponses
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, default=str).encode(), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    # ---- routes
    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        store: Store = self.server.store
        try:
            if url.path == "/":
                nonce = secrets.token_urlsafe(16)
                csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                       f"connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                self._send(200, PAGE.replace("__NONCE__", nonce).encode(), "text/html; charset=utf-8",
                           {"Content-Security-Policy": csp})
            elif url.path == "/healthz":
                self._send(200, b"ok", "text/plain; charset=utf-8")
            elif url.path == "/api/verdicts":
                before = _clamp_int(q.get("before_id"), 0, 0, 2 ** 62) or None
                self._json(200, {"verdicts": store.verdicts(_clamp_int(q.get("limit"), 50, 1, 200), before)})
            elif url.path == "/api/verdict":
                row = store.detail(_clamp_int(q.get("id"), -1, -1, 2 ** 62))
                self._json(200, row) if row else self._error(404, "verdict introuvable")
            elif url.path == "/api/groups":
                self._json(200, {"groups": store.groups(_clamp_int(q.get("limit"), 20, 1, 100))})
            elif url.path == "/api/summary":
                self._json(200, store.summary(_clamp_int(q.get("hours"), 24, 1, 24 * 30)))
            elif url.path == "/api/stream":
                self._stream(q)
            else:
                self._error(404, "introuvable")
        except ValueError:
            self._error(400, "paramètre invalide")
        except StoreUnavailable as e:
            _warn(f"Tableau de bord : base indisponible ({e})")
            self._error(503, "base d'historique indisponible")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _method_not_allowed(self):
        self._error(405, "méthode non autorisée")

    do_POST = do_PUT = do_DELETE = do_PATCH = _method_not_allowed

    def _client_gone(self) -> bool:
        """True si le navigateur a fermé la connexion (sans attendre la prochaine écriture)."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    # ---- flux en direct (Server-Sent Events)
    def _stream(self, q: dict) -> None:
        srv: DashboardServer = self.server
        if not srv.stream_slots.acquire(blocking=False):
            self._error(503, "trop de flux ouverts")
            return
        try:
            tail = _clamp_int(q.get("tail"), 20, 0, 200)
            resume = self.headers.get("Last-Event-ID")
            self.send_response(200)
            for k, v in (("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-cache"),
                         ("X-Accel-Buffering", "no"), ("X-Content-Type-Options", "nosniff")):
                self.send_header(k, v)
            self.end_headers()

            def emit(event: str, data, eid=None) -> None:
                head = (f"id: {eid}\n" if eid is not None else "") + f"event: {event}\n"
                self.wfile.write((head + "data: " + json.dumps(data, default=str) + "\n\n").encode())
                self.wfile.flush()

            try:
                if resume is not None and resume.isdigit():
                    last_id = int(resume)
                    backlog = srv.store.since(last_id)
                else:
                    backlog = list(reversed(srv.store.verdicts(tail))) if tail else []
                    last_id = backlog[-1]["id"] if backlog else srv.store.max_id()
                for row in backlog:
                    emit("verdict", row, row["id"])
                    last_id = row["id"]
                emit("ready", {"last_id": last_id})
            except StoreUnavailable:
                emit("problem", {"error": "base indisponible"})
                last_id = int(resume) if resume and resume.isdigit() else 0

            last_ping, in_outage = time.monotonic(), False
            while not srv.stop_event.is_set():
                srv.stop_event.wait(srv.cfg.poll_s)
                if self._client_gone():     # onglet fermé : on libère la place tout de suite
                    break
                try:
                    rows = srv.store.since(last_id)
                    if in_outage:
                        in_outage = False
                        emit("ready", {"last_id": last_id})
                    for row in rows:
                        emit("verdict", row, row["id"])
                        last_id = row["id"]
                except StoreUnavailable:
                    if not in_outage:
                        in_outage = True
                        emit("problem", {"error": "base indisponible"})
                if time.monotonic() - last_ping >= srv.cfg.ping_s:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass   # le navigateur a fermé l'onglet
        finally:
            srv.stream_slots.release()


def make_server(store: Store, cfg: DashConfig, host: str = "0.0.0.0") -> DashboardServer:
    return DashboardServer((host, cfg.port), store, cfg)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
                               '"service": "dashboard", "message": %(message)s}',
                        datefmt="%Y-%m-%dT%H:%M:%S+00:00")
    cfg = DashConfig.from_env()
    if not (cfg.db_user and cfg.db_password):
        raise SystemExit("DASH_DB_USER et DASH_DB_PASSWORD doivent être définis.")
    server = make_server(Store(cfg), cfg)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: (server.stop_event.set(),
                                                  threading.Thread(target=server.shutdown, daemon=True).start()))
    _info(f"Tableau de bord sur le port {cfg.port} (lecture seule, schéma {cfg.schema})")
    server.serve_forever()
    server.server_close()
    _info("Arrêt du tableau de bord")


if __name__ == "__main__":
    main()
