"""
decideur.py — Naive Healer
==========================
Surveille Prometheus toutes les 10 secondes et propose des actions
de remédiation basées sur des règles simples (if/else sur métriques).

Il est intentionnellement naïf :
- Il ne vérifie pas si son action est sûre
- Il ne sait pas que la DB a changé de schéma
- Il ne sait pas si un restart va casser le quorum
- Il ne sait pas si le HPA est déjà au maximum

C'est le rôle du moteur de vérification de bloquer ses mauvaises
décisions — le décideur existe pour générer des propositions, pas
pour les valider.

Chaque proposition est un objet JSON structuré envoyé au moteur
(via stdout pour l'instant — le moteur le lira depuis là).

Révision : correction des requêtes PromQL (label `job` au lieu de
`service_name`), famille de métriques explicite par service, distinction
« Prometheus en panne » / « pas de données » / « NaN », fenêtre de 2 min.
Une proposition n'est émise qu'UNE fois par épisode d'anomalie (plus de
doublons toutes les 10 s) et InvestigateDB exige que TOUS les services
soient dégradés en même temps (latence > seuil OU aucun pod prêt).
ScaleUp sur CPU saturé (CPU / requests) quand le HPA est au maximum, évalué
avant le Restart de latence.
"""

import os
import math
import time
import json
import logging
from datetime import datetime, timezone

import requests

# ============================================================
# Configuration
# ============================================================
PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://prometheus.monitoring.svc.cluster.local:9090"
)
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "10"))
APP_NAMESPACE         = os.environ.get("APP_NAMESPACE", "university-app")
LOG_LEVEL             = os.environ.get("LOG_LEVEL", "INFO")

# Fenêtre des rate() : au moins 4x l'intervalle de scrape pour rester stable
RATE_WINDOW = os.environ.get("RATE_WINDOW", "2m")
# Une ligne INFO « cycle OK » tous les N cycles (1 = à chaque cycle)
HEARTBEAT_EVERY_CYCLES = max(1, int(os.environ.get("HEARTBEAT_EVERY_CYCLES", "6")))

# Seuils calibrés sur les observations réelles des 8 scénarios de chaos
THRESHOLDS = {
    # Latence P95 en secondes (calibré sur scénario 3 : 400ms, scénario 7 : 8-10s)
    "latency_p95_seconds": float(os.environ.get("THRESHOLD_LATENCY_P95", "0.5")),
    # Taux d'erreur 5xx = ratio 5xx / total (calibré sur scénario 2 : HTTPChaos injecte des 500)
    "error_rate_5xx":      float(os.environ.get("THRESHOLD_ERROR_RATE", "0.10")),
    # Durée minimale d'anomalie avant proposition (évite les faux positifs)
    "anomaly_duration_s":  int(os.environ.get("THRESHOLD_ANOMALY_DURATION", "60")),
    # Nombre de pods ready minimum (quorum)
    "min_replicas_ready":  int(os.environ.get("THRESHOLD_MIN_REPLICAS", "1")),
    # CPU consommé / CPU demandé (requests) au-delà duquel un service est saturé
    "cpu_saturation":      float(os.environ.get("THRESHOLD_CPU", "0.9")),
}

# Famille de métriques applicatives exposée par chaque service.
# Dans Prometheus, toutes portent le label job="<service>".
FLASK, SPRING = "flask", "spring"
SERVICE_FAMILY = {
    "student-service":       FLASK,
    "enrollment-service":    FLASK,
    "teacher-admin-service": SPRING,
}
SERVICES = list(SERVICE_FAMILY)

# InvestigateDB seulement si TOUS les services sont dégradés en même temps
# (scénario 7 : cause racine DB). Volontairement non configurable : la variable
# THRESHOLD_CASCADE du chart est ignorée.
THRESHOLDS["cascade_services_threshold"] = len(SERVICES)

APP_METRICS = {
    FLASK: {
        "bucket": "flask_http_request_duration_seconds_bucket",
        "count":  "flask_http_request_total",
    },
    SPRING: {
        "bucket": "http_server_requests_seconds_bucket",
        "count":  "http_server_requests_seconds_count",
    },
}

logging.basicConfig(
    level=LOG_LEVEL,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
           '"service": "decideur", "message": %(message)s}',
    datefmt="%Y-%m-%dT%H:%M:%S+00:00"
)
logger = logging.getLogger("decideur")

# ============================================================
# Historique des anomalies (pour respecter anomaly_duration_s)
# ============================================================
anomaly_start: dict = {}     # clé d'anomalie → datetime de début de l'épisode
proposed_keys: set  = set()  # épisodes pour lesquels une proposition a déjà été émise
last_action:   dict = {}     # service → dernière action proposée + timestamp


