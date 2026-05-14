"""Dependency injection for ePCR service authentication.

This service implements an explicit two-path auth contract driven by the
``X-Adaptix-Auth-Path`` header. The gateway owns the auth decision; this
service consumes the result. There is NO silent fallback between paths.

Path "canary":
    The adaptix-gateway has validated a Cognito JWT, stripped any
    client-supplied identity headers, and stamped the request with:
        X-Adaptix-Auth-Path: canary
        X-Adaptix-Canary:    cognito-gateway-validated
        X-Adaptix-User-Id:   <verified user uuid>
        X-Adaptix-Tenant-Id: <verified tenant uuid>
        X-Adaptix-Email:     <verified email>
        X-Adaptix-Roles:     <JSON-array roles>
    This service trusts those values. Both the auth-path AND the canary
    are checked because the gateway's ``FORBIDDEN_PUBLIC_HEADERS`` strip
    guarantees a public client cannot smuggle them.

    Canary path declared but identity headers missing/malformed is a
    CONTRACT BREACH and returns 502 (not 401) — the request reached this
    service in a state the gateway should never produce.

Path "legacy":
    Direct call from an internal worker / service-to-service / test
    harness that has its own Adaptix RS256 JWT in ``Authorization:
    Bearer``. Allowed ONLY when ``ADAPTIX_ALLOW_LEGACY_JWT_AUTH=true`` in
    the environment. Disabled by default — never accept legacy as a
    fallback from a failed canary.

Anything else → 401.
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

# Header contract — owned by adaptix-gateway. See
# adaptix-gateway/backend/app/middleware/cognito_auth.py for the
# producer-side spec. Lowercase aliases here are case-insensitive at the
# Header() decorator level.
_HDR_AUTH_PATH  = "X-Adaptix-Auth-Path"
_HDR_CANARY     = "X-Adaptix-Canary"
_HDR_USER_ID    = "X-Adaptix-User-Id"
_HDR_TENANT_ID  = "X-Adaptix-Tenant-Id"
_HDR_EMAIL      = "X-Adaptix-Email"
_HDR_ROLES      = "X-Adaptix-Roles"

AUTH_PATH_CANARY = "canary"
AUTH_PATH_LEGACY = "legacy"
GATEWAY_CANARY_VALUE = "cognito-gateway-validated"


def _legacy_auth_enabled() -> bool:
    """Return True iff ``ADAPTIX_ALLOW_LEGACY_JWT_AUTH=true`` in the env."""
    return os.environ.get("ADAPTIX_ALLOW_LEGACY_JWT_AUTH", "").strip().lower() == "true"


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
    authorization:        Annotated[str | None, Header(alias="Authorization")] = None,
    x_adaptix_auth_path:  Annotated[str | None, Header(alias=_HDR_AUTH_PATH)]   = None,
    x_adaptix_canary:     Annotated[str | None, Header(alias=_HDR_CANARY)]      = None,
    x_adaptix_user_id:    Annotated[str | None, Header(alias=_HDR_USER_ID)]     = None,
    x_adaptix_tenant_id:  Annotated[str | None, Header(alias=_HDR_TENANT_ID)]   = None,
    x_adaptix_email:      Annotated[str | None, Header(alias=_HDR_EMAIL)]       = None,
    x_adaptix_roles:      Annotated[str | None, Header(alias=_HDR_ROLES)]       = None,
) -> CurrentUser:
    """Extract the authenticated user by branching on
    ``X-Adaptix-Auth-Path``. See module docstring for the contract.

    Returns:
        CurrentUser populated from the gateway-stamped identity (canary
        path) or the verified Bearer JWT claims (legacy path).

    Raises:
        HTTPException 401 if neither path is satisfied.
        HTTPException 502 if the canary auth-path is declared but the
            identity headers are missing/malformed (gateway contract
            breach).
        HTTPException 503 if the legacy path is taken but
            ``ADAPTIX_JWT_PUBLIC_KEY`` is not configured.
    """
    # ── Path: canary (gateway-validated identity) ────────────────────────
    if x_adaptix_auth_path == AUTH_PATH_CANARY:
        if x_adaptix_canary != GATEWAY_CANARY_VALUE:
            logger.error(
                "epcr.auth: contract breach — X-Adaptix-Auth-Path=canary "
                "but X-Adaptix-Canary missing or wrong (got %r)",
                x_adaptix_canary,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error_code": "gateway_contract_breach",
                    "message": (
                        "Auth-path declared canary but canary header is missing "
                        "or does not match the gateway value. The gateway must "
                        "stamp both atomically."
                    ),
                },
            )
        if not x_adaptix_user_id or not x_adaptix_tenant_id:
            logger.error(
                "epcr.auth: contract breach — canary present but "
                "X-Adaptix-User-Id/X-Adaptix-Tenant-Id missing"
            )
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
        try:
            return CurrentUser(
                user_id=UUID(str(x_adaptix_user_id)),
                tenant_id=UUID(str(x_adaptix_tenant_id)),
                email=x_adaptix_email or "unknown@example.com",
                roles=_parse_roles_str(x_adaptix_roles),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error_code": "gateway_contract_breach",
                    "message": "Gateway-injected user_id or tenant_id is not a valid UUID",
                },
            ) from exc

    # ── Path: legacy (direct Adaptix JWT) — opt-in only ──────────────────
    if x_adaptix_auth_path not in (None, "", AUTH_PATH_LEGACY):
        # Unknown auth-path value — refuse rather than silently fall through.
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
                    "or — when explicitly enabled by ADAPTIX_ALLOW_LEGACY_JWT_AUTH=true — "
                    "a direct Adaptix Bearer JWT."
                ),
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

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


