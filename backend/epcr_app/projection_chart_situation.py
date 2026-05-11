"""Projection: :class:`ChartSituation` (+ children) -> NEMSIS field-value ledger.

This module is the bridge between the domain model and the
registry-driven export path. Every domain column produces one
``NemsisFieldValue`` row whose ``element_number`` is the NEMSIS v3.5.1
canonical element ID and whose ``value`` is the coded string the NEMSIS
schema expects. Columns that are still ``None`` are NOT projected (they
remain absent from the export); the chart-finalization gate is
responsible for blocking finalization when a Required-at-National value
is missing.

The 1:1 scalar row projects with empty ``occurrence_id`` (one ledger
row per element). The two repeating groups
(eSituation.10 Other Associated Symptoms, eSituation.12 Provider's
Secondary Impressions) project one ledger row per child row, with the
child row's UUID as ``occurrence_id`` so the dataset XML builder can
reassemble each occurrence.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per the
service contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_situation import (
    ChartSituationOtherSymptomService,
    ChartSituationSecondaryImpressionService,
    ChartSituationService,
    _SITUATION_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eSituation"

# Group path applied to the Duration of Complaint pair so the NEMSIS XML
# builder can keep .05 and .06 together as one logical group.
_COMPLAINT_DURATION_GROUP = "eSituation.ComplaintGroup"


# (column_name, element_number, NEMSIS element name, group_path)
_SCALAR_BINDING: list[tuple[str, str, str, str]] = [
    ("symptom_onset_at", "eSituation.01", "Date/Time of Symptom Onset", ""),
    ("possible_injury_indicator_code", "eSituation.02", "Possible Injury", ""),
    ("complaint_type_code", "eSituation.03", "Complaint Type", ""),
    ("complaint_text", "eSituation.04", "Complaint", ""),
    (
        "complaint_duration_value",
        "eSituation.05",
        "Duration of Complaint",
        _COMPLAINT_DURATION_GROUP,
    ),
    (
        "complaint_duration_units_code",
        "eSituation.06",
        "Time Units of Duration of Complaint",
        _COMPLAINT_DURATION_GROUP,
    ),
    (
        "chief_complaint_anatomic_code",
        "eSituation.07",
        "Chief Complaint Anatomic Location",
        "",
    ),
    (
        "chief_complaint_organ_system_code",
        "eSituation.08",
        "Chief Complaint Organ System",
        "",
    ),
    ("primary_symptom_code", "eSituation.09", "Primary Symptom", ""),
    (
        "provider_primary_impression_code",
        "eSituation.11",
        "Provider's Primary Impression",
        "",
    ),
    ("initial_patient_acuity_code", "eSituation.13", "Initial Patient Acuity", ""),
    (
        "work_related_indicator_code",
        "eSituation.14",
        "Work-Related Illness/Injury",
        "",
    ),
    ("patient_industry_code", "eSituation.15", "Patient's Occupational Industry", ""),
    ("patient_occupation_code", "eSituation.16", "Patient's Occupation", ""),
    ("patient_activity_code", "eSituation.17", "Patient Activity", ""),
    ("last_known_well_at", "eSituation.18", "Date/Time Last Known Well", ""),
    (
        "transfer_justification_code",
        "eSituation.19",
        "Justification for Transfer or Encounter",
        "",
    ),
    (
        "interfacility_transfer_reason_code",
        "eSituation.20",
        "Reason for Interfacility Transfer/Medical Transport",
        "",
    ),
]

# Sanity guard: the scalar binding must cover every column declared on
# the model so we never silently drop a column from the export.
_BINDING_COLUMNS = {column for column, _, _, _ in _SCALAR_BINDING}
assert _BINDING_COLUMNS == set(_SITUATION_FIELDS), (
    "projection_chart_situation binding drift: missing="
    f"{set(_SITUATION_FIELDS) - _BINDING_COLUMNS}, "
    f"extra={_BINDING_COLUMNS - set(_SITUATION_FIELDS)}"
)

# Repeating-group bindings (one element each).
_OTHER_SYMPTOM_ELEMENT = ("eSituation.10", "Other Associated Symptoms")
_SECONDARY_IMPRESSION_ELEMENT = (
    "eSituation.12",
    "Provider's Secondary Impressions",
)


def _fmt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _scalar_payloads(record: dict[str, Any], user_id: str | None) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name, group_path in _SCALAR_BINDING:
        raw = record.get(column)
        formatted = _fmt(raw)
        if formatted is None:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=formatted,
                group_path=group_path,
                occurrence_id="",
                sequence_index=0,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


def _other_symptom_payloads(
    rows: list[dict[str, Any]], user_id: str | None
) -> list[FieldValuePayload]:
    element_number, element_name = _OTHER_SYMPTOM_ELEMENT
    payloads: list[FieldValuePayload] = []
    for row in rows:
        code = row.get("symptom_code")
        if not code:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(code),
                group_path="",
                occurrence_id=str(row["id"]),
                sequence_index=int(row.get("sequence_index") or 0),
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


def _secondary_impression_payloads(
    rows: list[dict[str, Any]], user_id: str | None
) -> list[FieldValuePayload]:
    element_number, element_name = _SECONDARY_IMPRESSION_ELEMENT
    payloads: list[FieldValuePayload] = []
    for row in rows:
        code = row.get("impression_code")
        if not code:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(code),
                group_path="",
                occurrence_id=str(row["id"]),
                sequence_index=int(row.get("sequence_index") or 0),
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_chart_situation(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project all persisted eSituation rows to the field-values ledger.

    Reads the 1:1 :class:`ChartSituation` row plus all non-deleted
    children (Other Associated Symptoms, Secondary Impressions) for the
    chart, then upserts one ``NemsisFieldValue`` row per populated
    column or repeating-group occurrence. Returns the full list of
    upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when no eSituation data
    exists yet; the gate decides whether absence is acceptable.
    """
    payloads: list[FieldValuePayload] = []

    scalar_record = await ChartSituationService.get(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if scalar_record is not None:
        payloads.extend(_scalar_payloads(scalar_record, user_id))

    symptoms = await ChartSituationOtherSymptomService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    payloads.extend(_other_symptom_payloads(symptoms, user_id))

    impressions = await ChartSituationSecondaryImpressionService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    payloads.extend(_secondary_impression_payloads(impressions, user_id))

    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "project_chart_situation",
    "SECTION",
    "_SCALAR_BINDING",
    "_OTHER_SYMPTOM_ELEMENT",
    "_SECONDARY_IMPRESSION_ELEMENT",
    "_COMPLAINT_DURATION_GROUP",
]
