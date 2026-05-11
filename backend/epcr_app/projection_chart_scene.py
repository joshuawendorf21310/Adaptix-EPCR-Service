"""Projection: :class:`ChartScene` / :class:`ChartSceneOtherAgency`
-> NEMSIS field-value ledger rows.

This module is the bridge between the eScene domain model and the
registry-driven export path. The 1:1 scene metadata produces one
``NemsisFieldValue`` row per populated column; the 1:M other-agencies
group produces a small fanout of ledger entries per row, all sharing
that row's UUID as ``occurrence_id`` so the NEMSIS dataset XML builder
can reassemble each agency as one repeating-group occurrence.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per
the service contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_scene import (
    ChartSceneOtherAgencyService,
    ChartSceneService,
    _AGENCY_FIELDS,
    _SCENE_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eScene"

# NEMSIS group path for the scene GPS lat/long pair (eScene.11).
SCENE_GPS_GROUP_PATH = "eScene.SceneGPSGroup"


# (column_name, element_number, NEMSIS element name, group_path,
#  occurrence_id) — occurrence_id is non-empty only when two columns
# share the same element_number (lat/long both bind to eScene.11) and we
# need to keep them as distinct ledger occurrences within the GPS group.
_SCENE_ELEMENT_BINDING: list[tuple[str, str, str, str, str]] = [
    (
        "first_ems_unit_indicator_code",
        "eScene.01",
        "First EMS Unit on Scene",
        "",
        "",
    ),
    (
        "initial_responder_arrived_at",
        "eScene.05",
        "Date/Time Initial Responder Arrived on Scene",
        "",
        "",
    ),
    (
        "number_of_patients",
        "eScene.06",
        "Number of Patients at Scene",
        "",
        "",
    ),
    (
        "mci_indicator_code",
        "eScene.07",
        "Mass Casualty Incident",
        "",
        "",
    ),
    (
        "mci_triage_classification_code",
        "eScene.08",
        "Triage Classification for MCI Patient",
        "",
        "",
    ),
    (
        "incident_location_type_code",
        "eScene.09",
        "Incident Location Type",
        "",
        "",
    ),
    (
        "incident_facility_code",
        "eScene.10",
        "Incident Facility Code",
        "",
        "",
    ),
    (
        "scene_lat",
        "eScene.11",
        "Scene GPS Location",
        SCENE_GPS_GROUP_PATH,
        "lat",
    ),
    (
        "scene_long",
        "eScene.11",
        "Scene GPS Location",
        SCENE_GPS_GROUP_PATH,
        "long",
    ),
    (
        "scene_usng",
        "eScene.12",
        "Scene US National Grid Coordinates",
        "",
        "",
    ),
    (
        "incident_facility_name",
        "eScene.13",
        "Incident Facility or Location Name",
        "",
        "",
    ),
    (
        "mile_post_or_major_roadway",
        "eScene.14",
        "Mile Post or Major Roadway",
        "",
        "",
    ),
    (
        "incident_street_address",
        "eScene.15",
        "Incident Street Address",
        "",
        "",
    ),
    (
        "incident_apartment",
        "eScene.16",
        "Incident Apartment, Suite, or Room",
        "",
        "",
    ),
    ("incident_city", "eScene.17", "Incident City", "", ""),
    ("incident_state", "eScene.18", "Incident State", "", ""),
    ("incident_zip", "eScene.19", "Incident ZIP Code", "", ""),
    (
        "scene_cross_street",
        "eScene.20",
        "Scene Cross Street or Directions",
        "",
        "",
    ),
    ("incident_county", "eScene.21", "Incident County", "", ""),
    ("incident_country", "eScene.22", "Incident Country", "", ""),
    (
        "incident_census_tract",
        "eScene.23",
        "Incident Census Tract",
        "",
        "",
    ),
]

# (column_name, element_number, NEMSIS element name) for the 1:M
# Other-EMS-or-Public-Safety-Agencies-at-Scene repeating group.
_AGENCY_ELEMENT_BINDING: list[tuple[str, str, str]] = [
    (
        "agency_id",
        "eScene.03",
        "Other EMS or Public Safety Agency ID Number",
    ),
    (
        "other_service_type_code",
        "eScene.04",
        "Type of Other Service at Scene",
    ),
    (
        "first_to_provide_patient_care_indicator",
        "eScene.24",
        "First Other EMS or Public Safety Agency at Scene to Provide Patient Care",
    ),
    (
        "patient_care_handoff_code",
        "eScene.25",
        "Transferred Patient/Care To/From Agency",
    ),
]


# Drift guards: the bindings must cover every NEMSIS-bound column on the
# corresponding model so we never silently drop a column from the export.
_SCENE_BINDING_COLUMNS = {col for col, _e, _n, _g, _o in _SCENE_ELEMENT_BINDING}
assert _SCENE_BINDING_COLUMNS == set(_SCENE_FIELDS), (
    "projection_chart_scene scene binding drift: missing="
    f"{set(_SCENE_FIELDS) - _SCENE_BINDING_COLUMNS}, "
    f"extra={_SCENE_BINDING_COLUMNS - set(_SCENE_FIELDS)}"
)
_AGENCY_BINDING_COLUMNS = {col for col, _e, _n in _AGENCY_ELEMENT_BINDING}
assert _AGENCY_BINDING_COLUMNS == set(_AGENCY_FIELDS), (
    "projection_chart_scene agency binding drift: missing="
    f"{set(_AGENCY_FIELDS) - _AGENCY_BINDING_COLUMNS}, "
    f"extra={_AGENCY_BINDING_COLUMNS - set(_AGENCY_FIELDS)}"
)


def _fmt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _scene_payloads(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for (
        column,
        element_number,
        element_name,
        group_path,
        occurrence_id,
    ) in _SCENE_ELEMENT_BINDING:
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
                # The lat/long pair shares element_number eScene.11 and
                # group_path eScene.SceneGPSGroup; occurrence_id ("lat"
                # vs "long") disambiguates them within the GPS group so
                # the ledger upsert key (element_number, group_path,
                # occurrence_id) keeps them as distinct rows.
                group_path=group_path,
                occurrence_id=occurrence_id,
                sequence_index=0,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


def _agency_payloads(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    occurrence_id = str(record["id"])
    sequence_index = int(record.get("sequence_index") or 0)
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _AGENCY_ELEMENT_BINDING:
        raw = record.get(column)
        if raw is None:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(raw),
                group_path="",
                occurrence_id=occurrence_id,
                sequence_index=sequence_index,
                attributes={},
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_chart_scene(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted scene meta and other-agencies rows to the ledger.

    Reads the 1:1 :class:`ChartScene` row and every non-deleted
    :class:`ChartSceneOtherAgency` row for the chart, then upserts
    one ``NemsisFieldValue`` row per populated scene column plus 2-4
    ledger entries per agency row. Returns the full list of upserted
    ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when neither the scene
    meta nor any agency rows exist yet; the gate decides whether absence
    is acceptable.
    """
    scene_record = await ChartSceneService.get(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    agency_records = await ChartSceneOtherAgencyService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    )

    payloads: list[FieldValuePayload] = []
    if scene_record is not None:
        payloads.extend(_scene_payloads(scene_record, user_id))
    for rec in agency_records:
        payloads.extend(_agency_payloads(rec, user_id))

    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "project_chart_scene",
    "SECTION",
    "SCENE_GPS_GROUP_PATH",
    "_SCENE_ELEMENT_BINDING",
    "_AGENCY_ELEMENT_BINDING",
]
