"""Projection: NEMSIS eVitals extension -> field-value ledger rows.

Bridges the per-Vitals-row extension aggregate (:mod:`models_vitals_ext`)
to the registry-driven NEMSIS export ledger
(:class:`NemsisFieldValue`). Each populated scalar column on the
extension produces one ledger row; each entry in a JSON 1:M list
column produces one ledger row per entry; each :class:`VitalsGcsQualifier`
and :class:`VitalsReperfusionChecklist` child row produces one ledger
row each.

NEMSIS occurrence semantics for eVitals: every Vitals row in a chart
represents one ``VitalGroup`` occurrence, so we key every projected
ledger row on ``occurrence_id=vitals_id`` (or a derived suffix for 1:M
entries) so the dataset XML builder can nest the values inside the
correct ``VitalGroup``. GCS-component elements use a sub-group path of
``eVitals.GlasgowComaScoreGroup`` so the builder can wrap them inside
the GCS sub-group on export.

Columns that are still ``None`` (or empty lists) are NOT projected; the
chart-finalization gate decides whether absence is acceptable. The
projector is idempotent: invoking it multiple times for the same
(chart, vitals_id) upserts by
``(element_number, group_path, occurrence_id)``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)
from epcr_app.services_vitals_ext import (
    _EXT_LIST_FIELDS,
    _EXT_SCALAR_FIELDS,
    VitalsExtService,
)


SECTION = "eVitals"
VITAL_GROUP_PATH = "eVitals.VitalGroup"
GCS_GROUP_PATH = "eVitals.GlasgowComaScoreGroup"


# (column_name, element_number, NEMSIS element name)
_SCALAR_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    ("obtained_prior_to_ems_code", "eVitals.02", "Obtained Prior to EMS Care"),
    ("ecg_type_code", "eVitals.04", "Type of Electrocardiogram"),
    ("blood_pressure_method_code", "eVitals.08", "Blood Pressure Method"),
    ("mean_arterial_pressure", "eVitals.09", "Mean Arterial Pressure"),
    ("heart_rate_method_code", "eVitals.11", "Method of Heart Rate Measurement"),
    ("pulse_rhythm_code", "eVitals.13", "Pulse Rhythm"),
    ("respiratory_effort_code", "eVitals.15", "Respiratory Effort"),
    ("etco2", "eVitals.16", "End Tidal Carbon Dioxide (ETCO2)"),
    ("carbon_monoxide_ppm", "eVitals.17", "Carbon Monoxide"),
    ("gcs_eye_code", "eVitals.19", "Glasgow Coma Score-Eye"),
    ("gcs_verbal_code", "eVitals.20", "Glasgow Coma Score-Verbal"),
    ("gcs_motor_code", "eVitals.21", "Glasgow Coma Score-Motor"),
    ("gcs_total", "eVitals.23", "Total Glasgow Coma Score"),
    ("temperature_method_code", "eVitals.25", "Temperature Method"),
    ("avpu_code", "eVitals.26", "Level of Responsiveness (AVPU)"),
    ("pain_score", "eVitals.27", "Pain Scale Score"),
    ("pain_scale_type_code", "eVitals.28", "Pain Scale Type"),
    ("stroke_scale_result_code", "eVitals.29", "Stroke Scale Result"),
    ("stroke_scale_type_code", "eVitals.30", "Stroke Scale Type"),
    ("stroke_scale_score", "eVitals.34", "Stroke Scale Score"),
    ("apgar_score", "eVitals.32", "APGAR"),
    ("revised_trauma_score", "eVitals.33", "Revised Trauma Score"),
]

# 1:M JSON list columns: (column_name, element_number, name)
_LIST_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    (
        "cardiac_rhythm_codes_json",
        "eVitals.03",
        "Cardiac Rhythm / Electrocardiogram (ECG)",
    ),
    (
        "ecg_interpretation_method_codes_json",
        "eVitals.05",
        "Method of ECG Interpretation",
    ),
]

# Columns that should be wrapped in the GCS sub-group on export.
_GCS_GROUP_COLUMNS = {
    "gcs_eye_code",
    "gcs_verbal_code",
    "gcs_motor_code",
    "gcs_total",
}


# Sanity guards: binding tables must cover every persisted column.
_SCALAR_BINDING_COLUMNS = {c for c, _, _ in _SCALAR_ELEMENT_BINDING}
assert _SCALAR_BINDING_COLUMNS == set(_EXT_SCALAR_FIELDS), (
    "projection_vitals_ext scalar binding drift: missing="
    f"{set(_EXT_SCALAR_FIELDS) - _SCALAR_BINDING_COLUMNS}, "
    f"extra={_SCALAR_BINDING_COLUMNS - set(_EXT_SCALAR_FIELDS)}"
)
_LIST_BINDING_COLUMNS = {c for c, _, _ in _LIST_ELEMENT_BINDING}
assert _LIST_BINDING_COLUMNS == set(_EXT_LIST_FIELDS), (
    "projection_vitals_ext list binding drift: missing="
    f"{set(_EXT_LIST_FIELDS) - _LIST_BINDING_COLUMNS}, "
    f"extra={_LIST_BINDING_COLUMNS - set(_EXT_LIST_FIELDS)}"
)


def _group_path_for(column: str) -> str:
    return GCS_GROUP_PATH if column in _GCS_GROUP_COLUMNS else VITAL_GROUP_PATH


def _scalar_payloads(
    ext_record: dict[str, Any],
    vitals_id: str,
    user_id: str | None,
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _SCALAR_ELEMENT_BINDING:
        raw = ext_record.get(column)
        if raw is None:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(raw),
                group_path=_group_path_for(column),
                occurrence_id=vitals_id,
                sequence_index=0,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


def _list_payloads(
    ext_record: dict[str, Any],
    vitals_id: str,
    user_id: str | None,
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _LIST_ELEMENT_BINDING:
        raw = ext_record.get(column)
        if not raw or not isinstance(raw, (list, tuple)):
            continue
        for idx, entry in enumerate(raw):
            if entry is None:
                continue
            payloads.append(
                FieldValuePayload(
                    section=SECTION,
                    element_number=element_number,
                    element_name=element_name,
                    value=str(entry),
                    group_path=VITAL_GROUP_PATH,
                    occurrence_id=f"{vitals_id}-{element_number}-{idx}",
                    sequence_index=idx,
                    attributes={},
                    source="manual",
                    validation_status="unvalidated",
                    validation_issues=[],
                    user_id=user_id,
                )
            )
    return payloads


def _gcs_qualifier_payloads(
    rows: list[dict[str, Any]],
    vitals_id: str,
    user_id: str | None,
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for row in rows:
        code = row.get("qualifier_code")
        if not code:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number="eVitals.22",
                element_name="Glasgow Coma Score-Qualifier",
                value=str(code),
                group_path=GCS_GROUP_PATH,
                occurrence_id=vitals_id,
                sequence_index=int(row.get("sequence_index") or 0),
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


def _reperfusion_payloads(
    rows: list[dict[str, Any]],
    vitals_id: str,
    user_id: str | None,
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for row in rows:
        code = row.get("item_code")
        if not code:
            continue
        seq = int(row.get("sequence_index") or 0)
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number="eVitals.31",
                element_name="Reperfusion Checklist",
                value=str(code),
                group_path=VITAL_GROUP_PATH,
                occurrence_id=f"{vitals_id}-rc-{seq}",
                sequence_index=seq,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_vitals_ext(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    vitals_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted eVitals extension to the ledger.

    Reads the extension aggregate (ext scalars/lists + gcs_qualifiers
    + reperfusion_checklist) for ``(tenant_id, chart_id, vitals_id)``,
    then upserts one ``NemsisFieldValue`` row per populated value.
    Returns the list of upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when no extension data
    exists yet; the gate decides whether absence is acceptable.
    """
    record = await VitalsExtService.get(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        vitals_id=vitals_id,
    )
    if record is None:
        return []

    payloads: list[FieldValuePayload] = []
    ext = record.get("ext")
    if ext is not None:
        payloads.extend(_scalar_payloads(ext, vitals_id, user_id))
        payloads.extend(_list_payloads(ext, vitals_id, user_id))
    payloads.extend(
        _gcs_qualifier_payloads(
            record.get("gcs_qualifiers") or [], vitals_id, user_id
        )
    )
    payloads.extend(
        _reperfusion_payloads(
            record.get("reperfusion_checklist") or [], vitals_id, user_id
        )
    )

    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "project_vitals_ext",
    "SECTION",
    "VITAL_GROUP_PATH",
    "GCS_GROUP_PATH",
    "_SCALAR_ELEMENT_BINDING",
    "_LIST_ELEMENT_BINDING",
    "_GCS_GROUP_COLUMNS",
]
