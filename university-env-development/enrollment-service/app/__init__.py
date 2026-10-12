import time

from flask import Flask, g, jsonify, request
from flask_cors import CORS

from .config import Config
from .logging_utils import configure_logging, log_inbound_request, new_trace_id
from .metrics import init_metrics
from .models import db


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, resources={r"/*": {"origins": "*"}})

    db.init_app(app)

    init_metrics(app)

    logger = configure_logging(Config.SERVICE_NAME)
    app.extensions["structured_logger"] = logger

    from .routes import bp as enrollments_bp

    app.register_blueprint(enrollments_bp)

    @app.before_request
    def _start_timer():
        g.trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
        g.start_time = time.perf_counter()

    @app.after_request
    def _log_request(response):
        latency_ms = (
            time.perf_counter() - g.get("start_time", time.perf_counter())
        ) * 1000
        log_inbound_request(
            logger,
            Config.SERVICE_NAME,
            request.method,
            request.path,
            response.status_code,
            latency_ms,
            g.get("trace_id", "unknown"),
        )
        response.headers["X-Trace-Id"] = g.get("trace_id", "unknown")
        return response

    @app.errorhandler(404)
    def not_found(_err):
        return jsonify({"error": "Ressource introuvable"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_err):
        return jsonify({"error": "Méthode non autorisée"}), 405

    @app.errorhandler(Exception)
    def handle_unexpected_error(err):
        logger.error(
            {
                "service": Config.SERVICE_NAME,
                "event": "unhandled_exception",
                "error": str(err),
            }
        )
        return jsonify({"error": "Erreur interne du serveur"}), 500

    return app
