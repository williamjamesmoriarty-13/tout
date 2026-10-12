"""
Tests UNITAIRES purs — enrollment-service
==========================================
Règles strictes :
  - Aucun app.test_client()
  - Aucune base de données
  - Aucun serveur Flask
  - Une seule unité testée par test, tout le reste mocké

Unités testées :
  1. EnrollmentCreateSchema          (schemas.py)
  2. call_service()                  (http_client.py)
  3. DownstreamError                 (http_client.py)
  4. log_outbound_call()             (logging_utils.py)
  5. Timer                           (logging_utils.py)
  6. OUTBOUND_CALLS counter          (metrics.py)
  7. Logique de validation des IDs   (routes.py — fonctions extraites)

Lancer :
    cd enrollment-service
    pytest ../tests/unit/enrollment-service/ -v
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

os.environ.update({
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "testdb",
    "DB_SCHEMA": "enrollment_schema",
    "STUDENT_SERVICE_URL": "http://student-mock:5001",
    "TEACHER_ADMIN_SERVICE_URL": "http://teacher-mock:8080",
    "LOG_LEVEL": "ERROR",
})

from app.schemas import EnrollmentCreateSchema
from app.http_client import DownstreamError, call_service
from app.logging_utils import Timer, log_outbound_call, log_inbound_request, new_trace_id


# =============================================================================
# 1. SCHÉMA — EnrollmentCreateSchema
# =============================================================================

class TestEnrollmentCreateSchema:

    def setup_method(self):
        self.schema = EnrollmentCreateSchema()

    # -- valides ---------------------------------------------------------------

    def test_valid_payload_passes(self):
        result = self.schema.load({"student_id": 1, "course_id": 2})
        assert result["student_id"] == 1
        assert result["course_id"] == 2

    def test_large_ids_pass(self):
        result = self.schema.load({"student_id": 99999, "course_id": 88888})
        assert result["student_id"] == 99999

    # -- student_id ------------------------------------------------------------

    def test_missing_student_id_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"course_id": 1})
        assert "student_id" in exc.value.messages

    def test_zero_student_id_raises(self):
        """student_id doit être >= 1 (validate.Range(min=1))."""
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"student_id": 0, "course_id": 1})
        assert "student_id" in exc.value.messages

    def test_negative_student_id_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"student_id": -5, "course_id": 1})
        assert "student_id" in exc.value.messages

    def test_string_student_id_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"student_id": "abc", "course_id": 1})
        assert "student_id" in exc.value.messages

    def test_float_student_id_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"student_id": 1.5, "course_id": 1})
        assert "student_id" in exc.value.messages

    # -- course_id -------------------------------------------------------------

    def test_missing_course_id_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"student_id": 1})
        assert "course_id" in exc.value.messages

    def test_zero_course_id_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"student_id": 1, "course_id": 0})
        assert "course_id" in exc.value.messages

    def test_negative_course_id_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({"student_id": 1, "course_id": -1})
        assert "course_id" in exc.value.messages

    # -- payload vide ----------------------------------------------------------

    def test_empty_payload_raises_both_fields(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError) as exc:
            self.schema.load({})
        assert "student_id" in exc.value.messages
        assert "course_id" in exc.value.messages

    # -- champs inconnus -------------------------------------------------------

    def test_unknown_field_raises(self):
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            self.schema.load({
                "student_id": 1, "course_id": 1,
                "status": "enrolled",  # champ non attendu
            })


# =============================================================================
# 2. HTTP CLIENT — call_service() pour enrollment-service
# =============================================================================

class TestCallService:
    """Même logique que student-service mais avec les cibles propres
    à enrollment-service (student-service + teacher-admin-service)."""

    def setup_method(self):
        self.mock_logger = MagicMock()

    def _call(self, target_service, url, status_code=200, side_effect=None, **kwargs):
        mock_resp = MagicMock(status_code=status_code)
        mock_resp.json.return_value = {}
        if side_effect:
            with patch("app.http_client.requests.request", side_effect=side_effect):
                return call_service(
                    self.mock_logger, "enrollment-service", target_service,
                    "GET", url, "trace-001", 3.0, **kwargs
                )
        with patch("app.http_client.requests.request", return_value=mock_resp):
            return call_service(
                self.mock_logger, "enrollment-service", target_service,
                "GET", url, "trace-001", 3.0, **kwargs
            )

    # -- appel vers student-service -------------------------------------------

    def test_call_to_student_service_success(self):
        resp = self._call(
            "student-service", "http://student-mock:5001/internal/students/1/exists"
        )
        assert resp.status_code == 200

    def test_call_to_student_service_logs_success(self):
        self._call(
            "student-service", "http://student-mock:5001/internal/students/1/exists"
        )
        log_payload = self.mock_logger.info.call_args[0][0]
        assert log_payload["target_service"] == "student-service"
        assert log_payload["outcome"] == "success"

    def test_student_service_404_raises_downstream_error(self):
        mock_resp = MagicMock(status_code=404)
        with patch("app.http_client.requests.request", return_value=mock_resp):
            with pytest.raises(DownstreamError) as exc:
                call_service(
                    self.mock_logger, "enrollment-service", "student-service",
                    "GET", "http://student-mock:5001/internal/students/999/exists",
                    "trace-001", 3.0
                )
        assert exc.value.status_code == 404

    # -- appel vers teacher-admin-service -------------------------------------

    def test_call_to_teacher_service_success(self):
        resp = self._call(
            "teacher-admin-service", "http://teacher-mock:8080/courses/1"
        )
        assert resp.status_code == 200

    def test_teacher_service_409_raises_downstream_error(self):
        mock_resp = MagicMock(status_code=409)
        with patch("app.http_client.requests.request", return_value=mock_resp):
            with pytest.raises(DownstreamError) as exc:
                call_service(
                    self.mock_logger, "enrollment-service", "teacher-admin-service",
                    "POST", "http://teacher-mock:8080/courses/1/reserve-seat",
                    "trace-001", 3.0
                )
        assert exc.value.status_code == 409

    # -- propagation du trace_id ----------------------------------------------

    def test_trace_id_propagated_in_header(self):
        mock_resp = MagicMock(status_code=200)
        with patch("app.http_client.requests.request", return_value=mock_resp) as mock_req:
            call_service(
                self.mock_logger, "enrollment-service", "student-service",
                "GET", "http://student-mock:5001/internal/students/1/exists",
                "my-trace-id", 3.0
            )
        headers = mock_req.call_args[1]["headers"]
        assert headers["X-Trace-Id"] == "my-trace-id"

    # -- compteurs Prometheus -------------------------------------------------

    def test_success_increments_outbound_counter(self):
        from app.metrics import OUTBOUND_CALLS
        before = OUTBOUND_CALLS.labels(
            target_service="student-service", outcome="success"
        )._value.get()
        self._call("student-service", "http://student-mock:5001/internal/students/1/exists")
        after = OUTBOUND_CALLS.labels(
            target_service="student-service", outcome="success"
        )._value.get()
        assert after == before + 1

    def test_failure_increments_outbound_counter(self):
        from app.metrics import OUTBOUND_CALLS
        import requests as req_lib
        before = OUTBOUND_CALLS.labels(
            target_service="student-service", outcome="failure"
        )._value.get()
        with pytest.raises(DownstreamError):
            self._call(
                "student-service", "http://student-mock:5001/x",
                side_effect=req_lib.exceptions.ConnectionError()
            )
        after = OUTBOUND_CALLS.labels(
            target_service="student-service", outcome="failure"
        )._value.get()
        assert after == before + 1

    # -- erreurs réseau -------------------------------------------------------

    def test_connection_error_raises_downstream_without_status_code(self):
        import requests as req_lib
        with patch("app.http_client.requests.request",
                   side_effect=req_lib.exceptions.ConnectionError()):
            with pytest.raises(DownstreamError) as exc:
                call_service(
                    self.mock_logger, "enrollment-service", "teacher-admin-service",
                    "POST", "http://teacher-mock:8080/courses/1/reserve-seat",
                    "trace", 3.0
                )
        assert exc.value.status_code is None

    def test_timeout_raises_downstream_error(self):
        import requests as req_lib
        with patch("app.http_client.requests.request",
                   side_effect=req_lib.exceptions.Timeout()):
            with pytest.raises(DownstreamError):
                call_service(
                    self.mock_logger, "enrollment-service", "student-service",
                    "GET", "http://student-mock:5001/x", "trace", 3.0
                )


# =============================================================================
# 3. DOWNSTREAM ERROR — comportement de l'exception elle-même
# =============================================================================

class TestDownstreamError:

    def test_stores_target_service(self):
        err = DownstreamError("student-service", 404)
        assert err.target_service == "student-service"

    def test_stores_status_code(self):
        err = DownstreamError("teacher-admin-service", 409)
        assert err.status_code == 409

    def test_status_code_none_by_default(self):
        err = DownstreamError("student-service")
        assert err.status_code is None

    def test_is_exception(self):
        assert isinstance(DownstreamError("x"), Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(DownstreamError) as exc:
            raise DownstreamError("teacher-admin-service", 503)
        assert exc.value.status_code == 503

    def test_message_is_generic(self):
        """Le message ne doit pas exposer de détail technique interne."""
        err = DownstreamError("teacher-admin-service", 503)
        message = str(err)
        assert "http://" not in message
        assert "traceback" not in message.lower()


# =============================================================================
# 4. LOG OUTBOUND CALL — enrollment-service
# =============================================================================

class TestLogOutboundCall:

    def setup_method(self):
        self.mock_logger = MagicMock()

    def test_success_uses_info_level(self):
        log_outbound_call(
            self.mock_logger, "enrollment-service", "student-service",
            "GET", "/internal/students/1/exists", "success", 5.0, "tid"
        )
        self.mock_logger.info.assert_called_once()
        self.mock_logger.warning.assert_not_called()

    def test_failure_uses_warning_level(self):
        log_outbound_call(
            self.mock_logger, "enrollment-service", "teacher-admin-service",
            "POST", "/courses/1/reserve-seat", "failure", 2.0, "tid",
            status_code=409
        )
        self.mock_logger.warning.assert_called_once()
        self.mock_logger.info.assert_not_called()

    def test_payload_has_correct_event_type(self):
        log_outbound_call(
            self.mock_logger, "enrollment-service", "student-service",
            "GET", "/x", "success", 1.0, "tid", status_code=200
        )
        payload = self.mock_logger.info.call_args[0][0]
        assert payload["event"] == "outbound_call"

    def test_payload_has_all_required_keys(self):
        log_outbound_call(
            self.mock_logger, "enrollment-service", "teacher-admin-service",
            "POST", "/courses/1/reserve-seat", "success", 15.7, "tid-xyz",
            status_code=200
        )
        payload = self.mock_logger.info.call_args[0][0]
        required_keys = {"service", "event", "target_service", "method",
                         "path", "outcome", "latency_ms", "trace_id", "status_code"}
        assert required_keys.issubset(set(payload.keys()))

    def test_release_seat_call_logged_correctly(self):
        """Test spécifique au rollback compensatoire d'enrollment-service :
        quand un release-seat est appelé, le log doit l'identifier."""
        log_outbound_call(
            self.mock_logger, "enrollment-service", "teacher-admin-service",
            "POST", "/courses/5/release-seat", "success", 8.3, "tid-rollback",
            status_code=200
        )
        payload = self.mock_logger.info.call_args[0][0]
        assert "release-seat" in payload["path"]
        assert payload["outcome"] == "success"


