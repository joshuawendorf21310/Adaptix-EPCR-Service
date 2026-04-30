#!/usr/bin/env python3
"""CTA EMS Collect Data probe — captures live -16 status as operator evidence.

Run this script to:
1. Build a minimal EMS probe payload from local artifacts
2. Submit to CTA and capture statusCode=-16
3. Write timestamped evidence to artifacts/

This script never claims EMS success unless CTA returns statusCode=1.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Insert backend on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from epcr_app.nemsis.cta_client import CtaSubmissionClient


PROBE_EMS_XML_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "artifact" / "generated" / "2025-EMS-1-Allergy_v351.xml",
    Path(__file__).resolve().parent.parent / "nemsis_test" / "xml" / "2025-EMS-1-Allergy_v351.xml",
]


def _find_probe_xml() -> tuple[Path, bytes] | None:
    for candidate in PROBE_EMS_XML_CANDIDATES:
        if candidate.exists():
            data = candidate.read_bytes()
            return candidate, data
    return None


async def run_probe() -> dict:
    """Submit EMS probe and capture response."""
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    found = _find_probe_xml()
    if not found:
        return {
            "status": "BLOCKED_NO_ARTIFACT",
            "timestamp_utc": timestamp,
            "message": "No local EMS XML artifact found. Run local validation first.",
            "searched": [str(c) for c in PROBE_EMS_XML_CANDIDATES],
        }

    xml_path, xml_bytes = found
    xml_sha256 = hashlib.sha256(xml_bytes).hexdigest()

    client = CtaSubmissionClient()

    integration_enabled = os.getenv("CTA_PROBE_LIVE", "0") == "1"

    result = await client.submit(
        xml_bytes=xml_bytes,
        integration_enabled=integration_enabled,
        submission_label="EMS-1-Allergy-probe",
    )

    evidence = {
        "probe_timestamp_utc": timestamp,
        "integration_enabled": integration_enabled,
        "xml_artifact": str(xml_path),
        "xml_sha256": xml_sha256,
        "endpoint": result.endpoint,
        "submitted": result.submitted,
        "http_status": result.http_status,
        "response_status": result.response_status,
        "status_code": result.status_code,
        "request_handle": result.request_handle,
        "message": result.message,
        "response_body": result.response_body,
    }

    # Interpret result
    code = result.status_code
    if not integration_enabled:
        evidence["final_status"] = "SKIPPED_GATE_DISABLED"
        evidence["operator_note"] = "Set CTA_PROBE_LIVE=1 to run live probe."
    elif code == "1":
        evidence["final_status"] = "EMS_CTA_PASS"
        evidence["operator_note"] = "EMS Collect Data submission accepted. Certification unlocked."
    elif code == "-16":
        evidence["final_status"] = "PASS_OPERATOR_ACTION_REQUIRED"
        evidence["operator_note"] = (
            "CTA EMS returns -16. Account not provisioned for EMS Collect Data. "
            "Contact NEMSIS support: is FusionEMSQuantum enrolled for EMS-1 through EMS-5 Collect Data?"
        )
    else:
        evidence["final_status"] = f"BLOCKED_STATUS_{code}"
        evidence["operator_note"] = f"Unexpected CTA status code: {code}. Investigate with NEMSIS support."

    return evidence


def main() -> None:
    evidence = asyncio.run(run_probe())

    # Write evidence
    out_path = Path(__file__).resolve().parent.parent / "artifacts" / "cta-ems-probe-live.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2, default=str))

    print(json.dumps(evidence, indent=2, default=str))

    final = evidence.get("final_status", "UNKNOWN")
    print(f"\n=== CTA EMS PROBE: {final} ===")

    if final == "EMS_CTA_PASS":
        sys.exit(0)
    elif final in ("PASS_OPERATOR_ACTION_REQUIRED", "SKIPPED_GATE_DISABLED"):
        # Not a code failure — operator must act
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
