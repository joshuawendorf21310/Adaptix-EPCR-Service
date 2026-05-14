"""
Auth dependencies for epcr — same explicit X-Adaptix-Auth-Path contract as
epcr_app.dependencies. The gateway owns the auth decision; this service
consumes the result. There is NO silent fallback between paths.

Path "canary":
    Gateway has validated a Cognito JWT. Identity flows via the
    X-Adaptix-{User,Tenant,Email,Roles}-Id headers; trust is asserted by
    X-Adaptix-Auth-Path=canary AND X-Adaptix-Canary=cognito-gateway-validated.
    Canary path declared but headers missing → 502 (contract breach).

Path "legacy":
    Direct call with an Adaptix Bearer JWT. Allowed only when
    ``ADAPTIX_ALLOW_LEGACY_JWT_AUTH=true``. Disabled by default.

Anything else → 401.
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

# X-Adaptix-* contract — owned by adaptix-gateway.
_HDR_AUTH_PATH = "X-Adaptix-Auth-Path"
_HDR_CANARY    = "X-Adaptix-Canary"
_HDR_USER_ID   = "X-Adaptix-User-Id"
_HDR_TENANT_ID = "X-Adaptix-Tenant-Id"
_HDR_EMAIL     = "X-Adaptix-Email"
_HDR_ROLES     = "X-Adaptix-Roles"

AUTH_PATH_CANARY = "canary"
AUTH_PATH_LEGACY = "legacy"
GATEWAY_CANARY_VALUE = "cognito-gateway-validated"


def _legacy_auth_enabled() -> bool:
    """Return True iff ``ADAPTIX_ALLOW_LEGACY_JWT_AUTH=true`` in the env."""
    return os.environ.get("ADAPTIX_ALLOW_LEGACY_JWT_AUTH", "").strip().lower() == "true"

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
    """Construct an AdaptixAuthContext from the gateway-stamped canary
    identity headers. The caller has already verified ``X-Adaptix-Auth-
    Path == "canary"`` and ``X-Adaptix-Canary == GATEWAY_CANARY_VALUE``.

    Raises:
        HTTPException 502 on contract breach (missing/bad identity).
    """
    if not gateway_user_id or not gateway_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_code": "gateway_contract_breach",
                "message": (
                    "Canary path requires X-Adaptix-User-Id and "
                    "X-Adaptix-Tenant-Id — the gateway must inject both."
                ),
            },
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
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error_code": "gateway_contract_breach",
                    "message": "Gateway identity headers did not produce a valid context",
                },
            ) from exc
    return payload


async def get_auth_context(
    credentials:          Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_adaptix_auth_path:  str | None = Header(default=None, alias=_HDR_AUTH_PATH),
    x_adaptix_canary:     str | None = Header(default=None, alias=_HDR_CANARY),
    x_adaptix_user_id:    str | None = Header(default=None, alias=_HDR_USER_ID),
    x_adaptix_tenant_id:  str | None = Header(default=None, alias=_HDR_TENANT_ID),
    x_adaptix_email:      str | None = Header(default=None, alias=_HDR_EMAIL),
    x_adaptix_roles:      str | None = Header(default=None, alias=_HDR_ROLES),
) -> AdaptixAuthContext:
    """Extract auth context by branching on X-Adaptix-Auth-Path. See module
    docstring for the contract.

    Raises:
        HTTPException 401 if neither path is satisfied.
        HTTPException 502 if canary path declared but identity headers are
            missing or malformed (gateway contract breach).
        HTTPException 503 if legacy path is taken but
            ``ADAPTIX_JWT_PUBLIC_KEY`` is not configured.
    """
    # ── Path: canary (gateway-validated identity) ────────────────────────
    if x_adaptix_auth_path == AUTH_PATH_CANARY:
        if x_adaptix_canary != GATEWAY_CANARY_VALUE:
            logger.error(
                "epcr.auth: contract breach — X-Adaptix-Auth-Path=canary "
                "but X-Adaptix-Canary missing or wrong"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error_code": "gateway_contract_breach",
                    "message": (
                        "Auth-path declared canary but canary header is missing "
                        "or does not match the gateway value."
                    ),
                },
            )
        return _auth_from_gateway_headers(
            x_adaptix_user_id or "",
            x_adaptix_tenant_id or "",
            x_adaptix_email,
            x_adaptix_roles,
        )

    # ── Path: legacy (direct Adaptix JWT) — opt-in only ──────────────────
    if x_adaptix_auth_path not in (None, "", AUTH_PATH_LEGACY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "unknown_auth_path",
                "message": f"Unknown X-Adaptix-Auth-Path: {x_adaptix_auth_path!r}",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not _legacy_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "auth_required",
                "message": (
                    "Authentication required. This endpoint accepts requests "
                    "stamped by the adaptix-gateway (X-Adaptix-Auth-Path=canary) "
                    "or — when ADAPTIX_ALLOW_LEGACY_JWT_AUTH=true — a direct "
                    "Adaptix Bearer JWT."
                ),
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

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
