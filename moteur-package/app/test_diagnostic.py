"""Tests du diagnostic et de l'invariant 6. Lancer : python3 test_diagnostic.py"""
import contextlib
import copy
import io
import json
import logging
import re
from datetime import datetime, timezone, timedelta

import diagnostic as d
import moteur as m

OK = True


def check(label, got, want):
    global OK
    good = got == want
    OK &= good
    print(("OK  " if good else "FAIL"), label, "->", got if not good else "")


NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
START = NOW - timedelta(minutes=10)
CFG = m.Config(dry_run=True)
S, E, T = "student-service", "enrollment-service", "teacher-admin-service"
DB = d.DB_GRAPH_NAME


# ---------------------------------------------------------------------
# Faux Prometheus : renvoie des valeurs configurées selon le type de requête
# ---------------------------------------------------------------------
class FakeProm:
    def __init__(self, state, timeline=None, fail=False):
        self.state, self.timeline, self.fail = state, timeline or {}, fail
        self.calls, self.range_args = [], []

    @staticmethod
    def kind(q):
        if "client_seconds_bucket" in q: return "dbp95"
        if "traces_service_graph_request_total" in q: return "edges"
        if "kube_deployment_status_replicas_ready" in q: return "ready"
        if "histogram_quantile" in q: return "p95"
        if 'status=~"5.."' in q: return "rate5"
        return "rate"

    @staticmethod
    def _labels(kind, key):
        if kind in ("p95", "rate", "rate5"): return {"job": key}
        if kind == "ready": return {"deployment": key}
        if kind == "dbp95": return {"client": key}
        return {"client": key[0], "server": key[1]}

    @staticmethod
    def _keys(data, q, kind):
        if kind in ("p95", "rate", "rate5"):
            jobs = set(re.search(r'job=~"([^"]+)"', q).group(1).split("|"))
            return [k for k in data if k in jobs]
        return list(data)

    def instant(self, q):
        self.calls.append(("instant", q))
        if self.fail:
            raise d.DiagnosticUnavailable("Prometheus injoignable : test")
        kind = self.kind(q)
        data = self.state.get(kind, {})
        return [{"metric": self._labels(kind, k), "value": [0, str(data[k])]}
                for k in self._keys(data, q, kind)]

    def range(self, q, start, end, step):
        self.calls.append(("range", q))
        self.range_args.append((start, end, step))
        if self.fail:
            raise d.DiagnosticUnavailable("Prometheus injoignable : test")
        kind = self.kind(q)
        data = self.timeline.get(kind, {})
        return [{"metric": self._labels(kind, k),
                 "values": [[start + i * step, str(v)] for i, v in enumerate(data[k])]}
                for k in self._keys(data, q, kind)]


def now_state(**over):
    """État instantané : tout est sain. over : p95={...}, rate5={...}, dbp95={...}."""
    st = {"p95": {S: 0.005, E: 0.025, T: 0.004},
          "rate": {S: 14.0, E: 10.0, T: 10.0},
          "rate5": {S: 0.0, E: 0.0, T: 0.0},
          "dbp95": {S: 0.002, E: 0.002, T: 0.002}}
    for kind, values in over.items():
        st[kind] = {**st.get(kind, {}), **values}
    return st


def drop(state, kind, key):
    state = copy.deepcopy(state)
    state[kind].pop(key, None)
    return state


def healthy_timeline(n=60):
    return {"p95": {S: [0.005] * n, E: [0.025] * n, T: [0.004] * n},
            "rate": {S: [14.0] * n, E: [10.0] * n, T: [10.0] * n},
            "rate5": {S: [0.0] * n, E: [0.0] * n, T: [0.0] * n},
            "ready": {S: [2] * n, E: [2] * n, T: [2] * n},
            "dbp95": {S: [0.002] * n, E: [0.002] * n, T: [0.002] * n},
            "edges": {(E, S): [5.0] * n, (E, T): [29.0] * n, (E, DB): [10.0] * n,
                      (S, DB): [14.0] * n, (T, DB): [10.0] * n,
                      (S, E): [0.1] * n, (S, T): [0.07] * n}}


