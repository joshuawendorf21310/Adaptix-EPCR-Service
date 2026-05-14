"""Live tier smoke for the Bedrock helper. Exits 0 only if all three tiers
return non-empty text from their expected Nova model."""

from __future__ import annotations

import os
import sys

# Ensure we don't accidentally pin a single model via legacy env.
os.environ.pop("BEDROCK_MODEL_ID", None)
os.environ.setdefault("AWS_PROFILE", "vscode")
os.environ.setdefault("BEDROCK_REGION", "us-east-1")

from epcr_app._ai_bedrock import invoke_ai, resolve_model_id  # noqa: E402

SYSTEM = "You are a strict JSON emitter. Output ONLY a JSON object."
USER = 'Reply with exactly: {"ok": true, "word": "PASS"}'

failures: list[str] = []
for tier, expected in (
    ("default", "amazon.nova-lite-v1:0"),
    ("cheap", "amazon.nova-micro-v1:0"),
    ("escalate", "amazon.nova-pro-v1:0"),
):
    resolved = resolve_model_id(tier)  # type: ignore[arg-type]
    print(f"[{tier}] resolve_model_id -> {resolved}")
    if resolved != expected:
        failures.append(f"{tier}: resolved={resolved} expected={expected}")
        continue
    try:
        provider, model, text = invoke_ai(
            system=SYSTEM, user=USER, max_tokens=128, tier=tier  # type: ignore[arg-type]
        )
        print(f"[{tier}] provider={provider} model={model} text={text!r}")
        if not text.strip():
            failures.append(f"{tier}: empty text")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{tier}: {type(exc).__name__}: {exc}")
        print(f"[{tier}] ERROR {type(exc).__name__}: {exc}")

if failures:
    print("\nFAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("\nALL TIERS PASS")
