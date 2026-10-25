"""Keycloak access-token validation. Approval authority comes only from the verified token's realm roles."""
import jwt
from fastapi import Header, HTTPException

from app import config

_jwks = jwt.PyJWKClient(config.KEYCLOAK_JWKS_URL, cache_keys=True, lifespan=300)
ROLE_RANK = ["cfo", "finance_controller", "ap_clerk"]


def user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Keycloak bearer token required")
    token = authorization.removeprefix("Bearer ")
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=config.KEYCLOAK_ISSUER, options={"verify_aud": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc
    roles = set(claims.get("realm_access", {}).get("roles", []))
    role = next((r for r in ROLE_RANK if r in roles), None)
    if role is None:
        raise HTTPException(403, "no approval role")
    return {"username": claims["preferred_username"], "role": role, "token": token}
