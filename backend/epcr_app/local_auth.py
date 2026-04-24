"""Local authentication helpers for the CTA testing portal.

This auth flow is intentionally scoped to local development and the CTA portal.
It issues signed JWT access and refresh tokens that match the Web App auth
provider contract without depending on the platform core auth service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import os
from pathlib import Path
import secrets
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt


_ACCESS_TOKEN_MINUTES = 60
_REFRESH_TOKEN_DAYS = 7
_ALGORITHM = "HS256"
_REVOKED_JTIS: set[str] = set()
_REVOKED_LOCK = Lock()


@dataclass(frozen=True)
class PortalUserConfig:
    """Configured local portal operator identity."""

    email: str
    password: str
    tenant_slug: str
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]


@dataclass(frozen=True)
class PortalAuthClaims:
    """Validated portal auth claims used by secured CTA routes."""

    user_id: str
    tenant_id: str
    email: str
    roles: list[str]
    exp: int


def _backend_root() -> Path:
    """Return the backend root path."""

    return Path(__file__).resolve().parents[1]


def _secret_path() -> Path:
    """Return the local auth secret file path."""

    configured = os.environ.get("EPCR_PORTAL_AUTH_SECRET_PATH", "").strip()
    if configured:
        return Path(configured)
    return _backend_root() / ".local" / "cta_portal" / "auth-secret.txt"


def _get_signing_secret() -> str:
    """Return the signing secret, creating a local one when needed."""

    configured = os.environ.get("EPCR_PORTAL_JWT_SECRET", "").strip()
    if configured:
        return configured

    secret_path = _secret_path()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()

    secret_value = secrets.token_urlsafe(64)
    secret_path.write_text(secret_value, encoding="utf-8")
    return secret_value


def get_portal_user_config() -> PortalUserConfig:
    """Resolve the configured local portal operator identity.

    Returns:
        PortalUserConfig: Local login identity and tenant context.
    """

    return PortalUserConfig(
        email=os.environ.get("EPCR_PORTAL_LOGIN_EMAIL", "local.operator@adaptix.dev").strip().lower(),
        password=os.environ.get("EPCR_PORTAL_LOGIN_PASSWORD", "AdaptixLocalPortal!2026").strip(),
        tenant_slug=os.environ.get("EPCR_PORTAL_TENANT_SLUG", "local-cta-lab").strip().lower(),
        tenant_id=os.environ.get("EPCR_PORTAL_TENANT_ID", "11111111-1111-4111-8111-111111111111").strip(),
        user_id=os.environ.get("EPCR_PORTAL_USER_ID", "22222222-2222-4222-8222-222222222222").strip(),
        roles=tuple(
            role.strip()
            for role in os.environ.get("EPCR_PORTAL_LOGIN_ROLES", "epcr,nemsis-testing").split(",")
            if role.strip()
        ),
    )


def _utc_now() -> datetime:
    """Return the current UTC datetime."""

    return datetime.now(UTC)


def _issue_token(*, subject: str, tenant_id: str, email: str, roles: tuple[str, ...], token_type: str, lifetime: timedelta) -> str:
    """Issue a signed JWT for the local portal.

    Args:
        subject: User identifier.
        tenant_id: Tenant identifier.
        email: User email.
        roles: Portal roles.
        token_type: ``access`` or ``refresh``.
        lifetime: Token lifetime.

    Returns:
        str: Signed JWT.
    """

    issued_at = _utc_now()
    payload = {
        "sub": subject,
        "tid": tenant_id,
        "email": email,
        "roles": list(roles),
        "type": token_type,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + lifetime).timestamp()),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, _get_signing_secret(), algorithm=_ALGORITHM)


def issue_login_tokens() -> dict[str, str]:
    """Issue a fresh access/refresh token pair for the local operator.

    Returns:
        dict[str, str]: Token payload matching the Web App login contract.
    """

    config = get_portal_user_config()
    access_token = _issue_token(
        subject=config.user_id,
        tenant_id=config.tenant_id,
        email=config.email,
        roles=config.roles,
        token_type="access",
        lifetime=timedelta(minutes=_ACCESS_TOKEN_MINUTES),
    )
    refresh_token = _issue_token(
        subject=config.user_id,
        tenant_id=config.tenant_id,
        email=config.email,
        roles=config.roles,
        token_type="refresh",
        lifetime=timedelta(days=_REFRESH_TOKEN_DAYS),
    )
    return {"token": access_token, "refresh_token": refresh_token}


def _decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    """Decode and validate a local portal token.

    Args:
        token: JWT string.
        expected_type: Expected token type.

    Returns:
        dict[str, Any]: Decoded claims.

    Raises:
        HTTPException: If the token is invalid, expired, or revoked.
    """

    try:
        claims = jwt.decode(token, _get_signing_secret(), algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    token_type = str(claims.get("type", "")).strip().lower()
    if token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Expected a {expected_type} token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = str(claims.get("jti", "")).strip()
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a token identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with _REVOKED_LOCK:
        if jti in _REVOKED_JTIS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return claims


def _extract_bearer_token(authorization: str | None) -> str:
    """Extract the bearer token from an Authorization header."""

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    prefix, _, token = authorization.partition(" ")
    if prefix.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def revoke_token(token: str) -> None:
    """Revoke a token by its JWT ID.

    Args:
        token: Token string to revoke.

    Returns:
        None.
    """

    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        return

    jti = str(claims.get("jti", "")).strip()
    if not jti:
        return

    with _REVOKED_LOCK:
        _REVOKED_JTIS.add(jti)


def validate_portal_login(email: str, password: str, tenant_slug: str) -> None:
    """Validate local login credentials.

    Args:
        email: Submitted email address.
        password: Submitted password.
        tenant_slug: Submitted tenant slug.

    Returns:
        None.

    Raises:
        HTTPException: If the login is invalid.
    """

    config = get_portal_user_config()
    submitted_email = email.strip().lower()
    submitted_tenant = tenant_slug.strip().lower()

    email_match = hmac.compare_digest(submitted_email, config.email)
    password_match = hmac.compare_digest(password, config.password)
    tenant_match = hmac.compare_digest(submitted_tenant, config.tenant_slug)
    if email_match and password_match and tenant_match:
        return

    failure_digest = hashlib.sha256(f"{submitted_email}|{submitted_tenant}".encode("utf-8")).hexdigest()[:12]
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Sign-in failed for the local CTA portal account ({failure_digest}).",
    )


def build_claims_response(token: str) -> PortalAuthClaims:
    """Validate an access token and return Web App auth claims.

    Args:
        token: Access token.

    Returns:
        PortalAuthClaims: Validated claims payload.
    """

    claims = _decode_token(token, expected_type="access")
    user_id = str(claims.get("sub", "")).strip()
    tenant_id = str(claims.get("tid", "")).strip()

    try:
        UUID(user_id)
        UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token identity claims are malformed.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    roles = claims.get("roles", [])
    if not isinstance(roles, list):
        roles = [roles]

    return PortalAuthClaims(
        user_id=user_id,
        tenant_id=tenant_id,
        email=str(claims.get("email", "local.operator@adaptix.dev")),
        roles=[str(role) for role in roles],
        exp=int(claims.get("exp", 0)),
    )


def refresh_login_tokens(refresh_token: str) -> dict[str, str]:
    """Refresh a local access/refresh token pair.

    Args:
        refresh_token: Submitted refresh token.

    Returns:
        dict[str, str]: Fresh access and refresh tokens.
    """

    _decode_token(refresh_token, expected_type="refresh")
    revoke_token(refresh_token)
    return issue_login_tokens()


async def get_portal_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> PortalAuthClaims:
    """FastAPI dependency that validates local portal access tokens.

    Args:
        authorization: Authorization header value.

    Returns:
        PortalAuthClaims: Authenticated local user claims.
    """

    token = _extract_bearer_token(authorization)
    return build_claims_response(token)


def extract_token_from_header(authorization: str | None) -> str:
    """Public helper for auth routes to parse bearer tokens."""

    return _extract_bearer_token(authorization)