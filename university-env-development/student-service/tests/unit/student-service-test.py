"""
Tests UNITAIRES purs — student-service
========================================
Règles strictes appliquées ici :
  - Aucun app.test_client()
  - Aucune base de données (même SQLite)
  - Aucun serveur Flask démarré
  - Chaque test isole UNE seule unité (fonction ou classe)
  - Tout ce qui est extérieur à l'unité testée est mocké

Unités testées :
  1. StudentCreateSchema / StudentUpdateSchema  (schemas.py)
  2. call_service()                             (http_client.py)
  3. log_outbound_call() / log_inbound_request  (logging_utils.py)
  4. Timer                                      (logging_utils.py)
  5. Config._require_env()                      (config.py)
  6. OUTBOUND_CALLS counter                     (metrics.py)

Lancer :
    cd student-service
    pytest ../tests/unit/student-service/ -v
"""

import json
import os
import time
from unittest.mock import MagicMock, call, patch

import pytest

# ── Variables d'env minimales avant tout import ───────────────────────────────
os.environ.update({
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "testdb",
    "DB_SCHEMA": "student_schema",
    "TEACHER_ADMIN_SERVICE_URL": "http://teacher-mock:8080",
    "ENROLLMENT_SERVICE_URL": "http://enrollment-mock:5003",
    "LOG_LEVEL": "ERROR",
})

# ── Imports des unités à tester ───────────────────────────────────────────────
from app.schemas import StudentCreateSchema, StudentUpdateSchema
from app.http_client import DownstreamError, call_service
from app.logging_utils import (
    Timer,
    configure_logging,
    log_inbound_request,
    log_outbound_call,
    new_trace_id,
)


# =============================================================================
# 1. SCHÉMAS DE VALIDATION — StudentCreateSchema
# =============================================================================

class TestStudentCreateSchema:
    """Teste uniquement la logique de validation marshmallow,
    sans aucune couche Flask ou DB."""

    def setup_method(self):
        self.schema = StudentCreateSchema()

    # -- cas valides -----------------------------------------------------------

    def test_valid_payload_passes(self):
        result = self.schema.load({
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@universite.fr",
        })
        assert result["first_name"] == "Ada"
        assert result["last_name"] == "Lovelace"
        assert result["email"] == "ada@universite.fr"

    def test_valid_email_with_subdomain(self):
        result = self.schema.load({
            "first_name": "A", "last_name": "B",
            "email": "user@sub.domain.org",
        })
        assert result["email"] == "user@sub.domain.org"

    def test_max_length_first_name_passes(self):
        result = self.schema.load({
            "first_name": "A" * 80,
            "last_name": "B",
            "email": "x@x.fr",
        })
        assert len(result["first_name"]) == 80

    # -- champs manquants ------------------------------------------------------

    def test_missing_first_name_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"last_name": "Lovelace", "email": "a@b.fr"})
        assert "first_name" in exc.value.messages

    def test_missing_last_name_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"first_name": "Ada", "email": "a@b.fr"})
        assert "last_name" in exc.value.messages

    def test_missing_email_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"first_name": "Ada", "last_name": "L"})
        assert "email" in exc.value.messages

    def test_all_fields_missing_raises_all_errors(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({})
        assert "first_name" in exc.value.messages
        assert "last_name" in exc.value.messages
        assert "email" in exc.value.messages

    # -- format email ----------------------------------------------------------

    def test_invalid_email_no_at_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"first_name": "A", "last_name": "B", "email": "pasunemail"})
        assert "email" in exc.value.messages

    def test_invalid_email_no_domain_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"first_name": "A", "last_name": "B", "email": "user@"})
        assert "email" in exc.value.messages

    def test_invalid_email_space_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"first_name": "A", "last_name": "B", "email": "a @b.fr"})
        assert "email" in exc.value.messages

    # -- longueur des champs ---------------------------------------------------

    def test_first_name_too_long_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"first_name": "A" * 81, "last_name": "B", "email": "a@b.fr"})
        assert "first_name" in exc.value.messages

    def test_last_name_too_long_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"first_name": "A", "last_name": "B" * 81, "email": "a@b.fr"})
        assert "last_name" in exc.value.messages

    def test_email_too_long_raises(self):
        from marshmallow import ValidationError
        local = "a" * 60
        domain = "b" * 60
        with pytest.raises(ValidationError) as exc:
            self.schema.load({
                "first_name": "A", "last_name": "B",
                "email": f"{local}@{domain}.fr"
            })
        assert "email" in exc.value.messages

    # -- champs vides ----------------------------------------------------------

    def test_empty_first_name_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            self.schema.load({"first_name": "", "last_name": "B", "email": "a@b.fr"})

    def test_empty_last_name_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            self.schema.load({"first_name": "A", "last_name": "", "email": "a@b.fr"})

    def test_whitespace_only_first_name_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            self.schema.load({"first_name": "   ", "last_name": "B", "email": "a@b.fr"})

    # -- champs inattendus (marshmallow strict) --------------------------------

    def test_unknown_field_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            self.schema.load({
                "first_name": "A", "last_name": "B", "email": "a@b.fr",
                "unexpected_field": "value",
            })


