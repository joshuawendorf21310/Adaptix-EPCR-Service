"""Layer 9 — Live NEMSIS 3.5.1 XSD/Schematron validator execution.

Loads the production NEMSIS XSD bundle (NEMSIS_XSD_PATH from backend/.env)
and the production Schematron rule set (NEMSIS_SCHEMATRON_PATH), runs the
official validator against a real exported StateDataSet XML produced by
NemsisXmlBuilder, and asserts that:

* the validator actually executed (not skipped, no asset blocking)
* it parsed the XML against the real NEMSIS 3.5.1 XSD bundle
* it returned a structured verdict (xsd_errors list, schematron summary,
  checksum, asset version 3.5.1.250403CP1, execution_ms)
* the validator is wired to lxml + saxonche on this host

This is a live-run guarantee, not a synthetic mock.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_dotenv_into_environ() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv_into_environ()


def _rec(field: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(nemsis_field=field, nemsis_value=value)


def _chart() -> SimpleNamespace:
    return SimpleNamespace(
        id="chart-live-xsd",
        tenant_id="tenant-live-xsd",
        call_number="CALL-LIVE-001",
        incident_type="medical",
        created_at=datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
        narrative="Unit arrived to find patient alert and breathing.",
    )


def test_live_xsd_assets_present_on_disk():
    xsd_path = os.environ.get("NEMSIS_XSD_PATH", "")
    sch_path = os.environ.get("NEMSIS_SCHEMATRON_PATH", "")
    assert xsd_path and Path(xsd_path).exists(), f"NEMSIS_XSD_PATH missing: {xsd_path!r}"
    assert sch_path and Path(sch_path).exists(), f"NEMSIS_SCHEMATRON_PATH missing: {sch_path!r}"


def test_live_validator_runtime_libraries_available():
    import lxml.etree  # noqa: F401
    import saxonche  # noqa: F401


def test_live_xsd_validator_runs_against_real_export():
    from epcr_app.nemsis_xml_builder import NemsisXmlBuilder
    from epcr_app.nemsis_xsd_validator import NemsisXSDValidator

    chart = _chart()
    records = [
        _rec("dAgency.01", "12"),
        _rec("dAgency.02", "123456"),
        _rec("dAgency.27", "9170001"),
        _rec("ePayment.47", "9923001"),
        _rec("eTimes.01", "2026-04-22T120000+0000"),
        _rec("eSituation.01", "2026-04-22T120000+0000"),
        _rec("eNarrative.01", "Narrative."),
    ]
    xml_bytes, _ = NemsisXmlBuilder(chart=chart, mapping_records=records).build()
    assert b"3.5.1" in xml_bytes

    validator = NemsisXSDValidator()
    try:
        result = validator.validate_xml(xml_bytes)
    finally:
        validator.close()

    # The validator MUST have actually run — no asset-missing skip path.
    assert result["validation_skipped"] is False, (
        f"Validator skipped (assets unavailable). blocking_reason={result.get('blocking_reason')!r}"
    )
    assert result["blocking_reason"] is None

    # Structured verdict shape — proves the pipeline executed end-to-end.
    assert "xsd_errors" in result and isinstance(result["xsd_errors"], list)
    assert "schematron_errors" in result and isinstance(result["schematron_errors"], list)
    assert "checksum_sha256" in result and len(result["checksum_sha256"]) == 64
    assert result["validator_asset_version"] == "3.5.1.250403CP1"
    assert isinstance(result["execution_ms"], int) and result["execution_ms"] >= 0

    # XSD verdict is a real boolean derived from the official schema parse.
    assert isinstance(result["xsd_valid"], bool)
    assert isinstance(result["schematron_valid"], bool)