def chaos_points(timeline, first_n):
    """Les first_n premiers points : enrollment lent et student sans réplica prêt."""
    tl = copy.deepcopy(timeline)
    for i in range(first_n):
        tl["p95"][E][i] = 4.0
        tl["ready"][S][i] = 0
    return tl


class FakeCluster:
    def __init__(self, ready=None):
        self.ready = ready or {}

    def snapshot(self, service):
        return {"ready": self.ready.get(service, 2), "spec_replicas": 2, "hpa_min": 2, "hpa_max": 4}


def diagnostician(state, timeline=None, ready=None, fail=False):
    prom = FakeProm(state, timeline if timeline is not None else healthy_timeline(), fail)
    return d.Diagnostician(prom, FakeCluster(ready), CFG), prom


# ---------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------
check("quantile 0,5", d._quantile([1, 2, 3, 4, 5], 0.5), 3)
check("quantile 0,95", round(d._quantile([1, 2, 3, 4, 5], 0.95), 2), 4.8)

# --- client Prometheus ---
ok_body = {"status": "success", "data": {"result": [{"metric": {"job": "x"}, "value": [0, "1.5"]}]}}
check("instant : lecture", d.Prometheus("http://p", http_get=lambda path, params: ok_body).instant("q")[0]["value"][1], "1.5")
for label, getter in (("erreur de Prometheus", lambda p, q: {"status": "error", "error": "bad query"}),
                      ("réseau coupé", lambda p, q: (_ for _ in ()).throw(ConnectionError("down")))):
    try:
        d.Prometheus("http://p", http_get=getter).instant("q"); raised = False
    except d.DiagnosticUnavailable:
        raised = True
    check(f"Prometheus {label} -> DiagnosticUnavailable", raised, True)

# ---------------------------------------------------------------------
# Étape 6 : baseline (échantillons sains uniquement)
# ---------------------------------------------------------------------
MIN_READY = {S: 2, E: 2, T: 2}
prom = FakeProm(now_state(), healthy_timeline())
b = d.compute_baseline(prom, CFG, NOW, MIN_READY)
check("baseline prête avec 60 points sains", (b.ok, b.samples), (True, 60))
check("seuils de la baseline", {k: round(v, 3) for k, v in b.p95_thresholds.items()},
      {S: 0.05, E: 0.075, T: 0.05})
end = int((NOW - timedelta(seconds=300)).timestamp())
check("fenêtre : 30 min qui s'arrêtent 5 min avant", prom.range_args[0], (end - 1800, end, 30))

b2 = d.compute_baseline(FakeProm(now_state(), chaos_points(healthy_timeline(), 20)), CFG, NOW, MIN_READY)
check("les points de panne sont exclus", (b2.ok, b2.samples), (True, 40))
check("aucune dérive : mêmes seuils malgré la panne", round(b2.p95_thresholds[E], 3), 0.075)

b3 = d.compute_baseline(FakeProm(now_state(), chaos_points(healthy_timeline(), 50)), CFG, NOW, MIN_READY)
check("historique sain insuffisant (10 points)", (b3.ok, b3.samples, b3.needed), (False, 10, 20))

check("dépendances observées (part d'appels >= 0,2)", b.observed_deps,
      {E: {S: 0.5, T: 2.9, "postgres": 1.0}, S: {"postgres": 1.0}, T: {"postgres": 1.0}})

# ---------------------------------------------------------------------
# Étape 6 : détection de dégradation
# ---------------------------------------------------------------------
NOW2 = NOW
dg, _ = diagnostician(now_state(p95={S: 0.06}))
x = dg.diagnose(NOW2)
check("source : baseline", x.source.startswith("baseline observée (60 points sains"), True)
check("student à 60 ms > seuil 50 ms : dégradé", (x.services[S]["degrade"], x.services[E]["degrade"]), (True, False))

