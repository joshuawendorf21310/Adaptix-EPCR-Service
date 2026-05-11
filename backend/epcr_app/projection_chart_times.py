"""Projection: :class:`ChartTimes` -> NEMSIS field-value ledger rows.

This module is the bridge between the domain model and the
registry-driven export path. Every domain time column produces one
``NemsisFieldValue`` row whose ``element_number`` is the NEMSIS v3.5.1
canonical element ID and whose ``value`` is the ISO-8601 timestamp the
NEMSIS schema expects. Columns that are still ``None`` are NOT projected
(they remain absent from the export); the chart-finalization gate is
responsible for blocking finalization when a Required-at-National time
is missing.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per the
service contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_times import ChartTimesService, _TIME_FIELDS
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eTimes"


# (column_name, element_number, NEMSIS element name)
_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    ("psap_call_at", "eTimes.01", "PSAP Call Date/Time"),
    ("dispatch_notified_at", "eTimes.02", "Dispatch Notified Date/Time"),
    ("unit_notified_by_dispatch_at", "eTimes.03", "Unit Notified by Dispatch Date/Time"),
    ("dispatch_acknowledged_at", "eTimes.04", "Dispatch Acknowledged Date/Time"),
    ("unit_en_route_at", "eTimes.05", "Unit En Route Date/Time"),
    ("unit_on_scene_at", "eTimes.06", "Unit Arrived on Scene Date/Time"),
    ("arrived_at_patient_at", "eTimes.07", "Arrived at Patient Date/Time"),
    ("transfer_of_ems_care_at", "eTimes.08", "Transfer of EMS Patient Care Date/Time"),
    ("unit_left_scene_at", "eTimes.09", "Unit Left Scene Date/Time"),
    ("arrival_landing_area_at", "eTimes.10", "Arrival at Destination Landing Area Date/Time"),
    ("patient_arrived_at_destination_at", "eTimes.11", "Patient Arrived at Destination Date/Time"),
    ("destination_transfer_of_care_at", "eTimes.12", "Destination Patient Transfer of Care Date/Time"),
    ("unit_back_in_service_at", "eTimes.13", "Unit Back in Service Date/Time"),
    ("unit_canceled_at", "eTimes.14", "Unit Canceled Date/Time"),
    ("unit_back_home_location_at", "eTimes.15", "Unit Back at Home Location Date/Time"),
    ("ems_call_completed_at", "eTimes.16", "EMS Call Completed Date/Time"),
    ("unit_arrived_staging_at", "eTimes.17", "Unit Arrived at Staging Area Date/Time"),
]

# Sanity guard: the binding must cover every column declared on the
# model so we never silently drop a column from the export.
_BINDING_COLUMNS = {column for column, _, _ in _ELEMENT_BINDING}
assert _BINDING_COLUMNS == set(_TIME_FIELDS), (
    "projection_chart_times binding drift: missing="
    f"{set(_TIME_FIELDS) - _BINDING_COLUMNS}, "
    f"extra={_BINDING_COLUMNS - set(_TIME_FIELDS)}"
)


def _fmt(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported time value type: {type(value).__name__}")


def _payloads_from_record(record: dict[str, Any], user_id: str | None) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _ELEMENT_BINDING:
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


async def project_chart_times(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted :class:`ChartTimes` row to the field-values ledger.

    Reads ``ChartTimes`` for the given chart, then upserts one
    ``NemsisFieldValue`` row per populated column. Returns the list of
    upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when no ``ChartTimes``
    row exists yet; the gate decides whether absence is acceptable.
    """
    record = await ChartTimesService.get(
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


__all__ = ["project_chart_times", "SECTION"]