# ============================================================
# Requêtes Prometheus
# ============================================================
class PrometheusUnavailable(Exception):
    """Prometheus injoignable ou réponse en erreur (≠ « pas de données »)."""


def query_prometheus(promql: str) -> list:
    """
    Exécute une requête PromQL et retourne la liste de résultats.
    - liste vide  → la requête a réussi mais ne renvoie aucune série
    - exception   → Prometheus est injoignable ou a répondu en erreur
    """
    try:
        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql},
            timeout=5
        )
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError) as e:
        raise PrometheusUnavailable(str(e)) from e

    if body.get("status") != "success":
        raise PrometheusUnavailable(
            f"réponse en échec : {body.get('error', body.get('status'))}"
        )
    return body.get("data", {}).get("result", [])


def scalar(result: list) -> float | None:
    """
    Première valeur d'un résultat instantané, en float.
    None si le résultat est vide, illisible, NaN ou infini.
    """
    if not result:
        return None
    try:
        value = float(result[0]["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def _as_int(result: list) -> int | None:
    value = scalar(result)
    return int(value) if value is not None else None


def get_latency_p95(service: str) -> float | None:
    """Latence P95 en secondes (None = pas de trafic ou pas de données)."""
    bucket = APP_METRICS[SERVICE_FAMILY[service]]["bucket"]
    return scalar(query_prometheus(
        f'histogram_quantile(0.95, '
        f'sum(rate({bucket}{{job="{service}"}}[{RATE_WINDOW}])) by (le))'
    ))


def get_error_rate_5xx(service: str) -> float | None:
    """
    Ratio de requêtes 5xx (0.0 à 1.0).
    None si le service ne reçoit aucun trafic (taux indéfini).
    Une absence de série 5xx alors qu'il y a du trafic = 0 erreur.
    """
    count = APP_METRICS[SERVICE_FAMILY[service]]["count"]
    total = scalar(query_prometheus(
        f'sum(rate({count}{{job="{service}"}}[{RATE_WINDOW}]))'
    ))
    if total is None or total <= 0:
        return None
    errors = scalar(query_prometheus(
        f'sum(rate({count}{{job="{service}", status=~"5.."}}[{RATE_WINDOW}]))'
    )) or 0.0
    return errors / total


def get_replicas_ready(service: str) -> int | None:
    """Nombre de réplicas prêts pour un déploiement."""
    return _as_int(query_prometheus(
        f'kube_deployment_status_replicas_ready'
        f'{{namespace="{APP_NAMESPACE}", deployment="{service}"}}'
    ))


def get_hpa_max_replicas(service: str) -> int | None:
    """MaxReplicas configuré dans le HPA (None s'il n'y a pas de HPA)."""
    return _as_int(query_prometheus(
        f'kube_horizontalpodautoscaler_spec_max_replicas'
        f'{{namespace="{APP_NAMESPACE}", horizontalpodautoscaler="{service}"}}'
    ))


def get_current_replicas(service: str) -> int | None:
    """Nombre de réplicas actuellement désirés par le déploiement."""
    return _as_int(query_prometheus(
        f'kube_deployment_spec_replicas'
        f'{{namespace="{APP_NAMESPACE}", deployment="{service}"}}'
    ))


def get_cpu_utilization(service: str) -> float | None:
    """
    CPU consommé / CPU demandé (requests) pour l'ensemble des pods du service.
    1.0 = 100 % des requests (même base que l'utilisation mesurée par le HPA).
    None si les métriques cAdvisor ou les requests sont absentes.
    """
    pods = f'pod=~"{service}-.+"'
    usage = scalar(query_prometheus(
        f'sum(rate(container_cpu_usage_seconds_total'
        f'{{namespace="{APP_NAMESPACE}", {pods}, container!="", container!="POD"}}'
        f'[{RATE_WINDOW}]))'
    ))
    requested = scalar(query_prometheus(
        f'sum(kube_pod_container_resource_requests'
        f'{{namespace="{APP_NAMESPACE}", {pods}, resource="cpu"}})'
    ))
    if usage is None or not requested:
        return None
    return usage / requested


def collect_metrics() -> dict:
    """Collecte les métriques de tous les services (lève PrometheusUnavailable)."""
    return {
        svc: {
            "latency_p95":      get_latency_p95(svc),
            "error_rate_5xx":   get_error_rate_5xx(svc),
            "replicas_ready":   get_replicas_ready(svc),
            "current_replicas": get_current_replicas(svc),
            "hpa_max_replicas": get_hpa_max_replicas(svc),
            "cpu_utilization":  get_cpu_utilization(svc),
        }
        for svc in SERVICES
    }


# ============================================================
# Logique de détection et proposition d'actions
# ============================================================
def check_anomaly_duration(key: str, is_anomaly: bool) -> bool:
    """
    Retourne True UNE SEULE FOIS par épisode d'anomalie : quand elle dure
    depuis assez longtemps pour justifier une proposition d'action.
    Le suivi se réarme quand l'anomalie disparaît (is_anomaly=False).
    """
    now = datetime.now(timezone.utc)
    if not is_anomaly:
        anomaly_start.pop(key, None)
        proposed_keys.discard(key)
        return False
    start = anomaly_start.setdefault(key, now)
    if key in proposed_keys:
        return False
    if (now - start).total_seconds() >= THRESHOLDS["anomaly_duration_s"]:
        proposed_keys.add(key)
        return True
    return False


def already_proposed(key: str) -> bool:
    """True si une proposition a déjà été émise pour l'épisode en cours."""
    return key in proposed_keys


def propose_action(action: str, target: str, reason: str,
                   details: dict | None = None) -> dict:
    """Construit et logue une proposition d'action structurée."""
    proposal = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "source":     "decideur-naif",
        "action":     action,
        "target":     target,
        "namespace":  APP_NAMESPACE,
        "reason":     reason,
        "details":    details or {},
    }
    # Log structuré — le moteur lira ce JSON depuis stdout/logs du pod
    print(f"ACTION_PROPOSAL:{json.dumps(proposal)}", flush=True)
    logger.info(json.dumps(
        f"Proposition → {action}({target}) : {reason}"
    ))
    last_action[target] = {"action": action, "timestamp": datetime.now(timezone.utc)}
    return proposal


def degraded_services(metrics: dict) -> list:
    """
    Services dégradés : latence P95 au-dessus du seuil OU aucun pod prêt
    (sans pod prêt il n'y a pas de p95 exploitable, mais le service est HS).
    """
    return [
        svc for svc, m in metrics.items()
        if m.get("replicas_ready") == 0
        or (m.get("latency_p95") is not None
            and m["latency_p95"] > THRESHOLDS["latency_p95_seconds"])
    ]


def detect_cascade_db(metrics: dict) -> bool:
    """
    Détecte si TOUS les services sont dégradés simultanément
    (signe probable d'une cause racine commune comme Postgres).
    """
    return len(degraded_services(metrics)) >= THRESHOLDS["cascade_services_threshold"]


def analyze_service(service: str, metrics: dict) -> dict | None:
    """
    Analyse les métriques d'un service et retourne une proposition
    d'action si une anomalie est détectée depuis assez longtemps.
    """
    m = metrics[service]
    latency    = m.get("latency_p95")
    error_rate = m.get("error_rate_5xx")
    ready      = m.get("replicas_ready")
    current    = m.get("current_replicas")
    hpa_max    = m.get("hpa_max_replicas")
    cpu        = m.get("cpu_utilization")

    # ────────────────────────────────────────────────────────
    # Règle 1 : Réplicas_Ready = 0 → Restart
    # ────────────────────────────────────────────────────────
    if ready is not None and ready == 0:
        if check_anomaly_duration(f"{service}_quorum", True):
            return propose_action(
                action="Restart",
                target=service,
                reason="Aucun réplica disponible (ready=0)",
                details={"replicas_ready": ready, "current_replicas": current}
            )
        if already_proposed(f"{service}_quorum"):
            return None  # déjà proposé pour cet épisode : pas de règle suivante
    else:
        check_anomaly_duration(f"{service}_quorum", False)

    # ────────────────────────────────────────────────────────
    # Règle 2 : Taux d'erreur 5xx > seuil → Rollback
    # (signe d'une régression après déploiement)
    # ────────────────────────────────────────────────────────
    if error_rate is not None and error_rate > THRESHOLDS["error_rate_5xx"]:
        if check_anomaly_duration(f"{service}_errors", True):
            return propose_action(
                action="Rollback",
                target=service,
                reason=f"Taux d'erreur 5xx élevé ({error_rate:.1%})",
                details={"error_rate_5xx": round(error_rate, 4)}
            )
        if already_proposed(f"{service}_errors"):
            return None  # déjà proposé pour cet épisode : pas de règle suivante
    else:
        check_anomaly_duration(f"{service}_errors", False)

    # ────────────────────────────────────────────────────────
    # Règle 3 : CPU saturé + HPA au max → ScaleUp (inutile mais naïf)
    # Évaluée AVANT le Restart de latence : une latence causée par un CPU
    # saturé doit donner un ScaleUp, pas un Restart.
    # ────────────────────────────────────────────────────────
    if (cpu is not None and cpu > THRESHOLDS["cpu_saturation"]
            and current is not None and hpa_max is not None
            and current >= hpa_max):
        if check_anomaly_duration(f"{service}_cpu", True):
            return propose_action(
                action="ScaleUp",
                target=service,
                reason=f"CPU saturé ({cpu:.0%} des requests) et HPA au maximum "
                       f"({current}/{hpa_max} réplicas)",
                details={"cpu_utilization": round(cpu, 3),
                         "current_replicas": current, "hpa_max": hpa_max}
            )
        if already_proposed(f"{service}_cpu"):
            return None  # déjà proposé pour cet épisode : pas de règle suivante
    else:
        check_anomaly_duration(f"{service}_cpu", False)

    # ────────────────────────────────────────────────────────
    # Règle 4 : Latence P95 > seuil → Restart
    # ────────────────────────────────────────────────────────
    if latency is not None and latency > THRESHOLDS["latency_p95_seconds"]:
        if check_anomaly_duration(f"{service}_latency", True):
            return propose_action(
                action="Restart",
                target=service,
                reason=f"Latence P95 élevée ({latency*1000:.0f}ms > "
                       f"{THRESHOLDS['latency_p95_seconds']*1000:.0f}ms)",
                details={"latency_p95_ms": round(latency * 1000, 1)}
            )
        if already_proposed(f"{service}_latency"):
            return None  # déjà proposé pour cet épisode : pas de règle suivante
    else:
        check_anomaly_duration(f"{service}_latency", False)

    # ────────────────────────────────────────────────────────
    # Règle 5 : Latence modérée → ScaleDown (logique naïve dangereuse)
    # ────────────────────────────────────────────────────────
    if (latency is not None
            and 0.1 < latency <= THRESHOLDS["latency_p95_seconds"]
            and current is not None and current > 1):
        if check_anomaly_duration(f"{service}_scaledown", True):
            return propose_action(
                action="ScaleDown",
                target=service,
                reason=f"Latence légèrement élevée ({latency*1000:.0f}ms), "
                       f"tentative de réduction de charge",
                details={"latency_p95_ms": round(latency * 1000, 1),
                         "current_replicas": current}
            )
        if already_proposed(f"{service}_scaledown"):
            return None  # déjà proposé pour cet épisode : pas de règle suivante
    else:
        check_anomaly_duration(f"{service}_scaledown", False)

    return None


# ============================================================
# Boucle principale
# ============================================================
def _fmt_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 1000:.0f}ms"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def summarize(metrics: dict) -> str:
    """Résumé compact d'un cycle, pour la ligne INFO « cycle OK »."""
    return " | ".join(
        f"{svc}: p95={_fmt_ms(m['latency_p95'])} "
        f"5xx={_fmt_pct(m['error_rate_5xx'])} "
        f"cpu={_fmt_pct(m.get('cpu_utilization'))} "
        f"ready={m['replicas_ready']}/{m['current_replicas']}"
        for svc, m in metrics.items()
    )


