import os

os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("TEACHER_ADMIN_SERVICE_URL", "http://teacher-admin-service")
os.environ.setdefault("ENROLLMENT_SERVICE_URL", "http://enrollment-service")

import pytest

from app import create_app


@pytest.fixture
def app(mocker):
    mocker.patch("app.init_metrics")

    app = create_app()

    app.config.update(TESTING=True)

    return app


@pytest.fixture
def client(app):
    return app.test_client()