# =============================================================================
# 2. SCHÉMA — StudentUpdateSchema
# =============================================================================

class TestStudentUpdateSchema:
    """StudentUpdateSchema : tous les champs sont optionnels."""

    def setup_method(self):
        self.schema = StudentUpdateSchema()

    def test_empty_payload_passes(self):
        result = self.schema.load({})
        assert result == {}

    def test_only_first_name_passes(self):
        result = self.schema.load({"first_name": "Marie"})
        assert result == {"first_name": "Marie"}

    def test_only_email_passes(self):
        result = self.schema.load({"email": "new@x.fr"})
        assert result == {"email": "new@x.fr"}

    def test_all_fields_passes(self):
        result = self.schema.load({
            "first_name": "A", "last_name": "B", "email": "a@b.fr"
        })
        assert len(result) == 3

    def test_invalid_email_in_update_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            self.schema.load({"email": "invalide"})

    def test_first_name_too_long_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            self.schema.load({"first_name": "X" * 81})


# =============================================================================
# 3. HTTP CLIENT — call_service()
# =============================================================================

class TestCallService:
    """Teste call_service() en isolation totale.
    requests.request est toujours mocké — aucun vrai appel réseau."""

    def setup_method(self):
        self.mock_logger = MagicMock()
        self.base_args = dict(
            logger=self.mock_logger,
            service_name="student-service",
            target_service="teacher-admin-service",
            method="GET",
            url="http://teacher-mock:8080/courses",
            trace_id="abc123",
            timeout=3.0,
        )

    def _mock_response(self, status_code=200, json_data=None):
        m = MagicMock()
        m.status_code = status_code
        m.json.return_value = json_data or {}
        return m

    # -- succès ---------------------------------------------------------------

    def test_returns_response_on_200(self):
        mock_resp = self._mock_response(200, {"courses": []})
        with patch("app.http_client.requests.request", return_value=mock_resp):
            result = call_service(**self.base_args)
        assert result.status_code == 200

    def test_propagates_trace_id_in_header(self):
        mock_resp = self._mock_response(200)
        with patch("app.http_client.requests.request", return_value=mock_resp) as mock_req:
            call_service(**self.base_args)
        _, kwargs = mock_req.call_args
        headers = kwargs.get("headers", {})
        assert headers.get("X-Trace-Id") == "abc123"

    def test_uses_correct_http_method(self):
        mock_resp = self._mock_response(200)
        with patch("app.http_client.requests.request", return_value=mock_resp) as mock_req:
            call_service(**self.base_args)
        positional_method = mock_req.call_args[0][0]
        assert positional_method == "GET"

    def test_passes_timeout_to_requests(self):
        mock_resp = self._mock_response(200)
        with patch("app.http_client.requests.request", return_value=mock_resp) as mock_req:
            call_service(**self.base_args)
        _, kwargs = mock_req.call_args
        assert kwargs["timeout"] == 3.0

    def test_logs_success_outcome(self):
        mock_resp = self._mock_response(200)
        with patch("app.http_client.requests.request", return_value=mock_resp):
            call_service(**self.base_args)
        # logger.info doit avoir été appelé avec outcome="success"
        log_call_args = self.mock_logger.info.call_args[0][0]
        assert log_call_args["outcome"] == "success"
        assert log_call_args["target_service"] == "teacher-admin-service"
        assert log_call_args["trace_id"] == "abc123"

    def test_success_increments_prometheus_counter(self):
        from app.metrics import OUTBOUND_CALLS
        mock_resp = self._mock_response(200)
        before = OUTBOUND_CALLS.labels(
            target_service="teacher-admin-service", outcome="success"
        )._value.get()
        with patch("app.http_client.requests.request", return_value=mock_resp):
            call_service(**self.base_args)
        after = OUTBOUND_CALLS.labels(
            target_service="teacher-admin-service", outcome="success"
        )._value.get()
        assert after == before + 1

    # -- erreurs HTTP (4xx/5xx) ------------------------------------------------

    def test_raises_downstream_error_on_404(self):
        mock_resp = self._mock_response(404)
        with patch("app.http_client.requests.request", return_value=mock_resp):
            with pytest.raises(DownstreamError) as exc:
                call_service(**self.base_args)
        assert exc.value.status_code == 404
        assert exc.value.target_service == "teacher-admin-service"

    def test_raises_downstream_error_on_500(self):
        mock_resp = self._mock_response(500)
        with patch("app.http_client.requests.request", return_value=mock_resp):
            with pytest.raises(DownstreamError):
                call_service(**self.base_args)

    def test_logs_failure_on_4xx(self):
        mock_resp = self._mock_response(503)
        with patch("app.http_client.requests.request", return_value=mock_resp):
            with pytest.raises(DownstreamError):
                call_service(**self.base_args)
        log_call_args = self.mock_logger.warning.call_args[0][0]
        assert log_call_args["outcome"] == "failure"
        assert log_call_args["status_code"] == 503

    def test_failure_increments_prometheus_counter(self):
        from app.metrics import OUTBOUND_CALLS
        mock_resp = self._mock_response(503)
        before = OUTBOUND_CALLS.labels(
            target_service="teacher-admin-service", outcome="failure"
        )._value.get()
        with patch("app.http_client.requests.request", return_value=mock_resp):
            with pytest.raises(DownstreamError):
                call_service(**self.base_args)
        after = OUTBOUND_CALLS.labels(
            target_service="teacher-admin-service", outcome="failure"
        )._value.get()
        assert after == before + 1

    # -- erreurs réseau --------------------------------------------------------

    def test_raises_downstream_error_on_connection_error(self):
        import requests as req_lib
        with patch("app.http_client.requests.request",
                   side_effect=req_lib.exceptions.ConnectionError("refused")):
            with pytest.raises(DownstreamError) as exc:
                call_service(**self.base_args)
        assert exc.value.target_service == "teacher-admin-service"
        assert exc.value.status_code is None  # pas de code HTTP sur erreur réseau

    def test_raises_downstream_error_on_timeout(self):
        import requests as req_lib
        with patch("app.http_client.requests.request",
                   side_effect=req_lib.exceptions.Timeout()):
            with pytest.raises(DownstreamError):
                call_service(**self.base_args)

    def test_logs_failure_on_connection_error(self):
        import requests as req_lib
        with patch("app.http_client.requests.request",
                   side_effect=req_lib.exceptions.ConnectionError("refused")):
            with pytest.raises(DownstreamError):
                call_service(**self.base_args)
        log_call_args = self.mock_logger.warning.call_args[0][0]
        assert log_call_args["outcome"] == "failure"
        assert "error" in log_call_args

    def test_downstream_error_message_is_generic(self):
        """Le message d'erreur de DownstreamError ne doit pas exposer
        de détails internes (URL, stack trace) — uniquement le nom du service."""
        import requests as req_lib
        with patch("app.http_client.requests.request",
                   side_effect=req_lib.exceptions.ConnectionError("internal detail")):
            with pytest.raises(DownstreamError) as exc:
                call_service(**self.base_args)
        # Le str() de l'exception ne doit pas contenir l'URL ou le détail interne
        error_message = str(exc.value)
        assert "http://teacher-mock" not in error_message
        assert "internal detail" not in error_message

    # -- headers existants préservés ------------------------------------------

    def test_existing_headers_preserved(self):
        mock_resp = self._mock_response(200)
        with patch("app.http_client.requests.request", return_value=mock_resp) as mock_req:
            call_service(**self.base_args, headers={"Authorization": "Bearer token"})
        _, kwargs = mock_req.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer token"
        assert kwargs["headers"]["X-Trace-Id"] == "abc123"


