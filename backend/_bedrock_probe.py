"""Live AWS Bedrock probe.

Walks candidate profiles, calls bedrock-runtime Converse against a small
Claude model in us-east-1, prints first profile that works.
"""
from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
MODEL_CANDIDATES = [
    os.environ.get("BEDROCK_MODEL_ID", "").strip()
    or "anthropic.claude-3-5-haiku-20241022-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
]
PROFILE_CANDIDATES = ["joshua-wendorf", "joshua", "vscode", "default"]


def try_profile(profile: str) -> tuple[bool, str]:
    try:
        session = boto3.Session(profile_name=profile, region_name=REGION)
        sts = session.client("sts")
        ident = sts.get_caller_identity()
        client = session.client("bedrock-runtime", region_name=REGION)
        last_err = ""
        for model in MODEL_CANDIDATES:
            if not model:
                continue
            try:
                resp = client.converse(
                    modelId=model,
                    messages=[{"role": "user", "content": [{"text": "Say OK."}]}],
                    inferenceConfig={"maxTokens": 16, "temperature": 0.0},
                )
                text = ""
                for blk in resp["output"]["message"]["content"]:
                    if "text" in blk:
                        text += blk["text"]
                return True, f"profile={profile} arn={ident.get('Arn')} model={model} reply={text!r}"
            except (BotoCoreError, ClientError) as exc:
                last_err = f"{model}: {exc}"
                continue
        return False, f"profile={profile} sts_ok arn={ident.get('Arn')} but no model accessible. last_err={last_err}"
    except (BotoCoreError, ClientError) as exc:
        return False, f"profile={profile} error={exc}"


def main() -> int:
    for profile in PROFILE_CANDIDATES:
        ok, msg = try_profile(profile)
        marker = "OK  " if ok else "FAIL"
        print(f"[{marker}] {msg}")
        if ok:
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
