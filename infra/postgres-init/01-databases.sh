#!/bin/sh
# Runs once on a fresh data volume: one database + one login role per service.
set -eu
create() {
  psql -v ON_ERROR_STOP=1 -U postgres <<SQL
CREATE ROLE $1 LOGIN PASSWORD '$2';
CREATE DATABASE $3 OWNER $1;
SQL
}
create custodian "$CUSTODIAN_DB_PASSWORD" custodian
create ledger "$LEDGER_DB_PASSWORD" ledger
create audit "$AUDIT_DB_PASSWORD" audit
create keycloak "$KEYCLOAK_DB_PASSWORD" keycloak
create infisical "$INFISICAL_DB_PASSWORD" infisical
create litellm "$LITELLM_DB_PASSWORD" litellm
create mlflow "$MLFLOW_DB_PASSWORD" mlflow
create langfuse "$LANGFUSE_DB_PASSWORD" langfuse
create openmetadata_user "$OPENMETADATA_DB_PASSWORD" openmetadata_db
