"""Signed internal auth context verifier — gateway → EPCR contract.

This is a byte-compatible verifier copy of
``adaptix-gateway/backend/app/services/auth_context.py``. The gateway
signs; this module verifies. Both sides MUST stay in lockstep — when the
gateway bumps ``AUTH_PATH_GATEWAY_V1`` to ``gateway-v2`` (new schema),
this module gets updated too.

The verifier is intentionally dependency-free (only stdlib) so it can be
copied byte-for-byte from the gateway source whenever the contract is
updated. Do not refactor this file to depend on epcr_app internals.

See the gateway-side module for the full contract docstring.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

# Header names — single source of truth, used by both signer and verifier.
HEADER_AUTH_CONTEXT = "x-adaptix-auth-context"
HEADER_AUTH_SIGNATURE = "x-adaptix-auth-signature"
HEADER_AUTH_PATH = "x-adaptix-auth-path"
HEADER_REQUEST_ID = "x-request-id"

# Protocol marker on X-Adaptix-Auth-Path. Bumping this on the gateway side
# requires updating this verifier in lockstep.
AUTH_PATH_GATEWAY_V1 = "gateway-v1"

CONTEXT_TTL_SECONDS = 60
GATEWAY_ISS = "adaptix-gateway"

# This service's audience identifier — the gateway pins the signed context
# to this exact string so a token destined for /api/v1/epcr cannot be
# replayed against /api/v1/billing.
EXPECTED_AUDIENCE = "adaptix-epcr"


class AuthContextError(Exception):
    """Raised by verify_context() when the context cannot be trusted."""


def _shared_secret() -> str:
    """Return the gateway↔EPCR shared secret, or raise.

    Read from ``ADAPTIX_GATEWAY_SHARED_SECRET``. Both the gateway (when
    signing) and EPCR (when verifying) must have the same value injected
    via AWS Secrets Manager.
    """
    secret = os.environ.get("ADAPTIX_GATEWAY_SHARED_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "ADAPTIX_GATEWAY_SHARED_SECRET is not configured. EPCR cannot "
            "verify gateway-signed auth contexts. Inject the same value the "
            "gateway uses, via Secrets Manager."
        )
    return secret


def _b64url_decode(s: str) -> bytes:
    padded = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def verify_context(
    *,
    context_b64: str,
    signature_hex: str,
    expected_audience: str = EXPECTED_AUDIENCE,
    clock_skew_seconds: int = 5,
) -> dict[str, Any]:
    """Verify an inbound signed auth context from the gateway.

    Raises ``AuthContextError`` on any failure. Never falls back silently.

    Args:
        context_b64: Value of ``X-Adaptix-Auth-Context`` (base64url JSON).
        signature_hex: Value of ``X-Adaptix-Auth-Signature`` (hex HMAC).
        expected_audience: This service's audience identifier. Tokens with
            a different ``aud`` are rejected. Default ``"adaptix-epcr"``.
        clock_skew_seconds: How much future ``iat`` and past ``exp`` we
            tolerate. Default 5s.

    Returns:
        The decoded, verified payload dict with keys:
        ``sub, user_id, tenant_id, agency_id, email, roles, scopes,
        iss, aud, iat, exp, jti``.

    Raises:
        AuthContextError on any verification failure.
        RuntimeError if ADAPTIX_GATEWAY_SHARED_SECRET is not set.
    """
    if not context_b64 or not signature_hex:
        raise AuthContextError("context or signature header missing")

    expected_sig = hmac.new(
        _shared_secret().encode("utf-8"),
        context_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_sig.lower(), signature_hex.strip().lower()):
        raise AuthContextError("signature mismatch")

    try:
        raw = _b64url_decode(context_b64)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuthContextError(f"payload decode failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise AuthContextError("payload is not an object")

    if payload.get("iss") != GATEWAY_ISS:
        raise AuthContextError(f"unexpected iss: {payload.get('iss')!r}")
    if payload.get("aud") != expected_audience:
        raise AuthContextError(
            f"audience mismatch: payload aud={payload.get('aud')!r}, "
            f"expected {expected_audience!r}"
        )

    now = int(time.time())
    iat = int(payload.get("iat", 0))
    exp = int(payload.get("exp", 0))
    if iat - clock_skew_seconds > now:
        raise AuthContextError("context not yet valid (iat in the future)")
    if exp + clock_skew_seconds < now:
        raise AuthContextError("context expired")

    if not payload.get("tenant_id"):
        raise AuthContextError("payload missing tenant_id")
    if not payload.get("sub"):
        raise AuthContextError("payload missing sub")

    return payload


__all__ = [
    "AUTH_PATH_GATEWAY_V1",
    "AuthContextError",
    "CONTEXT_TTL_SECONDS",
    "EXPECTED_AUDIENCE",
    "GATEWAY_ISS",
    "HEADER_AUTH_CONTEXT",
    "HEADER_AUTH_PATH",
    "HEADER_AUTH_SIGNATURE",
    "HEADER_REQUEST_ID",
    "verify_context",
]
