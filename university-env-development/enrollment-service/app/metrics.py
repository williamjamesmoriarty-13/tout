"""
Instrumentation Prometheus pour enrollment-service.
Voir student-service/app/metrics.py pour le détail du raisonnement — pattern
identique, dupliqué volontairement (les 2 services Flask sont indépendants).
"""

from prometheus_client import Counter
from prometheus_flask_exporter import PrometheusMetrics

OUTBOUND_CALLS = Counter(
    "outbound_calls_total",
    "Nombre d'appels sortants effectués vers un autre service",
    ["target_service", "outcome"],
)


def init_metrics(app):
    metrics = PrometheusMetrics(app, group_by="url_rule", path="/metrics")
    metrics.info(
        "enrollment_service_info",
        "Informations statiques du service",
        version="1.0.0",
    )
    return metrics
