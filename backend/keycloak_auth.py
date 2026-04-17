from __future__ import annotations

from functools import lru_cache

import jwt
from jwt import PyJWKClient

from settings import settings


@lru_cache(maxsize=8)
def _jwks_for_issuer(issuer: str) -> PyJWKClient:
    pub = settings.keycloak_url.rstrip("/")
    internal = (settings.keycloak_internal_url or settings.keycloak_url).rstrip("/")
    iss = issuer.rstrip("/")
    if pub and internal != pub and iss.startswith(pub):
        iss = iss.replace(pub, internal, 1)
    return PyJWKClient(f"{iss}/protocol/openid-connect/certs")


def verify_keycloak_token(token: str) -> dict:
    unverified = jwt.decode(token, options={"verify_signature": False})
    issuer = (unverified.get("iss") or "").strip().rstrip("/")
    if not issuer:
        raise ValueError("missing iss")
    claims = jwt.decode(
        token,
        _jwks_for_issuer(issuer).get_signing_key_from_jwt(token).key,
        algorithms=["RS256"],
        issuer=issuer,
        options={"verify_aud": False},
    )
    if (claims.get("azp") or claims.get("client_id")) != settings.keycloak_client_id:
        raise ValueError("azp mismatch")
    return claims


def claims_username(claims: dict) -> str:
    return str(claims.get("preferred_username") or claims.get("email") or claims.get("sub") or "unknown")
