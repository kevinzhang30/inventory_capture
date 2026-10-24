"""Authentication and role dependencies."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from fastapi import Depends, Request

from core_api.errors import ApiError
from inventory_common.auth import (
    AuthError,
    Principal,
    principal_from_claims,
    principal_from_event,
    principal_from_headers,
)
from inventory_common.config import settings

COGNITO_ISSUER = os.environ.get("COGNITO_ISSUER", "")
COGNITO_AUDIENCE = [a for a in os.environ.get("COGNITO_AUDIENCE", "").split(",") if a]


@lru_cache(maxsize=1)
def _jwks_client() -> Any:
    import jwt

    return jwt.PyJWKClient(f"{COGNITO_ISSUER}/.well-known/jwks.json", cache_keys=True)


def verify_jwt(token: str) -> dict[str, Any]:
    """Defense in depth when not behind the API Gateway JWT authorizer (e.g. uvicorn in cognito mode)."""
    import jwt

    key = _jwks_client().get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, key, algorithms=["RS256"], issuer=COGNITO_ISSUER,
                        options={"verify_aud": False})
    aud = claims.get("aud") or claims.get("client_id")
    if COGNITO_AUDIENCE and aud not in COGNITO_AUDIENCE:
        raise AuthError("audience mismatch")
    return claims


def get_principal(request: Request) -> Principal:
    try:
        event = request.scope.get("aws.event")
        if event is not None:
            return principal_from_event(event)
        if settings.auth_mode == "dev":
            return principal_from_headers(dict(request.headers))
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise AuthError("missing bearer token")
        return principal_from_claims(verify_jwt(auth.split(" ", 1)[1].strip()))
    except AuthError as exc:
        raise ApiError(401, "unauthorized", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - any JWT library error is a 401
        raise ApiError(401, "unauthorized", "invalid token") from exc


def require(*roles: str) -> Callable[..., Principal]:
    def dep(principal: Principal = Depends(get_principal)) -> Principal:  # noqa: B008
        if roles and not principal.has_any(*roles):
            raise ApiError(403, "forbidden", f"requires one of {list(roles)}")
        return principal

    return dep


any_user = require()
reviewer = require("reviewer")
admin = require("admin")