# =============================================================================
# 5. TIMER — même comportement que student-service
# =============================================================================

class TestTimer:

    def test_elapsed_ms_is_positive_after_context(self):
        with Timer() as t:
            pass
        assert t.elapsed_ms >= 0

    def test_elapsed_ms_is_float(self):
        with Timer() as t:
            pass
        assert isinstance(t.elapsed_ms, float)

    def test_measures_sleep_correctly(self):
        with Timer() as t:
            time.sleep(0.03)
        assert t.elapsed_ms >= 25  # marge généreuse

    def test_available_after_context_exit(self):
        with Timer() as t:
            time.sleep(0.01)
        latency = t.elapsed_ms  # ne doit pas lever AttributeError
        assert latency > 0

    def test_two_timers_independent(self):
        with Timer() as t1:
            time.sleep(0.01)
        with Timer() as t2:
            pass
        # t1 doit avoir une latence plus grande que t2
        assert t1.elapsed_ms > t2.elapsed_ms


# =============================================================================
# 6. TRACE ID — new_trace_id()
# =============================================================================

class TestNewTraceId:

    def test_is_string(self):
        assert isinstance(new_trace_id(), str)

    def test_non_empty(self):
        assert len(new_trace_id()) > 0

    def test_uniqueness(self):
        ids = {new_trace_id() for _ in range(200)}
        assert len(ids) == 200

    def test_is_hex(self):
        tid = new_trace_id()
        assert all(c in "0123456789abcdef" for c in tid)

    def test_length_32(self):
        assert len(new_trace_id()) == 32


