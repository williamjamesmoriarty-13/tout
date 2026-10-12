from flask import Blueprint, current_app, g, jsonify, request
from marshmallow import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .http_client import DownstreamError, call_service
from .models import Enrollment, db
from .schemas import EnrollmentCreateSchema

bp = Blueprint("enrollments", __name__)

enrollment_create_schema = EnrollmentCreateSchema()


def _logger():
    return current_app.extensions["structured_logger"]


def _trace_id():
    return getattr(g, "trace_id", "unknown")


@bp.route("/health", methods=["GET"])
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "service": "enrollment-service"}), 200
    except SQLAlchemyError:
        current_app.logger.error(
            {"service": "enrollment-service", "event": "health_check_failed"}
        )
        return (
            jsonify({"status": "unhealthy", "service": "enrollment-service"}),
            503,
        )


# --------------------------------------------------------------------------
# Création d'une inscription : dépend RÉELLEMENT et ACTIVEMENT de
# student-service (existence de l'étudiant) ET teacher-admin-service
# (existence du cours + place disponible + réservation de siège).
# --------------------------------------------------------------------------
def _check_student_exists(logger, trace_id, timeout, student_id):
    """Retourne (True, None) si l'étudiant existe, sinon (False, response)."""
    base_student_url = current_app.config["STUDENT_SERVICE_URL"]
    student_url = f"{base_student_url}/internal/students/{student_id}/exists"
    try:
        resp = call_service(
            logger,
            "enrollment-service",
            "student-service",
            "GET",
            student_url,
            trace_id=trace_id,
            timeout=timeout,
        )
    except DownstreamError:
        return False, (
            jsonify({"error": "Le service étudiant est momentanément indisponible"}),
            502,
        )
    if not resp.json().get("exists", False):
        return False, (jsonify({"error": "Étudiant introuvable"}), 404)
    return True, None


def _get_course_or_error(logger, trace_id, timeout, base_teacher_url, course_id):
    """Retourne (course_dict, None) ou (None, response)."""
    course_url = f"{base_teacher_url}/courses/{course_id}"
    try:
        resp = call_service(
            logger,
            "enrollment-service",
            "teacher-admin-service",
            "GET",
            course_url,
            trace_id=trace_id,
            timeout=timeout,
        )
    except DownstreamError as exc:
        if exc.status_code == 404:
            return None, (jsonify({"error": "Cours introuvable"}), 404)
        return None, (
            jsonify({"error": "Le service des cours est momentanément indisponible"}),
            502,
        )

    course = resp.json()
    if course.get("availableSeats", 0) <= 0:
        return None, (jsonify({"error": "Ce cours est complet"}), 409)
    return course, None


def _reserve_seat_or_error(logger, trace_id, timeout, base_teacher_url, course_id):
    """Retourne None si succès, sinon response d'erreur."""
    reserve_url = f"{base_teacher_url}/courses/{course_id}/reserve-seat"
    try:
        call_service(
            logger,
            "enrollment-service",
            "teacher-admin-service",
            "POST",
            reserve_url,
            trace_id=trace_id,
            timeout=timeout,
        )
    except DownstreamError as exc:
        if exc.status_code == 409:
            return jsonify({"error": "Ce cours est complet"}), 409
        return (
            jsonify({"error": "Impossible de réserver une place pour ce cours"}),
            502,
        )
    return None


def _release_seat_best_effort(logger, trace_id, timeout, base_teacher_url, course_id):
    """Rollback compensatoire : on ne bloque jamais la réponse HTTP dessus."""
    release_url = f"{base_teacher_url}/courses/{course_id}/release-seat"
    try:
        call_service(
            logger,
            "enrollment-service",
            "teacher-admin-service",
            "POST",
            release_url,
            trace_id=trace_id,
            timeout=timeout,
        )
    except DownstreamError:
        pass


def _persist_enrollment_or_error(
    logger, trace_id, timeout, base_teacher_url, student_id, course_id
):
    """Retourne (enrollment, None) ou (None, response)."""
    enrollment = Enrollment(
        student_id=student_id, course_id=course_id, status="enrolled"
    )
    db.session.add(enrollment)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        _release_seat_best_effort(logger, trace_id, timeout, base_teacher_url, course_id)
        return None, (
            jsonify({"error": "Cet étudiant est déjà inscrit à ce cours"}),
            409,
        )
    except SQLAlchemyError:
        db.session.rollback()
        logger.error(
            {
                "service": "enrollment-service",
                "event": "db_error",
                "action": "create_enrollment",
            }
        )
        return None, (jsonify({"error": "Erreur interne, réessayez plus tard"}), 500)
    return enrollment, None


