"""Validation rules for the 3D Physical Assessment anatomical findings.

The frontend posts a list of finding payloads in camelCase. This module
validates and normalizes each payload before it is persisted by
:mod:`epcr_app.services.anatomical_finding_service`. Failures raise
``AnatomicalFindingValidationError`` carrying an ``errors`` list of
``{"field": ..., "message": ...}`` entries so the API layer can surface
field-level diagnostics without translation.

The 18 canonical region IDs are duplicated verbatim here so the
backend does not have to import a frontend-owned registry. Frontend and
backend must remain in lock-step on these strings; any change requires
coordinated work in both repos.
"""

from __future__ import annotations

from datetime import datetime
from numbers import Real
from typing import Any, Iterable


CANONICAL_REGION_IDS: frozenset[str] = frozenset(
    {
        "region_head",
        "region_neck",
        "region_chest",
        "region_abdomen",
        "region_back",
        "region_pelvis",
        "region_left_upper_arm",
        "region_left_forearm",
        "region_left_hand",
        "region_right_upper_arm",
        "region_right_forearm",
        "region_right_hand",
        "region_left_thigh",
        "region_left_lower_leg",
        "region_left_foot",
        "region_right_thigh",
        "region_right_lower_leg",
        "region_right_foot",
    }
)


BODY_VIEW_VALUES: frozenset[str] = frozenset({"front", "back", "left", "right"})
SEVERITY_VALUES: frozenset[str] = frozenset(
    {"mild", "moderate", "severe", "not_specified"}
)
LATERALITY_VALUES: frozenset[str] = frozenset(
    {"left", "right", "midline", "bilateral", "not_applicable"}
)
CMS_PULSE_VALUES: frozenset[str] = frozenset(
    {"present", "weak", "absent", "not_assessed"}
)
CMS_MOTOR_VALUES: frozenset[str] = frozenset(
    {"intact", "weak", "absent", "not_assessed"}
)
CMS_SENSATION_VALUES: frozenset[str] = frozenset(
    {"intact", "decreased", "absent", "not_assessed"}
)
CMS_CAPILLARY_REFILL_VALUES: frozenset[str] = frozenset(
    {"normal", "delayed", "absent", "not_assessed"}
)


