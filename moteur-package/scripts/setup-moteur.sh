#!/bin/bash
# Construit, publie et déploie le moteur de vérification et son tableau de bord.
#
# Usage :
#   ENGINE_DB_PASSWORD='...' ENGINE_AUDIT_PASSWORD='...' DASHBOARD_DB_PASSWORD='...' \
#     bash scripts/setup-moteur.sh
#
# Mots de passe obligatoires (les rôles existent déjà : setup_engine_db.sh et setup_audit_db.sh) :
#   ENGINE_DB_PASSWORD       rôle engine_ro      (lit la compatibilité de schéma)
#   ENGINE_AUDIT_PASSWORD    rôle moteur_audit   (écrit l'historique des verdicts)
#   DASHBOARD_DB_PASSWORD    rôle moteur_viewer  (le tableau de bord lit, en lecture seule)
#
# Alertes WhatsApp via Twilio (facultatif : définir les QUATRE ou aucune) :
#   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM (ex. whatsapp:+14155238886),
#   WHATSAPP_TO (ex. whatsapp:+261...). Sans elles, les alertes sont enregistrées (statut disabled).
#
# Variables facultatives :
#   TAG=0.1.0          tag de l'image (à changer à chaque nouvelle version du code)
#   DRY_RUN=true       "false" : le moteur AGIT réellement (exige aussi CONFIRM_LIVE=yes)
#   K3D_CLUSTER=nom    importe l'image dans ce cluster k3d au lieu de la pousser
#   SKIP_PUSH=1        ne pousse pas l'image (déjà disponible pour le cluster)
#   REGISTRY=docker.io/darbi
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="university-moteur"
RELEASE="university-moteur"
REGISTRY="${REGISTRY:-docker.io/darbi}"
IMAGE_NAME="university-moteur"
TAG="${TAG:-0.1.0}"
DRY_RUN="${DRY_RUN:-true}"
IMAGE="$REGISTRY/$IMAGE_NAME:$TAG"

: "${ENGINE_DB_PASSWORD:?Définis ENGINE_DB_PASSWORD (rôle engine_ro, voir setup_engine_db.sh)}"
: "${ENGINE_AUDIT_PASSWORD:?Définis ENGINE_AUDIT_PASSWORD (rôle moteur_audit, voir setup_audit_db.sh)}"
: "${DASHBOARD_DB_PASSWORD:?Définis DASHBOARD_DB_PASSWORD (rôle moteur_viewer, voir setup_audit_db.sh)}"

for cmd in docker kubectl helm; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Commande introuvable : $cmd" >&2; exit 1; }
done

case "$DRY_RUN" in
  true) ;;
  false)
    if [ "${CONFIRM_LIVE:-}" != "yes" ]; then
      echo "DRY_RUN=false : le moteur redémarrerait, redimensionnerait et restaurerait de vrais déploiements." >&2
      echo "Relance avec CONFIRM_LIVE=yes pour confirmer." >&2
      exit 1
    fi ;;
  *) echo "DRY_RUN doit valoir true ou false (reçu : $DRY_RUN)" >&2; exit 1 ;;
esac

# Twilio : les quatre variables ou aucune (échec rapide, avant la construction de l'image)
TWILIO_SET=0
for v in TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_WHATSAPP_FROM WHATSAPP_TO; do
  if [ -n "${!v:-}" ]; then TWILIO_SET=$((TWILIO_SET + 1)); fi
done
if [ "$TWILIO_SET" -ne 0 ] && [ "$TWILIO_SET" -ne 4 ]; then
  echo "Twilio : $TWILIO_SET variable(s) sur 4. Définis TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN," >&2
  echo "TWILIO_WHATSAPP_FROM et WHATSAPP_TO, ou aucune." >&2
  exit 1
fi

apply_secret() {   # usage : apply_secret <nom> clé=valeur [clé=valeur ...]
  local name="$1"; shift
  local args=() kv
  for kv in "$@"; do args+=("--from-literal=$kv"); done
  kubectl create secret generic "$name" -n "$NS" "${args[@]}" --dry-run=client -o yaml | kubectl apply -f -
}

echo "Cluster : $(kubectl config current-context)  |  image : $IMAGE  |  mode : DRY_RUN=$DRY_RUN"

echo "[1/5] Construction de l'image"
docker build -t "$IMAGE" "$ROOT/app"

echo "[2/5] Publication de l'image"
if [ -n "${K3D_CLUSTER:-}" ]; then
  k3d image import "$IMAGE" -c "$K3D_CLUSTER"
elif [ -n "${SKIP_PUSH:-}" ]; then
  echo "  push ignoré (SKIP_PUSH)"
else
  docker push "$IMAGE"
fi

echo "[3/5] Namespace $NS (Pod Security : restricted)"
kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: $NS
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
EOF

echo "[4/5] Secrets (un par rôle : lecture du schéma, écriture de l'historique, lecture du tableau de bord)"
apply_secret moteur-db username=engine_ro password="$ENGINE_DB_PASSWORD"
apply_secret moteur-audit username=moteur_audit password="$ENGINE_AUDIT_PASSWORD"
apply_secret moteur-dashboard-db username=moteur_viewer password="$DASHBOARD_DB_PASSWORD"
if [ "$TWILIO_SET" -eq 4 ]; then
  apply_secret moteur-twilio sid="$TWILIO_ACCOUNT_SID" token="$TWILIO_AUTH_TOKEN" \
    from="$TWILIO_WHATSAPP_FROM" to="$WHATSAPP_TO"
else
  echo "  Twilio non configuré : les alertes seront enregistrées sans envoi (statut disabled)"
fi

echo "[5/5] Déploiement Helm"
helm upgrade --install "$RELEASE" "$ROOT/university-moteur" -n "$NS" \
  --set-string image.registry="$REGISTRY" \
  --set-string image.tag="$TAG" \
  --set-string config.dryRun="$DRY_RUN" \
  --wait --timeout 180s

echo
echo "Moteur et tableau de bord déployés."
echo "  Verdicts en direct :  kubectl logs -n $NS deploy/moteur -f"
echo "  Tableau de bord    :  kubectl port-forward -n $NS svc/moteur-dashboard 8088:80   puis http://localhost:8088"
if [ "$DRY_RUN" = "true" ]; then
  echo "Le moteur est en dry-run (aucune action réelle). Pour passer en mode réel :"
  echo "  DRY_RUN=false CONFIRM_LIVE=yes ... bash scripts/setup-moteur.sh   (mêmes variables)"
fi
