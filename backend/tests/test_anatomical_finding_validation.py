"""Validator-level tests for anatomical finding payloads."""

from __future__ import annotations

import pytest

from epcr_app.services.anatomical_finding_validation import (
    AnatomicalFindingValidationError,
    validate_finding,
)


def _base_payload(**overrides):
    payload = {
        "regionId": "region_head",
        "regionLabel": "Head",
        "bodyView": "front",
        "findingType": "laceration",
        "severity": "moderate",
        "laterality": "midline",
        "painScale": 5,
        "burnTbsaPercent": 0,
        "cms": {
            "pulse": "present",
            "motor": "intact",
            "sensation": "intact",
            "capillaryRefill": "normal",
        },
        "pertinentNegative": False,
        "notes": "ok",
        "assessedAt": "2026-05-12T10:00:00Z",
        "assessedBy": "user-1",
    }
    payload.update(overrides)
    return payload


def test_validate_finding_accepts_valid_payload() -> None:
    normalized = validate_finding(_base_payload())
    assert normalized["region_id"] == "region_head"
    assert normalized["body_view"] == "front"
    assert normalized["pain_scale"] == 5
    assert normalized["cms_pulse"] == "present"
    assert normalized["pertinent_negative"] is False


def test_validate_finding_missing_required_fields() -> None:
    with pytest.raises(AnatomicalFindingValidationError) as exc:
        validate_finding({"bodyView": "front"})
    fields = {e["field"] for e in exc.value.errors}
    assert "regionId" in fields
    assert "regionLabel" in fields
    assert "findingType" in fields
    assert "assessedBy" in fields
    assert "assessedAt" in fields


def test_validate_finding_rejects_unknown_region() -> None:
    with pytest.raises(AnatomicalFindingValidationError) as exc:
        validate_finding(_base_payload(regionId="region_not_real"))
    assert any(e["field"] == "regionId" for e in exc.value.errors)


def test_validate_finding_rejects_bad_body_view() -> None:
    with pytest.raises(AnatomicalFindingValidationError) as exc:
        validate_finding(_base_payload(bodyView="diagonal"))
    assert any(e["field"] == "bodyView" for e in exc.value.errors)


def test_validate_finding_rejects_bad_severity_and_laterality() -> None:
    with pytest.raises(AnatomicalFindingValidationError) as exc:
        validate_finding(_base_payload(severity="catastrophic", laterality="dorsal"))
    fields = {e["field"] for e in exc.value.errors}
    assert "severity" in fields
    assert "laterality" in fields


def test_validate_finding_rejects_pain_scale_out_of_range() -> None:
    with pytest.raises(AnatomicalFindingValidationError) as exc:
        validate_finding(_base_payload(painScale=99))
    assert any(e["field"] == "painScale" for e in exc.value.errors)


def test_validate_finding_rejects_burn_tbsa_out_of_range() -> None:
    with pytest.raises(AnatomicalFindingValidationError) as exc:
        validate_finding(_base_payload(burnTbsaPercent=120))
    assert any(e["field"] == "burnTbsaPercent" for e in exc.value.errors)


def test_validate_finding_rejects_bad_cms_enum() -> None:
    with pytest.raises(AnatomicalFindingValidationError) as exc:
        validate_finding(
            _base_payload(
                cms={
                    "pulse": "thready",
                    "motor": "intact",
                    "sensation": "intact",
                    "capillaryRefill": "normal",
                }
            )
        )
    assert any(e["field"] == "cms.pulse" for e in exc.value.errors)


def test_validate_finding_accepts_nullable_optional_fields() -> None:
    normalized = validate_finding(
        _base_payload(
            severity=None,
            laterality=None,
            painScale=None,
            burnTbsaPercent=None,
            cms={
                "pulse": None,
                "motor": None,
                "sensation": None,
                "capillaryRefill": None,
            },
        )
    )
    assert normalized["severity"] is None
    assert normalized["pain_scale"] is None
    assert normalized["cms_pulse"] is None
