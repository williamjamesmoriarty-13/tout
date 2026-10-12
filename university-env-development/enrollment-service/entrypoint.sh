#!/bin/sh
# IMPORTANT : ce script doit rester en shell (pas en Python).
# L'auto-instrumentation OpenTelemetry (injectée par l'opérateur via PYTHONPATH)
# retire son propre dossier de PYTHONPATH dans tout process Python qu'elle
# instrumente. Un entrypoint Python qui lance ensuite gunicorn (subprocess ou
# execvp) transmet donc un environnement SANS auto-instrumentation : gunicorn
# tourne alors sans aucun span. Un script shell ne modifie pas PYTHONPATH.
set -e

# Doit être défini avant le démarrage de gunicorn (prometheus_client le lit à l'import).
: "${PROMETHEUS_MULTIPROC_DIR:=/tmp/prometheus_multiproc_dir}"
export PROMETHEUS_MULTIPROC_DIR

# Dossier des métriques multiprocess : créé et vidé UNE seule fois, avant les workers.
# (on supprime les fichiers, pas le dossier : ça peut être un point de montage)
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
rm -f "$PROMETHEUS_MULTIPROC_DIR"/*.db

echo "[enrollment-service] Application des migrations Alembic..."
alembic upgrade head

echo "[enrollment-service] Démarrage de gunicorn..."
exec gunicorn \
  --bind 0.0.0.0:5003 \
  --workers 2 --threads 2 --timeout 30 \
  --access-logfile - --error-logfile - \
  -c gunicorn.conf.py \
  wsgi:app