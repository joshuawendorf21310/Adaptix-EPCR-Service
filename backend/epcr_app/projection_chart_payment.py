"""Projection: :class:`ChartPayment` -> NEMSIS field-value ledger rows.

Maps the ePayment 1:1 row plus its Supply Used 1:M child rows into the
registry-driven ``NemsisFieldValue`` ledger. Scalar columns produce one
ledger row per populated column. JSON-list columns
(``*_codes_json``) expand into one ledger row per list entry, with
``occurrence_id`` derived from the parent payment row's UUID and the
element number so re-projection is idempotent and each repeating-group
occurrence is uniquely addressable.

The Supply Used repeating group (ePayment.55/.56) expands each child
row into two ledger entries (name + quantity) sharing the child row's
UUID as ``occurrence_id`` so the paired group rebuilds correctly on
export. ``group_path`` for those entries is ``ePayment.SupplyUsedGroup``.

Columns / lists / supplies that are ``None`` or empty are NOT projected
— they remain absent from the export; the chart-finalization gate is
responsible for blocking finalization when a Required-at-National value
is missing.

The projector is idempotent: invoking it multiple times for the same
chart upserts by ``(element_number, group_path, occurrence_id)`` per
the service contract.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.services_chart_payment import (
    ChartPaymentService,
    _LIST_FIELDS,
    _PAYMENT_FIELDS,
    _SCALAR_FIELDS,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)


SECTION = "ePayment"
SUPPLY_USED_GROUP = "ePayment.SupplyUsedGroup"


# (column_name, element_number, NEMSIS element name) for scalar columns.
_SCALAR_BINDING: list[tuple[str, str, str]] = [
    ("primary_method_of_payment_code", "ePayment.01", "Primary Method of Payment"),
    (
        "physician_certification_statement_code",
        "ePayment.02",
        "Physician Certification Statement",
    ),
    ("pcs_signed_date", "ePayment.03", "PCS Signed Date"),
    ("pcs_provider_type_code", "ePayment.05", "PCS Provider Type"),
    ("pcs_last_name", "ePayment.06", "PCS Last Name"),
    ("pcs_first_name", "ePayment.07", "PCS First Name"),
    (
        "patient_resides_in_service_area_code",
        "ePayment.08",
        "Patient Resides in Service Area",
    ),
    ("insurance_company_id", "ePayment.09", "Insurance Company ID"),
    ("insurance_company_name", "ePayment.10", "Insurance Company Name"),
    (
        "insurance_billing_priority_code",
        "ePayment.11",
        "Insurance Billing Priority",
    ),
    ("insurance_company_address", "ePayment.12", "Insurance Company Address"),
    ("insurance_company_city", "ePayment.13", "Insurance Company City"),
    ("insurance_company_state", "ePayment.14", "Insurance Company State"),
    ("insurance_company_zip", "ePayment.15", "Insurance Company ZIP"),
    ("insurance_company_country", "ePayment.16", "Insurance Company Country"),
    ("insurance_group_id", "ePayment.17", "Insurance Group ID"),
    ("insurance_policy_id_number", "ePayment.18", "Insurance Policy ID Number"),
    ("insured_last_name", "ePayment.19", "Insured's Last Name"),
    ("insured_first_name", "ePayment.20", "Insured's First Name"),
    ("insured_middle_name", "ePayment.21", "Insured's Middle Initial/Name"),
    (
        "relationship_to_insured_code",
        "ePayment.22",
        "Relationship to the Insured",
    ),
    (
        "closest_relative_last_name",
        "ePayment.23",
        "Closest Relative/Guardian Last Name",
    ),
    (
        "closest_relative_first_name",
        "ePayment.24",
        "Closest Relative/Guardian First Name",
    ),
    (
        "closest_relative_middle_name",
        "ePayment.25",
        "Closest Relative/Guardian Middle Initial/Name",
    ),
    (
        "closest_relative_street_address",
        "ePayment.26",
        "Closest Relative/Guardian Street Address",
    ),
    (
        "closest_relative_city",
        "ePayment.27",
        "Closest Relative/Guardian City",
    ),
    (
        "closest_relative_state",
        "ePayment.28",
        "Closest Relative/Guardian State",
    ),
    ("closest_relative_zip", "ePayment.29", "Closest Relative/Guardian ZIP"),
    (
        "closest_relative_country",
        "ePayment.30",
        "Closest Relative/Guardian Country",
    ),
    (
        "closest_relative_phone",
        "ePayment.31",
        "Closest Relative/Guardian Phone Number",
    ),
    (
        "closest_relative_relationship_code",
        "ePayment.32",
        "Closest Relative/Guardian Relationship",
    ),
    ("patient_employer_name", "ePayment.33", "Patient's Employer Name"),
    ("patient_employer_address", "ePayment.34", "Patient's Employer Address"),
    ("patient_employer_city", "ePayment.35", "Patient's Employer City"),
    ("patient_employer_state", "ePayment.36", "Patient's Employer State"),
    ("patient_employer_zip", "ePayment.37", "Patient's Employer ZIP"),
    ("patient_employer_country", "ePayment.38", "Patient's Employer Country"),
    ("patient_employer_phone", "ePayment.39", "Patient's Employer Phone"),
    ("response_urgency_code", "ePayment.40", "Response Urgency"),
    (
        "patient_transport_assessment_code",
        "ePayment.41",
        "Patient Transport Assessment",
    ),
    (
        "specialty_care_transport_provider_code",
        "ePayment.42",
        "Specialty Care Transport (SCT) Provider",
    ),
    (
        "ambulance_transport_reason_code",
        "ePayment.44",
        "Ambulance Transport Reason",
    ),
    (
        "round_trip_purpose_description",
        "ePayment.45",
        "Round Trip Purpose Description",
    ),
    (
        "stretcher_purpose_description",
        "ePayment.46",
        "Stretcher Purpose Description",
    ),
    (
        "mileage_to_closest_hospital",
        "ePayment.48",
        "Mileage to Closest Appropriate Hospital",
    ),
    (
        "als_assessment_performed_warranted_code",
        "ePayment.49",
        "ALS Assessment Performed/Warranted",
    ),
    ("cms_service_level_code", "ePayment.50", "CMS Service Level"),
    (
        "transport_authorization_code",
        "ePayment.53",
        "Transport Authorization Code",
    ),
    (
        "prior_authorization_code_payer",
        "ePayment.54",
        "Prior Authorization Code from Payer",
    ),
    ("payer_type_code", "ePayment.57", "Payer Type"),
    ("insurance_group_name", "ePayment.58", "Insurance Group Name"),
    ("insurance_company_phone", "ePayment.59", "Insurance Company Phone"),
    ("insured_date_of_birth", "ePayment.60", "Insured's Date of Birth"),
]

# (column_name, element_number, NEMSIS element name) for 1:M list columns.
_LIST_BINDING: list[tuple[str, str, str]] = [
    ("reason_for_pcs_codes_json", "ePayment.04", "Reason for PCS"),
    (
        "ambulance_conditions_indicator_codes_json",
        "ePayment.47",
        "Ambulance Conditions Indicator",
    ),
    ("ems_condition_codes_json", "ePayment.51", "EMS Condition Codes"),
    (
        "cms_transportation_indicator_codes_json",
        "ePayment.52",
        "CMS Transportation Indicator Codes",
    ),
]

_ELEMENT_BINDING: list[tuple[str, str, str]] = _SCALAR_BINDING + _LIST_BINDING


# Sanity guards: bindings must cover every column declared on the model
# so we never silently drop a column from the export.
_BINDING_COLUMNS = {column for column, _, _ in _ELEMENT_BINDING}
assert _BINDING_COLUMNS == set(_PAYMENT_FIELDS), (
    "projection_chart_payment binding drift: missing="
    f"{set(_PAYMENT_FIELDS) - _BINDING_COLUMNS}, "
    f"extra={_BINDING_COLUMNS - set(_PAYMENT_FIELDS)}"
)
_SCALAR_BINDING_COLUMNS = {column for column, _, _ in _SCALAR_BINDING}
_LIST_BINDING_COLUMNS = {column for column, _, _ in _LIST_BINDING}
assert _SCALAR_BINDING_COLUMNS == set(_SCALAR_FIELDS), (
    "projection_chart_payment scalar drift"
)
assert _LIST_BINDING_COLUMNS == set(_LIST_FIELDS), (
    "projection_chart_payment list drift"
)


def _fmt_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        # NEMSIS code-list values: serialize via str()
        return str(value)
    if isinstance(value, str):
        return value
    return str(value)


def _payloads_from_record(
    record: dict[str, Any], user_id: str | None
) -> list[FieldValuePayload]:
    payloads: list[FieldValuePayload] = []
    payment_id = str(record.get("id") or "")

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
                    occurrence_id=f"{payment_id}-{element_number}-{idx}",
                    sequence_index=idx,
                    attributes={},
                    source="manual",
                    validation_status="unvalidated",
                    validation_issues=[],
                    user_id=user_id,
                )
            )

    # Supply Used repeating group (ePayment.55 name + ePayment.56 qty).
    supplies = record.get("supply_items") or []
    for supply in supplies:
        if not isinstance(supply, dict):
            continue
        if supply.get("deleted_at"):
            # Soft-deleted rows are not projected.
            continue
        row_id = str(supply.get("id") or "")
        name = supply.get("supply_item_name")
        qty = supply.get("supply_item_quantity")
        seq = supply.get("sequence_index", 0) or 0
        name_formatted = _fmt_scalar(name)
        if name_formatted:
            payloads.append(
                FieldValuePayload(
                    section=SECTION,
                    element_number="ePayment.55",
                    element_name="Supply Item Used",
                    value=name_formatted,
                    group_path=SUPPLY_USED_GROUP,
                    occurrence_id=row_id,
                    sequence_index=seq,
                    attributes={},
                    source="manual",
                    validation_status="unvalidated",
                    validation_issues=[],
                    user_id=user_id,
                )
            )
        if qty is not None:
            qty_formatted = _fmt_scalar(qty)
            if qty_formatted is not None and qty_formatted != "":
                payloads.append(
                    FieldValuePayload(
                        section=SECTION,
                        element_number="ePayment.56",
                        element_name="Quantity of Supply Item Used",
                        value=qty_formatted,
                        group_path=SUPPLY_USED_GROUP,
                        occurrence_id=row_id,
                        sequence_index=seq,
                        attributes={},
                        source="manual",
                        validation_status="unvalidated",
                        validation_issues=[],
                        user_id=user_id,
                    )
                )

    return payloads


async def project_chart_payment(
    session: AsyncSession,
    *,
    tenant_id: str,
    chart_id: str,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Project the persisted :class:`ChartPayment` row to the field-values ledger.

    Reads ``ChartPayment`` (and its Supply Used child rows) for the
    given chart, then upserts one ``NemsisFieldValue`` row per
    populated scalar column, plus one row per JSON-list entry, plus
    two rows per supply item (name + quantity). Returns the list of
    upserted ledger rows for observability/testing.

    The projection is a no-op (returns ``[]``) when no
    ``ChartPayment`` row exists yet; the gate decides whether absence
    is acceptable.
    """
    record = await ChartPaymentService.get(
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
    "project_chart_payment",
    "SECTION",
    "SUPPLY_USED_GROUP",
    "_ELEMENT_BINDING",
    "_SCALAR_BINDING",
    "_LIST_BINDING",
]
