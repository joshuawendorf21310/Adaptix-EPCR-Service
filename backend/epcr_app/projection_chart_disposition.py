"""Projection: :class:`ChartDisposition` -> NEMSIS field-value ledger rows.

This module is the bridge between the domain model and the
registry-driven export path. Scalar columns produce one
``NemsisFieldValue`` row per populated column. JSON-list columns
(``*_codes_json``) expand into one ledger row per list entry, with
``occurrence_id`` derived from the parent disposition row's UUID and
the element number so re-projection is idempotent and each
repeating-group occurrence is uniquely addressable.

Columns that are still ``None`` (or empty lists) are NOT projected
— they remain absent from the export; the chart-finalization gate is
responsible for blocking finalization when a Mandatory/Required-at-
National value is missing.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per
the service contract.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_disposition import (
    ChartDispositionService,
    _DISPOSITION_FIELDS,
    _LIST_FIELDS,
    _SCALAR_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eDisposition"


# (column_name, element_number, NEMSIS element name) for scalar columns.
_SCALAR_BINDING: list[tuple[str, str, str]] = [
    ("destination_name", "eDisposition.01", "Destination/Transferred To, Name"),
    ("destination_code", "eDisposition.02", "Destination/Transferred To, Code"),
    ("destination_address", "eDisposition.03", "Destination Address"),
    ("destination_city", "eDisposition.04", "Destination City"),
    ("destination_county", "eDisposition.05", "Destination County"),
    ("destination_state", "eDisposition.06", "Destination State"),
    ("destination_zip", "eDisposition.07", "Destination ZIP Code"),
    ("destination_country", "eDisposition.08", "Destination Country"),
    ("type_of_destination_code", "eDisposition.11", "Type of Destination"),
    (
        "incident_patient_disposition_code",
        "eDisposition.12",
        "Incident/Patient Disposition",
    ),
    (
        "transport_mode_from_scene_code",
        "eDisposition.13",
        "Mode of Transport from Scene",
    ),
    ("transport_disposition_code", "eDisposition.16", "Transport Disposition"),
    ("reason_not_transported_code", "eDisposition.17", "Reason Not Transported"),
    ("level_of_care_provided_code", "eDisposition.18", "Level of Care Provided"),
    (
        "position_during_transport_code",
        "eDisposition.19",
        "Position of Patient During Transport",
    ),
    (
        "condition_at_destination_code",
        "eDisposition.20",
        "Patient Condition at Destination",
    ),
    ("transferred_care_to_code", "eDisposition.21", "Transferred Patient/Care To"),
    (
        "destination_type_when_reason_code",
        "eDisposition.25",
        "Destination Type - When Reason Code Used",
    ),
    ("unit_disposition_code", "eDisposition.28", "Unit Disposition"),
    ("transport_method_code", "eDisposition.29", "EMS Transport Method"),
]

# (column_name, element_number, NEMSIS element name) for 1:M list columns.
_LIST_BINDING: list[tuple[str, str, str]] = [
    (
        "hospital_capability_codes_json",
        "eDisposition.09",
        "Hospital Capability",
    ),
    (
        "reason_for_choosing_destination_codes_json",
        "eDisposition.10",
        "Reason for Choosing Destination",
    ),
    (
        "additional_transport_descriptors_codes_json",
        "eDisposition.14",
        "Additional Transport Mode Descriptors",
    ),
    (
        "hospital_incapability_codes_json",
        "eDisposition.15",
        "Hospital In-Capability",
    ),
    (
        "prearrival_activation_codes_json",
        "eDisposition.22",
        "Prearrival Activation",
    ),
    (
        "type_of_destination_reason_codes_json",
        "eDisposition.23",
        "Type of Destination - Reason",
    ),
    (
        "destination_team_activations_codes_json",
        "eDisposition.24",
        "Destination Team Activations",
    ),
    (
        "crew_disposition_codes_json",
        "eDisposition.27",
        "Crew Disposition",
    ),
    (
        "transport_method_additional_codes_json",
        "eDisposition.30",
        "EMS Transport Method, Additional",
    ),
]

_ELEMENT_BINDING: list[tuple[str, str, str]] = _SCALAR_BINDING + _LIST_BINDING


# Sanity guard: the binding must cover every column declared on the
# model so we never silently drop a column from the export.
_BINDING_COLUMNS = {column for column, _, _ in _ELEMENT_BINDING}
assert _BINDING_COLUMNS == set(_DISPOSITION_FIELDS), (
    "projection_chart_disposition binding drift: missing="
    f"{set(_DISPOSITION_FIELDS) - _BINDING_COLUMNS}, "
    f"extra={_BINDING_COLUMNS - set(_DISPOSITION_FIELDS)}"
)
_SCALAR_BINDING_COLUMNS = {column for column, _, _ in _SCALAR_BINDING}
_LIST_BINDING_COLUMNS = {column for column, _, _ in _LIST_BINDING}
assert _SCALAR_BINDING_COLUMNS == set(_SCALAR_FIELDS), (
    "projection_chart_disposition scalar drift"
)
assert _LIST_BINDING_COLUMNS == set(_LIST_FIELDS), (
    "projection_chart_disposition list drift"
)


def _fmt_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _payloads_from_record(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    disposition_id = str(record.get("id") or "")

    # Scalar columns: one ledger row per populated column.
    for column, element_number, element_name in _SCALAR_BINDING:
        raw = record.get(column)
        formatted = _fmt_scalar(raw)
        if formatted is None or formatted == "":
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

    # JSON list columns: one ledger row per list entry.
    for column, element_number, element_name in _LIST_BINDING:
        raw = record.get(column)
        if raw is None:
            continue
        if not isinstance(raw, list):
            continue
        for idx, entry in enumerate(raw):
            formatted = _fmt_scalar(entry)
            if formatted is None or formatted == "":
                continue
            payloads.append(
                FieldValuePayload(
                    section=SECTION,
                    element_number=element_number,
                    element_name=element_name,
                    value=formatted,
                    group_path="",
                    occurrence_id=f"{disposition_id}-{element_number}-{idx}",
                    sequence_index=idx,
                    attributes={},
                    source="manual",
                    validation_status="unvalidated",
                    validation_issues=[],
                    user_id=user_id,
                )
            )

    return payloads


async def project_chart_disposition(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted :class:`ChartDisposition` row to the field-values ledger.

    Reads ``ChartDisposition`` for the given chart, then upserts one
    ``NemsisFieldValue`` row per populated scalar column, plus one row
    per JSON-list entry. Returns the list of upserted ledger rows for
    observability/testing.

    The projection is a no-op (returns ``[]``) when no
    ``ChartDisposition`` row exists yet; the gate decides whether
    absence is acceptable.
    """
    record = await ChartDispositionService.get(
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


__all__ = [
    "project_chart_disposition",
    "SECTION",
    "_ELEMENT_BINDING",
    "_SCALAR_BINDING",
    "_LIST_BINDING",
]