# =============================================================================
# 7. LOGIQUE MÉTIER — vérification de capacité (extraite)
# =============================================================================

class TestCapacityCheckLogic:
    """Teste la logique pure de vérification de capacité, extraite des
    dépendances Flask/DB. On simule exactement ce que fait la route
    POST /enrollments en inspectant le champ availableSeats."""

    def _check_capacity(self, course_data: dict) -> bool:
        """Réplique exacte de la condition dans routes.py :
        if course.get("availableSeats", 0) <= 0 → refus."""
        return course_data.get("availableSeats", 0) > 0

    def test_course_with_seats_available(self):
        course = {"id": 1, "title": "Algo", "capacity": 30, "availableSeats": 5}
        assert self._check_capacity(course) is True

    def test_course_with_exactly_one_seat(self):
        course = {"id": 1, "title": "Algo", "capacity": 30, "availableSeats": 1}
        assert self._check_capacity(course) is True

    def test_course_full(self):
        course = {"id": 1, "title": "Algo", "capacity": 30, "availableSeats": 0}
        assert self._check_capacity(course) is False

    def test_course_with_negative_available_seats(self):
        """Cas défensif : ne devrait pas arriver en prod, mais la logique
        doit le traiter comme 'complet'."""
        course = {"id": 1, "title": "Algo", "capacity": 30, "availableSeats": -1}
        assert self._check_capacity(course) is False

    def test_course_without_available_seats_field(self):
        """Si le champ est absent, défaut à 0 → refus."""
        course = {"id": 1, "title": "Algo"}
        assert self._check_capacity(course) is False


# =============================================================================
# 8. LOGIQUE MÉTIER — vérification de l'existence étudiant (extraite)
# =============================================================================

class TestStudentExistenceCheck:
    """Teste la logique pure d'interprétation de la réponse
    de GET /internal/students/<id>/exists."""

    def _student_exists(self, response_body: dict) -> bool:
        """Réplique de la condition dans routes.py :
        if not resp.json().get("exists", False)"""
        return response_body.get("exists", False)

    def test_exists_true(self):
        assert self._student_exists({"exists": True}) is True

    def test_exists_false(self):
        assert self._student_exists({"exists": False}) is False

    def test_missing_exists_field_defaults_to_false(self):
        assert self._student_exists({}) is False

    def test_exists_with_extra_fields(self):
        assert self._student_exists({"exists": True, "id": 1, "email": "x@x.fr"}) is True