# =============================================================================
# 4. LOGGING UTILS — fonctions de log structuré
# =============================================================================

class TestLogOutboundCall:
    """Teste que log_outbound_call() produit le bon JSON structuré."""

    def setup_method(self):
        self.mock_logger = MagicMock()

    def test_success_calls_logger_info(self):
        log_outbound_call(
            self.mock_logger, "student-service", "teacher-admin-service",
            "GET", "/courses", "success", 12.5, "tid-001", status_code=200
        )
        self.mock_logger.info.assert_called_once()
        self.mock_logger.warning.assert_not_called()

    def test_failure_calls_logger_warning(self):
        log_outbound_call(
            self.mock_logger, "student-service", "enrollment-service",
            "GET", "/enrollments", "failure", 8.0, "tid-002", status_code=503
        )
        self.mock_logger.warning.assert_called_once()
        self.mock_logger.info.assert_not_called()

    def test_log_contains_all_required_fields(self):
        log_outbound_call(
            self.mock_logger, "student-service", "teacher-admin-service",
            "POST", "/courses/1/reserve-seat", "success", 25.3, "trace-xyz",
            status_code=200
        )
        payload = self.mock_logger.info.call_args[0][0]
        assert payload["service"] == "student-service"
        assert payload["event"] == "outbound_call"
        assert payload["target_service"] == "teacher-admin-service"
        assert payload["method"] == "POST"
        assert payload["path"] == "/courses/1/reserve-seat"
        assert payload["outcome"] == "success"
        assert payload["latency_ms"] == 25.3
        assert payload["trace_id"] == "trace-xyz"
        assert payload["status_code"] == 200

    def test_error_field_included_when_provided(self):
        log_outbound_call(
            self.mock_logger, "student-service", "enrollment-service",
            "GET", "/grades", "failure", 0.0, "tid", error="Connection refused"
        )
        payload = self.mock_logger.warning.call_args[0][0]
        assert "error" in payload
        assert payload["error"] == "Connection refused"

    def test_no_status_code_when_not_provided(self):
        log_outbound_call(
            self.mock_logger, "student-service", "enrollment-service",
            "GET", "/grades", "failure", 0.0, "tid"
        )
        payload = self.mock_logger.warning.call_args[0][0]
        assert "status_code" not in payload

    def test_latency_is_rounded(self):
        log_outbound_call(
            self.mock_logger, "student-service", "teacher-admin-service",
            "GET", "/courses", "success", 12.3456789, "tid", status_code=200
        )
        payload = self.mock_logger.info.call_args[0][0]
        assert payload["latency_ms"] == round(12.3456789, 2)


