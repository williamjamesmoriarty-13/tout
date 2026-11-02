#!/bin/bash
# Crée l'historique durable du moteur dans Postgres :
#   - schéma moteur_schema, tables verdicts et notifications ;
#   - rôle moteur_audit  : INSERT + SELECT sur ces deux tables (le moteur écrit) ;
#   - rôle moteur_viewer : SELECT seulement, session en lecture seule (le tableau de bord lit).
# Aucun de ces rôles ne voit les schémas de l'application.
#
# Usage : ENGINE_AUDIT_PASSWORD='...' DASHBOARD_DB_PASSWORD='...' bash scripts/setup_audit_db.sh
# Relançable : tables et rôles sont créés s'ils manquent, les mots de passe sont remis à jour.
set -euo pipefail

: "${ENGINE_AUDIT_PASSWORD:?Définis ENGINE_AUDIT_PASSWORD (mot de passe du rôle moteur_audit)}"
: "${DASHBOARD_DB_PASSWORD:?Définis DASHBOARD_DB_PASSWORD (mot de passe du rôle moteur_viewer)}"

NS="university-app"
POD="postgres-0"
ADMIN="postgres_admin"
DB="university_db"

kubectl exec -i -n "$NS" "$POD" -- \
  psql -v ON_ERROR_STOP=1 -v audit_pw="$ENGINE_AUDIT_PASSWORD" -v viewer_pw="$DASHBOARD_DB_PASSWORD" \
       -U "$ADMIN" -d "$DB" <<'SQL'
CREATE SCHEMA IF NOT EXISTS moteur_schema;

CREATE TABLE IF NOT EXISTS moteur_schema.verdicts (
    id                  bigserial PRIMARY KEY,
    recorded_at         timestamptz NOT NULL DEFAULT now(),
    proposal_ts         timestamptz,
    verdict_ts          timestamptz,
    mode                text NOT NULL,
    action              text NOT NULL,
    target              text NOT NULL,
    verdict             text NOT NULL CHECK (verdict IN ('ALLOW', 'DENY')),
    incident_id         text,
    attempt             integer,
    invariants_violated text[] NOT NULL DEFAULT '{}',
    justification       text,
    execution           jsonb,
    proposal            jsonb,
    evidence            jsonb,
    alerts              jsonb,
    cause_key           text,
    cause_group         text
);
CREATE INDEX IF NOT EXISTS verdicts_recorded_at_idx ON moteur_schema.verdicts (recorded_at DESC);
CREATE INDEX IF NOT EXISTS verdicts_cause_group_idx ON moteur_schema.verdicts (cause_group);

CREATE TABLE IF NOT EXISTS moteur_schema.notifications (
    id           bigserial PRIMARY KEY,
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    group_id     text NOT NULL,
    cause_key    text NOT NULL,
    channel      text NOT NULL DEFAULT 'whatsapp',
    status       text NOT NULL,
    message      text,
    services     text[] NOT NULL DEFAULT '{}',
    error        text,
    provider_sid text
);
CREATE INDEX IF NOT EXISTS notifications_group_idx ON moteur_schema.notifications (group_id);

SELECT format('CREATE ROLE moteur_audit LOGIN PASSWORD %L', :'audit_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'moteur_audit')
\gexec
SELECT format('CREATE ROLE moteur_viewer LOGIN PASSWORD %L', :'viewer_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'moteur_viewer')
\gexec
ALTER ROLE moteur_audit PASSWORD :'audit_pw';
ALTER ROLE moteur_viewer PASSWORD :'viewer_pw';
ALTER ROLE moteur_viewer SET default_transaction_read_only = on;

REVOKE ALL ON SCHEMA moteur_schema FROM PUBLIC;
GRANT CONNECT ON DATABASE university_db TO moteur_audit, moteur_viewer;
GRANT USAGE ON SCHEMA moteur_schema TO moteur_audit, moteur_viewer;
GRANT INSERT, SELECT ON moteur_schema.verdicts, moteur_schema.notifications TO moteur_audit;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA moteur_schema TO moteur_audit;
GRANT SELECT ON moteur_schema.verdicts, moteur_schema.notifications TO moteur_viewer;

SELECT 'historique du moteur prêt (moteur_audit écrit, moteur_viewer lit)' AS resultat;
SQL
