from flask import Blueprint, current_app, g, jsonify, request
from marshmallow import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .http_client import DownstreamError, call_service
from .models import Student, db
from .schemas import StudentCreateSchema, StudentUpdateSchema

bp = Blueprint("students", __name__)

student_create_schema = StudentCreateSchema()
student_update_schema = StudentUpdateSchema()


def _logger():
    return current_app.extensions["structured_logger"]


def _trace_id():
    return getattr(g, "trace_id", "unknown")


# --------------------------------------------------------------------------
# Health check (utilisé par docker-compose healthcheck)
# --------------------------------------------------------------------------
@bp.route("/health", methods=["GET"])
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "service": "student-service"}), 200
    except SQLAlchemyError:
        current_app.logger.error(
            {"service": "student-service", "event": "health_check_failed"}
        )
        return (
            jsonify({"status": "unhealthy", "service": "student-service"}),
            503,
        )


# --------------------------------------------------------------------------
# CRUD étudiant
# --------------------------------------------------------------------------
@bp.route("/students", methods=["POST"])
def create_student():
    payload = request.get_json(silent=True)
    if payload is None:
        return (
            jsonify({"error": "Corps de requête JSON invalide ou manquant"}),
            400,
        )
    try:
        data = student_create_schema.load(payload)
    except ValidationError as err:
        return (
            jsonify({"error": "Validation échouée", "details": err.messages}),
            400,
        )

    student = Student(
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data["email"],
    )
    db.session.add(student)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return (
            jsonify({"error": "Un étudiant avec cet email existe déjà"}),
            409,
        )
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error(
            {
                "service": "student-service",
                "event": "db_error",
                "action": "create_student",
            }
        )
        return jsonify({"error": "Erreur interne, réessayez plus tard"}), 500

    return jsonify(student.to_dict()), 201


@bp.route("/students", methods=["GET"])
def list_students():
    students = Student.query.order_by(Student.id.asc()).limit(200).all()
    return jsonify([s.to_dict() for s in students]), 200


@bp.route("/students/<int:student_id>", methods=["GET"])
def get_student(student_id: int):
    student = Student.query.get(student_id)
    if student is None:
        return jsonify({"error": "Étudiant introuvable"}), 404
    return jsonify(student.to_dict()), 200


@bp.route("/students/<int:student_id>", methods=["PUT"])
def update_student(student_id: int):
    student = Student.query.get(student_id)
    if student is None:
        return jsonify({"error": "Étudiant introuvable"}), 404

    payload = request.get_json(silent=True)
    if payload is None:
        return (
            jsonify({"error": "Corps de requête JSON invalide ou manquant"}),
            400,
        )
    try:
        data = student_update_schema.load(payload)
    except ValidationError as err:
        return (
            jsonify({"error": "Validation échouée", "details": err.messages}),
            400,
        )

    for field, value in data.items():
        setattr(student, field, value)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return (
            jsonify({"error": "Un étudiant avec cet email existe déjà"}),
            409,
        )
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error(
            {
                "service": "student-service",
                "event": "db_error",
                "action": "update_student",
            }
        )
        return jsonify({"error": "Erreur interne, réessayez plus tard"}), 500

    return jsonify(student.to_dict()), 200


@bp.route("/students/<int:student_id>", methods=["DELETE"])
def delete_student(student_id: int):
    student = Student.query.get(student_id)
    if student is None:
        return jsonify({"error": "Étudiant introuvable"}), 404
    db.session.delete(student)
    db.session.commit()
    return "", 204


# --------------------------------------------------------------------------
# Endpoint interne, consommé par enrollment-service pour vérifier l'existence
# d'un étudiant (surface minimale, pas de données sensibles exposées).
# --------------------------------------------------------------------------
@bp.route("/internal/students/<int:student_id>/exists", methods=["GET"])
def student_exists(student_id: int):
    exists = (
        db.session.query(Student.id).filter_by(id=student_id).first()
        is not None
    )
    return jsonify({"exists": exists}), 200


# --------------------------------------------------------------------------
# Endpoints "fan-out" : chacun déclenche un appel sortant vers un autre service
# --------------------------------------------------------------------------
@bp.route("/students/<int:student_id>/available-courses", methods=["GET"])
def available_courses(student_id: int):
    student = Student.query.get(student_id)
    if student is None:
        return jsonify({"error": "Étudiant introuvable"}), 404

    url = f"{current_app.config['TEACHER_ADMIN_SERVICE_URL']}/courses"
    try:
        response = call_service(
            _logger(),
            "student-service",
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
                        "Le service des cours est momentanément"
                        " indisponible"
                    )
                }
            ),
            502,
        )

    return jsonify(response.json()), 200


@bp.route("/students/<int:student_id>/enrollments", methods=["GET"])
def student_enrollments(student_id: int):
    student = Student.query.get(student_id)
    if student is None:
        return jsonify({"error": "Étudiant introuvable"}), 404

    base_url = current_app.config["ENROLLMENT_SERVICE_URL"]
    url = f"{base_url}/enrollments?student_id={student_id}"
    try:
        response = call_service(
            _logger(),
            "student-service",
            "enrollment-service",
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
                        "Le service des inscriptions est momentanément"
                        " indisponible"
                    )
                }
            ),
            502,
        )

    return jsonify(response.json()), 200


@bp.route("/students/<int:student_id>/grades", methods=["GET"])
def student_grades(student_id: int):
    student = Student.query.get(student_id)
    if student is None:
        return jsonify({"error": "Étudiant introuvable"}), 404

    base_url = current_app.config["ENROLLMENT_SERVICE_URL"]
    url = f"{base_url}/grades?student_id={student_id}"
    try:
        response = call_service(
            _logger(),
            "student-service",
            "enrollment-service",
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
