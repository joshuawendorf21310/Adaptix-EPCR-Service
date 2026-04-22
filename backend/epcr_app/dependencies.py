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
) -> CurrentUser:
    """Extract and validate the authenticated user from the Authorization header.

    Decodes the Bearer JWT using RS256 and extracts ``sub`` (user_id) and
    ``tid`` (tenant_id) claims. ``ADAPTIX_JWT_PUBLIC_KEY`` must be set in
    the environment; the service raises HTTP 503 if it is absent.

    Args:
        authorization: Value of the HTTP ``Authorization`` header.

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
    options: dict = {}
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


