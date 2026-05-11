"""Projection: ePatient extension aggregates -> NEMSIS field-value ledger.

This module is the bridge between the ePatient extension domain models
and the registry-driven export path. It projects four sources:

* scalar 1:1 extension  -> one ledger row per populated scalar column.
* home address 1:1      -> one ledger row per populated address column,
                           inside ``group_path="ePatient.PatientHomeAddressGroup"``.
* races 1:M             -> one ledger row per race (ePatient.14), with
                           ``occurrence_id = race row.id``.
* languages 1:M         -> one ledger row per language (ePatient.24),
                           with ``occurrence_id = language row.id``.
* phones 1:M            -> one ledger row per phone (ePatient.18), with
                           ``occurrence_id = phone row.id`` and
                           ``attributes["type"] = phone_type_code`` if set.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per the
service contract.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)
from epcr_app.services_patient_profile_ext import (
    PatientHomeAddressService,
    PatientLanguageService,
    PatientPhoneNumberService,
    PatientProfileExtService,
    PatientRaceService,
    _ADDRESS_FIELDS,
    _SCALAR_FIELDS,
)


SECTION = "ePatient"
HOME_ADDRESS_GROUP = "ePatient.PatientHomeAddressGroup"


# (column_name, element_number, NEMSIS element name) — scalar 1:1 extension.
_SCALAR_BINDING: list[tuple[str, str, str]] = [
    ("ems_patient_id", "ePatient.01", "EMS Patient ID"),
    ("country_of_residence_code", "ePatient.10", "Patient's Country of Residence"),
    ("patient_home_census_tract", "ePatient.11", "Patient Home Census Tract"),
    ("ssn_hash", "ePatient.12", "Social Security Number"),
    ("age_units_code", "ePatient.16", "Age Units"),
    ("email_address", "ePatient.19", "Patient's Email Address"),
    ("driver_license_state", "ePatient.20", "State Issuing Driver's License"),
    ("driver_license_number", "ePatient.21", "Driver's License Number"),
    ("alternate_home_residence_code", "ePatient.22", "Alternate Home Residence"),
    ("name_suffix", "ePatient.23", "Name Suffix"),
    ("sex_nemsis_code", "ePatient.25", "Sex"),
]

# (column_name, element_number, NEMSIS element name) — Patient's Home Address group.
_ADDRESS_BINDING: list[tuple[str, str, str]] = [
    ("home_street_address", "ePatient.05", "Patient's Home Address"),
    ("home_city", "ePatient.06", "Patient's Home City"),
    ("home_county", "ePatient.07", "Patient's Home County"),
    ("home_state", "ePatient.08", "Patient's Home State"),
    ("home_zip", "ePatient.09", "Patient's Home ZIP Code"),
]

RACE_ELEMENT_NUMBER = "ePatient.14"
RACE_ELEMENT_NAME = "Race"
LANGUAGE_ELEMENT_NUMBER = "ePatient.24"
LANGUAGE_ELEMENT_NAME = "Preferred Language(s)"
PHONE_ELEMENT_NUMBER = "ePatient.18"
PHONE_ELEMENT_NAME = "Patient's Phone Number"

# Drift guards: ensure column lists from the service layer match the
# projection bindings, so we never silently drop or leak a column.
_SCALAR_BINDING_COLS = {col for col, _, _ in _SCALAR_BINDING}
assert _SCALAR_BINDING_COLS == set(_SCALAR_FIELDS), (
    "projection_patient_profile_ext scalar binding drift: missing="
    f"{set(_SCALAR_FIELDS) - _SCALAR_BINDING_COLS}, "
    f"extra={_SCALAR_BINDING_COLS - set(_SCALAR_FIELDS)}"
)
_ADDR_BINDING_COLS = {col for col, _, _ in _ADDRESS_BINDING}
assert _ADDR_BINDING_COLS == set(_ADDRESS_FIELDS), (
    "projection_patient_profile_ext address binding drift: missing="
    f"{set(_ADDRESS_FIELDS) - _ADDR_BINDING_COLS}, "
    f"extra={_ADDR_BINDING_COLS - set(_ADDRESS_FIELDS)}"
)


def _scalar_payloads(record: dict[str, Any], user_id: str | None) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _SCALAR_BINDING:
        value = record.get(column)
        if value is None or value == "":
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(value),
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


def _address_payloads(record: dict[str, Any], user_id: str | None) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _ADDRESS_BINDING:
        value = record.get(column)
        if value is None or value == "":
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(value),
                group_path=HOME_ADDRESS_GROUP,
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


def _race_payloads(rows: list[dict[str, Any]], user_id: str | None) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for row in rows:
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=RACE_ELEMENT_NUMBER,
                element_name=RACE_ELEMENT_NAME,
                value=str(row["race_code"]),
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


def _language_payloads(
    rows: list[dict[str, Any]], user_id: str | None
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for row in rows:
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=LANGUAGE_ELEMENT_NUMBER,
                element_name=LANGUAGE_ELEMENT_NAME,
                value=str(row["language_code"]),
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


def _phone_payloads(rows: list[dict[str, Any]], user_id: str | None) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    for row in rows:
        attributes: dict[str, Any] = {}
        ptype = row.get("phone_type_code")
        if ptype is not None:
            attributes["type"] = ptype
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=PHONE_ELEMENT_NUMBER,
                element_name=PHONE_ELEMENT_NAME,
                value=str(row["phone_number"]),
                group_path="",
                occurrence_id=str(row["id"]),
                sequence_index=int(row.get("sequence_index") or 0),
                attributes=attributes,
                source="manual",
                validation_status="unvalidated",
                validation_issues=[],
                user_id=user_id,
            )
        )
    return payloads


async def project_patient_profile_ext(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project all ePatient-extension aggregates to the field-values ledger.

    Reads each aggregate (scalar ext, home address, races, languages,
    phones), then upserts one or more ``NemsisFieldValue`` rows. Returns
    the combined list of upserted ledger rows for observability/testing.

    No-op (``[]``) when none of the aggregates have rows yet.
    """
    payloads: list[FieldValuePayload] = []

    scalar = await PatientProfileExtService.get(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if scalar is not None:
        payloads.extend(_scalar_payloads(scalar, user_id))

    address = await PatientHomeAddressService.get(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if address is not None:
        payloads.extend(_address_payloads(address, user_id))

    races = await PatientRaceService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    payloads.extend(_race_payloads(races, user_id))

    languages = await PatientLanguageService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    payloads.extend(_language_payloads(languages, user_id))

    phones = await PatientPhoneNumberService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    payloads.extend(_phone_payloads(phones, user_id))

    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "project_patient_profile_ext",
    "SECTION",
    "HOME_ADDRESS_GROUP",
    "_SCALAR_BINDING",
    "_ADDRESS_BINDING",
    "RACE_ELEMENT_NUMBER",
    "LANGUAGE_ELEMENT_NUMBER",
    "PHONE_ELEMENT_NUMBER",
]