@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Corps de requête JSON invalide ou manquant"}), 400
    try:
        data = enrollment_create_schema.load(payload)
    except ValidationError as err:
        return jsonify({"error": "Validation échouée", "details": err.messages}), 400

    student_id = data["student_id"]
    course_id = data["course_id"]
    logger = _logger()
    trace_id = _trace_id()
    timeout = current_app.config["HTTP_TIMEOUT_SECONDS"]
    base_teacher_url = current_app.config["TEACHER_ADMIN_SERVICE_URL"]

    ok, error_response = _check_student_exists(logger, trace_id, timeout, student_id)
    if not ok:
        return error_response

    course, error_response = _get_course_or_error(
        logger, trace_id, timeout, base_teacher_url, course_id
    )
    if course is None:
        return error_response

    error_response = _reserve_seat_or_error(
        logger, trace_id, timeout, base_teacher_url, course_id
    )
    if error_response is not None:
        return error_response

    enrollment, error_response = _persist_enrollment_or_error(
        logger, trace_id, timeout, base_teacher_url, student_id, course_id
    )
    if enrollment is None:
        return error_response

    return jsonify(enrollment.to_dict()), 201


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    student_id = request.args.get("student_id", type=int)
    query = Enrollment.query
    if student_id is not None:
        query = query.filter_by(student_id=student_id)
    enrollments = query.order_by(Enrollment.id.asc()).limit(200).all()
    return jsonify([e.to_dict() for e in enrollments]), 200


@bp.route("/enrollments/<int:enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id: int):
    enrollment = Enrollment.query.get(enrollment_id)
    if enrollment is None:
        return jsonify({"error": "Inscription introuvable"}), 404
    return jsonify(enrollment.to_dict()), 200


@bp.route("/enrollments/<int:enrollment_id>", methods=["DELETE"])
def cancel_enrollment(enrollment_id: int):
    enrollment = Enrollment.query.get(enrollment_id)
    if enrollment is None:
        return jsonify({"error": "Inscription introuvable"}), 404

    logger = _logger()
    trace_id = _trace_id()
    timeout = current_app.config["HTTP_TIMEOUT_SECONDS"]

    base_teacher_url = current_app.config["TEACHER_ADMIN_SERVICE_URL"]
    release_url = (
        f"{base_teacher_url}/courses/{enrollment.course_id}/release-seat"
    )
    try:
        call_service(
            logger,
            "enrollment-service",
            "teacher-admin-service",
            "POST",
            release_url,
            trace_id=trace_id,
            timeout=timeout,
        )
    except DownstreamError:
        return (
            jsonify({"error": "Impossible de libérer la place pour ce cours"}),
            502,
        )

    enrollment.status = "cancelled"
    db.session.commit()
    return jsonify(enrollment.to_dict()), 200


# --------------------------------------------------------------------------
# Proxy des notes : les notes sont la propriété de teacher-admin-service,
# enrollment-service les relaie pour le compte de student-service.
# --------------------------------------------------------------------------
@bp.route("/grades", methods=["GET"])
def grades():
    student_id = request.args.get("student_id", type=int)
    if student_id is None:
        return jsonify({"error": "Le paramètre student_id est requis"}), 400

    base_teacher_url = current_app.config["TEACHER_ADMIN_SERVICE_URL"]
    url = f"{base_teacher_url}/grades?studentId={student_id}"
    try:
        response = call_service(
            _logger(),
            "enrollment-service",
            "teacher-admin-service",
            "GET",
            url,
            trace_id=_trace_id(),
            timeout=current_app.config["HTTP_TIMEOUT_SECONDS"],
        )
    except DownstreamError:
        return (
            jsonify(
                {
                    "error": (
                        "Le service des notes est momentanément"
                        " indisponible"
                    )
                }
            ),
            502,
        )

    return jsonify(response.json()), 200
