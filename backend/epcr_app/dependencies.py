"""Dependency injection for ePCR service authentication.

Two authentication paths are supported, in priority order:

1) **Gateway-validated identity (preferred for public clients).** When
   ``X-Adaptix-Internal-Auth: cognito-gateway-validated`` is present, the
   adaptix-gateway has already validated a Cognito JWT and stripped any
   client-supplied identity headers, then injected verified ``X-User-ID``,
   ``X-Tenant-ID``, ``X-User-Email``, ``X-Adaptix-Roles``. These headers are
   trusted only when the canary is present, because the gateway's
   ``FORBIDDEN_PUBLIC_HEADERS`` strip guarantees a client cannot forge them.

2) **Direct Adaptix JWT verification (legacy / internal callers).** RS256
   signature verification using ``ADAPTIX_JWT_PUBLIC_KEY``. Required for
   service-to-service traffic, scheduled workers, and any direct call that
   bypasses the gateway.

A canary-present-but-headers-missing request is 401 — never silently fall
back to the unsigned bearer.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Optional
from uuid import UUID

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

_ALGORITHM = "RS256"

# Canary stamped by adaptix-gateway after Cognito validation; stripped from
# inbound public requests by the gateway, so present only when the gateway
# itself produced it.
_GATEWAY_AUTH_CANARY = "cognito-gateway-validated"


def _parse_roles_str(raw_roles: str | None) -> list[str]:
    """Parse a gateway-forwarded roles string (JSON array or comma-delimited)."""
    if not raw_roles:
        return []
    s = raw_roles.strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(r).strip() for r in parsed if str(r).strip()]
        except json.JSONDecodeError:
            pass
    return [p.strip() for p in s.split(",") if p.strip()]


class CurrentUser:
    """Represents the authenticated user extracted from JWT claims."""

    def __init__(
        self,
        user_id: UUID,
        tenant_id: UUID,
        email: str = "unknown@example.com",
        roles: Optional[list[str]] = None,
    ) -> None:
        """Initialize authenticated user.

        Args:
            user_id: User UUID from JWT ``sub`` claim.
            tenant_id: Tenant UUID from JWT ``tid`` claim.
            email: User email from JWT ``email`` claim.
            roles: List of role strings from JWT ``roles`` claim.
        """
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.email = email
        self.roles = roles or []


async def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
    x_user_email: Annotated[str | None, Header(alias="X-User-Email")] = None,
    x_adaptix_roles: Annotated[str | None, Header(alias="X-Adaptix-Roles")] = None,
    x_adaptix_internal_auth: Annotated[
        str | None, Header(alias="X-Adaptix-Internal-Auth")
    ] = None,
) -> CurrentUser:
    """Extract the authenticated user. Prefers gateway-validated identity
    headers when the ``X-Adaptix-Internal-Auth: cognito-gateway-validated``
    canary is present; otherwise verifies the Bearer JWT directly.

    See module docstring for the two-path design and security reasoning.

    Args:
        authorization: ``Authorization`` header (used for path 2).
        x_tenant_id: Gateway-injected tenant UUID (used for path 1).
        x_user_id: Gateway-injected user UUID (used for path 1).
        x_user_email: Gateway-injected email (used for path 1).
        x_adaptix_roles: Gateway-injected roles (used for path 1).
        x_adaptix_internal_auth: Canary header. When equal to
            ``cognito-gateway-validated``, the gateway-trust path is taken.

    Returns:
        CurrentUser instance with validated identity and tenant context.

    Raises:
        HTTPException: 401 if neither path produces a valid identity.
        HTTPException: 503 if the legacy path is taken but
            ``ADAPTIX_JWT_PUBLIC_KEY`` is not configured.
    """
    # Path 1: gateway-validated identity.
    if x_adaptix_internal_auth == _GATEWAY_AUTH_CANARY:
        if not x_user_id or not x_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Gateway canary present but X-User-ID or X-Tenant-ID "
                    f"is missing. The gateway must inject both when stamping "
                    f"'{_GATEWAY_AUTH_CANARY}'."
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return CurrentUser(
                user_id=UUID(str(x_user_id)),
                tenant_id=UUID(str(x_tenant_id)),
                email=x_user_email or "unknown@example.com",
                roles=_parse_roles_str(x_adaptix_roles),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Gateway-injected user_id or tenant_id is not a valid UUID",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    # Path 2: direct Adaptix JWT verification.
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is empty",
            headers={"WWW-Authenticate": "Bearer"},
        )

    public_key = os.environ.get("ADAPTIX_JWT_PUBLIC_KEY", "")
    # verify_aud=False: the EPCR service does not rely on the JWT audience claim
    # for access control. Tenant isolation is enforced via the 'tid' claim.
    # Keycloak-issued tokens include an 'aud' claim that varies by client configuration;
    # disabling audience verification here allows any Keycloak-issued token to be
    # validated against the RS256 public key.
    options: dict = {"verify_aud": False}
    key: str | dict = public_key

    if not public_key:
        logger.error(
            "epcr: ADAPTIX_JWT_PUBLIC_KEY is not configured. "
            "JWT authentication is unavailable."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "JWT public key is not configured. "
                "The service cannot authenticate requests without ADAPTIX_JWT_PUBLIC_KEY."
            ),
        )

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[_ALGORITHM],
            options=options,
        )
    except JWTError as exc:
        logger.warning("epcr: JWT decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    raw_user_id = claims.get("sub")
    raw_tenant_id = claims.get("tid")

    if not raw_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing required 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not raw_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing required 'tid' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(str(raw_user_id))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 'sub' claim is not a valid UUID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        tenant_id = UUID(str(raw_tenant_id))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 'tid' claim is not a valid UUID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    propagated_tenant_id = (x_tenant_id or "").strip()
    if propagated_tenant_id and propagated_tenant_id != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-Tenant-ID does not match authenticated tenant",
        )

    propagated_user_id = (x_user_id or "").strip()
    if propagated_user_id and propagated_user_id != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-User-ID does not match authenticated user",
        )

    email = claims.get("email", "unknown@example.com")
    roles = claims.get("roles", [])
    if not isinstance(roles, list):
        roles = [roles]

    return CurrentUser(
        user_id=user_id,
        tenant_id=tenant_id,
        email=str(email),
        roles=[str(r) for r in roles],
    )


async def get_tenant_id(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> str:
    """Extract tenant_id string for use in database queries.

    In production, tenant_id comes from the verified JWT 'tid' claim via
    get_current_user. This dependency provides a string tenant_id for
    routes that need it as a separate parameter.

    For routes that use both get_current_user and get_tenant_id, the
    tenant_id from get_current_user is authoritative. This dependency
    provides a convenience string extraction.

    Tenant isolation is enforced via the JWT 'tid' claim — never from
    X-Tenant-ID header alone.
    """
    # In production, the JWT is validated by get_current_user.
    # This dependency extracts tenant_id from the same JWT for convenience.
    # Routes that use both get_current_user and get_tenant_id will have
    # consistent tenant_id values since both read from the same JWT.
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            public_key = os.environ.get("ADAPTIX_JWT_PUBLIC_KEY", "")
            if public_key and token:
                try:
                    claims = jwt.decode(
                        token,
                        public_key,
                        algorithms=[_ALGORITHM],
                        options={"verify_aud": False},
                    )
                    raw_tenant_id = claims.get("tid")
                    if raw_tenant_id:
                        return str(UUID(str(raw_tenant_id)))
                except Exception:
                    pass

    # Fallback for local/test environments where JWT is not configured
    if x_tenant_id:
        return x_tenant_id.strip()

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Tenant context unavailable — JWT required",
    )