dg, _ = diagnostician(now_state(p95={S: 0.06}), timeline=chaos_points(healthy_timeline(), 55))
x = dg.diagnose(NOW2)
check("source : seuils fixes de repli", x.source.startswith("seuils fixes de démarrage (historique sain insuffisant : 5/20"), True)
check("seuil fixe de student", x.services[S]["seuil_ms"], 50.0)
dg, _ = diagnostician(now_state(p95={E: 0.1}), timeline=chaos_points(healthy_timeline(), 55))
check("enrollment à 100 ms < seuil fixe 155 ms : sain", dg.diagnose(NOW2).services[E]["degrade"], False)

dg, _ = diagnostician(now_state(), ready={S: 0})
x = dg.diagnose(NOW2)
check("aucun réplica prêt : dégradé", (x.services[S]["degrade"], x.services[S]["raisons"]), (True, ["aucun réplica prêt"]))

dg, _ = diagnostician(now_state(rate5={E: 3.0}))
x = dg.diagnose(NOW2)
check("30 % de 5xx : dégradé", (x.services[E]["degrade"], x.services[E]["taux_5xx"]), (True, 0.3))
dg, _ = diagnostician(now_state(rate={E: 0.2}, rate5={E: 0.2}))
check("trafic trop faible pour juger les erreurs", dg.diagnose(NOW2).services[E]["degrade"], False)

# --- base de données : il faut au moins 2 services lents vers elle ---
dg, _ = diagnostician(now_state(dbp95={S: 0.5}))
x = dg.diagnose(NOW2)
check("un seul client lent vers la base : Postgres non dégradé", (x.db["degrade"], "postgres" in x.degraded_nodes), (False, False))
dg, _ = diagnostician(now_state(dbp95={S: 0.5, E: 0.6}))
check("deux clients lents : Postgres dégradé", "postgres" in dg.diagnose(NOW2).degraded_nodes, True)
st = now_state(); st["dbp95"] = {}
dg, _ = diagnostician(st)
try:
    dg.diagnose(NOW2); raised = False
except d.DiagnosticUnavailable as e:
    raised = "non vérifiable" in str(e)
check("latences vers la base absentes : refus", raised, True)

# --- caches : cohérence au sein d'un cycle, baseline rafraîchie chaque minute ---
dg, prom = diagnostician(now_state())
dg.diagnose(NOW2); n = len(prom.calls)
dg.diagnose(NOW2)
check("même cycle : aucune nouvelle requête", len(prom.calls), n)
dg.diagnose(NOW2 + timedelta(seconds=30))
ranges = lambda: len([c for c in prom.calls if c[0] == "range"])
check("30 s plus tard : baseline réutilisée", ranges(), 9)
dg.diagnose(NOW2 + timedelta(seconds=90))
check("90 s plus tard : baseline recalculée", ranges(), 18)

# ---------------------------------------------------------------------
# Étape 7 : cause racine sur le graphe de dépendances
# ---------------------------------------------------------------------
DEPS = {E: [S, T, "postgres"], S: ["postgres"], T: ["postgres"]}
def diag(bad, deps=DEPS):
    return d.Diagnosis(source="test", services={}, db={}, deps=deps, degraded_nodes=set(bad))
check("service seul dégradé : cause = lui-même", diag({E}).roots_for(E), {E})
check("enrollment + student : cause = student", diag({E, S}).roots_for(E), {S})
check("student est sa propre cause", diag({E, S}).roots_for(S), {S})
check("deux causes indépendantes", diag({E, S, T}).roots_for(E), {S, T})
check("tous dégradés + Postgres : cause = Postgres", diag({E, S, T, "postgres"}).roots_for(E), {"postgres"})
check("teacher + Postgres : cause = Postgres", diag({T, "postgres"}).roots_for(T), {"postgres"})
cyc = {E: [S], S: [E]}
try:
    diag({E, S}, cyc).roots_for(E); raised = False
except d.DiagnosticUnavailable as e:
    raised = "cause ambiguë" in str(e)
check("cycle entre nœuds dégradés : cause ambiguë", raised, True)
check("cycle non dégradé : sans effet", diag({E}, cyc).roots_for(E), {E})


