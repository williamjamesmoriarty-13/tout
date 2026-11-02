"""Tests du regroupement par cause racine et des messages. Lancer : python3 test_causes.py"""
from datetime import datetime, timezone, timedelta

import causes as c

OK = True


def check(label, got, want):
    global OK
    good = got == want
    OK &= good
    print(("OK  " if good else "FAIL"), label, "->", got if not good else "")


NOW = datetime(2026, 10, 19, 6, 0, 0, tzinfo=timezone.utc)
S, E, T = "student-service", "enrollment-service", "teacher-admin-service"


def deny(action, target, violated, roots=None, degraded=None, justification="refusé"):
    violations = [{"invariant": i, "message": justification, "evidence": {}} for i in violated]
    if roots is not None:
        for v in violations:
            if v["invariant"] == "invariant6_cause_racine":
                v["evidence"] = {"causes_racines": roots, "noeuds_degrades": degraded or roots}
    return {"verdict": "DENY", "proposal": {"action": action, "target": target},
            "invariant_violated": list(violated), "violations": violations,
            "justification": justification, "evidence": {}}


# --- clé de cause ---
check("ALLOW : pas de clé", c.cause_key({"verdict": "ALLOW", "proposal": {"target": S}}), None)
check("symptôme : la clé est celle de la cause (invariant 6)",
      c.cause_key(deny("Restart", E, ["invariant6_cause_racine"], roots=[S], degraded=[S, E])), "cause:student-service")
check("service en panne (quorum) : il est sa propre cause",
      c.cause_key(deny("Restart", S, ["invariant1_quorum"])), "cause:student-service")
check("S6 : student sans pod et enrollment symptôme = MÊME clé",
      c.cause_key(deny("Restart", S, ["invariant1_quorum"])),
      c.cause_key(deny("Restart", E, ["invariant6_cause_racine"], roots=[S])))
check("S7 : 3 services lents = une seule clé",
      {c.cause_key(deny("Restart", n, ["invariant6_cause_racine"], roots=["postgres"], degraded=[S, E, T, "postgres"])) for n in (S, E, T)},
      {"cause:postgres"})
check("quorum + cause racine : l'invariant 6 l'emporte",
      c.cause_key(deny("Restart", S, ["invariant1_quorum", "invariant6_cause_racine"], roots=["postgres"])), "cause:postgres")
check("S4 : ScaleUp(teacher) au maximum et ScaleDown(enrollment) symptôme = MÊME clé",
      c.cause_key(deny("ScaleUp", T, ["invariant4_hpa_max"])),
      c.cause_key(deny("ScaleDown", E, ["invariant6_cause_racine"], roots=[T])))
check("anti-flapping : rattaché à la cause du service",
      c.cause_key(deny("Restart", S, ["invariant3_anti_flapping"])), "cause:student-service")
check("plusieurs causes racines : clé composée triée",
      c.cause_key(deny("Restart", E, ["invariant6_cause_racine"], roots=[T, S])), "cause:student-service+teacher-admin-service")
check("schéma : le service visé", c.cause_key(deny("Rollback", E, ["invariant2_schema"])), "cause:enrollment-service")
check("proposition invalide sans cible : pas de plantage", c.cause_key({"verdict": "DENY", "proposal": {}, "violations": []}), "cause:inconnu")

# --- services concernés ---
check("services concernés (S7)", c.affected_services(
      deny("Restart", S, ["invariant6_cause_racine"], roots=["postgres"], degraded=[S, E, T, "postgres"])), sorted([S, E, T, "postgres"]))
check("services concernés (sans invariant 6)", c.affected_services(deny("ScaleUp", T, ["invariant4_hpa_max"])), [T])

# --- groupes ---
g = c.CauseGrouper(ttl_s=600)
id1, new1 = g.observe("cause:postgres", NOW)
check("1er refus : nouveau groupe", new1, True)
id2, new2 = g.observe("cause:postgres", NOW + timedelta(seconds=20))
check("refus suivant de même cause : même groupe, pas de nouvelle alerte", (id2 == id1, new2), (True, False))
id3, new3 = g.observe("cause:student-service", NOW + timedelta(seconds=30))
check("autre cause : nouveau groupe", (id3 != id1, new3), (True, True))
id4, new4 = g.observe("cause:postgres", NOW + timedelta(seconds=20 + 600))
check("l'activité prolonge le groupe", (id4 == id1, new4), (True, False))
id5, new5 = g.observe("cause:postgres", NOW + timedelta(seconds=20 + 600 + 601))
check("silence de plus de 600 s : nouveau groupe", (id5 != id1, new5), (True, True))
check("l'identifiant contient la clé et l'heure d'ouverture", id1, f"cause:postgres|{int(NOW.timestamp())}")

# --- messages ---
m7 = c.build_message(deny("Restart", S, ["invariant1_quorum", "invariant6_cause_racine"], roots=["postgres"], degraded=[S, E, T, "postgres"]))
check("S7 : « 3 services lents » + cause postgres + conseil BD",
      ("3 service(s) lent(s)" in m7, "student, enrollment, teacher-admin" in m7, "Cause racine probable : postgres" in m7, "investigation de la base de données" in m7), (True,) * 4)
check("S7 : une seule alerte, pas de répétition du nom complet des services", "student-service" not in m7, True)

m3 = c.build_message(deny("Restart", E, ["invariant6_cause_racine"], roots=[S], degraded=[S, E]),
                     recent_actions=[{"target": S, "action": "Restart", "ago_s": 21.4, "simulated": False}])
check("S3 : cause = student, enrollment touché, action déjà faite",
      ("cause racine probable = student" in m3, "Services touchés : enrollment" in m3, "Restart sur enrollment refusé" in m3,
       "Déjà fait : Restart sur student il y a 21 s." in m3), (True,) * 4)
check("action simulée signalée", "(simulé)" in c.build_message(deny("Restart", E, ["invariant6_cause_racine"], roots=[S]),
      recent_actions=[{"target": S, "action": "Restart", "ago_s": 5, "simulated": True}]), True)

m1 = c.build_message(deny("Restart", E, ["invariant1_quorum"], justification="Restart refusé — enrollment-service n'a aucun réplica actif (ready=0)."))
check("S1 : message de quorum avec conseil", ("aucun réplica actif" in m1, "vérifier l'état des pods (enrollment)" in m1), (True, True))
m2 = c.build_message(deny("Rollback", E, ["invariant2_schema"], justification="Rollback vers 1.6 impossible — schéma DB actuel (0002) incompatible."))
check("S2 : message de schéma avec conseil", ("schéma DB actuel (0002)" in m2, "corriger en avant" in m2), (True, True))
m4 = c.build_message(deny("ScaleUp", T, ["invariant4_hpa_max"], justification="ScaleUp impossible — teacher-admin-service est déjà au maximum (4/4)."))
check("S4 : message de capacité avec conseil", ("(4/4)" in m4, "maxReplicas" in m4), (True, True))
check("message borné", len(c.build_message(deny("Restart", S, ["invariant1_quorum"], justification="x" * 5000))) <= 1500, True)
check("noms courts", (c.short("student-service"), c.short("teacher-admin-service"), c.short("postgres")), ("student", "teacher-admin", "postgres"))

print("\nTOUS LES TESTS PASSENT" if OK else "\nDES TESTS ÉCHOUENT")
