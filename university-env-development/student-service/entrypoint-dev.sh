#!/bin/sh
set -e

echo "[student-service] Application des migrations Alembic..."
alembic upgrade head

echo "[student-service] Démarrage de gunicorn..."
exec python wsgi.py