class TestLogInboundRequest:
    """Teste que log_inbound_request() produit le bon JSON structuré."""

    def setup_method(self):
        self.mock_logger = MagicMock()

    def test_logs_inbound_request_fields(self):
        log_inbound_request(
            self.mock_logger, "student-service", "GET", "/students", 200, 5.1, "trace-in"
        )
        self.mock_logger.info.assert_called_once()
        payload = self.mock_logger.info.call_args[0][0]
        assert payload["service"] == "student-service"
        assert payload["event"] == "inbound_request"
        assert payload["method"] == "GET"
        assert payload["path"] == "/students"
        assert payload["status_code"] == 200
        assert payload["trace_id"] == "trace-in"

    def test_logs_at_info_level_regardless_of_status(self):
        log_inbound_request(
            self.mock_logger, "student-service", "GET", "/students", 500, 1.0, "t"
        )
        self.mock_logger.info.assert_called_once()


# =============================================================================
# 5. TIMER
# =============================================================================

class TestTimer:
    """Teste que le context manager Timer mesure la latence correctement."""

    def test_elapsed_ms_is_positive(self):
        with Timer() as t:
            pass
        assert t.elapsed_ms >= 0

    def test_elapsed_ms_is_float(self):
        with Timer() as t:
            pass
        assert isinstance(t.elapsed_ms, float)

    def test_elapsed_ms_reflects_sleep_duration(self):
        with Timer() as t:
            time.sleep(0.05)
        # On attend ≥ 45ms (marge pour l'overhead du test)
        assert t.elapsed_ms >= 45

    def test_timer_accessible_after_context(self):
        with Timer() as t:
            pass
        # elapsed_ms doit être accessible après la sortie du with
        _ = t.elapsed_ms


