#!/bin/bash
# =============================================================================
# lint.sh — Lint, SAST et audit de dépendances pour les 3 services
# =============================================================================
#
# Usage :
#   ./scripts/lint.sh                    # analyse les 3 services
#   ./scripts/lint.sh --service student  # student-service uniquement
#   ./scripts/lint.sh --service teacher  # teacher-admin-service uniquement
#   ./scripts/lint.sh --service enroll   # enrollment-service uniquement
#   ./scripts/lint.sh --fix              # corrige automatiquement ce qui peut l'être
#   ./scripts/lint.sh --no-gitleaks      # saute le scan de secrets (si gitleaks absent)
#
# Pré-requis (installés automatiquement si absents) :
#   Python : flake8, bandit, pip-audit
#   Java   : maven (mvn), java ≥ 21
#   Optionnel : gitleaks (https://github.com/gitleaks/gitleaks)
#
# Sorties :
#   - Rapport lisible dans le terminal (couleurs ANSI)
#   - Rapports détaillés dans ./lint-reports/ (créé automatiquement)
#   - Code de sortie 0 si tout passe, 1 si au moins un outil a échoué
# =============================================================================

set -uo pipefail

# ── Répertoires ───────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR_REPORT="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
CONFIG_DIR="${ROOT_DIR}/lint/config"   # ajuster si lint/config est ailleurs
REPORT_DIR="${ROOT_DIR_REPORT}/lint-reports"
STUDENT_DIR="${ROOT_DIR}/student-service"
TEACHER_DIR="${ROOT_DIR}/teacher-admin-service"
ENROLL_DIR="${ROOT_DIR}/enrollment-service"

# ── Arguments ─────────────────────────────────────────────────────────────────
SERVICE_FILTER=""
FIX_MODE=false
SKIP_GITLEAKS=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --service) SERVICE_FILTER="$2"; shift 2 ;;
        --fix)     FIX_MODE=true; shift ;;
        --no-gitleaks) SKIP_GITLEAKS=true; shift ;;
        *) echo "Option inconnue : $1" >&2; exit 1 ;;
    esac
done

# ── Couleurs ──────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; BOLD=''; NC=''
fi

# ── Compteurs de résultats ────────────────────────────────────────────────────
TOTAL_CHECKS=0
PASSED=0
FAILED=0
SKIPPED=0
FAILED_CHECKS=()

# ── Fonctions utilitaires ─────────────────────────────────────────────────────

log_section() {
    echo ""
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${BLUE}  $1${NC}"
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════${NC}"
}

log_step() {
    echo -e "\n${CYAN}▶ $1${NC}"
}

pass() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    PASSED=$((PASSED + 1))
    echo -e "  ${GREEN}✓ $1${NC}"
}

fail() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    FAILED=$((FAILED + 1))
    FAILED_CHECKS+=("$1")
    echo -e "  ${RED}✗ $1${NC}"
}

skip() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    SKIPPED=$((SKIPPED + 1))
    echo -e "  ${YELLOW}⊘ $1 (ignoré)${NC}"
}

# Exécute une commande, capture la sortie dans un rapport, affiche pass/fail
run_check() {
    local label="$1"
    local report_file="$2"
    shift 2
    local cmd=("$@")

    log_step "$label"
    mkdir -p "$(dirname "$report_file")"

    if "${cmd[@]}" > "$report_file" 2>&1; then
        pass "$label"
        return 0
    else
        fail "$label"
        echo -e "  ${YELLOW}→ Rapport complet : ${report_file}${NC}"
        # Afficher les 25 premières lignes d'erreur directement dans le terminal
        echo -e "  ${YELLOW}→ Aperçu :${NC}"
        head -25 "$report_file" | sed 's/^/    /'
        local lines
        lines=$(wc -l < "$report_file")
        if [ "$lines" -gt 25 ]; then
            echo -e "    ${YELLOW}... (${lines} lignes au total, voir le rapport)${NC}"
        fi
        return 1
    fi
}

