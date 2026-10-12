#!/bin/bash
# =============================================================================
# scripts/docker-push.sh
#
# Build, tag et push les 4 images du projet vers Docker Hub sous le compte
# "darbi" :
#   darbi/
#   darbi/university-teacher-admin-service
#   darbi/university-enrollment-service
#   darbi/university-frontend
#
# Usage :
#   ./scripts/docker-push.sh                 # tag "latest" uniquement
#   ./scripts/docker-push.sh v1.0.0          # tag "v1.0.0" ET "latest"
#   DOCKERHUB_USERNAME=autre ./scripts/docker-push.sh v1.0.0
#
# Prérequis : être connecté à Docker Hub (le script propose "docker login"
# automatiquement si ce n'est pas déjà fait).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
    GREEN=''; RED=''; BLUE=''; YELLOW=''; NC=''
fi

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
fail() { echo -e "${RED}[ÉCHEC]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[ATTENTION]${NC} $1"; }

DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:-darbi}"
IMAGE_PREFIX="university"
VERSION_TAG="${1:-latest}"

# service_dir:image_name
SERVICES=(
    "student-service:${IMAGE_PREFIX}-student-service"
    "teacher-admin-service:${IMAGE_PREFIX}-teacher-admin-service"
    "enrollment-service:${IMAGE_PREFIX}-enrollment-service"
    "frontend:${IMAGE_PREFIX}-frontend"
)

# --- 0) Prérequis ---
if ! command -v docker >/dev/null 2>&1; then
    fail "docker est requis sur cette machine."
    exit 1
fi

info "Compte Docker Hub cible : ${DOCKERHUB_USERNAME}"
info "Tag de version : ${VERSION_TAG}"

# --- 1) Connexion Docker Hub (si pas déjà connecté) ---
if ! docker info 2>/dev/null | grep -qi "Username: ${DOCKERHUB_USERNAME}"; then
    info "Connexion à Docker Hub requise (compte ${DOCKERHUB_USERNAME})..."
    docker login -u "${DOCKERHUB_USERNAME}"
fi

FAILURES=0
PUSHED_IMAGES=()

# --- 2) Build + tag + push pour chaque service ---
for entry in "${SERVICES[@]}"; do
    service_dir="${entry%%:*}"
    image_name="${entry##*:}"
    full_image="${DOCKERHUB_USERNAME}/${image_name}"

    echo ""
    info "=== ${service_dir} -> ${full_image} ==="

    if [ ! -d "$service_dir" ]; then
        fail "Dossier introuvable : ${service_dir}"
        FAILURES=$((FAILURES + 1))
        continue
    fi

    info "Build de l'image (contexte: ./${service_dir})..."
    if ! docker build -t "${full_image}:${VERSION_TAG}" "./${service_dir}"; then
        fail "Build échoué pour ${service_dir}"
        FAILURES=$((FAILURES + 1))
        continue
    fi
    ok "Image construite : ${full_image}:${VERSION_TAG}"

    # Tag "latest" en plus, sauf si on a déjà demandé "latest" comme tag principal
    if [ "$VERSION_TAG" != "latest" ]; then
        docker tag "${full_image}:${VERSION_TAG}" "${full_image}:latest"
        ok "Tag additionnel créé : ${full_image}:latest"
    fi

    info "Push de ${full_image}:${VERSION_TAG}..."
    if docker push "${full_image}:${VERSION_TAG}"; then
        ok "Push réussi : ${full_image}:${VERSION_TAG}"
        PUSHED_IMAGES+=("${full_image}:${VERSION_TAG}")
    else
        fail "Push échoué : ${full_image}:${VERSION_TAG}"
        FAILURES=$((FAILURES + 1))
        continue
    fi

    if [ "$VERSION_TAG" != "latest" ]; then
        info "Push de ${full_image}:latest..."
        if docker push "${full_image}:latest"; then
            ok "Push réussi : ${full_image}:latest"
            PUSHED_IMAGES+=("${full_image}:latest")
        else
            fail "Push échoué : ${full_image}:latest"
            FAILURES=$((FAILURES + 1))
        fi
    fi
done

# --- 3) Résumé ---
echo ""
echo "==============================================================="
if [ "$FAILURES" -eq 0 ]; then
    echo -e "${GREEN}Toutes les images ont été publiées avec succès :${NC}"
    for img in "${PUSHED_IMAGES[@]}"; do
        echo "  - docker.io/${img}"
    done
    echo "==============================================================="
    exit 0
else
    echo -e "${RED}${FAILURES} publication(s) ont échoué. Voir les messages [ÉCHEC] ci-dessus.${NC}"
    echo "==============================================================="
    exit 1
fi
