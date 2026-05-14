"""Live end-to-end test of the _ai_bedrock helper used by the EPCR routers."""
from epcr_app._ai_bedrock import invoke_ai, select_ai_provider

print("provider=", select_ai_provider())
provider, model, text = invoke_ai(
    system="You are a JSON-only assistant. Reply with exactly one short JSON object.",
    user='Return: {"ok": true, "word": "PASS"}',
    max_tokens=64,
)
print("provider_used=", provider)
print("model=", model)
print("text=", text)