# ── Installation des outils Python si absents ─────────────────────────────────
ensure_python_tools() {
    local tools_needed=()
    command -v flake8   &>/dev/null || tools_needed+=("flake8")
    command -v bandit   &>/dev/null || tools_needed+=("bandit")
    command -v pip-audit &>/dev/null || tools_needed+=("pip-audit")

    if [ ${#tools_needed[@]} -gt 0 ]; then
        log_step "Installation des outils Python manquants : ${tools_needed[*]}"
        pip install --quiet "${tools_needed[@]}" 2>&1 | tail -3
    fi
}

# ── Vérifier la présence de mvn ───────────────────────────────────────────────
ensure_java_tools() {
    if ! command -v mvn &>/dev/null; then
        echo -e "${RED}[ERREUR] Maven (mvn) est requis pour l'analyse Java.${NC}"
        echo -e "${YELLOW}         Installe Maven : https://maven.apache.org/install.html${NC}"
        return 1
    fi
    if ! command -v java &>/dev/null; then
        echo -e "${RED}[ERREUR] Java est requis.${NC}"
        return 1
    fi
    local java_version
    java_version=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | cut -d'.' -f1)
    if [ "${java_version:-0}" -lt 21 ]; then
        echo -e "${YELLOW}[ATTENTION] Java 21+ recommandé (détecté : ${java_version})${NC}"
    fi
    return 0
}

# =============================================================================
# SCAN DE SECRETS — GitLeaks (une seule fois pour tout le repo)
# =============================================================================
run_gitleaks() {
    log_section "SCAN DE SECRETS — GitLeaks"

    if [ "$SKIP_GITLEAKS" = true ]; then
        skip "GitLeaks (--no-gitleaks passé)"
        return
    fi

    if ! command -v gitleaks &>/dev/null; then
        echo -e "${YELLOW}  GitLeaks non trouvé. Installation depuis GitHub releases...${NC}"
        local os_name arch download_url tmp_dir gitleaks_version
        
        os_name=$(uname -s | tr '[:upper:]' '[:lower:]')
        arch=$(uname -m | sed 's/x86_64/x64/' | sed 's/aarch64/arm64/')
        
        # Version fixe pour éviter de dépendre de l'API GitHub
        gitleaks_version="8.30.1"

        download_url="https://github.com/gitleaks/gitleaks/releases/download/v${gitleaks_version}/gitleaks_${gitleaks_version}_${os_name}_${arch}.tar.gz"
        tmp_dir=$(mktemp -d)

        mkdir -p "${HOME}/.local/bin"

        # On affiche les erreurs pour comprendre si ça échoue à nouveau
        if curl -sSL "$download_url" | tar -xz -C "$tmp_dir" && [ -f "${tmp_dir}/gitleaks" ]; then
            sudo mv "${tmp_dir}/gitleaks" /usr/local/bin/gitleaks 2>/dev/null || \
                mv "${tmp_dir}/gitleaks" "${HOME}/.local/bin/gitleaks" 2>/dev/null || {
                skip "GitLeaks (impossible d'installer, ajoutez-le manuellement)"
                rm -rf "$tmp_dir"
                return
            }
            chmod +x /usr/local/bin/gitleaks 2>/dev/null || \
                chmod +x "${HOME}/.local/bin/gitleaks" 2>/dev/null
            rm -rf "$tmp_dir"
        else
            skip "GitLeaks (téléchargement échoué — vérifiez l'URL : $download_url)"
            rm -rf "$tmp_dir"
            return
        fi
    fi

    run_check \
        "GitLeaks — scan de secrets dans tout le repo" \
        "${REPORT_DIR}/gitleaks-report.json" \
        gitleaks detect \
            --source="${ROOT_DIR}" \
            --report-format=json \
            --report-path="${REPORT_DIR}/gitleaks-report.json" \
            --no-git \
            --exit-code 1
}

# =============================================================================
# PYTHON — student-service
# =============================================================================
run_student_service() {
    log_section "student-service (Python/Flask)"

    if [ ! -d "$STUDENT_DIR" ]; then
        echo -e "${YELLOW}  Dossier student-service introuvable : ${STUDENT_DIR}${NC}"
        skip "student-service (dossier absent)"
        return
    fi

    ensure_python_tools

    local report_base="${REPORT_DIR}/student-service"
    mkdir -p "$report_base"

    # -- Flake8 ----------------------------------------------------------------
    local flake8_config=""
    [ -f "${CONFIG_DIR}/.flake8" ] && flake8_config="--config=${CONFIG_DIR}/.flake8"

    if [ "$FIX_MODE" = true ] && command -v autopep8 &>/dev/null; then
        log_step "autopep8 — correction automatique de style"
        autopep8 --in-place --recursive \
            --max-line-length 120 \
            --exclude "${STUDENT_DIR}/migrations" \
            "${STUDENT_DIR}/app/" 2>&1 | tail -5
    fi

    run_check \
        "Flake8 — linting PEP8" \
        "${report_base}/flake8.txt" \
        flake8 "${STUDENT_DIR}/app/" \
            $flake8_config \
            --format="%(path)s:%(row)d:%(col)d: %(code)s %(text)s"

    # -- Bandit ----------------------------------------------------------------
    local bandit_config=""
    [ -f "${CONFIG_DIR}/bandit.ini" ] && bandit_config="--ini=${CONFIG_DIR}/bandit.ini"

    run_check \
        "Bandit — SAST (vulnérabilités sécurité)" \
        "${report_base}/bandit.txt" \
        bandit \
            --recursive "${STUDENT_DIR}/app/" \
            $bandit_config \
            --severity-level medium \
            --confidence-level medium \
            --format txt \
            --output "${report_base}/bandit.txt"

    # -- pip-audit -------------------------------------------------------------
    if [ -f "${STUDENT_DIR}/requirements.txt" ]; then
        run_check \
            "pip-audit — audit des dépendances (CVE)" \
            "${report_base}/pip-audit.txt" \
            pip-audit \
                --requirement "${STUDENT_DIR}/requirements.txt" \
                --output "${report_base}/pip-audit.json" \
                --format json
    else
        skip "pip-audit student-service (requirements.txt absent)"
    fi
}

# =============================================================================
# PYTHON — enrollment-service
# =============================================================================
run_enrollment_service() {
    log_section "enrollment-service (Python/Flask)"

    if [ ! -d "$ENROLL_DIR" ]; then
        skip "enrollment-service (dossier absent)"
        return
    fi

    ensure_python_tools

    local report_base="${REPORT_DIR}/enrollment-service"
    mkdir -p "$report_base"

    local flake8_config=""
    [ -f "${CONFIG_DIR}/.flake8" ] && flake8_config="--config=${CONFIG_DIR}/.flake8"

    # -- Flake8 ----------------------------------------------------------------
    run_check \
        "Flake8 — linting PEP8" \
        "${report_base}/flake8.txt" \
        flake8 "${ENROLL_DIR}/app/" \
            $flake8_config \
            --format="%(path)s:%(row)d:%(col)d: %(code)s %(text)s"

    # -- Bandit ----------------------------------------------------------------
    local bandit_config=""
    [ -f "${CONFIG_DIR}/bandit.ini" ] && bandit_config="--ini=${CONFIG_DIR}/bandit.ini"

    run_check \
        "Bandit — SAST (vulnérabilités sécurité)" \
        "${report_base}/bandit.txt" \
        bandit \
            --recursive "${ENROLL_DIR}/app/" \
            $bandit_config \
            --severity-level medium \
            --confidence-level medium \
            --format txt \
            --output "${report_base}/bandit.txt"

    # -- pip-audit -------------------------------------------------------------
    if [ -f "${ENROLL_DIR}/requirements.txt" ]; then
        run_check \
            "pip-audit — audit des dépendances (CVE)" \
            "${report_base}/pip-audit.txt" \
            pip-audit \
                --requirement "${ENROLL_DIR}/requirements.txt" \
                --output "${report_base}/pip-audit.json" \
                --format json
    else
        skip "pip-audit enrollment-service (requirements.txt absent)"
    fi
}

# =============================================================================
# JAVA — teacher-admin-service
# =============================================================================
run_teacher_service() {
    log_section "teacher-admin-service (Java/Spring Boot)"

    if [ ! -d "$TEACHER_DIR" ]; then
        skip "teacher-admin-service (dossier absent)"
        return
    fi

    if ! ensure_java_tools; then
        skip "teacher-admin-service (Java/Maven absent)"
        return
    fi

    local report_base="${REPORT_DIR}/teacher-admin-service"
    mkdir -p "$report_base"

    # Télécharger Checkstyle JAR si absent
    local checkstyle_jar="${SCRIPT_DIR}/../lint/tools/checkstyle.jar"
    mkdir -p "$(dirname "$checkstyle_jar")"
    if [ ! -f "$checkstyle_jar" ]; then
        log_step "Téléchargement de Checkstyle..."
        local cs_version="14.1.0"
        curl -sSL \
            "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-${cs_version}/checkstyle-${cs_version}-all.jar" \
            -o "$checkstyle_jar" || {
            skip "Checkstyle (téléchargement échoué)"
            checkstyle_jar=""
        }
    fi

    # Télécharger PMD si absent
    local pmd_dir="${SCRIPT_DIR}/../lint/tools/pmd"
    if [ ! -d "$pmd_dir" ]; then
        log_step "Téléchargement de PMD..."
        local pmd_version="7.27.0"
        local pmd_zip="/tmp/pmd-${pmd_version}.zip"
        curl -sSL \
            "https://github.com/pmd/pmd/releases/download/pmd_releases%2F${pmd_version}/pmd-dist-${pmd_version}-bin.zip" \
            -o "$pmd_zip" && \
        unzip -q "$pmd_zip" -d "${SCRIPT_DIR}/../lint/tools/" && \
        mv "${SCRIPT_DIR}/../lint/tools/pmd-bin-${pmd_version}" "$pmd_dir" && \
        rm -f "$pmd_zip" || {
            skip "PMD (téléchargement échoué)"
            pmd_dir=""
        }
    fi

    # -- Checkstyle ------------------------------------------------------------
    log_section "${CONFIG_DIR}checkstyle-sun.xml"
    if [ -n "${checkstyle_jar:-}" ] && [ -f "$checkstyle_jar" ]; then
        local cs_config="${CONFIG_DIR}/checkstyle-sun.xml"
        if [ ! -f "$cs_config" ]; then
            cs_config="${CONFIG_DIR}/checkstyle-sun.xml"  # fallback vers le profil intégré
        fi

        run_check \
            "Checkstyle — style de code (profil Sun)" \
            "${report_base}/checkstyle.xml" \
            java -jar "$checkstyle_jar" \
                -c "$cs_config" \
                -f xml \
                -o "${report_base}/checkstyle.xml" \
                "${TEACHER_DIR}/src/main/java"
    else
        skip "Checkstyle (JAR non disponible)"
    fi

    # -- PMD -------------------------------------------------------------------
    if [ -n "${pmd_dir:-}" ] && [ -d "$pmd_dir" ]; then
        local pmd_bin="${pmd_dir}/bin/pmd"
        local pmd_ruleset="${CONFIG_DIR}/pmd-ruleset.xml"
        echo $pmd_ruleset
        echo $(pwd)
        [ -f "$pmd_ruleset" ] && echo "Ruleset trouvé : $pmd_ruleset" || echo "Ruleset non trouvé : $pmd_ruleset"
        [ ! -f "$pmd_ruleset" ] && pmd_ruleset="rulesets/java/quickstart.xml"
        run_check \
            "PMD — analyse statique (bugs, code mort, complexité)" \
            "${report_base}/pmd.xml" \
            "$pmd_bin" check \
                --dir "${TEACHER_DIR}/src/main/java" \
                --rulesets "$pmd_ruleset" \
                --format xml \
                --report-file "${report_base}/pmd.xml" \
                --minimum-priority 3
    else
        skip "PMD (binaire non disponible)"
    fi

    # -- OWASP Dependency Check v12.1.6 ----------------------------------------
    # Depuis v9.0.0+ : utilise l'API NVD (plus le data feed).
    # Sans NVD_API_KEY : téléchargement très lent (rate limit 5 req/30s ≈ 2h+).
    # Avec NVD_API_KEY  : ~2-5 min. Obtenir gratuitement sur :
    #   https://nvd.nist.gov/developers/request-an-api-key
    # Exporter avant de lancer : export NVD_API_KEY=votre-clé
    log_step "OWASP Dependency Check v12.1.6 — SCA (CVE sur les dépendances Maven)"

    local dc_report="${report_base}/dependency-check"
    mkdir -p "$dc_report"

    if [ -z "${NVD_API_KEY:-}" ]; then
        echo -e "  ${YELLOW}⚠ NVD_API_KEY non définie — mise à jour de la base NVD sera très lente.${NC}"
        echo -e "  ${YELLOW}  Obtenir une clé gratuite : https://nvd.nist.gov/developers/request-an-api-key${NC}"
        echo -e "  ${YELLOW}  Puis : export NVD_API_KEY=votre-clé${NC}"
        NVD_API_ARGS=""
    else
        echo -e "  ${GREEN}→ NVD_API_KEY détectée, mise à jour rapide activée${NC}"
        NVD_API_ARGS="-DnvdApiKey=${NVD_API_KEY}"
    fi

    if mvn -f "${TEACHER_DIR}/pom.xml" \
            org.owasp:dependency-check-maven:12.1.6:check \
            -DfailBuildOnCVSS=7 \
            -DsuppressionFile="${CONFIG_DIR}/dependency-check-suppression.xml" \
            -DreportOutputDirectory="$dc_report" \
            -Dformats=HTML,JSON \
            ${NVD_API_ARGS} \
            --no-transfer-progress \
            -q > "${report_base}/dependency-check.log" 2>&1; then
        pass "OWASP Dependency Check — aucune CVE ≥ 9.8"
        echo -e "  ${GREEN}→ Rapport HTML : ${dc_report}/dependency-check-report.html${NC}"
    else
        if grep -q "CVE" "${report_base}/dependency-check.log" 2>/dev/null; then
            fail "OWASP Dependency Check — CVE(s) détectée(s) (score ≥ 9.8)"
        else
            echo -e "  ${YELLOW}⚠ Dependency Check — résultat incertain (voir log)${NC}"
            echo -e "  ${YELLOW}→ Log : ${report_base}/dependency-check.log${NC}"
            SKIPPED=$((SKIPPED))
        fi
        echo -e "  ${YELLOW}→ Rapport complet : ${dc_report}/dependency-check-report.html${NC}"
    fi
    TOTAL_CHECKS=$((TOTAL_CHECKS))
}

# =============================================================================
# RÉSUMÉ FINAL
# =============================================================================
print_summary() {
    echo ""
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${BLUE}  RÉSUMÉ DE L'ANALYSE${NC}"
    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  Total     : ${BOLD}${TOTAL_CHECKS} vérifications${NC}"
    echo -e "  ${GREEN}Passées   : ${PASSED}${NC}"
    echo -e "  ${RED}Échouées  : ${FAILED}${NC}"
    echo -e "  ${YELLOW}Ignorées  : ${SKIPPED}${NC}"
    echo ""

    if [ ${#FAILED_CHECKS[@]} -gt 0 ]; then
        echo -e "  ${RED}${BOLD}Vérifications échouées :${NC}"
        for check in "${FAILED_CHECKS[@]}"; do
            echo -e "    ${RED}• ${check}${NC}"
        done
        echo ""
    fi

    echo -e "  Rapports détaillés : ${BOLD}${REPORT_DIR}/${NC}"
    echo ""

    if [ "$FAILED" -eq 0 ]; then
        echo -e "${GREEN}${BOLD}  ✓ Tout est propre !${NC}"
    else
        echo -e "${RED}${BOLD}  ✗ ${FAILED} vérification(s) ont échoué.${NC}"
        echo -e "${YELLOW}    Consultez les rapports dans ${REPORT_DIR}/${NC}"
    fi

    echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════════${NC}"
    echo ""
}

# =============================================================================
# POINT D'ENTRÉE
# =============================================================================

mkdir -p "$REPORT_DIR"

echo -e "${BOLD}${BLUE}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║     Analyse qualité — University System          ║"
echo "  ║     Lint · SAST · Secrets · SCA                 ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  Racine du projet : ${ROOT_DIR}"
echo -e "  Rapports vers    : ${REPORT_DIR}"
echo -e "  Mode fix         : ${FIX_MODE}"

# GitLeaks — toujours, sauf si --no-gitleaks
run_gitleaks

# Sélection des services à analyser
case "${SERVICE_FILTER}" in
    student)
        run_student_service
        ;;
    teacher)
        run_teacher_service
        ;;
    enroll|enrollment)
        run_enrollment_service
        ;;
    "")
        # Tous les services
        run_student_service
        run_enrollment_service
        run_teacher_service
        ;;
    *)
        echo -e "${RED}Service inconnu : ${SERVICE_FILTER}${NC}"
        echo "Valeurs possibles : student | teacher | enroll"
        exit 1
        ;;
esac

print_summary

[ "$FAILED" -eq 0 ] && exit 0 || exit 1