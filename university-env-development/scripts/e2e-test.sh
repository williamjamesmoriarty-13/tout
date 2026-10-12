#!/bin/bash
# =============================================================================
# scripts/e2e-test.sh
#
# Démarre l'ensemble de la stack (docker compose), attend que tous les
# services soient healthy, puis exécute un scénario de bout en bout :
#   1) création d'un étudiant (student-service)
#   2) création d'un cours (teacher-admin-service)
#   3) inscription de l'étudiant au cours (enrollment-service, qui vérifie
#      l'étudiant auprès de student-service ET le cours auprès de
#      teacher-admin-service)
#   4) interrogation de student-service pour vérifier toute la chaîne
#      (available-courses, enrollments, grades)
#
# Pour chaque étape, le script va chercher dans les logs structurés des
# conteneurs (via le trace_id propagé de bout en bout) la trace réelle des
# appels inter-services et affiche "[OK] A -> B" ou "[ÉCHEC] A -> B".
#
# Prérequis sur la machine hôte : docker, docker compose (v2), curl, jq.
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

# --- Couleurs (désactivées si pas de TTY) ---
if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; BLUE='\033[0;34m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BLUE=''; NC=''
fi

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
fail() { echo -e "${RED}[ÉCHEC]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[ATTENTION]${NC} $1"; }

FAILURES=0

# --- 0) Prérequis ---
for bin in curl jq docker; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        fail "Commande requise absente sur l'hôte : $bin"
        exit 1
    fi
done

if ! docker compose version >/dev/null 2>&1; then
    fail "docker compose (v2) est requis."
    exit 1
fi

if [ ! -f .env ]; then
    warn "Fichier .env absent, copie de .env.example vers .env"
    cp .env.example .env
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

FRONTEND_URL="http://localhost:${FRONTEND_PORT}"

STUDENT_URL="${FRONTEND_URL}/api/students"
TEACHER_URL="${FRONTEND_URL}/api/teachers"
ENROLLMENT_URL="${FRONTEND_URL}/api/enrollments"

# =============================================================================
# 1) Démarrage complet
# =============================================================================
info "Démarrage de la stack (docker compose up -d --build)..."
docker compose up -d --build
if [ $? -ne 0 ]; then
    fail "docker compose up a échoué."
    exit 1
fi

# =============================================================================
# 2) Attente des healthchecks
# =============================================================================
wait_healthy() {
    local service="$1"
    local max_wait=120
    local waited=0
    info "Attente que '$service' soit healthy..."
    while [ "$waited" -lt "$max_wait" ]; do
        # On récupère le statut
        status=$(docker inspect --format='{{.State.Health.Status}}' "$(docker compose ps -q "$service")" 2>/dev/null)
        
        # Si le container a complètement crashé (exited)
        state=$(docker inspect --format='{{.State.Status}}' "$(docker compose ps -q "$service")" 2>/dev/null)
        if [ "$state" = "exited" ]; then
            fail "$service s'est arrêté brutalement !"
            echo "=== LOGS DE $service ==="
            docker compose logs "$service"
            FAILURES=$((FAILURES + 1))
            return 1
        fi

        if [ "$status" = "healthy" ]; then
            ok "$service est healthy (en ${waited}s)"
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
    done

    fail "$service n'est pas devenu healthy après ${max_wait}s"
    echo "=== LOGS DE $service ==="
    docker compose logs "$service"
    FAILURES=$((FAILURES + 1))
    return 1
}

wait_healthy postgres
wait_healthy student-service
wait_healthy teacher-admin-service
wait_healthy enrollment-service
wait_healthy frontend

echo ""
info "=== Scénario de bout en bout ==="
echo ""

# Petite aide : extrait le trace_id d'une réponse curl (header X-Trace-Id)
extract_trace_id() {
    grep -i '^x-trace-id:' | tr -d '\r' | awk '{print $2}'
}

