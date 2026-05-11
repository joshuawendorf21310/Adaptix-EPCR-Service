"""Projection: :class:`ChartArrest` -> NEMSIS field-value ledger rows.

This module is the bridge between the domain model and the
registry-driven export path. Every populated single-value column on
the arrest aggregate produces one ``NemsisFieldValue`` row whose
``element_number`` is the NEMSIS v3.5.1 canonical element ID and whose
``value`` is the coded string (or ISO-8601 timestamp) the NEMSIS schema
expects.

The four 1:M code-list columns
(eArrest.03/04/09/12) emit ONE ledger row per list entry. Each entry
shares the parent row's UUID with an ``-{idx}`` suffix as
``occurrence_id`` and uses ``sequence_index=idx`` so the dataset XML
builder can reassemble each entry as one repeating-group occurrence.

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

from epcr_app.services_chart_arrest import (
    ChartArrestService,
    _ARREST_FIELDS,
    _ARREST_LIST_FIELDS,
    _ARREST_DATETIME_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eArrest"


# (column_name, element_number, NEMSIS element name)
_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    ("cardiac_arrest_code", "eArrest.01", "Cardiac Arrest"),
    ("etiology_code", "eArrest.02", "Cardiac Arrest Etiology"),
    (
        "resuscitation_attempted_codes_json",
        "eArrest.03",
        "Resuscitation Attempted By EMS",
    ),
    ("witnessed_by_codes_json", "eArrest.04", "Arrest Witnessed By"),
    ("aed_use_prior_code", "eArrest.07", "AED Use Prior to EMS Arrival"),
    ("cpr_type_codes_json", "eArrest.09", "Type of CPR Provided"),
    ("hypothermia_indicator_code", "eArrest.10", "Therapeutic Hypothermia by EMS"),
    (
        "first_monitored_rhythm_code",
        "eArrest.11",
        "First Monitored Arrest Rhythm of the Patient",
    ),
    ("rosc_codes_json", "eArrest.12", "Any Return of Spontaneous Circulation"),
    (
        "neurological_outcome_code",
        "eArrest.13",
        "Neurological Outcome at Hospital Discharge",
    ),
    ("arrest_at", "eArrest.14", "Date/Time of Cardiac Arrest"),
    (
        "resuscitation_discontinued_at",
        "eArrest.15",
        "Date/Time Resuscitation Discontinued",
    ),
    (
        "reason_discontinued_code",
        "eArrest.16",
        "Reason CPR/Resuscitation Discontinued",
    ),
    (
        "rhythm_on_arrival_code",
        "eArrest.17",
        "Cardiac Rhythm on Arrival at Destination",
    ),
    ("end_of_event_code", "eArrest.18", "End of EMS Cardiac Arrest Event"),
    ("initial_cpr_at", "eArrest.19", "Date/Time of Initial CPR"),
    ("who_first_cpr_code", "eArrest.20", "Who First Initiated CPR"),
    ("who_first_aed_code", "eArrest.21", "Who First Applied the AED"),
    ("who_first_defib_code", "eArrest.22", "Who First Defibrillated the Patient"),
]

# Sanity guard: the binding must cover every persisted column declared
# on the service so we never silently drop a column from the export.
_BINDING_COLUMNS = {column for column, _, _ in _ELEMENT_BINDING}
assert _BINDING_COLUMNS == set(_ARREST_FIELDS), (
    "projection_chart_arrest binding drift: missing="
    f"{set(_ARREST_FIELDS) - _BINDING_COLUMNS}, "
    f"extra={_BINDING_COLUMNS - set(_ARREST_FIELDS)}"
)


def _fmt_scalar(field: str, value: Any) -> str | None:
    if value is None:
        return None
    if field in _ARREST_DATETIME_FIELDS:
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

        if column in _ARREST_LIST_FIELDS:
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
                        occurrence_id=f"{row_id}-{idx}",
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


async def project_chart_arrest(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted :class:`ChartArrest` row to the ledger.

    Reads ``ChartArrest`` for the given chart, then upserts one
    ``NemsisFieldValue`` row per populated single-value column and one
    row per entry in each populated 1:M list column. Returns the list
    of upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when no ``ChartArrest``
    row exists yet; the gate decides whether absence is acceptable.
    """
    record = await ChartArrestService.get(
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


__all__ = ["project_chart_arrest", "SECTION", "_ELEMENT_BINDING"]
