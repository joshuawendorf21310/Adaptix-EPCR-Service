"""Regression: ``epcr_app.auth.dependencies.get_auth_context`` MUST verify
the JWT signature.

Historic defect: ``get_auth_context`` decoded the JWT payload with
``base64.urlsafe_b64decode`` without verifying the signature, the
algorithm, the issuer, or the expiry. Any well-formed but unsigned token
was accepted.

This module pins the corrected behavior so the defect cannot regress.

Auth contract under test (legacy Bearer JWT path)
-------------------------------------------------
The legacy path runs when ``ADAPTIX_ALLOW_LEGACY_JWT_AUTH=true`` AND no
gateway-v1 signed-context headers are present. These tests force-enable
that flag via the ``configured_public_key`` fixture so the JWT branch is
exercised. Production runs with the flag OFF and uses the gateway-v1
signed-context path instead (covered by ``test_gateway_auth_context``).

Expected outcomes:

* No bearer token                       -> 401 ``unauthorized``
* Empty bearer token                    -> 401 ``unauthorized``
* Forged unsigned JWT (alg=none)        -> 401 ``token_invalid``
* JWT signed with wrong RSA key         -> 401 ``token_invalid``
* JWT signed with correct RSA key       -> success (auth context returned)
* ADAPTIX_JWT_PUBLIC_KEY not configured -> 503 ``auth_unavailable``

When calling the dependency directly (outside FastAPI's DI), every
``Header(default=None, ...)`` parameter must be passed as ``None``
explicitly — otherwise the parameter retains its ``Header`` sentinel
value and the dependency takes the "unknown auth path" branch.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from epcr_app.auth.dependencies import get_auth_context

_ALGORITHM = "RS256"


def _make_rsa_keypair() -> tuple[str, str]:
    """Generate a fresh 2048-bit RSA keypair and return (private_pem, public_pem)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return private_pem, public_pem


_PRIVATE_PEM, _PUBLIC_PEM = _make_rsa_keypair()
_OTHER_PRIVATE_PEM, _ = _make_rsa_keypair()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _forge_unsigned_jwt(payload: dict) -> str:
    """Build a structurally valid JWT with a fabricated signature."""
    header = {"alg": "none", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    s = _b64url(b"forged-signature")
    return f"{h}.{p}.{s}"


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed loop")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _call(credentials):
    """Invoke get_auth_context with all header kwargs explicit so FastAPI's
    Header(default=None, ...) sentinels don't leak through when called outside
    a FastAPI request lifecycle.
    """
    return _run(
        get_auth_context(
            credentials=credentials,
            x_adaptix_auth_path=None,
            x_adaptix_context=None,
            x_adaptix_signature=None,
        )
    )


@pytest.fixture
def configured_public_key(monkeypatch):
    """Configure the legacy JWT path: public key + flag both set."""
    monkeypatch.setenv("ADAPTIX_JWT_PUBLIC_KEY", _PUBLIC_PEM)
    monkeypatch.setenv("ADAPTIX_ALLOW_LEGACY_JWT_AUTH", "true")
    yield


def test_missing_credentials_returns_401(configured_public_key):
    with pytest.raises(HTTPException) as exc:
        _call(credentials=None)
    assert exc.value.status_code == 401


def test_empty_bearer_token_returns_401(configured_public_key):
    with pytest.raises(HTTPException) as exc:
        _call(credentials=_bearer("   "))
    assert exc.value.status_code == 401


def test_forged_unsigned_jwt_returns_401(configured_public_key):
    """REGRESSION: previously the dependency accepted unsigned JWTs."""
    forged = _forge_unsigned_jwt(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "tid": "00000000-0000-0000-0000-000000000099",
            "tenant_id": "00000000-0000-0000-0000-000000000099",
            "email": "attacker@example.invalid",
            "roles": ["founder"],
            "exp": int(time.time()) + 3600,
        }
    )
    with pytest.raises(HTTPException) as exc:
        _call(credentials=_bearer(forged))
    assert exc.value.status_code == 401
    assert exc.value.detail.get("error_code") == "token_invalid"


def test_token_signed_with_wrong_key_returns_401(configured_public_key):
    """A token signed by a different RSA key must fail verification."""
    bad_token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000099",
            "exp": int(time.time()) + 3600,
        },
        _OTHER_PRIVATE_PEM,
        algorithm=_ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        _call(credentials=_bearer(bad_token))
    assert exc.value.status_code == 401


def test_public_key_not_configured_returns_503(monkeypatch):
    monkeypatch.setenv("ADAPTIX_ALLOW_LEGACY_JWT_AUTH", "true")
    monkeypatch.delenv("ADAPTIX_JWT_PUBLIC_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        _call(credentials=_bearer("anything.at.all"))
    assert exc.value.status_code == 503


def test_valid_signed_token_is_accepted(configured_public_key):
    payload = {
        "sub": "00000000-0000-0000-0000-000000000001",
        "tid": "00000000-0000-0000-0000-000000000099",
        "tenant_id": "00000000-0000-0000-0000-000000000099",
        "session_id": "00000000-0000-0000-0000-0000000000aa",
        "email": "real.user@example.com",
        "roles": ["founder"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, _PRIVATE_PEM, algorithm=_ALGORITHM)
    result = _call(credentials=_bearer(token))
    tenant = (
        getattr(result, "tenant_id", None)
        or (result.get("tenant_id") if isinstance(result, dict) else None)
    )
    assert str(tenant) == "00000000-0000-0000-0000-000000000099"
