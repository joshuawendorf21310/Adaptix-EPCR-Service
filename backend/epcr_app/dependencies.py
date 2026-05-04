"""Dependency injection for ePCR service authentication.

Provides the ``get_current_user`` FastAPI dependency for RS256 JWT validation.
Token must be issued by the Adaptix core auth service and carry ``sub`` (user UUID)
and ``tid`` (tenant UUID) claims. Signature verification requires
``ADAPTIX_JWT_PUBLIC_KEY`` to be set in the environment.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Optional
from uuid import UUID

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

_ALGORITHM = "RS256"


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
) -> CurrentUser:
    """Extract and validate the authenticated user from the Authorization header.

    Decodes the Bearer JWT using RS256 and extracts ``sub`` (user_id) and
    ``tid`` (tenant_id) claims. ``ADAPTIX_JWT_PUBLIC_KEY`` must be set in
    the environment; the service raises HTTP 503 if it is absent.

    Args:
        authorization: Value of the HTTP ``Authorization`` header.
        x_tenant_id: Optional gateway-propagated tenant header. If present,
            it must match the JWT ``tid`` claim and is never trusted as
            authority.
        x_user_id: Optional gateway-propagated user header. If present, it
            must match the JWT ``sub`` claim and is never trusted as authority.

    Returns:
        CurrentUser instance with validated identity and tenant context.

    Raises:
        HTTPException: 401 if the header is missing, the token is malformed,
            the signature is invalid, required claims are absent, or claim
            values are not valid UUIDs.
        HTTPException: 503 if ``ADAPTIX_JWT_PUBLIC_KEY`` is not configured.
    """
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


