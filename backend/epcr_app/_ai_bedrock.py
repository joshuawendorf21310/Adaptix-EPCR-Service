"""Bedrock + Anthropic advisory AI invocation helper for EPCR routers.

This module exists because the ``anthropic.AnthropicBedrock`` SDK route on
Amazon Bedrock requires a per-account "Anthropic use case details" form to
be submitted before the Messages-on-Bedrock endpoint will respond — even
when the underlying model is fully accessible via the standard
``bedrock-runtime`` Converse API. We therefore call Converse directly with
boto3 for the Bedrock path and keep the Anthropic SDK only for the direct
``ANTHROPIC_API_KEY`` path.

Model tiering (Amazon Nova family, no per-vendor form gate):

* ``default`` — Amazon Nova Lite. Best initial model for: patient portal
  help, billing-support explanations, statement lookup guidance, document
  summaries, screenshot/image understanding, EMS workflow explanations,
  internal admin assistance, lightweight RAG over our docs.
* ``cheap`` — Amazon Nova Micro. Lowest-cost text-only tier; used as the
  automatic fallback when the default is throttled or unavailable, and
  for very short prompts where Lite would be overkill.
* ``escalate`` — Amazon Nova Pro. Reserved for hard reasoning, long
  context, complex multi-step advisory tasks. Callers opt in via
  ``tier="escalate"``.

Env overrides:

* ``BEDROCK_MODEL_DEFAULT``  (default ``amazon.nova-lite-v1:0``)
* ``BEDROCK_MODEL_CHEAP``    (default ``amazon.nova-micro-v1:0``)
* ``BEDROCK_MODEL_ESCALATE`` (default ``amazon.nova-pro-v1:0``)
* ``BEDROCK_MODEL_ID``       — legacy single-model override; when set it
  forces every call to use that one model regardless of tier.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

logger = logging.getLogger(__name__)

Tier = Literal["default", "cheap", "escalate"]

# Default Bedrock model per tier. These IDs are ``ON_DEMAND`` ACTIVE models
# on Amazon Bedrock in us-east-1 (verified 2026-05-12).
_TIER_DEFAULTS: dict[str, str] = {
    "default": "amazon.nova-lite-v1:0",
    "cheap": "amazon.nova-micro-v1:0",
    "escalate": "amazon.nova-pro-v1:0",
}

# Bedrock error codes that warrant an automatic fallback from the default
# tier down to the cheap tier (transient capacity / throttling). Anything
# else (validation errors, access denied, model-not-found) is raised so
# the caller renders a truthful failure.
_FALLBACK_ERROR_CODES = frozenset(
    {
        "ThrottlingException",
        "ServiceUnavailableException",
        "ModelTimeoutException",
        "ModelStreamErrorException",
        "ModelErrorException",
        "ServiceQuotaExceededException",
    }
)


def anthropic_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def bedrock_configured() -> bool:
    """Bedrock is considered configured when ``BEDROCK_REGION`` is set.

    A model id is no longer required at the env level because the helper
    falls back to the built-in Nova tier defaults; callers may still pin
    a single model via ``BEDROCK_MODEL_ID`` for legacy behavior.
    """

    return bool(os.environ.get("BEDROCK_REGION", "").strip())


def select_ai_provider() -> str | None:
    """Choose the advisory AI backend.

    Order:
      1. Explicit override via ``AI_PROVIDER`` env (``bedrock`` | ``anthropic``).
      2. Bedrock when ``BEDROCK_REGION`` is set.
      3. Direct Anthropic when ``ANTHROPIC_API_KEY`` is set.
      4. ``None`` otherwise.
    """

    override = os.environ.get("AI_PROVIDER", "").strip().lower()
    if override == "bedrock" and bedrock_configured():
        return "bedrock"
    if override == "anthropic" and anthropic_configured():
        return "anthropic"
    if bedrock_configured():
        return "bedrock"
    if anthropic_configured():
        return "anthropic"
    return None


def resolve_model_id(tier: Tier = "default") -> str:
    """Return the Bedrock model id for the requested tier.

    ``BEDROCK_MODEL_ID`` (legacy single-model env) overrides every tier
    when set. Otherwise tier-specific envs (``BEDROCK_MODEL_DEFAULT``,
    ``BEDROCK_MODEL_CHEAP``, ``BEDROCK_MODEL_ESCALATE``) override the
    built-in defaults.
    """

    legacy = os.environ.get("BEDROCK_MODEL_ID", "").strip()
    if legacy:
        return legacy
    env_key = {
        "default": "BEDROCK_MODEL_DEFAULT",
        "cheap": "BEDROCK_MODEL_CHEAP",
        "escalate": "BEDROCK_MODEL_ESCALATE",
    }[tier]
    return os.environ.get(env_key, "").strip() or _TIER_DEFAULTS[tier]


def _resolve_aws_profile() -> str | None:
    """Resolve AWS profile for Bedrock.

    Returns the first non-empty of ``BEDROCK_AWS_PROFILE`` or ``AWS_PROFILE``.
    When neither is set, returns ``None`` so boto3 uses its standard
    credential resolution chain (default profile, IAM role on ECS/EC2, etc.).
    """

    profile = (
        os.environ.get("BEDROCK_AWS_PROFILE", "").strip()
        or os.environ.get("AWS_PROFILE", "").strip()
    )
    return profile or None


def _converse_once(
    *, model_id: str, region: str, system: str, user: str, max_tokens: int
) -> str:
    """Single Bedrock Converse call. Raises on empty response or API error."""

    import boto3  # type: ignore  # noqa: PLC0415

    profile = _resolve_aws_profile()
    session = (
        boto3.Session(profile_name=profile, region_name=region)
        if profile
        else boto3.Session(region_name=region)
    )
    client = session.client("bedrock-runtime", region_name=region)
    resp = client.converse(
        modelId=model_id,
        system=[{"text": system}] if system else [],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": int(max_tokens), "temperature": 0.0},
    )
    parts: list[str] = []
    output = resp.get("output") or {}
    message = output.get("message") or {}
    for block in message.get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if isinstance(text, str):
            parts.append(text)
    combined = "".join(parts).strip()
    if not combined:
        raise RuntimeError("Bedrock Converse returned empty response.")
    return combined


def _invoke_bedrock(
    *, system: str, user: str, max_tokens: int, tier: Tier
) -> tuple[str, str]:
    """Call Bedrock with tier ladder + transient-failure fallback.

    Returns ``(model_id_used, text)``. ``tier="default"`` will fall back to
    the cheap tier on throttling/transient errors. ``tier="cheap"`` and
    ``tier="escalate"`` do not auto-fallback (the caller chose them
    explicitly).
    """

    from botocore.exceptions import ClientError  # type: ignore  # noqa: PLC0415

    region = os.environ.get("BEDROCK_REGION", "").strip()
    if not region:
        raise RuntimeError("BEDROCK_REGION must be set.")

    primary_model = resolve_model_id(tier)
    try:
        text = _converse_once(
            model_id=primary_model,
            region=region,
            system=system,
            user=user,
            max_tokens=max_tokens,
        )
        return primary_model, text
    except ClientError as exc:
        code = (exc.response.get("Error", {}) or {}).get("Code", "")
        if tier == "default" and code in _FALLBACK_ERROR_CODES:
            fallback_model = resolve_model_id("cheap")
            if fallback_model and fallback_model != primary_model:
                logger.warning(
                    "Bedrock primary model %s failed (%s); falling back to cheap tier %s",
                    primary_model,
                    code,
                    fallback_model,
                )
                text = _converse_once(
                    model_id=fallback_model,
                    region=region,
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                )
                return fallback_model, text
        raise


def _invoke_anthropic(
    *, system: str, user: str, max_tokens: int
) -> tuple[str, str]:
    """Call the direct Anthropic API and return ``(model_id, text)``."""

    import anthropic  # type: ignore  # noqa: PLC0415

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    model_id = os.environ.get("ANTHROPIC_TAC_MODEL", "claude-sonnet-4-6").strip()
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model_id,
        max_tokens=int(max_tokens),
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        block_text = getattr(block, "text", None)
        if isinstance(block_text, str):
            parts.append(block_text)
    combined = "".join(parts).strip()
    if not combined:
        raise RuntimeError("Anthropic API returned empty response.")
    return model_id, combined


def invoke_ai(
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
    tier: Tier = "default",
) -> tuple[str, str, str]:
    """Invoke the active advisory AI backend.

    Args:
        system: System prompt.
        user: User prompt content.
        max_tokens: Output token cap.
        tier: Bedrock model tier — ``"default"`` (Nova Lite),
            ``"cheap"`` (Nova Micro), or ``"escalate"`` (Nova Pro).
            Ignored when the active provider is direct Anthropic.

    Returns ``(provider_name, model_id, text)``. Raises ``RuntimeError``
    when no provider is configured or the call fails.
    """

    provider = select_ai_provider()
    if provider == "bedrock":
        model_id, text = _invoke_bedrock(
            system=system, user=user, max_tokens=max_tokens, tier=tier
        )
        return "bedrock", model_id, text
    if provider == "anthropic":
        model_id, text = _invoke_anthropic(
            system=system, user=user, max_tokens=max_tokens
        )
        return "anthropic", model_id, text
    raise RuntimeError("No AI provider configured.")


__all__ = [
    "Tier",
    "anthropic_configured",
    "bedrock_configured",
    "invoke_ai",
    "resolve_model_id",
    "select_ai_provider",
]