# ---------------------------------------------------------------------
# Scénarios de bout en bout : moteur complet (invariants 1 à 6), faux Prometheus
# ---------------------------------------------------------------------
class FakeReader:
    def __init__(self, lines): self.lines = lines
    def read_lines(self): return list(self.lines)


def proposal(action, target, age_s=5):
    return {"timestamp": (NOW - timedelta(seconds=age_s)).isoformat(), "source": "decideur-naif",
            "action": action, "target": target, "namespace": "university-app",
            "reason": "test", "details": {}}


class FakeAudit:
    """Faux historique : garde les verdicts et notifications reçus."""
    configured = True
    def __init__(self): self.verdicts, self.notifications = [], []
    def record_verdict(self, verdict, cause_key, cause_group): self.verdicts.append((verdict, cause_key, cause_group))
    def record_notification(self, *args): self.notifications.append(args)
    def flush(self): return True


class FakeNotifier:
    """Faux notifieur : garde les alertes demandées."""
    configured = True
    def __init__(self): self.sent = []
    def submit(self, message, group_id, cause_key, services): self.sent.append((message, group_id, cause_key, services)); return "queued"
    def wait(self, timeout=0): pass


def run_engine(proposals, state, ready=None, timeline=None, fail=False, registry=None, schema=None,
               audit=None, notifier=None):
    cluster = FakeCluster(ready)
    prom = FakeProm(state, timeline if timeline is not None else healthy_timeline(), fail)
    dg = d.Diagnostician(prom, cluster, CFG)
    lines = ["ACTION_PROPOSAL:" + json.dumps(p) for p in proposals]
    saved = list(m.INVARIANTS)
    if registry is not None:
        m.INVARIANTS[:] = registry
    logbuf = io.StringIO()
    handler = logging.StreamHandler(logbuf)
    m.logger.addHandler(handler)
    try:
        eng = m.Engine(CFG, FakeReader(lines), started_at=START, cluster=cluster,
                       diagnostic=dg, schema=schema, audit=audit, notifier=notifier)
        with contextlib.redirect_stdout(io.StringIO()):
            verdicts = eng.run_cycle(NOW)
    finally:
        m.INVARIANTS[:] = saved
        m.logger.removeHandler(handler)
    return {(v["proposal"]["action"], v["proposal"]["target"]): v for v in verdicts}, prom, logbuf.getvalue()


# --- scénario 1 : enrollment sans réplica prêt ---
v, _, _ = run_engine([proposal("Restart", E)], now_state(), ready={E: 0})
r = v[("Restart", E)]
check("S1 : refus par le quorum seulement", (r["verdict"], r["invariant_violated"]), ("DENY", ["invariant1_quorum"]))
check("S1 : enrollment est sa propre cause", r["evidence"]["invariant6_cause_racine"]["causes_racines"], [E])

# --- scénario 3 : student lent, enrollment lent par propagation ---
s3 = now_state(p95={S: 2.4, E: 4.0}, dbp95={S: 0.5})
v, _, logs = run_engine([proposal("Restart", S), proposal("Restart", E)], s3)
check("S3 : Restart(student) autorisé", v[("Restart", S)]["verdict"], "ALLOW")
r = v[("Restart", E)]
check("S3 : Restart(enrollment) refusé (cause = student)", (r["verdict"], r["invariant_violated"]), ("DENY", ["invariant6_cause_racine"]))
check("S3 : message", "cause racine probable = student-service" in r["justification"], True)
check("S3 : pas d'alerte Postgres", r["alerts"], [])

# --- scénario 4 : teacher-admin saturé, enrollment ralenti ---
s4 = now_state(p95={T: 3.0, E: 0.3})
v, _, _ = run_engine([proposal("Restart", E), proposal("Restart", T)], s4)
check("S4 : Restart(enrollment) refusé (cause = teacher-admin)", (v[("Restart", E)]["verdict"], "teacher-admin-service" in v[("Restart", E)]["justification"]), ("DENY", True))
check("S4 : Restart(teacher-admin) autorisé (c'est la cause)", v[("Restart", T)]["verdict"], "ALLOW")

