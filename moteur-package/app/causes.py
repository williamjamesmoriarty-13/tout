"""
causes.py — Regroupement des refus par cause racine et messages d'alerte
=======================================================================
Un incident réel produit souvent plusieurs refus (trois services lents à cause
de Postgres, un service en panne et ses dépendants...). On ne veut qu'UNE alerte
par cause racine, pas une par refus.

Clé de cause d'un DENY :
- si l'invariant 6 a désigné une ou plusieurs causes racines : "cause:postgres",
  "cause:student-service", "cause:enrollment-service+teacher-admin-service" ;
- sinon le service visé est lui-même la cause : "cause:<service>"
  (quorum, schéma, anti-flapping, bornes du HPA).
Ainsi « student sans pod prêt » et « enrollment lent à cause de student »
tombent dans le même groupe : "cause:student-service".

Un groupe reste ouvert tant que de nouveaux refus de même cause arrivent
dans les `ttl` secondes ; au-delà, un nouveau refus ouvre un nouveau groupe
(donc une nouvelle alerte).
"""

from datetime import datetime

MAX_MESSAGE_CHARS = 1500   # limite WhatsApp : 1600 caractères


def short(name: str) -> str:
    """student-service -> student ; postgres reste postgres."""
    return name[:-len("-service")] if name.endswith("-service") else name


def _violation(verdict: dict, invariant: str) -> dict | None:
    for v in verdict.get("violations", []):
        if v.get("invariant") == invariant:
            return v
    return None


def cause_roots(verdict: dict) -> list[str]:
    """Cause(s) racine(s) d'un refus : celles de l'invariant 6, sinon le service visé."""
    v6 = _violation(verdict, "invariant6_cause_racine")
    if v6:
        roots = v6.get("evidence", {}).get("causes_racines")
        if roots:
            return sorted(roots)
    return [verdict.get("proposal", {}).get("target", "inconnu")]


def cause_key(verdict: dict) -> str | None:
    """Clé de regroupement d'un DENY ; None pour un ALLOW."""
    if verdict.get("verdict") != "DENY":
        return None
    return "cause:" + "+".join(cause_roots(verdict))


def affected_services(verdict: dict) -> list[str]:
    """Services concernés par l'incident : causes, services dégradés, service visé."""
    names = set(cause_roots(verdict))
    v6 = _violation(verdict, "invariant6_cause_racine")
    if v6:
        names.update(v6.get("evidence", {}).get("noeuds_degrades", []))
    target = verdict.get("proposal", {}).get("target")
    if target:
        names.add(target)
    return sorted(names)


class CauseGrouper:
    """Décide si un refus ouvre un nouveau groupe (donc une nouvelle alerte)."""

    def __init__(self, ttl_s: int):
        self.ttl = ttl_s
        self._groups: dict[str, dict] = {}

    def observe(self, key: str, now: datetime) -> tuple[str, bool]:
        """Retourne (identifiant du groupe, True si le groupe vient d'être ouvert)."""
        group = self._groups.get(key)
        if group and (now - group["last"]).total_seconds() <= self.ttl:
            group["last"] = now
            group["count"] += 1
            return group["id"], False
        group_id = f"{key}|{int(now.timestamp())}"
        self._groups[key] = {"id": group_id, "first": now, "last": now, "count": 1}
        self._purge(now)
        return group_id, True

    def _purge(self, now: datetime) -> None:
        self._groups = {k: g for k, g in self._groups.items()
                        if (now - g["last"]).total_seconds() <= self.ttl * 6}


ADVICE = {
    "invariant1_quorum": "Conseil : vérifier l'état des pods ({s}).",
    "invariant2_schema": "Conseil : corriger en avant (nouvelle version) plutôt que revenir en arrière.",
    "invariant3_anti_flapping": "Conseil : laisser l'action précédente aboutir (rollout en cours).",
    "invariant4_hpa_max": "Conseil : service saturé, augmenter maxReplicas ou réduire la charge.",
    "invariant5_hpa_min": "Conseil : rien à faire, le service est déjà au minimum.",
}


def build_message(verdict: dict, recent_actions: list[dict] | None = None) -> str:
    """
    Message d'alerte (français, court) pour le premier refus d'un groupe.
    recent_actions : actions déjà exécutées sur les causes racines,
    [{"target", "action", "ago_s", "simulated"}].
    """
    proposal = verdict.get("proposal", {})
    action, target = proposal.get("action", "?"), proposal.get("target", "?")
    roots = cause_roots(verdict)
    v6 = _violation(verdict, "invariant6_cause_racine")
    lines = []

    if v6:
        degraded = [n for n in v6.get("evidence", {}).get("noeuds_degrades", []) if n != "postgres"]
        if roots == ["postgres"]:
            lines.append(f"🔴 Moteur de sûreté : {len(degraded)} service(s) lent(s) "
                         f"({', '.join(short(n) for n in degraded)}).")
            lines.append("Cause racine probable : postgres.")
            lines.append(f"{action} sur {short(target)} refusé : inutile tant que la base est en cause.")
            lines.append("Conseil : faire une investigation de la base de données.")
        else:
            cause = ", ".join(short(r) for r in roots)
            touched = [n for n in degraded if n not in roots]
            lines.append(f"🔴 Moteur de sûreté : cause racine probable = {cause}.")
            if touched:
                lines.append(f"Services touchés : {', '.join(short(n) for n in touched)}.")
            lines.append(f"{action} sur {short(target)} refusé (symptôme, pas la cause).")
            lines.append(f"Conseil : traiter {cause} plutôt que {short(target)}.")
    else:
        lines.append(f"🔴 Moteur de sûreté : {verdict.get('justification', 'action refusée')}")
        for invariant in verdict.get("invariant_violated", []):
            if invariant in ADVICE:
                lines.append(ADVICE[invariant].format(s=short(target)))
                break

    for act in recent_actions or []:
        note = " (simulé)" if act.get("simulated") else ""
        lines.append(f"Déjà fait : {act['action']} sur {short(act['target'])} "
                     f"il y a {int(act['ago_s'])} s{note}.")
    return "\n".join(lines)[:MAX_MESSAGE_CHARS]
