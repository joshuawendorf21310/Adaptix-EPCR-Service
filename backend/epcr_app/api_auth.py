"""Local authentication API for the CTA testing portal."""

from __future__ import annotations

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, Field

from epcr_app.local_auth import (
    PortalAuthClaims,
    build_claims_response,
    extract_token_from_header,
    get_portal_user_config,
    issue_login_tokens,
    refresh_login_tokens,
    revoke_token,
    validate_portal_login,
)


router = APIRouter(prefix="/api/v1/auth", tags=["local-auth"])


class LoginRequest(BaseModel):
    """Local CTA portal login request payload."""

    email: str = Field(min_length=3)
    password: str = Field(min_length=1)
    tenant_slug: str = Field(min_length=1)


class LoginResponse(BaseModel):
    """Token pair returned by the local auth flow."""

    token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    """Refresh token request payload."""

    refresh_token: str = Field(min_length=1)


@router.post("/login", response_model=LoginResponse, summary="Sign in to the local CTA testing portal")
async def login(payload: LoginRequest) -> LoginResponse:
    """Validate local operator credentials and issue a JWT pair.

    Args:
        payload: Submitted local login credentials.

    Returns:
        LoginResponse: Access and refresh tokens for the local portal.
    """

    validate_portal_login(payload.email, payload.password, payload.tenant_slug)
    return LoginResponse(**issue_login_tokens())


@router.get("/validate", response_model=PortalAuthClaims, summary="Validate a local CTA portal access token")
async def validate(authorization: str | None = Header(default=None, alias="Authorization")) -> PortalAuthClaims:
    """Validate a local access token and return claims expected by the Web App.

    Args:
        authorization: Authorization header with bearer token.

    Returns:
        PortalAuthClaims: Validated local auth claims.
    """

    token = extract_token_from_header(authorization)
    return build_claims_response(token)


@router.post("/refresh", response_model=LoginResponse, summary="Refresh local CTA portal auth tokens")
async def refresh(payload: RefreshRequest) -> LoginResponse:
    """Exchange a valid refresh token for a fresh token pair.

    Args:
        payload: Refresh token payload.

    Returns:
        LoginResponse: Refreshed access and refresh tokens.
    """

    return LoginResponse(**refresh_login_tokens(payload.refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of the local CTA testing portal")
async def logout(authorization: str | None = Header(default=None, alias="Authorization")) -> Response:
    """Revoke the presented access token for the local CTA portal.

    Args:
        authorization: Authorization header with bearer token.

    Returns:
        Response: Empty success response.
    """

    token = extract_token_from_header(authorization)
    revoke_token(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/local-config", summary="Inspect the local CTA portal login identity")
async def local_config() -> dict[str, str]:
    """Return non-secret local login configuration helpful for local debugging.

    Returns:
        dict[str, str]: Public login identity details.
    """

    config = get_portal_user_config()
    return {
        "email": config.email,
        "tenant_slug": config.tenant_slug,
    }