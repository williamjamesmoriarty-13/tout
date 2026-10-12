"""
Format de log JSON commun à TOUS les services (Python et Java) du projet.
Chaque ligne de log est un objet JSON unique (JSON Lines), ce qui la rend
facilement parsable par un futur collecteur (agent OpenTelemetry, Fluentd,
ou simple grep) pour reconstruire le graphe de dépendances dynamique.

Schéma commun pour un appel sortant :
{
  "timestamp": "2026-08-01T10:00:00.123Z",
  "service": "student-service",
  "event": "outbound_call",
  "target_service": "teacher-admin-service",
  "method": "GET",
  "path": "/courses",
  "outcome": "success" | "failure",
  "status_code": 200,
  "latency_ms": 12.4,
  "trace_id": "b3c1..."
}

Schéma commun pour une requête entrante :
{
  "timestamp": "...",
  "service": "student-service",
  "event": "inbound_request",
  "method": "GET",
  "path": "/students/1",
  "status_code": 200,
  "latency_ms": 3.1,
  "trace_id": "b3c1..."
}
"""

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
        }
        if isinstance(record.msg, dict):
            payload.update(record.msg)
        else:
            payload["message"] = record.getMessage()
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service_name: str) -> logging.Logger:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger(service_name)
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


def new_trace_id() -> str:
    return uuid.uuid4().hex


def log_inbound_request(
    logger: logging.Logger,
    service_name: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    trace_id: str,
) -> None:
    logger.info(
        {
            "service": service_name,
            "event": "inbound_request",
            "method": method,
            "path": path,
            "status_code": status_code,
            "latency_ms": round(latency_ms, 2),
            "trace_id": trace_id,
        }
    )


def log_outbound_call(
    logger: logging.Logger,
    service_name: str,
    target_service: str,
    method: str,
    path: str,
    outcome: str,
    latency_ms: float,
    trace_id: str,
    status_code: int = None,
    error: str = None,
) -> None:
    entry = {
        "service": service_name,
        "event": "outbound_call",
        "target_service": target_service,
        "method": method,
        "path": path,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
        "trace_id": trace_id,
    }
    if status_code is not None:
        entry["status_code"] = status_code
    if error is not None:
        entry["error"] = error
    if outcome == "success":
        logger.info(entry)
    else:
        logger.warning(entry)


class Timer:
    """Petit chronomètre pour mesurer la latence en millisecondes."""

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
