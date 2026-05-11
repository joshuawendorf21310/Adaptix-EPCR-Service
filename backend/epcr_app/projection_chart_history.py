"""Projection: eHistory aggregate -> NEMSIS field-value ledger rows.

This module bridges the eHistory domain model (one meta row + four
1:M child collections) and the registry-driven export path. Every
populated value produces one ``NemsisFieldValue`` row whose
``element_number`` is the NEMSIS v3.5.1 canonical element ID and whose
``value`` is the serialized representation the NEMSIS schema expects.
Absent columns are NOT projected (they remain absent from the export);
the chart-finalization gate is responsible for blocking finalization
when a Required-at-National element is missing.

NEMSIS element bindings (canonical names from the v3.5.1 data
dictionary):

    eHistory.01  Barriers to Care                              (1:M, meta JSON)
    eHistory.02  Practitioner Last Name                        (meta scalar)
    eHistory.03  Practitioner First Name                       (meta scalar)
    eHistory.04  Practitioner Middle Initial/Name              (meta scalar)
    eHistory.05  Advance Directives                            (1:M, meta JSON)
    eHistory.06  Medication Allergies                          (1:M, allergies)
    eHistory.07  Environmental/Food Allergies                  (1:M, allergies)
    eHistory.08  Medical/Surgical History                      (1:M, surgical)
    eHistory.09  Medical History Obtained From                 (1:M, meta JSON)
    eHistory.10  Immunizations                                 (1:M, immunizations)
    eHistory.11  Immunization Year                             (1:M, immunizations)
    eHistory.12  Current Medications                           (1:M, meds)
    eHistory.13  Current Medication Dose                       (1:M, meds)
    eHistory.14  Current Medication Dosage Units               (1:M, meds)
    eHistory.15  Current Medication Administration Route       (1:M, meds)
    eHistory.16  Information Source Code                       (meta scalar)
    eHistory.17  Alcohol/Drug Use Indicators                   (1:M, meta JSON)
    eHistory.18  Pregnancy                                     (meta scalar)
    eHistory.19  Last Oral Intake Date/Time                    (meta scalar)
    eHistory.20  Current Medication Administered Frequency     (1:M, meds)

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per
the service contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_history import (
    ChartHistoryAllergyService,
    ChartHistoryCurrentMedicationService,
    ChartHistoryImmunizationService,
    ChartHistoryMetaService,
    ChartHistorySurgicalService,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "eHistory"


# Meta single-valued bindings: (column, element_number, element_name)
_META_SCALAR_BINDING: list[tuple[str, str, str]] = [
    ("practitioner_last_name", "eHistory.02", "Practitioner Last Name"),
    ("practitioner_first_name", "eHistory.03", "Practitioner First Name"),
    ("practitioner_middle_name", "eHistory.04", "Practitioner Middle Initial/Name"),
    ("emergency_information_form_code", "eHistory.16", "Information Source Code"),
    ("pregnancy_code", "eHistory.18", "Pregnancy"),
    ("last_oral_intake_at", "eHistory.19", "Last Oral Intake Date/Time"),
]


# Meta 1:M JSON-list bindings: (column, element_number, element_name)
_META_LIST_BINDING: list[tuple[str, str, str]] = [
    ("barriers_to_care_codes_json", "eHistory.01", "Barriers to Care"),
    ("advance_directives_codes_json", "eHistory.05", "Advance Directives"),
    (
        "medical_history_obtained_from_codes_json",
        "eHistory.09",
        "Medical History Obtained From",
    ),
    ("alcohol_drug_use_codes_json", "eHistory.17", "Alcohol/Drug Use Indicators"),
]


# Current medication bindings (per row): (column, element_number, element_name)
_MEDICATION_BINDING: list[tuple[str, str, str]] = [
    ("drug_code", "eHistory.12", "Current Medications"),
    ("dose_value", "eHistory.13", "Current Medication Dose"),
    ("dose_unit_code", "eHistory.14", "Current Medication Dosage Units"),
    ("route_code", "eHistory.15", "Current Medication Administration Route"),
    (
        "frequency_code",
        "eHistory.20",
        "Current Medication Administered Frequency",
    ),
]


# Allergy element discriminator
_ALLERGY_KIND_BINDING: dict[str, tuple[str, str, str]] = {
    # kind -> (element_number, element_name, group_path)
    "medication": (
        "eHistory.06",
        "Medication Allergies",
        "eHistory.MedicationAllergyGroup",
    ),
    "environmental_food": (
        "eHistory.07",
        "Environmental/Food Allergies",
        "eHistory.EnvironmentalFoodAllergyGroup",
    ),
}


_SURGICAL_ELEMENT = ("eHistory.08", "Medical/Surgical History")
_IMMUNIZATION_TYPE_ELEMENT = ("eHistory.10", "Immunizations")
_IMMUNIZATION_YEAR_ELEMENT = ("eHistory.11", "Immunization Year")
_CURRENT_MED_GROUP = "eHistory.CurrentMedicationGroup"


def _fmt_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _meta_payloads(meta: dict[str, Any], user_id: str | None) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    meta_id = str(meta["id"])

    # Single-valued elements
    for column, element_number, element_name in _META_SCALAR_BINDING:
        raw = meta.get(column)
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

    # 1:M JSON-list elements: one ledger row per list entry
    for column, element_number, element_name in _META_LIST_BINDING:
        raw_list = meta.get(column)
        if not raw_list:
            continue
        if not isinstance(raw_list, list):
            # Defensive: skip malformed payloads rather than crashing the export.
            continue
        for idx, entry in enumerate(raw_list):
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
                    occurrence_id=f"{meta_id}-{element_number}-{idx}",
                    sequence_index=idx,
                    attributes={},
                    source="manual",
                    validation_status="unvalidated",
                    validation_issues=[],
                    user_id=user_id,
                )
            )
    return payloads


def _allergy_payloads(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    kind = record.get("allergy_kind")
    binding = _ALLERGY_KIND_BINDING.get(str(kind) if kind else "")
    if binding is None:
        return []
    element_number, element_name, group_path = binding
    code = record.get("allergy_code")
    if code is None:
        return []
    occurrence_id = str(record["id"])
    sequence_index = int(record.get("sequence_index") or 0)
    return [
        FieldValuePayload(
            section=SECTION,
            element_number=element_number,
            element_name=element_name,
            value=str(code),
            group_path=group_path,
            occurrence_id=occurrence_id,
            sequence_index=sequence_index,
            attributes={},
            source="manual",
            validation_status="unvalidated",
            validation_issues=[],
            user_id=user_id,
        )
    ]


def _surgical_payloads(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    code = record.get("condition_code")
    if code is None:
        return []
    element_number, element_name = _SURGICAL_ELEMENT
    occurrence_id = str(record["id"])
    sequence_index = int(record.get("sequence_index") or 0)
    return [
        FieldValuePayload(
            section=SECTION,
            element_number=element_number,
            element_name=element_name,
            value=str(code),
            group_path="",
            occurrence_id=occurrence_id,
            sequence_index=sequence_index,
            attributes={},
            source="manual",
            validation_status="unvalidated",
            validation_issues=[],
            user_id=user_id,
        )
    ]


def _medication_payloads(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    occurrence_id = str(record["id"])
    sequence_index = int(record.get("sequence_index") or 0)
    payloads: list[FieldValuePayload] = []
    for column, element_number, element_name in _MEDICATION_BINDING:
        raw = record.get(column)
        if raw is None:
            continue
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(raw),
                group_path=_CURRENT_MED_GROUP,
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


def _immunization_payloads(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    occurrence_id = str(record["id"])
    sequence_index = int(record.get("sequence_index") or 0)
    payloads: list[FieldValuePayload] = []

    type_code = record.get("immunization_type_code")
    if type_code is not None:
        element_number, element_name = _IMMUNIZATION_TYPE_ELEMENT
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(type_code),
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

    year = record.get("immunization_year")
    if year is not None:
        element_number, element_name = _IMMUNIZATION_YEAR_ELEMENT
        payloads.append(
            FieldValuePayload(
                section=SECTION,
                element_number=element_number,
                element_name=element_name,
                value=str(year),
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


async def project_chart_history(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted eHistory aggregate to the field-values ledger.

    Reads the meta row plus all four 1:M child collections, then
    upserts one ``NemsisFieldValue`` row per populated value. Returns
    the list of upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when nothing has been
    recorded yet; the gate decides whether absence is acceptable.
    """
    payloads: list[FieldValuePayload] = []

    meta = await ChartHistoryMetaService.get(
        session, tenant_id=tenant_id, chart_id=chart_id
    )
    if meta is not None:
        payloads.extend(_meta_payloads(meta, user_id))

    for record in await ChartHistoryAllergyService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    ):
        payloads.extend(_allergy_payloads(record, user_id))

    for record in await ChartHistorySurgicalService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    ):
        payloads.extend(_surgical_payloads(record, user_id))

    for record in await ChartHistoryCurrentMedicationService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    ):
        payloads.extend(_medication_payloads(record, user_id))

    for record in await ChartHistoryImmunizationService.list_for_chart(
        session, tenant_id=tenant_id, chart_id=chart_id
    ):
        payloads.extend(_immunization_payloads(record, user_id))

    if not payloads:
        return []
    return await NemsisFieldValueService.bulk_save(
        session, tenant_id=tenant_id, chart_id=chart_id, payloads=payloads
    )


__all__ = [
    "SECTION",
    "_ALLERGY_KIND_BINDING",
    "_CURRENT_MED_GROUP",
    "_IMMUNIZATION_TYPE_ELEMENT",
    "_IMMUNIZATION_YEAR_ELEMENT",
    "_MEDICATION_BINDING",
    "_META_LIST_BINDING",
    "_META_SCALAR_BINDING",
    "_SURGICAL_ELEMENT",
    "project_chart_history",
]
