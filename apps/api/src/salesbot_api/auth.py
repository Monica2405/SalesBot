"""Verify Supabase Auth JWTs sent by the admin app (Authorization: Bearer <access_token>).

Supports both Supabase signing modes:
- HS256 with the project's legacy JWT secret (SUPABASE_JWT_SECRET; also what local dev uses)
- asymmetric keys (ES256/RS256) via the project's JWKS endpoint
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from salesbot_api.settings import Settings, get_settings

AUDIENCE = "authenticated"


class AuthUser(BaseModel):
    id: UUID
    email: str | None = None
    claims: dict[str, Any]


class InvalidTokenError(Exception):
    pass


@lru_cache
def _jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def verify_supabase_jwt(token: str, settings: Settings) -> AuthUser:
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256":
            if settings.supabase_jwt_secret is None:
                raise InvalidTokenError("SUPABASE_JWT_SECRET is not configured")
            key: Any = settings.supabase_jwt_secret.get_secret_value()
        elif alg in ("ES256", "RS256"):
            if not settings.supabase_url:
                raise InvalidTokenError("SUPABASE_URL is not configured")
            key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token).key
        else:
            raise InvalidTokenError(f"unsupported alg {alg!r}")
        claims = jwt.decode(token, key, algorithms=[alg], audience=AUDIENCE)
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    return AuthUser(id=UUID(claims["sub"]), email=claims.get("email"), claims=claims)


_bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return verify_supabase_jwt(creds.credentials, settings)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