# --- scénario 5 : enrollment seul lent (latence sur ses propres paquets) ---
s5 = now_state(p95={E: 0.4}, dbp95={E: 0.3})
v, _, _ = run_engine([proposal("Restart", E)], s5)
check("S5 : enrollment seul en cause : autorisé par l'invariant 6", v[("Restart", E)]["verdict"], "ALLOW")

# --- scénario 6 : student sans réplica prêt, enrollment en erreur et lent ---
s6 = drop(now_state(p95={E: 4.5}, rate5={E: 2.6}), "p95", S)
v, _, _ = run_engine([proposal("Restart", S), proposal("Restart", E)], s6, ready={S: 0})
r = v[("Restart", S)]
check("S6 : Restart(student) refusé par le quorum, pas par la cause racine", r["invariant_violated"], ["invariant1_quorum"])
r = v[("Restart", E)]
check("S6 : Restart(enrollment) refusé (cause = student)", (r["verdict"], r["invariant_violated"]), ("DENY", ["invariant6_cause_racine"]))
check("S6 : cause désignée", r["evidence"]["invariant6_cause_racine"]["causes_racines"], [S])

# --- scénario 7 : Postgres lent, les trois services dégradés ---
s7 = now_state(p95={S: 3.0, E: 4.0, T: 3.0}, dbp95={S: 2.5, E: 2.5, T: 2.5})
props = [proposal("Restart", S), proposal("Restart", E), proposal("Restart", T)]
v, prom7, logs = run_engine(props, s7)
check("S7 : les 3 restarts refusés", sorted((k[1], x["verdict"]) for k, x in v.items()), sorted([(S, "DENY"), (E, "DENY"), (T, "DENY")]))
check("S7 : cause = postgres partout", all(x["evidence"]["invariant6_cause_racine"]["causes_racines"] == ["postgres"] for x in v.values()), True)
check("S7 : alerte dans chaque verdict", all(x["alerts"][0]["action_suggeree"] == "InvestigateDB" for x in v.values()), True)
check("S7 : alerte journalisée une seule fois (délai de 60 s)", logs.count("ALERTE"), 1)
check("S7 : services dégradés listés", v[("Restart", S)]["alerts"][0]["services_degrades"], sorted([S, E, T]))
check("S7 : un seul diagnostic pour les 3 propositions", len([c for c in prom7.calls if c[0] == "instant"]), 7)

# --- cas limites ---
v, _, _ = run_engine([proposal("Restart", S)], now_state())
r = v[("Restart", S)]
check("service sain : l'invariant 6 ne reproche rien", (r["verdict"], "causes_racines" in r["evidence"]["invariant6_cause_racine"]), ("ALLOW", False))

v, _, _ = run_engine([proposal("Restart", E)], s6, fail=True)
r = v[("Restart", E)]
check("Prometheus muet : refus", (r["verdict"], r["invariant_violated"]), ("DENY", ["invariant6_cause_racine"]))
check("Prometheus muet : message", "Données insuffisantes" in r["justification"], True)

nodb = now_state(); nodb["dbp95"] = {}
v, _, _ = run_engine([proposal("Restart", E)], nodb)
check("pas de latence vers la base : refus", "non vérifiable" in v[("Restart", E)]["justification"], True)

# --- l'invariant 6 s'applique aussi aux ScaleUp et ScaleDown (agir sur un symptôme ne sert à rien) ---
# (le faux cluster est à 2 réplicas, minimum 2 : un ScaleDown y viole aussi l'invariant 5, d'où les "in")
v, _, _ = run_engine([proposal("ScaleUp", T), proposal("ScaleDown", E), proposal("ScaleUp", E)], s4)
check("S4 : ScaleUp(teacher) : teacher est la cause, l'invariant 6 ne dit rien",
      ("invariant6_cause_racine" in v[("ScaleUp", T)]["invariant_checked"], v[("ScaleUp", T)]["invariant_violated"]), (True, []))
check("S4 : ScaleDown(enrollment) refusé par l'invariant 6 : enrollment n'est qu'un symptôme de teacher-admin",
      (v[("ScaleDown", E)]["verdict"], "invariant6_cause_racine" in v[("ScaleDown", E)]["invariant_violated"]), ("DENY", True))
