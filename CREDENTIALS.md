# Local-development credentials

Everything here is a **local-development-only** credential. All published ports bind to 127.0.0.1.
Values live in `.env` (gitignored; copied from `.env.example`). Nothing in this file is secret in the
production sense; it exists so you can find every login quickly.

## Browser logins

| Service | URL | Username | Password (`.env` variable) |
|---|---|---|---|
| Custodian Console | http://localhost:13000 | `clerk` / `controller` / `cfo` (Keycloak) | `KC_CLERK_PASSWORD` / `KC_CONTROLLER_PASSWORD` / `KC_CFO_PASSWORD` |
| Keycloak admin console | http://localhost:18081/admin | `admin` | `KEYCLOAK_ADMIN_PASSWORD` |
| Infisical | http://localhost:18082 | `INFISICAL_ADMIN_EMAIL` | `INFISICAL_ADMIN_PASSWORD` |
| Grafana | http://localhost:13002 | `admin` | `GRAFANA_ADMIN_PASSWORD` |
| Langfuse | http://localhost:13001 | `LANGFUSE_ADMIN_EMAIL` | `LANGFUSE_ADMIN_PASSWORD` |
| MinIO console | http://localhost:19001 | `MINIO_ROOT_USER` | `MINIO_ROOT_PASSWORD` |
| MLflow UI | http://localhost:15000 | (no auth) | - |
| OpenMetadata | http://localhost:18585 | `admin@open-metadata.org` | `admin` (OpenMetadata's built-in default) |
| Prometheus | http://localhost:19090 | (no auth) | - |
| LiteLLM admin API | http://localhost:14000 | bearer token | `LITELLM_MASTER_KEY` |

Keycloak approval tiers (enforced by `policies/human-approval.cedar`): `clerk` = ap_clerk (up to
$10,000), `controller` = finance_controller (up to $100,000; may operate the kill switch), `cfo` = cfo
(any amount; may operate the kill switch).

## Service and machine credentials

| Credential | Used by | Where it lives |
|---|---|---|
| Postgres superuser `postgres` | admin only | `POSTGRES_PASSWORD` |
| Postgres roles `custodian`, `ledger`, `audit`, `keycloak`, `infisical`, `litellm`, `mlflow`, `langfuse`, `openmetadata_user` | one per service, own database each | `*_DB_PASSWORD` |
| MinIO `audit-writer` (put/get/list only on `audit-log`) | custodian-audit-log | `AUDIT_MINIO_PASSWORD` |
| MinIO `langfuse` (bucket `langfuse` only) | Langfuse | `LANGFUSE_MINIO_PASSWORD` |
| Redis | Langfuse (db 0), Infisical (db 1) | `REDIS_PASSWORD` |
| Infisical identity `custodian-payment-execution` | backend, payment path | `PAYMENT_EXEC_CLIENT_ID/SECRET` -> reads `LEDGER_API_KEY` |
| Infisical identity `custodian-vendor-lookup` | backend, risk path + console reads | `VENDOR_LOOKUP_CLIENT_ID/SECRET` -> reads `VENDOR_LOOKUP_API_KEY` |
| Infisical identity `custodian-ledger-service` | custodian-ledger | `LEDGER_SERVICE_CLIENT_ID/SECRET` -> reads both keys to verify callers |
| Infisical identity `custodian-litellm` | LiteLLM entrypoint | `LITELLM_CLIENT_ID/SECRET` -> reads `OPENAI_API_KEY`, `GROQ_API_KEY` |
| `LEDGER_API_KEY`, `VENDOR_LOOKUP_API_KEY` | ledger write / ledger read | Infisical only |
| LiteLLM virtual keys | one per LLM-using agent + the eval job | `LITELLM_KEY_*` |
| Langfuse project keys | backend OTLP exporter | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` |
| SPIRE join token | spire-agent first attestation | `SPIRE_JOIN_TOKEN` (single use) |
