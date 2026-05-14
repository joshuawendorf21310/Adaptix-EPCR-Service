"""Smoke test against Amazon Nova on Bedrock (no per-vendor form gate)."""
import boto3

s = boto3.Session(profile_name="vscode", region_name="us-east-1")
c = s.client("bedrock-runtime")
r = c.converse(
    modelId="amazon.nova-lite-v1:0",
    system=[{"text": "You return ONLY a JSON object, nothing else."}],
    messages=[{"role": "user", "content": [{"text": 'Return JSON: {"ok": true, "word": "PASS"}'}]}],
    inferenceConfig={"maxTokens": 64, "temperature": 0.0},
)
print("text=", r["output"]["message"]["content"][0]["text"])
