from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from epcr_app.nemsis_xml_builder import NemsisBuildError, NemsisXmlBuilder
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator


def rec(field: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(nemsis_field=field, nemsis_value=value)


def chart(**kwargs) -> SimpleNamespace:
    base = {
        "id": "chart-001",
        "tenant_id": "tenant-001",
        "call_number": "CALL-001",
        "incident_type": "medical",
        "created_at": datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
        "narrative": "Unit arrived to find patient alert and breathing.",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_builder_blocks_missing_legal_identifier():
    c = chart(call_number=None, id=None)
    records = [
        rec("dAgency.01", "12"),
        rec("dAgency.02", "123456"),
        rec("eTimes.01", "2026-04-22T120000+0000"),
        rec("eSituation.01", "2026-04-22T120000+0000"),
        rec("eNarrative.01", "Narrative"),
    ]
    with pytest.raises(NemsisBuildError, match="identifier|report"):
        NemsisXmlBuilder(chart=c, mapping_records=records).build()


def test_builder_never_emits_unknown_identifier():
    c = chart()
    records = [
        rec("dAgency.01", "12"),
        rec("dAgency.02", "123456"),
        rec("eTimes.01", "2026-04-22T120000+0000"),
        rec("eSituation.01", "2026-04-22T120000+0000"),
        rec("eNarrative.01", "Narrative"),
    ]
    xml_bytes, _ = NemsisXmlBuilder(chart=c, mapping_records=records).build()
    xml = xml_bytes.decode("utf-8")
    assert "UNKNOWN" not in xml


def test_builder_never_emits_contaminated_metadata():
    c = chart()
    records = [
        rec("dAgency.01", "12"),
        rec("dAgency.02", "123456"),
        rec("eTimes.01", "2026-04-22T120000+0000"),
        rec("eSituation.01", "2026-04-22T120000+0000"),
        rec("eNarrative.01", "Narrative"),
    ]
    xml_bytes, _ = NemsisXmlBuilder(chart=c, mapping_records=records).build()
    xml = xml_bytes.decode("utf-8")
    assert "FusionEMSQuantum" not in xml
    assert "Adaptix Platform" in xml


def test_builder_blocks_raw_text_in_coded_fields():
    c = chart()
    records = [
        rec("dAgency.01", "12"),
        rec("dAgency.02", "123456"),
        rec("eResponse.05", "high priority"),
        rec("eTimes.01", "2026-04-22T120000+0000"),
        rec("eSituation.01", "2026-04-22T120000+0000"),
        rec("eNarrative.01", "Narrative"),
    ]
    with pytest.raises(NemsisBuildError, match="coded|non-numeric|validation"):
        NemsisXmlBuilder(chart=c, mapping_records=records).build()


def test_validator_reports_blocked_when_assets_missing(monkeypatch):
    monkeypatch.delenv("NEMSIS_XSD_PATH", raising=False)
    monkeypatch.delenv("NEMSIS_SCHEMATRON_PATH", raising=False)
    validator = NemsisXSDValidator()
    result = validator.validate_xml(b"<EMSDataSet/>")
    assert result["valid"] is False
    assert result["validation_skipped"] is False
    assert result["blocking_reason"] is None