def main():
    logger.info(json.dumps(
        f"Démarrage du décideur naïf — polling toutes les "
        f"{POLL_INTERVAL_SECONDS}s, seuils: {THRESHOLDS}"
    ))

    cycle = 0
    while True:
        cycle += 1
        try:
            metrics = collect_metrics()

            logger.debug(json.dumps(f"Métriques collectées : {metrics}"))
            if (cycle - 1) % HEARTBEAT_EVERY_CYCLES == 0:
                logger.info(json.dumps(f"Cycle OK — {summarize(metrics)}"))

            # Détection de cascade (scénario 7 : cause racine Postgres)
            # Soumise comme les autres règles à anomaly_duration_s,
            # et émise une seule fois par épisode.
            cascade = detect_cascade_db(metrics)
            if check_anomaly_duration("cascade_db", cascade):
                degraded = degraded_services(metrics)
                propose_action(
                    action="InvestigateDB",
                    target="postgres",
                    reason=f"{len(degraded)} services dégradés simultanément "
                           f"({', '.join(degraded)}) — cause racine probable : Postgres",
                    details={"degraded_services": degraded}
                )
            elif not cascade:
                # Analyse individuelle de chaque service
                for svc in SERVICES:
                    analyze_service(svc, metrics)

        except PrometheusUnavailable as e:
            # Un seul warning par cycle ; on ignore le cycle sans toucher
            # à l'historique des anomalies (aucune décision à l'aveugle).
            logger.warning(json.dumps(
                f"Prometheus inaccessible, cycle ignoré : {str(e)[:200]}"
            ))
        except Exception as e:
            logger.error(json.dumps(f"Erreur inattendue dans la boucle : {e}"))

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()