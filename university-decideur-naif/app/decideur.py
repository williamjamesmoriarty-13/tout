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
- Il ne cherche pas la cause racine : chaque service est traité seul

Naïf ne veut pas dire absurde : chacune de ses règles doit rester plausible
avec l'information qu'il a (une règle locale raisonnable qui devient
dangereuse globalement). C'est le rôle du moteur de vérification de bloquer
ses mauvaises décisions — le décideur existe pour générer des propositions,
pas pour les valider.

Chaque proposition est un objet JSON structuré envoyé au moteur
(via stdout pour l'instant — le moteur le lira depuis là).

Révision 1 : correction des requêtes PromQL (label `job` au lieu de
`service_name`), famille de métriques explicite par service, distinction
« Prometheus en panne » / « pas de données » / « NaN », fenêtre de 2 min.

Révision 2 (règles plausibles) :
- Rollback seulement si les erreurs 5xx suivent un CHANGEMENT D'IMAGE récent
  (une autre image a tourné sur ce service dans la fenêtre de déploiement).
  Sinon, des 5xx se traitent par un Restart. La proposition de Rollback
  porte l'image précédente et sa version dans `details`.
- « ready=0 » n'est une panne que si le pod le plus récent a dépassé la
  période de démarrage (sinon c'est simplement un service qui démarre).
- ScaleDown (latence modérée) seulement si le CPU est bas : « lent mais
  sous-utilisé, donc sur-dimensionné ».

Révision 3 :
- Plus de détection de cascade : quand plusieurs services sont dégradés,
  chacun reçoit sa propre proposition (le moteur trouve la cause racine).
- Une proposition est retentée UNE fois (2 tentatives au total, à
  THRESHOLD_RETRY_AFTER secondes d'intervalle) tant que l'anomalie dure.
  Les tentatives d'un même service et d'une même règle partagent un
  `incident_id` (details.incident_id, details.attempt) pour que le moteur
  sache qu'il s'agit du même incident et non de plusieurs.
- ScaleUp se déclenche sur le seul CPU saturé : le décideur ignore le
  nombre de réplicas et le maximum du HPA.

Révision 4 (démarrages) : mesuré sur 15 h d'historique, un redémarrage du
cluster ou le début d'un test k6 fait dépasser 90 % de CPU à teacher-admin
(JVM qui chauffe) pendant 1 à 3 minutes, et sa P95 dépasse 500 ms jusqu'à
90 s. Deux protections :
- Garde « cluster en démarrage » : si les trois services ont été à 0 réplica
  prêt EN MÊME TEMPS pendant les THRESHOLD_BOOT_GRACE dernières secondes,
  l'analyse est suspendue et les épisodes repartent de zéro. La panne d'un
  seul service (scénarios de chaos, restart exécuté par le moteur) ne la
  déclenche jamais.
- Un CPU saturé doit durer THRESHOLD_CPU_DURATION secondes (240 par défaut,
  au-dessus des 180 s maximum observées pour un pic de démarrage) : un
  pic de chauffe n'est pas une saturation.

Révision 5 (erreurs 409/422) :
- Un taux élevé de 409/422 (conflit, validation) déclenche un Rollback
  UNIQUEMENT si un changement d'image a eu lieu dans la fenêtre de
  déploiement (deploy_window_s). Sans déploiement récent, aucune
  proposition n'est émise (ni Restart, ni autre action) : ce sont des
  erreurs client « normales ».
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
    # Taux de 409/422 (ratio / total) au-delà duquel un nouveau déploiement
    # est suspecté de régression (validation, contrainte d'unicité, schéma)
    "error_rate_409_422":  float(os.environ.get("THRESHOLD_ERROR_RATE_409_422", "0.10")),
    # Durée minimale d'anomalie avant proposition (évite les faux positifs)
    "anomaly_duration_s":  int(os.environ.get("THRESHOLD_ANOMALY_DURATION", "60")),
    # Nombre de pods ready minimum (quorum)
    "min_replicas_ready":  int(os.environ.get("THRESHOLD_MIN_REPLICAS", "1")),
    # CPU consommé / CPU demandé (requests) au-delà duquel un service est saturé
    "cpu_saturation":      float(os.environ.get("THRESHOLD_CPU", "0.9")),
    # CPU / requests en dessous duquel un service est jugé sous-utilisé
    "cpu_low":             float(os.environ.get("THRESHOLD_CPU_LOW", "0.3")),
    # Fenêtre (s) pendant laquelle un changement d'image compte comme « déploiement récent ».
    # À garder plus grande que le délai entre le déploiement et l'injection du chaos.
    "deploy_window_s":     int(os.environ.get("THRESHOLD_DEPLOY_WINDOW", "900")),
    # Âge (s) du pod le plus récent en dessous duquel « ready=0 » = démarrage normal
    "startup_grace_s":     int(os.environ.get("THRESHOLD_STARTUP_GRACE", "180")),
    # Nouvelle tentative : délai (s) après la proposition précédente
    "retry_after_s":       int(os.environ.get("THRESHOLD_RETRY_AFTER", "60")),
    # Nombre total de propositions par incident (1 = pas de nouvelle tentative)
    "max_attempts":        int(os.environ.get("THRESHOLD_MAX_ATTEMPTS", "2")),
    # Durée (s) pendant laquelle le CPU doit rester saturé avant un ScaleUp
    # (les pics de chauffe de la JVM au démarrage durent jusqu'à 180 s)
    "cpu_duration_s":      int(os.environ.get("THRESHOLD_CPU_DURATION", "240")),
    # Après un redémarrage complet du cluster (3 services à 0 prêt en même
    # temps), durée (s) pendant laquelle l'analyse reste suspendue
    "boot_grace_s":        int(os.environ.get("THRESHOLD_BOOT_GRACE", "300")),
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
# Historique des anomalies et des incidents
# ============================================================
anomaly_start: dict = {}   # clé d'anomalie → datetime de début de l'épisode
incidents:     dict = {}   # clé d'anomalie → {"id", "attempts", "last"} (propositions émises)
last_action:   dict = {}   # service → dernière action proposée + timestamp


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


def get_error_rate_409_422(service: str) -> float | None:
    """
    Ratio de requêtes 409 ou 422 (0.0 à 1.0).
    None si le service ne reçoit aucun trafic (taux indéfini).
    Une absence de série 409/422 alors qu'il y a du trafic = 0 erreur.
    """
    count = APP_METRICS[SERVICE_FAMILY[service]]["count"]
    total = scalar(query_prometheus(
        f'sum(rate({count}{{job="{service}"}}[{RATE_WINDOW}]))'
    ))
    if total is None or total <= 0:
        return None
    errors = scalar(query_prometheus(
        f'sum(rate({count}{{job="{service}", status=~"409|422"}}[{RATE_WINDOW}]))'
    )) or 0.0
    return errors / total


def get_replicas_ready(service: str) -> int | None:
    """Nombre de réplicas prêts pour un déploiement."""
    return _as_int(query_prometheus(
        f'kube_deployment_status_replicas_ready'
        f'{{namespace="{APP_NAMESPACE}", deployment="{service}"}}'
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


def get_youngest_pod_age(service: str) -> float | None:
    """
    Âge en secondes du pod le plus récent du service (None si inconnu).
    Sert à distinguer « service en cours de démarrage » de « service en panne ».
    """
    return scalar(query_prometheus(
        f'time() - max(kube_pod_created'
        f'{{namespace="{APP_NAMESPACE}", pod=~"{service}-.+"}})'
    ))


def _image_tag(image: str) -> str | None:
    """Tag d'une image (« docker.io/darbi/x:1.7 » → « 1.7 »), None si absent/digest."""
    name = image.rsplit("/", 1)[-1]
    if "@" in name or ":" not in name:
        return None
    return name.split(":", 1)[1]


def get_recent_deployment(service: str) -> dict | None:
    """
    Détecte un changement d'image récent sur le service.

    On compare les images des pods vus pendant la fenêtre de déploiement
    à celles des pods actuels. Un simple restart ne change pas l'image
    (contrairement à ce que laisserait croire le nombre de ReplicaSets,
    car `rollout restart` en crée un aussi).

    Retourne None s'il n'y a pas de changement d'image récent, si un rollout
    est encore en cours (plusieurs images actuelles) ou si l'info est absente.
    """
    pods = f'pod=~"{service}-.+"'
    window = f'{THRESHOLDS["deploy_window_s"]}s'
    seen = query_prometheus(
        f'count by (image) (count_over_time('
        f'kube_pod_container_info{{namespace="{APP_NAMESPACE}", {pods}}}[{window}]))'
    )
    current = query_prometheus(
        f'count by (image) (kube_pod_container_info'
        f'{{namespace="{APP_NAMESPACE}", {pods}}})'
    )
    seen_images = sorted({r["metric"]["image"] for r in seen if r.get("metric", {}).get("image")})
    current_images = sorted({r["metric"]["image"] for r in current if r.get("metric", {}).get("image")})

    if len(current_images) != 1:
        return None
    previous = [i for i in seen_images if i not in current_images]
    if not previous:
        return None
    return {
        "current_image":   current_images[0],
        "previous_images": previous,
        # Une seule image précédente → version cible non ambiguë pour le moteur
        "target_version":  _image_tag(previous[0]) if len(previous) == 1 else None,
    }


def get_cluster_booting() -> bool:
    """
    True si les trois services ont été à 0 réplica prêt EN MÊME TEMPS pendant
    les boot_grace_s dernières secondes : le cluster (ou la machine) vient de
    redémarrer, les métriques de démarrage ne reflètent pas un fonctionnement
    normal. La panne d'un seul service ne déclenche jamais cette garde.
    Une série absente (kube-state-metrics pas encore revenu) donne False.
    """
    deployments = "|".join(SERVICES)
    window = THRESHOLDS["boot_grace_s"]
    value = scalar(query_prometheus(
        f'max_over_time((max(kube_deployment_status_replicas_ready'
        f'{{namespace="{APP_NAMESPACE}", deployment=~"{deployments}"}}) == bool 0)'
        f'[{window}s:15s])'
    ))
    return value is not None and value >= 1


def reset_episodes() -> None:
    """Efface tous les épisodes et incidents en cours (les timers repartent de zéro)."""
    anomaly_start.clear()
    incidents.clear()


def collect_metrics() -> dict:
    """Collecte les métriques de tous les services (lève PrometheusUnavailable)."""
    return {
        svc: {
            "latency_p95":        get_latency_p95(svc),
            "error_rate_5xx":     get_error_rate_5xx(svc),
            "error_rate_409_422": get_error_rate_409_422(svc),
            "replicas_ready":     get_replicas_ready(svc),
            "current_replicas":   get_current_replicas(svc),
            "cpu_utilization":    get_cpu_utilization(svc),
        }
        for svc in SERVICES
    }


# ============================================================
# Épisodes d'anomalie, incidents et nouvelles tentatives
# ============================================================
def check_anomaly_duration(key: str, is_anomaly: bool,
                           min_duration_s: int | None = None) -> bool:
    """
    Dit s'il faut émettre une proposition maintenant pour cette anomalie.

    - 1re proposition : quand l'anomalie dure depuis min_duration_s
      (anomaly_duration_s par défaut).
    - Nouvelle tentative : si l'anomalie dure toujours retry_after_s après la
      proposition précédente, dans la limite de max_attempts au total.
    - Le suivi se réarme (et l'incident se ferme) quand l'anomalie disparaît.
    """
    now = datetime.now(timezone.utc)
    if not is_anomaly:
        anomaly_start.pop(key, None)
        incidents.pop(key, None)
        return False

    start = anomaly_start.setdefault(key, now)
    needed = THRESHOLDS["anomaly_duration_s"] if min_duration_s is None else min_duration_s
    if (now - start).total_seconds() < needed:
        return False

    incident = incidents.get(key)
    if incident is None:
        incidents[key] = {
            "id":       f"{key}-{int(start.timestamp())}",
            "attempts": 1,
            "last":     now,
        }
        return True

    if (incident["attempts"] < THRESHOLDS["max_attempts"]
            and (now - incident["last"]).total_seconds() >= THRESHOLDS["retry_after_s"]):
        incident["attempts"] += 1
        incident["last"] = now
        return True
    return False


def already_proposed(key: str) -> bool:
    """True si une proposition a déjà été émise pour l'incident en cours."""
    return key in incidents


def propose_action(action: str, target: str, reason: str,
                   details: dict | None = None,
                   episode_key: str | None = None) -> dict:
    """
    Construit et logue une proposition d'action structurée.
    Si episode_key est fourni, ajoute incident_id / attempt / max_attempts
    dans details pour que le moteur relie les tentatives d'un même incident.
    """
    details = dict(details or {})
    incident = incidents.get(episode_key) if episode_key else None
    if incident:
        details["incident_id"]  = incident["id"]
        details["attempt"]      = incident["attempts"]
        details["max_attempts"] = THRESHOLDS["max_attempts"]

    proposal = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "source":     "decideur-naif",
        "action":     action,
        "target":     target,
        "namespace":  APP_NAMESPACE,
        "reason":     reason,
        "details":    details,
    }
    # Log structuré — le moteur lira ce JSON depuis stdout/logs du pod
    print(f"ACTION_PROPOSAL:{json.dumps(proposal)}", flush=True)
    logger.info(json.dumps(
        f"Proposition → {action}({target}) : {reason}"
    ))
    last_action[target] = {"action": action, "timestamp": datetime.now(timezone.utc)}
    return proposal


# ============================================================
# Logique de détection et proposition d'actions
# ============================================================
def analyze_service(service: str, metrics: dict) -> dict | None:
    """
    Analyse les métriques d'un service et retourne une proposition
    d'action si une anomalie est détectée depuis assez longtemps.
    """
    m = metrics[service]
    latency       = m.get("latency_p95")
    error_rate    = m.get("error_rate_5xx")
    error_409_422 = m.get("error_rate_409_422")
    ready         = m.get("replicas_ready")
    current       = m.get("current_replicas")
    cpu           = m.get("cpu_utilization")

    # ────────────────────────────────────────────────────────
    # Règle 1 : Réplicas_Ready = 0 → Restart
    # Garde : si le pod le plus récent vient d'être créé, le service est en
    # train de démarrer (cluster qui redémarre, restart déjà en cours) :
    # ce n'est pas une panne, on réarme sans proposer.
    # ────────────────────────────────────────────────────────
    key = f"{service}_quorum"
    starting_up = False
    if ready is not None and ready == 0:
        age = get_youngest_pod_age(service)
        starting_up = age is not None and age < THRESHOLDS["startup_grace_s"]

    if ready is not None and ready == 0 and not starting_up:
        if check_anomaly_duration(key, True):
            return propose_action(
                action="Restart",
                target=service,
                reason="Aucun réplica disponible (ready=0)",
                details={"replicas_ready": ready, "current_replicas": current},
                episode_key=key
            )
        if already_proposed(key):
            return None  # incident en cours : pas de règle suivante
    else:
        check_anomaly_duration(key, False)

    # ────────────────────────────────────────────────────────
    # Règle 2 : Taux d'erreur 5xx > seuil
    #   - après un changement d'image récent → Rollback (régression probable)
    #   - sinon → Restart (rien ne justifie de revenir en arrière)
    # ────────────────────────────────────────────────────────
    key = f"{service}_errors"
    if error_rate is not None and error_rate > THRESHOLDS["error_rate_5xx"]:
        deploy = get_recent_deployment(service)
        if check_anomaly_duration(key, True):
            details = {"error_rate_5xx": round(error_rate, 4)}
            if deploy:
                details.update(deploy)
                return propose_action(
                    action="Rollback",
                    target=service,
                    reason=f"Taux d'erreur 5xx élevé ({error_rate:.1%}) après un "
                           f"changement d'image récent",
                    details=details,
                    episode_key=key
                )
            return propose_action(
                action="Restart",
                target=service,
                reason=f"Taux d'erreur 5xx élevé ({error_rate:.1%}), "
                       f"aucun déploiement récent",
                details=details,
                episode_key=key
            )
        if already_proposed(key):
            return None  # incident en cours : pas de règle suivante
    else:
        check_anomaly_duration(key, False)

    # ────────────────────────────────────────────────────────
    # Règle 2bis : Taux de 409/422 élevé APRÈS un changement d'image récent
    # → Rollback uniquement. Sans déploiement récent (fenêtre deploy_window_s
    # dépassée ou jamais de changement), des 409/422 sont des erreurs client
    # « normales » : aucune action n'est proposée (pas de Restart).
    # Si la fenêtre se referme pendant l'épisode, l'incident est clos et
    # plus aucune nouvelle tentative n'est émise.
    # ────────────────────────────────────────────────────────
    key = f"{service}_client_errors"
    deploy_409 = None
    if error_409_422 is not None and error_409_422 > THRESHOLDS["error_rate_409_422"]:
        deploy_409 = get_recent_deployment(service)

    if deploy_409:
        if check_anomaly_duration(key, True):
            return propose_action(
                action="Rollback",
                target=service,
                reason=f"Taux d'erreurs 409/422 élevé ({error_409_422:.1%}) après "
                       f"un changement d'image récent",
                details={"error_rate_409_422": round(error_409_422, 4), **deploy_409},
                episode_key=key
            )
        if already_proposed(key):
            return None  # incident en cours : pas de règle suivante
    else:
        check_anomaly_duration(key, False)  # pas d'anomalie ou pas de déploiement récent

    # ────────────────────────────────────────────────────────
    # Règle 3 : CPU saturé → ScaleUp
    # Le décideur ne regarde que le CPU : il ignore le nombre de réplicas et
    # le maximum du HPA (c'est au moteur de vérifier qu'il reste de la marge).
    # Évaluée AVANT le Restart de latence : une latence causée par un CPU
    # saturé doit donner un ScaleUp, pas un Restart.
    # ────────────────────────────────────────────────────────
    key = f"{service}_cpu"
    if cpu is not None and cpu > THRESHOLDS["cpu_saturation"]:
        if check_anomaly_duration(key, True, THRESHOLDS["cpu_duration_s"]):
            return propose_action(
                action="ScaleUp",
                target=service,
                reason=f"CPU saturé ({cpu:.0%} des requests)",
                details={"cpu_utilization": round(cpu, 3)},
                episode_key=key
            )
        if already_proposed(key):
            return None  # incident en cours : pas de règle suivante
    else:
        check_anomaly_duration(key, False)

    # ────────────────────────────────────────────────────────
    # Règle 4 : Latence P95 > seuil → Restart
    # ────────────────────────────────────────────────────────
    key = f"{service}_latency"
    if latency is not None and latency > THRESHOLDS["latency_p95_seconds"]:
        if check_anomaly_duration(key, True):
            return propose_action(
                action="Restart",
                target=service,
                reason=f"Latence P95 élevée ({latency*1000:.0f}ms > "
                       f"{THRESHOLDS['latency_p95_seconds']*1000:.0f}ms)",
                details={"latency_p95_ms": round(latency * 1000, 1)},
                episode_key=key
            )
        if already_proposed(key):
            return None  # incident en cours : pas de règle suivante
    else:
        check_anomaly_duration(key, False)

    # ────────────────────────────────────────────────────────
    # Règle 5 : Latence modérée + CPU bas → ScaleDown
    # Raisonnement naïf mais cohérent : « le service est lent alors qu'il est
    # sous-utilisé, il est sur-dimensionné, on réduit les réplicas ».
    # Sans CPU connu ou avec un CPU élevé, la règle ne se déclenche pas.
    # ────────────────────────────────────────────────────────
    key = f"{service}_scaledown"
    if (latency is not None
            and 0.1 < latency <= THRESHOLDS["latency_p95_seconds"]
            and current is not None and current > 1
            and cpu is not None and cpu < THRESHOLDS["cpu_low"]):
        if check_anomaly_duration(key, True):
            return propose_action(
                action="ScaleDown",
                target=service,
                reason=f"Latence légèrement élevée ({latency*1000:.0f}ms) avec un "
                       f"CPU bas ({cpu:.0%} des requests) : service jugé "
                       f"sur-dimensionné",
                details={"latency_p95_ms": round(latency * 1000, 1),
                         "cpu_utilization": round(cpu, 3),
                         "current_replicas": current},
                episode_key=key
            )
        if already_proposed(key):
            return None  # incident en cours : pas de règle suivante
    else:
        check_anomaly_duration(key, False)

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
        f"409/422={_fmt_pct(m.get('error_rate_409_422'))} "
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
    was_booting = False
    while True:
        cycle += 1
        try:
            metrics = collect_metrics()

            logger.debug(json.dumps(f"Métriques collectées : {metrics}"))
            if (cycle - 1) % HEARTBEAT_EVERY_CYCLES == 0:
                logger.info(json.dumps(f"Cycle OK — {summarize(metrics)}"))

            # Redémarrage complet du cluster : les pics de démarrage (CPU de la
            # JVM, latences) ne sont pas des anomalies, on suspend l'analyse.
            if get_cluster_booting():
                if not was_booting:
                    logger.info(json.dumps(
                        "Cluster en démarrage (3 services à 0 prêt simultanément) : "
                        f"analyse suspendue pendant {THRESHOLDS['boot_grace_s']}s"
                    ))
                    reset_episodes()
                was_booting = True
            else:
                was_booting = False
                # Chaque service est analysé seul : pas de lien entre services,
                # même si plusieurs sont dégradés en même temps.
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