class AnatomicalFindingValidationError(ValueError):
    """Raised when one or more anatomical finding fields fail validation."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors: list[dict[str, str]] = list(errors)
        message = "; ".join(f"{e['field']}: {e['message']}" for e in self.errors)
        super().__init__(message or "anatomical_finding_validation_error")


def _add_required(errors: list[dict[str, str]], field: str, value: Any) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        errors.append({"field": field, "message": "is required"})


def _check_enum(
    errors: list[dict[str, str]],
    field: str,
    value: Any,
    allowed: Iterable[str],
    *,
    nullable: bool,
) -> Any:
    if value is None:
        if not nullable:
            errors.append({"field": field, "message": "is required"})
        return None
    if not isinstance(value, str) or value not in allowed:
        errors.append(
            {
                "field": field,
                "message": f"must be one of {sorted(allowed)}",
            }
        )
        return None
    return value


def _parse_iso(value: Any, field: str, errors: list[dict[str, str]]) -> str | None:
    if value is None or value == "":
        errors.append({"field": field, "message": "is required"})
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if not isinstance(value, str):
        errors.append({"field": field, "message": "must be an ISO 8601 string"})
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append({"field": field, "message": "must be an ISO 8601 string"})
        return None
    return value


def validate_finding(payload: Any) -> dict[str, Any]:
    """Validate and normalize a single anatomical finding payload.

    Args:
        payload: Raw camelCase dict supplied by the frontend.

    Returns:
        Normalized dict with snake_case keys ready to be persisted.

    Raises:
        AnatomicalFindingValidationError: One or more fields are invalid.
    """
    if not isinstance(payload, dict):
        raise AnatomicalFindingValidationError(
            [{"field": "_root", "message": "finding payload must be an object"}]
        )

    errors: list[dict[str, str]] = []

    region_id = payload.get("regionId")
    region_label = payload.get("regionLabel")
    body_view = payload.get("bodyView")
    finding_type = payload.get("findingType")
    assessed_by = payload.get("assessedBy")

    _add_required(errors, "regionId", region_id)
    _add_required(errors, "regionLabel", region_label)
    _add_required(errors, "findingType", finding_type)
    _add_required(errors, "assessedBy", assessed_by)

    if region_id is not None and isinstance(region_id, str):
        if region_id not in CANONICAL_REGION_IDS:
            errors.append(
                {
                    "field": "regionId",
                    "message": "unknown region; not in canonical registry",
                }
            )

    body_view_v = _check_enum(
        errors, "bodyView", body_view, BODY_VIEW_VALUES, nullable=False
    )

    severity = payload.get("severity")
    severity_v = _check_enum(
        errors, "severity", severity, SEVERITY_VALUES, nullable=True
    )

    laterality = payload.get("laterality")
    laterality_v = _check_enum(
        errors, "laterality", laterality, LATERALITY_VALUES, nullable=True
    )

    pain_scale = payload.get("painScale")
    pain_scale_v: int | None = None
    if pain_scale is not None:
        if isinstance(pain_scale, bool) or not isinstance(pain_scale, int):
            errors.append({"field": "painScale", "message": "must be an integer"})
        elif pain_scale < 0 or pain_scale > 10:
            errors.append({"field": "painScale", "message": "must be in 0..10"})
        else:
            pain_scale_v = int(pain_scale)

    burn = payload.get("burnTbsaPercent")
    burn_v: float | None = None
    if burn is not None:
        if isinstance(burn, bool) or not isinstance(burn, Real):
            errors.append(
                {"field": "burnTbsaPercent", "message": "must be a number"}
            )
        elif burn < 0 or burn > 100:
            errors.append(
                {"field": "burnTbsaPercent", "message": "must be in 0..100"}
            )
        else:
            burn_v = float(burn)

    cms = payload.get("cms") or {}
    if not isinstance(cms, dict):
        errors.append({"field": "cms", "message": "must be an object"})
        cms = {}

    cms_pulse = _check_enum(
        errors, "cms.pulse", cms.get("pulse"), CMS_PULSE_VALUES, nullable=True
    )
    cms_motor = _check_enum(
        errors, "cms.motor", cms.get("motor"), CMS_MOTOR_VALUES, nullable=True
    )
    cms_sensation = _check_enum(
        errors,
        "cms.sensation",
        cms.get("sensation"),
        CMS_SENSATION_VALUES,
        nullable=True,
    )
    cms_cap = _check_enum(
        errors,
        "cms.capillaryRefill",
        cms.get("capillaryRefill"),
        CMS_CAPILLARY_REFILL_VALUES,
        nullable=True,
    )

    pertinent_negative = bool(payload.get("pertinentNegative", False))
    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        errors.append({"field": "notes", "message": "must be a string"})
        notes = None

    assessed_at_v = _parse_iso(payload.get("assessedAt"), "assessedAt", errors)

    if errors:
        raise AnatomicalFindingValidationError(errors)

    return {
        "id": payload.get("id"),
        "region_id": region_id,
        "region_label": region_label,
        "body_view": body_view_v,
        "finding_type": finding_type,
        "severity": severity_v,
        "laterality": laterality_v,
        "pain_scale": pain_scale_v,
        "burn_tbsa_percent": burn_v,
        "cms_pulse": cms_pulse,
        "cms_motor": cms_motor,
        "cms_sensation": cms_sensation,
        "cms_capillary_refill": cms_cap,
        "pertinent_negative": pertinent_negative,
        "notes": notes,
        "assessed_at": assessed_at_v,
        "assessed_by": str(assessed_by),
    }


__all__ = [
    "AnatomicalFindingValidationError",
    "CANONICAL_REGION_IDS",
    "BODY_VIEW_VALUES",
    "SEVERITY_VALUES",
    "LATERALITY_VALUES",
    "CMS_PULSE_VALUES",
    "CMS_MOTOR_VALUES",
    "CMS_SENSATION_VALUES",
    "CMS_CAPILLARY_REFILL_VALUES",
    "validate_finding",
]
