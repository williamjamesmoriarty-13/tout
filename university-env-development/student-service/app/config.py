import os


def _require_env(name: str) -> str:
    """Lève une erreur explicite au démarrage si un secret obligatoire manque,
    plutôt que de démarrer silencieusement avec une valeur par défaut
    dangereuse.
    """
    value = os.environ.get(name)
    if value is None or value == "":
        raise RuntimeError(
            f"Variable d'environnement obligatoire manquante: {name}"
        )
    return value


class Config:
    SERVICE_NAME = "student-service"

    DB_USER = _require_env("DB_USER")
    DB_PASSWORD = _require_env("DB_PASSWORD")
    DB_HOST = os.environ.get("DB_HOST", "postgres")
    DB_PORT = os.environ.get("DB_PORT", "5432")
    DB_NAME = _require_env("DB_NAME")
    DB_SCHEMA = os.environ.get("DB_SCHEMA", "student_schema")

    SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}" # noqa: E261,E501
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "connect_args": {"options": f"-c search_path={DB_SCHEMA}"},
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    TEACHER_ADMIN_SERVICE_URL = _require_env("TEACHER_ADMIN_SERVICE_URL")
    ENROLLMENT_SERVICE_URL = _require_env("ENROLLMENT_SERVICE_URL")

    HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "3.0"))
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
