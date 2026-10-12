#!/bin/bash
# Usage : bash set_schema.sh 0001   -> supprime discount_code, alembic_version = 0001
#         bash set_schema.sh 0002   -> ajoute discount_code (NOT NULL, sans default), alembic_version = 0002
# Ne touche QUE à la base : le helm upgrade (1.6 / 1.7) reste manuel.
set -euo pipefail

TARGET="${1:-}"
NS="university-app"
POD="postgres-0"
DB_USER="postgres_admin"
DB_NAME="university_db"

case "$TARGET" in
  0001) SQL="
ALTER TABLE enrollment_schema.enrollments DROP COLUMN IF EXISTS discount_code;
UPDATE enrollment_schema.alembic_version SET version_num = '0001';
" ;;
  0002) SQL="
ALTER TABLE enrollment_schema.enrollments
  ADD COLUMN IF NOT EXISTS discount_code VARCHAR(50) NOT NULL DEFAULT 'NONE';
ALTER TABLE enrollment_schema.enrollments ALTER COLUMN discount_code DROP DEFAULT;
UPDATE enrollment_schema.alembic_version SET version_num = '0002';
" ;;
  *) echo "Usage : $0 <0001|0002>"; exit 1 ;;
esac

# -1 : tout dans une seule transaction (tout passe ou rien)
echo "$SQL" | kubectl exec -i -n "$NS" "$POD" -- \
  psql -v ON_ERROR_STOP=1 -1 -U "$DB_USER" -d "$DB_NAME"

echo ">> Vérification"
kubectl exec -n "$NS" "$POD" -- psql -U "$DB_USER" -d "$DB_NAME" \
  -c "SELECT version_num FROM enrollment_schema.alembic_version;" \
  -c "SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_schema='enrollment_schema' AND table_name='enrollments' ORDER BY ordinal_position;"