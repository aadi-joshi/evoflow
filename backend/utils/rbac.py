"""
RBAC — Role-Based Access Control simulation for EvoFlow AI.

In a production system this would validate JWT tokens against an IdP.
Here we simulate it via a static role registry and an API-key-based
header (`X-EvoFlow-Role`) that the demo UI sends.

Roles:
  admin      — full access (run, read, reset, benchmark)
  operator   — run workflows + read history + read audit
  viewer     — read history + read audit only
  readonly   — read history only (no audit details)

The FastAPI dependency `require_role(...)` raises 403 if the caller's
role does not satisfy the minimum required role.
"""
from __future__ import annotations

from enum import IntEnum
from typing import Optional

from fastapi import Header, HTTPException


class Role(IntEnum):
    readonly = 0
    viewer   = 1
    operator = 2
    admin    = 3


# Static demo registry: header value → Role
_ROLE_MAP: dict[str, Role] = {
    "admin-key":    Role.admin,
    "operator-key": Role.operator,
    "viewer-key":   Role.viewer,
    # Default (no header) → operator for demo convenience
}

_DEFAULT_ROLE = Role.operator


def resolve_role(x_evoflow_role: Optional[str] = Header(default=None)) -> Role:
    """FastAPI dependency: resolve caller role from header."""
    if x_evoflow_role is None:
        return _DEFAULT_ROLE
    return _ROLE_MAP.get(x_evoflow_role, Role.readonly)


def require_role(minimum: Role):
    """
    FastAPI dependency factory.

    Usage:
        @app.get("/api/reset")
        def reset(role: Role = Depends(require_role(Role.admin))):
            ...
    """
    def _check(role: Optional[str] = Header(default=None, alias="x-evoflow-role")):  # noqa: B008
        actual = _ROLE_MAP.get(role or "", _DEFAULT_ROLE)
        if actual < minimum:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient privileges. Required: {minimum.name}, got: {actual.name}",
            )
        return actual
    return _check
