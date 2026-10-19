#!/bin/bash
# Prépare l'invariant 2 du moteur :
#   1. crée la table enrollment_schema.service_compatibility si elle manque
#      et la remplit (plage de schémas supportée par chaque version) ;
#   2. crée le rôle Postgres en LECTURE SEULE engine_ro, qui ne voit que
#      alembic_version et service_compatibility, rien d'autre.
#
# Usage :
#   ENGINE_DB_PASSWORD='ton-mot-de-passe' bash setup_engine_db.sh
# Relançable : table et rôle sont créés s'ils manquent, les lignes de
# compatibilité et le mot de passe du rôle sont remis à jour.
set -euo pipefail

: "${ENGINE_DB_PASSWORD:?Définis ENGINE_DB_PASSWORD avant de lancer ce script}"

NS="university-app"
POD="postgres-0"
ADMIN="postgres_admin"
DB="university_db"

kubectl exec -i -n "$NS" "$POD" -- \
  psql -v ON_ERROR_STOP=1 -v pw="$ENGINE_DB_PASSWORD" -U "$ADMIN" -d "$DB" <<'SQL'

-- ── 1. Table de compatibilité version de service ↔ schéma DB ──
CREATE TABLE IF NOT EXISTS enrollment_schema.service_compatibility (
    service_name    TEXT NOT NULL,
    service_version TEXT NOT NULL,
    min_schema      TEXT NOT NULL,
    max_schema      TEXT NOT NULL,
    PRIMARY KEY (service_name, service_version)
);

-- À adapter à tes migrations Alembic :
--   1.6 ne fonctionne que sur le schéma 0001 ; 1.7 exige 0002.
INSERT INTO enrollment_schema.service_compatibility
    (service_name, service_version, min_schema, max_schema)
VALUES
    ('enrollment-service', '1.6', '0001', '0001'),
    ('enrollment-service', '1.7', '0002', '0002')
ON CONFLICT (service_name, service_version) DO UPDATE
    SET min_schema = EXCLUDED.min_schema,
        max_schema = EXCLUDED.max_schema;

ALTER TABLE enrollment_schema.service_compatibility OWNER TO enrollment_user;

-- ── 2. Rôle en lecture seule pour le moteur ──
SELECT format('CREATE ROLE engine_ro LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'engine_ro')
\gexec
ALTER ROLE engine_ro PASSWORD :'pw';
ALTER ROLE engine_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE university_db TO engine_ro;
GRANT USAGE ON SCHEMA enrollment_schema TO engine_ro;
GRANT SELECT ON enrollment_schema.alembic_version,
                enrollment_schema.service_compatibility TO engine_ro;

SELECT 'table service_compatibility et rôle engine_ro prêts (lecture seule)' AS resultat;
SQL