# Affiche, pour un trace_id donné, toutes les lignes de log "outbound_call"
# trouvées dans les logs agrégés des 3 services, sous la forme demandée.
print_call_trace() {
    local trace_id="$1"
    local logs
    logs=$(docker compose logs --no-color student-service teacher-admin-service enrollment-service 2>/dev/null)
    local found=0
    while IFS= read -r line; do
        json=$(echo "$line" | grep -o '{.*}' || true)
        [ -z "$json" ] && continue
        event=$(echo "$json" | jq -r '.event // empty' 2>/dev/null)
        tid=$(echo "$json" | jq -r '.trace_id // empty' 2>/dev/null)
        [ "$event" != "outbound_call" ] && continue
        [ "$tid" != "$trace_id" ] && continue
        found=1
        source_svc=$(echo "$json" | jq -r '.service // "?"')
        target_svc=$(echo "$json" | jq -r '.target_service // "?"')
        outcome=$(echo "$json" | jq -r '.outcome // "?"')
        latency=$(echo "$json" | jq -r '.latency_ms // "?"')
        if [ "$outcome" = "success" ]; then
            ok "${source_svc} -> ${target_svc} (${latency} ms)"
        else
            fail "${source_svc} -> ${target_svc} (${latency} ms)"
            FAILURES=$((FAILURES + 1))
        fi
    done <<< "$logs"
    if [ "$found" -eq 0 ]; then
        warn "Aucune trace d'appel inter-service trouvée pour trace_id=$trace_id (logs pas encore flush ?)"
    fi
}

# =============================================================================
# 3) Création d'un étudiant
# =============================================================================
info "Création d'un étudiant via student-service..."
STUDENT_EMAIL="etudiant.$(date +%s)@universite.test"
STUDENT_RESPONSE=$(curl -s -X POST "${STUDENT_URL}/students" \
    -H "Content-Type: application/json" \
    -d "{\"first_name\":\"Ada\",\"last_name\":\"Lovelace\",\"email\":\"${STUDENT_EMAIL}\"}")
STUDENT_ID=$(echo "$STUDENT_RESPONSE" | jq -r '.id // empty')

if [ -z "$STUDENT_ID" ]; then
    fail "Création de l'étudiant échouée : $STUDENT_RESPONSE"
    FAILURES=$((FAILURES + 1))
else
    ok "Étudiant créé (id=$STUDENT_ID)"
fi

# =============================================================================
# 4) Création d'un cours (côté teacher-admin-service)
# =============================================================================
info "Création d'un cours via teacher-admin-service..."
COURSE_RESPONSE=$(curl -s -X POST "${TEACHER_URL}/courses" \
    -H "Content-Type: application/json" \
    -d '{"title":"Algorithmique avancée","description":"Cours de test e2e","capacity":2}')
COURSE_ID=$(echo "$COURSE_RESPONSE" | jq -r '.id // empty')

if [ -z "$COURSE_ID" ]; then
    fail "Création du cours échouée : $COURSE_RESPONSE"
    FAILURES=$((FAILURES + 1))
else
    ok "Cours créé (id=$COURSE_ID)"
fi

# =============================================================================
# 5) Inscription de l'étudiant (enrollment-service -> student-service ET
#    enrollment-service -> teacher-admin-service)
# =============================================================================
if [ -n "$STUDENT_ID" ] && [ -n "$COURSE_ID" ]; then
    info "Inscription de l'étudiant $STUDENT_ID au cours $COURSE_ID..."
    ENROLL_HEADERS=$(mktemp)
    ENROLL_RESPONSE=$(curl -s -D "$ENROLL_HEADERS" -X POST "${ENROLLMENT_URL}/enrollments" \
        -H "Content-Type: application/json" \
        -d "{\"student_id\":${STUDENT_ID},\"course_id\":${COURSE_ID}}")
    ENROLL_TRACE_ID=$(extract_trace_id < "$ENROLL_HEADERS")
    rm -f "$ENROLL_HEADERS"

    ENROLLMENT_ID=$(echo "$ENROLL_RESPONSE" | jq -r '.id // empty')
    if [ -z "$ENROLLMENT_ID" ]; then
        fail "Inscription échouée : $ENROLL_RESPONSE"
        FAILURES=$((FAILURES + 1))
    else
        ok "Inscription créée (id=$ENROLLMENT_ID)"
    fi

    sleep 1  # laisser le temps aux logs de s'écrire
    if [ -n "$ENROLL_TRACE_ID" ]; then
        info "Trace des appels inter-services pour cette inscription (trace_id=$ENROLL_TRACE_ID) :"
        print_call_trace "$ENROLL_TRACE_ID"
    fi
