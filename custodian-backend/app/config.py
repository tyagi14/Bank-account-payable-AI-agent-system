import os


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"missing required environment variable {name}")
    return value


CUSTODIAN_DB_URL = _env("CUSTODIAN_DB_URL")
LITELLM_URL = _env("LITELLM_URL", "http://litellm:4000")
LITELLM_KEYS = {
    "extraction": _env("LITELLM_KEY_EXTRACTION", ""),
    "risk-scoring": _env("LITELLM_KEY_RISK", ""),
    "approval": _env("LITELLM_KEY_APPROVAL", ""),
}
POLICY_SERVICE_URL = _env("POLICY_SERVICE_URL", "http://policy-service:8000")
CONTROL_PLANE_URL = _env("CONTROL_PLANE_URL", "http://custodian-control-plane:8000")
AUDIT_LOG_URL = _env("AUDIT_LOG_URL", "http://custodian-audit-log:8000")
LEDGER_URL = _env("LEDGER_URL", "http://custodian-ledger:8000")
SANDBOX_RUNNER_URL = _env("SANDBOX_RUNNER_URL", "http://custodian-sandbox-runner:8000")
INFISICAL_URL = _env("INFISICAL_URL", "http://infisical:8080")
LANGFUSE_URL = _env("LANGFUSE_URL", "http://langfuse-web:3000")
LANGFUSE_PUBLIC_KEY = _env("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = _env("LANGFUSE_SECRET_KEY", "")
KEYCLOAK_JWKS_URL = _env("KEYCLOAK_JWKS_URL", "http://keycloak:8080/realms/custodian/protocol/openid-connect/certs")
KEYCLOAK_ISSUER = _env("KEYCLOAK_ISSUER", "http://localhost:18081/realms/custodian")
SPIFFE_EXPECTED_ID = _env("SPIFFE_EXPECTED_ID", "spiffe://custodian.local/service/custodian-backend")

ROUTINE_AMOUNT_CENTS = int(_env("ROUTINE_AMOUNT_CENTS", "100000"))
DECISION_CONFIDENCE_MIN = float(_env("DECISION_CONFIDENCE_MIN", "0.75"))
SETTLEMENT_HOLD_SECONDS = int(_env("SETTLEMENT_HOLD_SECONDS", "20"))
CORS_ORIGINS = _env("CORS_ORIGINS", "http://localhost:13000").split(",")

# Each machine identity can read exactly one Infisical project (see provision-infisical-identities.py).
INFISICAL_IDENTITIES = {
    "ledger-write": (_env("PAYMENT_EXEC_CLIENT_ID", ""), _env("PAYMENT_EXEC_CLIENT_SECRET", ""), _env("INFISICAL_PROJECT_LEDGER_WRITE", ""), "LEDGER_API_KEY"),
    "vendor-lookup": (_env("VENDOR_LOOKUP_CLIENT_ID", ""), _env("VENDOR_LOOKUP_CLIENT_SECRET", ""), _env("INFISICAL_PROJECT_VENDOR_LOOKUP", ""), "VENDOR_LOOKUP_API_KEY"),
}
