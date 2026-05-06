"""
Auth dependencies for epcr.
All protected routes must use require_auth or require_role.
Tenant context is derived from cryptographically verified JWT claims only -
never from raw headers and never from unverified base64 payload parsing.

The verification path mirrors ``epcr_app.dependencies.get_current_user``:
RS256 signature verification using the ``ADAPTIX_JWT_PUBLIC_KEY`` PEM
provisioned in production via AWS Secrets Manager. A future migration to
Keycloak JWKS-based verification (kid-pinned, JWKS-cached) is tracked
separately and will replace the static PEM source without changing this
dependency's contract.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

_ALGORITHM = "RS256"

# Import shared auth context from contracts
try:
    from adaptix_contracts.auth.context import AdaptixAuthContext, AdaptixRole
    CONTRACTS_AVAILABLE = True
except ImportError:
    CONTRACTS_AVAILABLE = False
    AdaptixAuthContext = None
    AdaptixRole = None


async def get_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AdaptixAuthContext:
    """
    Extract and cryptographically verify auth context from Bearer token.

    Verifies the JWT signature with RS256 against the configured Adaptix
    public key. NEVER trusts X-Tenant-ID, X-User-ID, or X-User-Roles
    headers. NEVER parses claims without verifying the signature.

    Raises:
        HTTPException: 401 if the header is missing/malformed, the token
            signature is invalid, the token is expired, or required claims
            are absent.
        HTTPException: 503 if ``ADAPTIX_JWT_PUBLIC_KEY`` is not configured.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "unauthorized", "message": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "unauthorized", "message": "Bearer token is empty"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    public_key = os.environ.get("ADAPTIX_JWT_PUBLIC_KEY", "")
    if not public_key:
        logger.error(
            "epcr.auth: ADAPTIX_JWT_PUBLIC_KEY is not configured. "
            "JWT authentication is unavailable."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "auth_unavailable",
                "message": (
                    "JWT public key is not configured. "
                    "The service cannot authenticate requests without ADAPTIX_JWT_PUBLIC_KEY."
                ),
            },
        )

    try:
        # verify_aud=False: tenant isolation is enforced via the verified
        # 'tid'/'tenant_id' claim, not the JWT audience claim. Audience
        # verification is intentionally disabled to accept tokens issued
        # by any Adaptix-trusted client of the configured signing key.
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[_ALGORITHM],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        logger.warning("epcr.auth: JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "token_invalid", "message": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if CONTRACTS_AVAILABLE:
        try:
            return AdaptixAuthContext.from_token_payload(payload)
        except Exception as exc:  # noqa: BLE001 - contract conversion failure must surface as 401
            logger.warning("epcr.auth: AdaptixAuthContext construction failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "token_invalid", "message": "Token claims are not valid"},
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
    return payload


async def require_auth(
    auth: AdaptixAuthContext = Depends(get_auth_context),
) -> AdaptixAuthContext:
    """Require authenticated user. Returns verified auth context."""
    return auth


async def require_tenant(
    auth: AdaptixAuthContext = Depends(require_auth),
) -> AdaptixAuthContext:
    """Require authenticated user with valid tenant context."""
    tenant_id = getattr(auth, "tenant_id", None) or (auth.get("tenant_id") if isinstance(auth, dict) else None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "tenant_inactive", "message": "Valid tenant context required"},
        )
    return auth


async def require_founder(
    auth: AdaptixAuthContext = Depends(require_auth),
) -> AdaptixAuthContext:
    """Require founder role."""
    is_founder = getattr(auth, "is_founder", False) or (
        "founder" in (auth.get("roles", []) if isinstance(auth, dict) else [])
    )
    if not is_founder:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "insufficient_role", "message": "Founder role required"},
        )
    return auth
