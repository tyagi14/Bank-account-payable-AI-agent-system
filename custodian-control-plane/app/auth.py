"""Validates Keycloak-issued access tokens for manual kill-switch operations."""
import os

import jwt
from fastapi import Header, HTTPException

JWKS = jwt.PyJWKClient(os.environ["KEYCLOAK_JWKS_URL"], cache_keys=True, lifespan=300)
ISSUER = os.environ["KEYCLOAK_ISSUER"]
OPERATOR_ROLES = {"finance_controller", "cfo"}


def require_operator(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Keycloak bearer token required")
    token = authorization.removeprefix("Bearer ")
    try:
        key = JWKS.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=ISSUER, options={"verify_aud": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc
    roles = set(claims.get("realm_access", {}).get("roles", []))
    if not roles & OPERATOR_ROLES:
        raise HTTPException(403, "kill switch operations need the finance_controller or cfo role")
    return {"username": claims.get("preferred_username"), "roles": sorted(roles & OPERATOR_ROLES)}
