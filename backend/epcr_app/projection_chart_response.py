"""Projection: :class:`ChartResponse` and :class:`ChartResponseDelay`
to NEMSIS field-value ledger rows.

This module is the bridge between the domain models and the
registry-driven export path.

Metadata projection (1:1):
  * Every populated scalar column produces one ``NemsisFieldValue`` row
    whose ``element_number`` is the NEMSIS v3.5.1 canonical element ID.
  * The vehicle-dispatch-location bundle (lat/long/address/usng) is
    grouped under ``group_path="eResponse.VehicleDispatchLocationGroup"``.
  * The ``additional_response_descriptors_json`` list (eResponse.24) is
    projected as one ledger row per list entry, each carrying its own
    ``sequence_index`` to preserve order.

Delay projection (1:M):
  * Each row in ``epcr_chart_response_delays`` produces one ledger row,
    mapped to its delay_kind's eResponse.NN element number, with
    ``occurrence_id = delay.id`` so the dataset XML builder can
    reassemble the repeating-group occurrences.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per
the service contract.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_response import ChartResponseService
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eResponse"
VEHICLE_DISPATCH_GROUP = "eResponse.VehicleDispatchLocationGroup"


# (column_name, element_number, NEMSIS element name) for non-grouped
# scalar columns. Lat/long/address/usng are handled separately because
# they share a group_path.
_SCALAR_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    ("agency_number", "eResponse.01", "EMS Agency Number"),
    ("agency_name", "eResponse.02", "EMS Agency Name"),
    ("type_of_service_requested_code", "eResponse.05", "Type of Service Requested"),
    ("standby_purpose_code", "eResponse.06", "Primary Role of the Unit"),
    ("unit_transport_capability_code", "eResponse.07", "Type of Service Requested"),
    ("unit_vehicle_number", "eResponse.13", "EMS Unit (Vehicle) Number"),
    ("unit_call_sign", "eResponse.14", "EMS Unit Call Sign"),
    ("beginning_odometer", "eResponse.19", "Beginning Odometer Reading of Responding Vehicle"),
    ("on_scene_odometer", "eResponse.20", "On-Scene Odometer Reading of Responding Vehicle"),
    ("destination_odometer", "eResponse.21", "Patient Destination Odometer Reading of Responding Vehicle"),
    ("ending_odometer", "eResponse.22", "Ending Odometer Reading of Responding Vehicle"),
    ("response_mode_to_scene_code", "eResponse.23", "Response Mode to Scene"),
]


# (column_name, element_number, NEMSIS element name) for columns that
# belong to the VehicleDispatchLocationGroup grouping.
_VEHICLE_DISPATCH_BINDING: list[tuple[str, str, str]] = [
    ("vehicle_dispatch_address", "eResponse.16", "Vehicle Dispatch GPS Location"),
    ("vehicle_dispatch_lat", "eResponse.17", "Vehicle Dispatch Location (GPS)"),
    ("vehicle_dispatch_long", "eResponse.17", "Vehicle Dispatch Location (GPS)"),
    ("vehicle_dispatch_usng", "eResponse.18", "Vehicle Dispatch Location (US National Grid)"),
]


# delay_kind -> (element_number, element_name) for the typed-delay 1:M
# children. Each row in epcr_chart_response_delays maps to one of these.
_DELAY_ELEMENT_BINDING: dict[str, tuple[str, str]] = {
    "dispatch": ("eResponse.08", "Type of Dispatch Delay"),
    "response": ("eResponse.09", "Type of Response Delay"),
    "scene": ("eResponse.10", "Type of Scene Delay"),
    "transport": ("eResponse.11", "Type of Transport Delay"),
    "turn_around": ("eResponse.12", "Type of Turn-Around Delay"),
}


# eResponse.24 — Additional Response Descriptors (Optional, 1:M list).
_ADDITIONAL_DESCRIPTORS_ELEMENT = (
    "eResponse.24",
    "Additional Response Agency Activities",
)


def _payloads_from_meta(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []

    # Scalar non-grouped fields.
    for column, element_number, element_name in _SCALAR_ELEMENT_BINDING:
        raw = record.get(column)
        if raw is None or (isinstance(raw, str) and raw == ""):
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(raw),
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

    # Vehicle dispatch location bundle (grouped).
    for column, element_number, element_name in _VEHICLE_DISPATCH_BINDING:
        raw = record.get(column)
        if raw is None or (isinstance(raw, str) and raw == ""):
            continue
        # lat/long share the same element_number (eResponse.17); they
        # are distinguished inside the group by attributes the dataset
        # XML builder consumes downstream.
        attributes: dict[str, Any] = {}
        if column == "vehicle_dispatch_lat":
            attributes["axis"] = "lat"
        elif column == "vehicle_dispatch_long":
            attributes["axis"] = "long"
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(raw),
                group_path=VEHICLE_DISPATCH_GROUP,
                occurrence_id="",
                sequence_index=0,
                attributes=attributes,
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )

    # Additional response descriptors (eResponse.24, 1:M list).
    descriptors = record.get("additional_response_descriptors_json")
    if isinstance(descriptors, list):
        for idx, code in enumerate(descriptors):
            if code is None or (isinstance(code, str) and code == ""):
                continue
            element_number, element_name = _ADDITIONAL_DESCRIPTORS_ELEMENT
            payloads.append(
                FieldValuePayload(
                    section=SECTION,
                    element_number=element_number,
                    element_name=element_name,
                    value=str(code),
                    group_path="",
                    occurrence_id=f"additional-{idx}",
                    sequence_index=idx,
                    attributes={},
                    source="manual",
                    validation_status="unvalidated",
                    validation_issues=[],
                    user_id=user_id,
                )
            )

    return payloads


def _payloads_from_delays(
    delays: list[dict[str, Any]], user_id: str | None
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for delay in delays:
        kind = delay.get("delay_kind")
        code = delay.get("delay_code")
        if not kind or not code:
            continue
        if kind not in _DELAY_ELEMENT_BINDING:
            continue
        element_number, element_name = _DELAY_ELEMENT_BINDING[kind]
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(code),
                group_path="",
                occurrence_id=str(delay["id"]),
                sequence_index=int(delay.get("sequence_index") or 0),
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_chart_response(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project persisted eResponse rows to the field-values ledger.

    Reads the 1:1 metadata row plus every non-deleted delay row, then
    upserts one ``NemsisFieldValue`` row per populated column / list
    entry / delay. Returns the list of upserted ledger rows for
    observability/testing.

    The projection is a no-op (returns ``[]``) when neither metadata nor
    delays exist; the chart-finalization gate decides whether absence
    is acceptable.
    """
    meta = await ChartResponseService.get(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    delays = await ChartResponseService.list_delays(
        session, tenant_id=tenant_id, chart_id=chart_id
    )

    payloads: list[FieldValuePayload] = []
    if meta is not None:
        payloads.extend(_payloads_from_meta(meta, user_id))
    if delays:
        payloads.extend(_payloads_from_delays(delays, user_id))

    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "project_chart_response",
    "SECTION",
    "VEHICLE_DISPATCH_GROUP",
    "_SCALAR_ELEMENT_BINDING",
    "_VEHICLE_DISPATCH_BINDING",
    "_DELAY_ELEMENT_BINDING",
    "_ADDITIONAL_DESCRIPTORS_ELEMENT",
]
