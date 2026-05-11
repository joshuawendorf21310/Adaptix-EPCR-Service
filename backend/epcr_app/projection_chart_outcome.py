"""Projection: :class:`ChartOutcome` -> NEMSIS field-value ledger rows.

This module is the bridge between the domain model and the
registry-driven export path. Every populated single-value column on
the outcome aggregate produces one ``NemsisFieldValue`` row whose
``element_number`` is the NEMSIS v3.5.1 canonical element ID and whose
``value`` is the coded string (or ISO-8601 timestamp / integer string)
the NEMSIS schema expects.

The four 1:M code-list columns
(eOutcome.03/04/05/19) emit ONE ledger row per list entry. Each entry
uses ``occurrence_id = f"{row_id}-{element_number}-{idx}"`` and
``sequence_index=idx`` so the dataset XML builder can reassemble each
entry as one repeating-group occurrence.

Columns that are still ``None`` (or empty lists) are NOT projected;
the chart-finalization gate is responsible for blocking finalization
when a Mandatory/Required-at-National/Conditional value is missing.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per
the service contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_outcome import (
    ChartOutcomeService,
    _OUTCOME_DATETIME_FIELDS,
    _OUTCOME_FIELDS,
    _OUTCOME_LIST_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eOutcome"


# (column_name, element_number, NEMSIS element name)
_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    (
        "emergency_department_disposition_code",
        "eOutcome.01",
        "Emergency Department Disposition",
    ),
    ("hospital_disposition_code", "eOutcome.02", "Hospital Disposition"),
    (
        "emergency_department_diagnosis_codes_json",
        "eOutcome.03",
        "Emergency Department Diagnosis",
    ),
    (
        "hospital_admission_diagnosis_codes_json",
        "eOutcome.04",
        "Hospital Admission Diagnosis",
    ),
    (
        "hospital_procedures_performed_codes_json",
        "eOutcome.05",
        "Hospital Procedures Performed",
    ),
    ("trauma_registry_incident_id", "eOutcome.06", "Trauma Registry Incident ID"),
    (
        "hospital_outcome_at_discharge_code",
        "eOutcome.07",
        "Hospital Outcome at Discharge",
    ),
    (
        "patient_disposition_from_emergency_department_at",
        "eOutcome.08",
        "Patient Disposition from Emergency Department",
    ),
    (
        "emergency_department_arrival_at",
        "eOutcome.09",
        "Emergency Department Arrival Date/Time",
    ),
    (
        "emergency_department_admit_at",
        "eOutcome.10",
        "Emergency Department Admit Date/Time",
    ),
    (
        "emergency_department_discharge_at",
        "eOutcome.11",
        "Emergency Department Discharge Date/Time",
    ),
    ("hospital_admit_at", "eOutcome.12", "Hospital Admit Date/Time"),
    ("hospital_discharge_at", "eOutcome.13", "Hospital Discharge Date/Time"),
    ("icu_admit_at", "eOutcome.14", "ICU Admit Date/Time"),
    ("icu_discharge_at", "eOutcome.15", "ICU Discharge Date/Time"),
    ("hospital_length_of_stay_days", "eOutcome.16", "Hospital Length of Stay"),
    ("icu_length_of_stay_days", "eOutcome.17", "ICU Length of Stay"),
    ("final_patient_acuity_code", "eOutcome.18", "Final Patient Acuity"),
    ("cause_of_death_codes_json", "eOutcome.19", "Cause of Death"),
    ("date_of_death", "eOutcome.20", "Date/Time of Death"),
    ("medical_record_number", "eOutcome.21", "Medical Record Number"),
    (
        "receiving_facility_record_number",
        "eOutcome.22",
        "Receiving Facility Record Number",
    ),
    ("referred_to_facility_code", "eOutcome.23", "Referred to Facility Code"),
    ("referred_to_facility_name", "eOutcome.24", "Referred to Facility Name"),
]

# Sanity guard: the binding must cover every persisted column declared
# on the service so we never silently drop a column from the export.
_BINDING_COLUMNS = {column for column, _, _ in _ELEMENT_BINDING}
assert _BINDING_COLUMNS == set(_OUTCOME_FIELDS), (
    "projection_chart_outcome binding drift: missing="
    f"{set(_OUTCOME_FIELDS) - _BINDING_COLUMNS}, "
    f"extra={_BINDING_COLUMNS - set(_OUTCOME_FIELDS)}"
)


def _fmt_scalar(field: str, value: Any) -> str | None:
    if value is None:
        return None
    if field in _OUTCOME_DATETIME_FIELDS:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)
    return str(value)


def _payloads_from_record(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    row_id = str(record["id"])
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _ELEMENT_BINDING:
        raw = record.get(column)
        if raw is None:
            continue

        if column in _OUTCOME_LIST_FIELDS:
            # 1:M list column: emit one ledger row per entry. Skip
            # empty lists entirely (NEMSIS absence semantics).
            if not isinstance(raw, (list, tuple)) or len(raw) == 0:
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
                        group_path="",
                        occurrence_id=f"{row_id}-{element_number}-{idx}",
                        sequence_index=idx,
                        attributes={},
                        source="manual",
                        validation_status="unvalidated",
                        validation_issues=[],
                        user_id=user_id,
                    )
                )
            continue

        formatted = _fmt_scalar(column, raw)
        if formatted is None:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=formatted,
                group_path="",
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


async def project_chart_outcome(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted :class:`ChartOutcome` row to the ledger.

    Reads ``ChartOutcome`` for the given chart, then upserts one
    ``NemsisFieldValue`` row per populated single-value column and one
    row per entry in each populated 1:M list column. Returns the list
    of upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when no ``ChartOutcome``
    row exists yet; the gate decides whether absence is acceptable.
    """
    record = await ChartOutcomeService.get(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if record is None:
        return []
    payloads = _payloads_from_record(record, user_id)
    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = ["project_chart_outcome", "SECTION", "_ELEMENT_BINDING"]