check("S4 : message", "cause racine probable = teacher-admin-service" in v[("ScaleDown", E)]["justification"], True)
check("S4 : ScaleUp(enrollment) refusé aussi", v[("ScaleUp", E)]["invariant_violated"], ["invariant6_cause_racine"])
v, _, _ = run_engine([proposal("ScaleDown", E)], s5)
check("S5 : ScaleDown(enrollment) : enrollment est la cause, seul l'invariant 5 refuse",
      ("invariant6_cause_racine" in v[("ScaleDown", E)]["invariant_checked"], v[("ScaleDown", E)]["invariant_violated"]), (True, ["invariant5_hpa_min"]))
v, _, _ = run_engine([proposal("ScaleUp", T), proposal("ScaleDown", S)], s7)
check("S7 : ScaleUp et ScaleDown refusés par l'invariant 6 (cause = postgres)",
      sorted(k[0] for k, x in v.items() if "invariant6_cause_racine" in x["invariant_violated"]), ["ScaleDown", "ScaleUp"])

# --- Rollback : l'invariant 6 s'applique aussi (registre limité à l'invariant 6) ---
only6 = [("invariant6_cause_racine", m.invariant_root_cause)]
v, _, _ = run_engine([proposal("Rollback", E)], s6, ready={S: 0}, registry=only6)
check("Rollback(enrollment) refusé (cause = student)", (v[("Rollback", E)]["verdict"], v[("Rollback", E)]["invariant_violated"]), ("DENY", ["invariant6_cause_racine"]))

# --- le diagnostic n'est pas configuré ---
saved = list(m.INVARIANTS)
m.INVARIANTS[:] = only6
eng = m.Engine(CFG, FakeReader(["ACTION_PROPOSAL:" + json.dumps(proposal("Restart", S))]), started_at=START)
with contextlib.redirect_stdout(io.StringIO()):
    out = eng.run_cycle(NOW)
m.INVARIANTS[:] = saved
check("diagnostic non configuré : refus", (out[0]["verdict"], "diagnostic non configuré" in out[0]["justification"]), ("DENY", True))


# ---------------------------------------------------------------------
# Alertes et historique de bout en bout : UNE alerte par cause racine
# ---------------------------------------------------------------------
def with_alerts(proposals, state, **kw):
    audit, notifier = FakeAudit(), FakeNotifier()
    v, prom, logs = run_engine(proposals, state, audit=audit, notifier=notifier, **kw)
    return v, audit, notifier

# S7 : trois services lents à cause de Postgres = UNE alerte
v, audit, notifier = with_alerts([proposal("Restart", S), proposal("Restart", E), proposal("Restart", T)], s7)
check("S7 : 3 refus, 1 seule alerte", (len(v), len(notifier.sent)), (3, 1))
msg, group, key, services = notifier.sent[0]
check("S7 : le message dit « 3 services lents », la cause et le conseil",
      ("3 service(s) lent(s)" in msg, "postgres" in msg, "investigation de la base de données" in msg), (True, True, True))
check("S7 : clé et services concernés", (key, services), ("cause:postgres", sorted([S, E, T, "postgres"])))
check("S7 : les 3 verdicts sont dans l'historique avec le même groupe",
      ({g for _, _, g in audit.verdicts}, [k for _, k, _ in audit.verdicts], len(audit.verdicts)), ({group}, ["cause:postgres"] * 3, 3))
check("S7 : le verdict porte sa cause et dit si le groupe est nouveau",
      sorted(x["cause"]["new_group"] for x in v.values()), [False, False, True])