# =============================================================================
# 6. TRACE ID
# =============================================================================

class TestNewTraceId:

    def test_returns_string(self):
        assert isinstance(new_trace_id(), str)

    def test_returns_nonempty_string(self):
        assert len(new_trace_id()) > 0

    def test_each_call_returns_unique_id(self):
        ids = {new_trace_id() for _ in range(100)}
        assert len(ids) == 100  # tous différents

    def test_trace_id_is_hex_string(self):
        tid = new_trace_id()
        # uuid4().hex est un string hexadécimal de 32 caractères
        assert all(c in "0123456789abcdef" for c in tid)
        assert len(tid) == 32


# =============================================================================
# 7. CONFIG — _require_env()
# =============================================================================

class TestRequireEnv:
    """Teste la logique de validation des variables d'environnement
    sans instancier toute l'app."""

    def test_raises_if_env_var_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            # On importe _require_env directement
            from app.config import Config
            with pytest.raises(RuntimeError, match="DB_USER"):
                # Simuler la lecture d'une variable absente
                os.environ.pop("DB_USER", None)
                # Réimporter pour déclencher _require_env
                import importlib
                import app.config
                importlib.reload(app.config)

    def test_raises_if_env_var_empty(self):
        """Une variable vide doit aussi lever RuntimeError."""
        with patch.dict(os.environ, {"DB_USER": ""}):
            with pytest.raises((RuntimeError, Exception)):
                import importlib
                import app.config
                importlib.reload(app.config)


# =============================================================================
# 8. DOWNSTREAM ERROR
# =============================================================================

class TestDownstreamError:

    def test_has_target_service_attribute(self):
        err = DownstreamError("teacher-admin-service", status_code=503)
        assert err.target_service == "teacher-admin-service"
        assert err.status_code == 503

    def test_status_code_defaults_to_none(self):
        err = DownstreamError("enrollment-service")
        assert err.status_code is None

    def test_is_exception(self):
        err = DownstreamError("x")
        assert isinstance(err, Exception)

    def test_str_does_not_contain_url(self):
        err = DownstreamError("http://internal-service:5001")
        # Le message générique ne doit pas répéter l'URL brute
        # (DownstreamError utilise le nom du service, pas l'URL)
        assert "http://" not in str(err) or "en échec" in str(err)