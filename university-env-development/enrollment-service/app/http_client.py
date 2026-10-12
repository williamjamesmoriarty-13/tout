import requests

from .logging_utils import Timer, log_outbound_call
from .metrics import OUTBOUND_CALLS


class DownstreamError(Exception):
    """Erreur générique levée quand un appel vers un service dépendant échoue.
    Le message est volontairement générique côté client final ; le détail
    technique reste seulement dans les logs internes."""

    def __init__(self, target_service: str, status_code: int = None):
        self.target_service = target_service
        self.status_code = status_code
        super().__init__(f"Appel vers {target_service} en échec")


def call_service(
    logger,
    service_name: str,
    target_service: str,
    method: str,
    url: str,
    trace_id: str,
    timeout: float,
    **kwargs,
) -> requests.Response:
    """Effectue un appel HTTP sortant vers un autre service, en loggant
    systématiquement le résultat (succès ou échec) avec la latence."""
    headers = kwargs.pop("headers", {}) or {}
    headers["X-Trace-Id"] = trace_id
    path = url.split("://", 1)[-1]
    path = "/" + path.split("/", 1)[1] if "/" in path else "/"

    with Timer() as t:
        try:
            response = requests.request(
                method, url, timeout=timeout, headers=headers, **kwargs
            )
        except requests.exceptions.RequestException as exc:
            log_outbound_call(
                logger,
                service_name,
                target_service,
                method,
                path,
                outcome="failure",
                latency_ms=t.elapsed_ms if hasattr(t, "elapsed_ms") else 0.0,
                trace_id=trace_id,
                error=str(exc),
            )
            OUTBOUND_CALLS.labels(
                target_service=target_service, outcome="failure"
            ).inc()
            raise DownstreamError(target_service) from exc

    if response.status_code >= 400:
        log_outbound_call(
            logger,
            service_name,
            target_service,
            method,
            path,
            outcome="failure",
            latency_ms=t.elapsed_ms,
            trace_id=trace_id,
            status_code=response.status_code,
        )
        OUTBOUND_CALLS.labels(
            target_service=target_service, outcome="failure"
        ).inc()
        raise DownstreamError(target_service, status_code=response.status_code)

    log_outbound_call(
        logger,
        service_name,
        target_service,
        method,
        path,
        outcome="success",
        latency_ms=t.elapsed_ms,
        trace_id=trace_id,
        status_code=response.status_code,
    )
    OUTBOUND_CALLS.labels(
        target_service=target_service, outcome="success"
    ).inc()
    return response