# S3 : student redémarré, enrollment refusé (symptôme), relance de student refusée (anti-flapping)
p_s2 = proposal("Restart", S); p_s2["details"] = {"attempt": 2}
v, audit, notifier = with_alerts([proposal("Restart", E), proposal("Restart", S), p_s2], s3)
check("S3 : 1 ALLOW, 2 DENY", sorted(r[0]["verdict"] for r in audit.verdicts), ["ALLOW", "DENY", "DENY"])
check("S3 : les deux refus (symptôme, relance) partagent la cause student : UNE alerte", len(notifier.sent), 1)
check("S3 : alerte sur la cause student", notifier.sent[0][2], "cause:student-service")
check("S3 : l'ALLOW n'a pas de cause ni d'alerte", [(r[1], r[2]) for r in audit.verdicts if r[0]["verdict"] == "ALLOW"], [(None, None)])

# S6 : student sans pod prêt + enrollment symptôme = même groupe, UNE alerte
v, audit, notifier = with_alerts([proposal("Restart", S), proposal("Restart", E)], s6, ready={S: 0})
check("S6 : student en panne + enrollment symptôme : UNE alerte", (len(notifier.sent), notifier.sent[0][2]), (1, "cause:student-service"))

# Deux causes indépendantes = deux alertes
v, audit, notifier = with_alerts([proposal("Restart", S), proposal("Restart", T)], now_state(), ready={S: 0, T: 0})
check("deux services en panne indépendants : 2 alertes", sorted(x[2] for x in notifier.sent), ["cause:student-service", "cause:teacher-admin-service"])

# Aucun refus = aucune alerte ; tout est quand même dans l'historique
v, audit, notifier = with_alerts([proposal("Restart", S)], now_state())
check("ALLOW seul : aucune alerte, 1 ligne d'historique", (len(notifier.sent), len(audit.verdicts), audit.verdicts[0][0]["verdict"]), (0, 1, "ALLOW"))

# Sans identifiants Twilio (notifieur par défaut) : le message est enregistré avec le statut disabled
audit = FakeAudit()
v, _, _ = run_engine([proposal("Restart", S), proposal("Restart", E), proposal("Restart", T)], s7, audit=audit)
check("sans Twilio : 1 message enregistré, statut disabled, texte conservé",
      (len(audit.notifications), audit.notifications[0][2], "postgres" in audit.notifications[0][3]), (1, "disabled", True))

# Même cause, mais plus de 10 minutes plus tard : nouvelle alerte
cluster = FakeCluster({S: 0})
prom = FakeProm(now_state(), healthy_timeline())
notifier = FakeNotifier()
eng = m.Engine(CFG, FakeReader([]), started_at=START, cluster=cluster,
               diagnostic=d.Diagnostician(prom, cluster, CFG), audit=FakeAudit(), notifier=notifier)
def one_cycle(p, at):
    eng.reader.lines = ["ACTION_PROPOSAL:" + json.dumps(p)]
    with contextlib.redirect_stdout(io.StringIO()): eng.run_cycle(at)
p1 = proposal("Restart", S, age_s=5); p1["details"] = {"attempt": 1}
p2 = proposal("Restart", S, age_s=5); p2["details"] = {"attempt": 2}
p3 = proposal("Restart", S, age_s=5); p3["details"] = {"attempt": 3}
for p, at in ((p1, NOW), (p2, NOW + timedelta(seconds=60)), (p3, NOW + timedelta(seconds=60 + 650))):
    p = dict(p); p["timestamp"] = (at - timedelta(seconds=5)).isoformat()
    one_cycle(p, at)
check("même cause : pas de nouvelle alerte à 60 s, nouvelle alerte après 10 min de silence", len(notifier.sent), 2)

# Un historique ou un notifieur en panne ne gêne pas le moteur
class BrokenAudit(FakeAudit):
    def record_verdict(self, *a): raise RuntimeError("base en panne")
class BrokenNotifier(FakeNotifier):
    def submit(self, *a): raise RuntimeError("twilio en panne")
v, _, _ = run_engine([proposal("Restart", S), proposal("Restart", E)], s3, audit=BrokenAudit(), notifier=BrokenNotifier())
check("historique et notifieur en panne : les verdicts sortent quand même", sorted(x["verdict"] for x in v.values()), ["ALLOW", "DENY"])

print("\nTOUS LES TESTS PASSENT" if OK else "\nDES TESTS ÉCHOUENT")
