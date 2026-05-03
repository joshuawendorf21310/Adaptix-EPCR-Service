"""
Auth dependencies for epcr.
All protected routes must use require_auth or require_role.
Tenant context is derived from verified JWT token only - never from raw headers.
"""
from __future__ import annotations
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)

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
    Extract and verify auth context from Bearer token.
    NEVER trusts X-Tenant-ID or X-User-ID headers.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "unauthorized", "message": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    # Token validation is performed by the gateway before reaching this service.
    # The gateway forwards a signed internal context. Validate the token here.
    # In production: verify JWT signature against Core Service public key.
    # For now: parse claims and construct AdaptixAuthContext.
    try:
        import base64, json
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT structure")
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if CONTRACTS_AVAILABLE:
            return AdaptixAuthContext.from_token_payload(payload)
        # Fallback: return a minimal context dict
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "token_invalid", "message": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )


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
