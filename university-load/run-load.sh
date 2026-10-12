#!/bin/bash
set -euo pipefail

# ============================================================
# run-load.sh — Lance un scénario de trafic synthétique k6
#
# Usage :
#   ./run-load.sh light                        # charge légère continue
#   ./run-load.sh realistic                    # parcours étudiant complet
#   ./run-load.sh stress                       # pic de charge
#   ./run-load.sh light http://172.18.0.2      # avec URL custom
#   ./run-load.sh stress http://localhost:8080  # via port-forward
#
# L'URL peut aussi être définie via variable d'environnement :
#   BASE_URL=http://172.18.0.2 ./run-load.sh light
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="${SCRIPT_DIR}/scripts"

log()  { echo -e "\n\033[1;34m[load]\033[0m $1"; }
ok()   { echo -e "\033[1;32m  ✓ $1\033[0m"; }
err()  { echo -e "\033[1;31m  ✗ $1\033[0m"; exit 1; }
warn() { echo -e "\033[1;33m  ⚠ $1\033[0m"; }

# Vérifier que k6 est installé
if ! command -v k6 &>/dev/null; then
  err "k6 n'est pas installé. Installe-le : https://k6.io/docs/get-started/installation/"
fi

SCENARIO=${1:-""}
# URL custom en 2ème argument ou depuis la variable d'environnement
BASE_URL=${2:-${BASE_URL:-"http://university.local:8080"}}

case "${SCENARIO}" in
  light|realistic|stress|cleanup) ;;
  "") err "Précise un scénario : light, realistic, stress, cleanup" ;;
  *)  err "Scénario inconnu : ${SCENARIO}. Valeurs : light, realistic, stress, cleanup" ;;
esac

log "Scénario    : ${SCENARIO}"
log "URL de base : ${BASE_URL}"
warn "L'URL doit être accessible depuis cette machine (ping/curl avant de lancer)"

echo ""
echo "  Test de connectivité..."
if curl -sf --max-time 5 "${BASE_URL}" > /dev/null 2>&1; then
  ok "URL accessible"
else
  warn "L'URL ne répond pas — vérifie que le cluster est démarré et l'Ingress configuré"
  read -r -p "  Continuer quand même ? (y/N) " confirm
  [[ "${confirm}" =~ ^[yY]$ ]] || exit 0
fi

echo ""
log "Lancement de k6 — scénario '${SCENARIO}'"
echo "  → Grafana : http://grafana.university.local:8080"
echo "  → Ctrl+C pour stopper"
echo ""

# BASE_URL passé en variable d'environnement k6 (--env)
# → récupéré dans config.js via __ENV.BASE_URL
k6 run \
  --env BASE_URL="${BASE_URL}" \
  "${SCRIPTS_DIR}/${SCENARIO}.js"
