"""
Auth dependencies for epcr.

Two authentication paths are supported, in priority order:

1) **Gateway-validated identity (preferred for public clients).** When the
   adaptix-gateway has validated a Cognito JWT, it strips any client-supplied
   identity headers, injects verified ``X-User-ID`` / ``X-Tenant-ID`` /
   ``X-User-Email`` / ``X-Adaptix-Roles``, and stamps the canary header
   ``X-Adaptix-Internal-Auth: cognito-gateway-validated``. The gateway's
   ``FORBIDDEN_PUBLIC_HEADERS`` strip step guarantees a client cannot spoof
   these headers — they are only present when the gateway has produced them
   after verifying the Cognito signature.

2) **Direct Adaptix JWT verification (legacy / internal callers).** RS256
   signature verification using the ``ADAPTIX_JWT_PUBLIC_KEY`` PEM
   provisioned via AWS Secrets Manager. Retained for service-to-service
   traffic, scheduled workers, and any caller that bypasses the gateway.

A request that arrives WITH the canary header but WITHOUT the identity
headers is rejected (401) — never silently fall back to the unsigned bearer,
because the canary's sole purpose is to signal "the gateway validated and
filled the X-* headers".

Tenant context is derived from cryptographically verified JWT claims (path
2) or from gateway-stamped headers (path 1) — never from raw client headers.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

_ALGORITHM = "RS256"

# Canary stamped by adaptix-gateway after Cognito JWT validation. Stripped from
# inbound public requests by the gateway, so it is only present when produced
# by the gateway itself.
_GATEWAY_AUTH_CANARY = "cognito-gateway-validated"

# Import shared auth context from contracts
try:
    from adaptix_contracts.auth.context import AdaptixAuthContext, AdaptixRole
    CONTRACTS_AVAILABLE = True
except ImportError:
    CONTRACTS_AVAILABLE = False
    AdaptixAuthContext = None
    AdaptixRole = None


def _parse_roles(raw_roles: str | None) -> list[str]:
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


def _auth_from_gateway_headers(
    gateway_user_id: str,
    gateway_tenant_id: str,
    gateway_email: str | None,
    gateway_roles: str | None,
):
    """Construct an AdaptixAuthContext (or payload dict fallback) from
    gateway-validated identity headers.

    Called only when ``X-Adaptix-Internal-Auth: cognito-gateway-validated``
    is present.

    Raises:
        HTTPException 401 if user_id or tenant_id is missing.
    """
    if not gateway_user_id or not gateway_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "gateway_identity_incomplete",
                "message": (
                    "Gateway canary present but X-User-ID or X-Tenant-ID is "
                    "missing. The gateway must inject both when stamping "
                    f"'{_GATEWAY_AUTH_CANARY}'."
                ),
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    roles = _parse_roles(gateway_roles)
    payload = {
        "sub": gateway_user_id,
        "user_id": gateway_user_id,
        "tenant_id": gateway_tenant_id,
        "email": gateway_email or "",
        "roles": roles,
        "is_founder": "founder" in [r.lower() for r in roles],
        "auth_source": "gateway",
    }

    if CONTRACTS_AVAILABLE:
        try:
            return AdaptixAuthContext.from_token_payload(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "epcr.auth: gateway-headers AdaptixAuthContext construction failed: %s",
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error_code": "gateway_identity_invalid",
                    "message": "Gateway identity headers did not produce a valid context",
                },
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
    return payload


async def get_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    gateway_auth: str | None = Header(default=None, alias="X-Adaptix-Internal-Auth"),
    gateway_user_id: str | None = Header(default=None, alias="X-User-ID"),
    gateway_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    gateway_email: str | None = Header(default=None, alias="X-User-Email"),
    gateway_roles: str | None = Header(default=None, alias="X-Adaptix-Roles"),
) -> AdaptixAuthContext:
    """
    Extract auth context. Prefers gateway-validated identity when the
    ``X-Adaptix-Internal-Auth: cognito-gateway-validated`` canary is present;
    otherwise verifies the Bearer JWT against ``ADAPTIX_JWT_PUBLIC_KEY``.

    See module docstring for the two-path design.

    Raises:
        HTTPException: 401 if neither path produces a valid identity.
        HTTPException: 503 if the legacy path is taken but
            ``ADAPTIX_JWT_PUBLIC_KEY`` is not configured.
    """
    # Path 1: gateway-validated identity.
    if gateway_auth == _GATEWAY_AUTH_CANARY:
        return _auth_from_gateway_headers(
            gateway_user_id or "",
            gateway_tenant_id or "",
            gateway_email,
            gateway_roles,
        )

    # Path 2: direct Adaptix JWT verification (legacy / internal callers).
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
