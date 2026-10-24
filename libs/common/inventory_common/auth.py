"""Principal extraction from API Gateway v2 events (docs/CONTRACTS.md §6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from inventory_common.config import settings

ROLES = ("operator", "reviewer", "admin")


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str | None = None
    groups: frozenset[str] = field(default_factory=frozenset)

    def has_any(self, *roles: str) -> bool:
        return "admin" in self.groups or any(r in self.groups for r in roles)


class AuthError(Exception):
    pass


def _parse_groups(raw: Any) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if isinstance(raw, list):
        return frozenset(str(g) for g in raw)
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    parts = s.replace(",", " ").split()
    return frozenset(p.strip().strip('"') for p in parts if p.strip())


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    sub = claims.get("sub")
    if not sub:
        raise AuthError("missing sub claim")
    return Principal(user_id=str(sub), email=claims.get("email"), groups=_parse_groups(claims.get("cognito:groups")))


def principal_from_headers(headers: dict[str, str]) -> Principal:
    h = {k.lower(): v for k, v in (headers or {}).items()}
    groups = h.get("x-dev-groups", "operator,reviewer,admin")
    return Principal(
        user_id=h.get("x-dev-user", "dev-user"),
        email=h.get("x-dev-email", "dev@example.com"),
        groups=frozenset(g.strip() for g in groups.split(",") if g.strip()),
    )


def principal_from_event(event: dict[str, Any]) -> Principal:
    if settings.auth_mode == "dev":
        return principal_from_headers(event.get("headers") or {})
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims")
    if not claims:
        raise AuthError("no JWT claims on request")
    return principal_from_claims(claims)
