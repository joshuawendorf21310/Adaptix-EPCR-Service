"""Projection: :class:`ChartInjury` + :class:`ChartInjuryAcn` -> NEMSIS ledger.

This module is the bridge between the eInjury domain model and the
registry-driven export path. It emits one ``NemsisFieldValue`` row per
populated NEMSIS element occurrence:

* Scalar columns on :class:`ChartInjury` produce one ledger row.
* JSON-list columns on :class:`ChartInjury` (1:M repeating-group lists)
  produce one ledger row per list entry, with
  ``occurrence_id=f"{injury.id}-{element}-{idx}"`` so the dataset XML
  builder can reassemble each occurrence.
* :class:`ChartInjuryAcn` columns are emitted with
  ``group_path="eInjury.AutomatedCrashNotificationGroup"`` and an empty
  ``occurrence_id`` (the ACN block is 1:1).

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per
the service contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_injury import (
    ChartInjuryService,
    _ACN_FIELDS,
    _INJURY_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eInjury"
ACN_GROUP_PATH = "eInjury.AutomatedCrashNotificationGroup"


# (column_name, element_number, NEMSIS element name, is_json_list)
_INJURY_BINDING: list[tuple[str, str, str, bool]] = [
    ("cause_of_injury_codes_json", "eInjury.01", "Cause of Injury", True),
    ("mechanism_of_injury_code", "eInjury.02", "Mechanism of Injury", False),
    ("trauma_triage_high_codes_json", "eInjury.03", "Trauma Triage Criteria (High Risk)", True),
    ("trauma_triage_moderate_codes_json", "eInjury.04", "Trauma Triage Criteria (Moderate Risk)", True),
    ("vehicle_impact_area_code", "eInjury.05", "Main Area of the Vehicle Impacted", False),
    ("patient_location_in_vehicle_code", "eInjury.06", "Location of Patient in Vehicle", False),
    ("occupant_safety_equipment_codes_json", "eInjury.07", "Use of Occupant Safety Equipment", True),
    ("airbag_deployment_code", "eInjury.08", "Airbag Deployment", False),
    ("height_of_fall_feet", "eInjury.09", "Height of Fall", False),
    ("osha_ppe_used_codes_json", "eInjury.10", "OSHA Personal Protective Equipment Used", True),
]


# (column_name, element_number, NEMSIS element name)
_ACN_BINDING: list[tuple[str, str, str]] = [
    ("acn_system_company", "eInjury.11", "ACN System/Company"),
    ("acn_incident_id", "eInjury.12", "ACN Incident ID"),
    ("acn_callback_phone", "eInjury.13", "ACN Call Back Phone Number"),
    ("acn_incident_at", "eInjury.14", "Date/Time of ACN Incident"),
    ("acn_incident_location", "eInjury.15", "ACN Incident Location"),
    ("acn_vehicle_body_type_code", "eInjury.16", "ACN Incident Vehicle Body Type"),
    ("acn_vehicle_manufacturer", "eInjury.17", "ACN Incident Vehicle Manufacturer"),
    ("acn_vehicle_make", "eInjury.18", "ACN Incident Vehicle Make"),
    ("acn_vehicle_model", "eInjury.19", "ACN Incident Vehicle Model"),
    ("acn_vehicle_model_year", "eInjury.20", "ACN Incident Vehicle Model Year"),
    ("acn_multiple_impacts_code", "eInjury.21", "ACN Incident Multiple Impacts"),
    ("acn_delta_velocity", "eInjury.22", "ACN Incident Delta Velocity"),
    ("acn_high_probability_code", "eInjury.23", "ACN High Probability of Injury"),
    ("acn_pdof", "eInjury.24", "ACN Incident PDOF"),
    ("acn_rollover_code", "eInjury.25", "ACN Incident Rollover"),
    ("acn_seat_location_code", "eInjury.26", "ACN Vehicle Seat Location"),
    ("seat_occupied_code", "eInjury.27", "Seat Occupied"),
    ("acn_seatbelt_use_code", "eInjury.28", "ACN Incident Seatbelt Use"),
    ("acn_airbag_deployed_code", "eInjury.29", "ACN Incident Airbag Deployed"),
]


# Sanity guards: bindings must cover every column declared on the
# corresponding model/service so we never silently drop a column.
_INJURY_BINDING_COLUMNS = {col for col, _e, _n, _l in _INJURY_BINDING}
assert _INJURY_BINDING_COLUMNS == set(_INJURY_FIELDS), (
    "projection_chart_injury injury binding drift: missing="
    f"{set(_INJURY_FIELDS) - _INJURY_BINDING_COLUMNS}, "
    f"extra={_INJURY_BINDING_COLUMNS - set(_INJURY_FIELDS)}"
)

_ACN_BINDING_COLUMNS = {col for col, _e, _n in _ACN_BINDING}
assert _ACN_BINDING_COLUMNS == set(_ACN_FIELDS), (
    "projection_chart_injury acn binding drift: missing="
    f"{set(_ACN_FIELDS) - _ACN_BINDING_COLUMNS}, "
    f"extra={_ACN_BINDING_COLUMNS - set(_ACN_FIELDS)}"
)


def _fmt_scalar(value: Any) -> str | None:
    """Stringify a scalar element value for ledger storage.

    NEMSIS ledger values are stored as JSON (any type); we prefer the
    canonical string form for primitive codes/numbers/datetimes so
    downstream consumers can rely on a deterministic shape.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _injury_payloads(
    injury: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    injury_id = str(injury["id"])
    for column, element_number, element_name, is_list in _INJURY_BINDING:
        raw = injury.get(column)
        if raw is None:
            continue
        if is_list:
            # 1:M repeating group -- one ledger row per list entry.
            if not isinstance(raw, (list, tuple)):
                # Defensive: coerce a single value into a one-element list.
                raw = [raw]
            for idx, entry in enumerate(raw):
                formatted = _fmt_scalar(entry)
                if formatted is None:
                    continue
                payloads.append(
                    FieldValuePayload(
                        section=SECTION,
                        element_number=element_number,
                        element_name=element_name,
                        value=formatted,
                        group_path="",
                        occurrence_id=f"{injury_id}-{element_number}-{idx}",
                        sequence_index=idx,
                        attributes={},
                        source="manual",
                        validation_status="unvalidated",
                        validation_issues=[],
                        user_id=user_id,
                    )
                )
        else:
            formatted = _fmt_scalar(raw)
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


def _acn_payloads(
    acn: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _ACN_BINDING:
        raw = acn.get(column)
        formatted = _fmt_scalar(raw)
        if formatted is None:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=formatted,
                group_path=ACN_GROUP_PATH,
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


async def project_chart_injury(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted eInjury aggregate to the field-values ledger.

    Reads ``ChartInjury`` (and optional ``ChartInjuryAcn``) for the
    chart, then upserts one ``NemsisFieldValue`` row per populated
    element occurrence. Returns the list of upserted ledger rows for
    observability/testing.

    The projection is a no-op (returns ``[]``) when no ``ChartInjury``
    row exists yet; the gate decides whether absence is acceptable.
    """
    injury = await ChartInjuryService.get_injury(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if injury is None:
        return []

    payloads: list[FieldValuePayload] = _injury_payloads(injury, user_id)

    acn = await ChartInjuryService.get_acn(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if acn is not None:
        payloads.extend(_acn_payloads(acn, user_id))

    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "project_chart_injury",
    "SECTION",
    "ACN_GROUP_PATH",
    "_INJURY_BINDING",
    "_ACN_BINDING",
]
