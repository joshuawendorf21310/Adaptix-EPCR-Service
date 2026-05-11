from __future__ import annotations

from pathlib import Path

from epcr_app.nemsis_xsd_validator import NemsisXSDValidator


def _sample_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[1] / "epcr_app" / "nemsis_pretesting_v351" / Path(*parts)


def test_real_ems_sample_validates_against_shipped_xsd_bundle() -> None:
    xml_bytes = _sample_path("full", "2026-EMS-1-RespiratoryTransfer_v351.xml").read_bytes()

    result = NemsisXSDValidator().validate_xml(xml_bytes)

    assert result["validation_skipped"] is False
    assert result["blocking_reason"] is None
    assert result["xsd_valid"] is True, result["xsd_errors"]
    assert result["valid"] is True, result["errors"]
    assert len(result["checksum_sha256"]) == 64


def test_known_bad_ems_sample_fails_xsd_validation() -> None:
    xml_bytes = _sample_path("fail", "2026-EMS-FailXsd.xml").read_bytes()

    result = NemsisXSDValidator().validate_xml(xml_bytes)

    assert result["validation_skipped"] is False
    assert result["xsd_valid"] is False
    assert result["valid"] is False
    assert result["xsd_errors"], "expected concrete XSD errors from shipped fail fixture"
    assert len(result["checksum_sha256"]) == 64


def test_validator_checksum_is_deterministic_for_same_ems_payload() -> None:
    xml_bytes = _sample_path("full", "2026-EMS-1-RespiratoryTransfer_v351.xml").read_bytes()
    validator = NemsisXSDValidator()

    first = validator.validate_xml(xml_bytes)
    second = validator.validate_xml(xml_bytes)

    assert first["checksum_sha256"] == second["checksum_sha256"]
    assert first["xsd_valid"] is True
    assert second["xsd_valid"] is True