else
    warn "Étape d'inscription ignorée (étudiant ou cours manquant)"
fi

echo ""

# =============================================================================
# 6) Vérification de la chaîne complète depuis student-service
# =============================================================================
if [ -n "$STUDENT_ID" ]; then
    info "Vérification : student-service -> teacher-admin-service (cours disponibles)"
    AC_HEADERS=$(mktemp)
    AC_RESPONSE=$(curl -s -D "$AC_HEADERS" "${STUDENT_URL}/students/${STUDENT_ID}/available-courses")
    AC_TRACE_ID=$(extract_trace_id < "$AC_HEADERS")
    rm -f "$AC_HEADERS"
    if echo "$AC_RESPONSE" | jq -e 'type == "array"' >/dev/null 2>&1; then
        ok "student-service a bien reçu la liste des cours disponibles"
    else
        fail "Échec de la récupération des cours disponibles : $AC_RESPONSE"
        FAILURES=$((FAILURES + 1))
    fi
    sleep 1
    [ -n "$AC_TRACE_ID" ] && print_call_trace "$AC_TRACE_ID"

    echo ""
    info "Vérification : student-service -> enrollment-service (inscriptions)"
    EN_HEADERS=$(mktemp)
    EN_RESPONSE=$(curl -s -D "$EN_HEADERS" "${STUDENT_URL}/students/${STUDENT_ID}/enrollments")
    EN_TRACE_ID=$(extract_trace_id < "$EN_HEADERS")
    rm -f "$EN_HEADERS"
    if echo "$EN_RESPONSE" | jq -e 'type == "array"' >/dev/null 2>&1; then
        ok "student-service a bien reçu la liste des inscriptions"
    else
        fail "Échec de la récupération des inscriptions : $EN_RESPONSE"
        FAILURES=$((FAILURES + 1))
    fi
    sleep 1
    [ -n "$EN_TRACE_ID" ] && print_call_trace "$EN_TRACE_ID"

    echo ""
    info "Vérification : student-service -> enrollment-service -> teacher-admin-service (notes)"
    GR_HEADERS=$(mktemp)
    GR_RESPONSE=$(curl -s -D "$GR_HEADERS" "${STUDENT_URL}/students/${STUDENT_ID}/grades")
    GR_TRACE_ID=$(extract_trace_id < "$GR_HEADERS")
    rm -f "$GR_HEADERS"
    if echo "$GR_RESPONSE" | jq -e 'type == "array"' >/dev/null 2>&1; then
        ok "student-service a bien reçu la liste des notes (via enrollment-service)"
    else
        fail "Échec de la récupération des notes : $GR_RESPONSE"
        FAILURES=$((FAILURES + 1))
    fi
    sleep 1
    [ -n "$GR_TRACE_ID" ] && print_call_trace "$GR_TRACE_ID"
fi

echo ""
echo "==============================================================="
if [ "$FAILURES" -eq 0 ]; then
    echo -e "${GREEN}Scénario end-to-end terminé avec succès (0 échec).${NC}"
    echo "==============================================================="
    exit 0
else
    echo -e "${RED}Scénario end-to-end terminé avec ${FAILURES} échec(s).${NC}"
    echo "==============================================================="
    exit 1
fi
