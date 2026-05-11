"""NEMSIS ePayment service: tenant-scoped persistence for payment + supplies.

Every read and write is filtered by ``tenant_id`` at the SQL layer so no
cross-tenant escape is possible. The service is intentionally thin: it
persists raw scalar codes, dates, JSON arrays, and the Supply Used
repeating-group child rows; conversion to NEMSIS XML is the projection
layer's job (:mod:`projection_chart_payment`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_chart_payment import ChartPayment, ChartPaymentSupplyItem


# Scalar columns on the ePayment 1:1 row.
_SCALAR_FIELDS: tuple[str, ...] = (
    "primary_method_of_payment_code",
    "physician_certification_statement_code",
    "pcs_signed_date",
    "pcs_provider_type_code",
    "pcs_last_name",
    "pcs_first_name",
    "patient_resides_in_service_area_code",
    "insurance_company_id",
    "insurance_company_name",
    "insurance_billing_priority_code",
    "insurance_company_address",
    "insurance_company_city",
    "insurance_company_state",
    "insurance_company_zip",
    "insurance_company_country",
    "insurance_group_id",
    "insurance_policy_id_number",
    "insured_last_name",
    "insured_first_name",
    "insured_middle_name",
    "relationship_to_insured_code",
    "closest_relative_last_name",
    "closest_relative_first_name",
    "closest_relative_middle_name",
    "closest_relative_street_address",
    "closest_relative_city",
    "closest_relative_state",
    "closest_relative_zip",
    "closest_relative_country",
    "closest_relative_phone",
    "closest_relative_relationship_code",
    "patient_employer_name",
    "patient_employer_address",
    "patient_employer_city",
    "patient_employer_state",
    "patient_employer_zip",
    "patient_employer_country",
    "patient_employer_phone",
    "response_urgency_code",
    "patient_transport_assessment_code",
    "specialty_care_transport_provider_code",
    "ambulance_transport_reason_code",
    "round_trip_purpose_description",
    "stretcher_purpose_description",
    "mileage_to_closest_hospital",
    "als_assessment_performed_warranted_code",
    "cms_service_level_code",
    "transport_authorization_code",
    "prior_authorization_code_payer",
    "payer_type_code",
    "insurance_group_name",
    "insurance_company_phone",
    "insured_date_of_birth",
)

# JSON list (1:M repeating-group) columns on the ePayment 1:1 row.
_LIST_FIELDS: tuple[str, ...] = (
    "reason_for_pcs_codes_json",
    "ambulance_conditions_indicator_codes_json",
    "ems_condition_codes_json",
    "cms_transportation_indicator_codes_json",
)

# All updatable domain columns on the parent row.
_PAYMENT_FIELDS: tuple[str, ...] = _SCALAR_FIELDS + _LIST_FIELDS


class ChartPaymentError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"message": message, **extra}


@dataclass
class ChartPaymentPayload:
    """Caller-side payload for upsert.

    ``primary_method_of_payment_code`` is required on the first
    (creation) upsert; subsequent partial upserts may omit it to retain
    the existing value. Every other field is optional; ``None`` retains
    the existing value. Explicit clearing of a single field is exposed
    via :py:meth:`ChartPaymentService.clear_field`.
    """

    # ePayment.01 (Required at creation)
    primary_method_of_payment_code: str | None = None

    # ePayment.02..03
    physician_certification_statement_code: str | None = None
    pcs_signed_date: date | None = None
    # ePayment.04 (1:M)
    reason_for_pcs_codes_json: list[str] | None = None
    # ePayment.05..07
    pcs_provider_type_code: str | None = None
    pcs_last_name: str | None = None
    pcs_first_name: str | None = None
    # ePayment.08
    patient_resides_in_service_area_code: str | None = None
    # ePayment.09..18
    insurance_company_id: str | None = None
    insurance_company_name: str | None = None
    insurance_billing_priority_code: str | None = None
    insurance_company_address: str | None = None
    insurance_company_city: str | None = None
    insurance_company_state: str | None = None
    insurance_company_zip: str | None = None
    insurance_company_country: str | None = None
    insurance_group_id: str | None = None
    insurance_policy_id_number: str | None = None
    # ePayment.19..22
    insured_last_name: str | None = None
    insured_first_name: str | None = None
    insured_middle_name: str | None = None
    relationship_to_insured_code: str | None = None
    # ePayment.23..32
    closest_relative_last_name: str | None = None
    closest_relative_first_name: str | None = None
    closest_relative_middle_name: str | None = None
    closest_relative_street_address: str | None = None
    closest_relative_city: str | None = None
    closest_relative_state: str | None = None
    closest_relative_zip: str | None = None
    closest_relative_country: str | None = None
    closest_relative_phone: str | None = None
    closest_relative_relationship_code: str | None = None
    # ePayment.33..39
    patient_employer_name: str | None = None
    patient_employer_address: str | None = None
    patient_employer_city: str | None = None
    patient_employer_state: str | None = None
    patient_employer_zip: str | None = None
    patient_employer_country: str | None = None
    patient_employer_phone: str | None = None
    # ePayment.40..42
    response_urgency_code: str | None = None
    patient_transport_assessment_code: str | None = None
    specialty_care_transport_provider_code: str | None = None
    # ePayment.44..46
    ambulance_transport_reason_code: str | None = None
    round_trip_purpose_description: str | None = None
    stretcher_purpose_description: str | None = None
    # ePayment.47 (1:M)
    ambulance_conditions_indicator_codes_json: list[str] | None = None
    # ePayment.48..50
    mileage_to_closest_hospital: float | None = None
    als_assessment_performed_warranted_code: str | None = None
    cms_service_level_code: str | None = None
    # ePayment.51..52 (1:M)
    ems_condition_codes_json: list[str] | None = None
    cms_transportation_indicator_codes_json: list[str] | None = None
    # ePayment.53..54
    transport_authorization_code: str | None = None
    prior_authorization_code_payer: str | None = None
    # ePayment.57..60
    payer_type_code: str | None = None
    insurance_group_name: str | None = None
    insurance_company_phone: str | None = None
    insured_date_of_birth: date | None = None


def _fmt_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _serialize_payment(row: ChartPayment) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
    }
    for field_name in _PAYMENT_FIELDS:
        value = getattr(row, field_name)
        if field_name in ("pcs_signed_date", "insured_date_of_birth"):
            out[field_name] = _fmt_date(value)
        else:
            out[field_name] = value
    out.update(
        {
            "version": row.version,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        }
    )
    return out


def _serialize_supply(row: ChartPaymentSupplyItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "chart_id": row.chart_id,
        "supply_item_name": row.supply_item_name,
        "supply_item_quantity": row.supply_item_quantity,
        "sequence_index": row.sequence_index,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


class ChartPaymentService:
    """Tenant-scoped persistence for chart payment + supply items."""

    @staticmethod
    async def get(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise ChartPaymentError(400, "tenant_id is required")
        if not chart_id:
            raise ChartPaymentError(400, "chart_id is required")

        stmt = select(ChartPayment).where(
            ChartPayment.tenant_id == tenant_id,
            ChartPayment.chart_id == chart_id,
            ChartPayment.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None

        payment = _serialize_payment(row)
        supplies = await ChartPaymentService.list_supplies(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        payment["supply_items"] = supplies
        return payment

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        payload: ChartPaymentPayload,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartPaymentError(400, "tenant_id is required")
        if not chart_id:
            raise ChartPaymentError(400, "chart_id is required")

        now = datetime.now(UTC)

        stmt = select(ChartPayment).where(
            ChartPayment.tenant_id == tenant_id,
            ChartPayment.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            # Creation: ePayment.01 is NEMSIS-Required and the column
            # is NOT NULL. Reject the create when the caller omits it.
            if payload.primary_method_of_payment_code is None:
                raise ChartPaymentError(
                    400,
                    "primary_method_of_payment_code is required to create payment",
                    field="primary_method_of_payment_code",
                )
            row = ChartPayment(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                chart_id=chart_id,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for field_name in _PAYMENT_FIELDS:
                value = getattr(payload, field_name)
                setattr(row, field_name, value)
            session.add(row)
        else:
            for field_name in _PAYMENT_FIELDS:
                value = getattr(payload, field_name)
                # ``None`` retains existing value; explicit clearing
                # is a separate endpoint.
                if value is not None:
                    setattr(row, field_name, value)
            row.updated_by_user_id = user_id
            row.updated_at = now
            row.deleted_at = None
            row.version = (row.version or 1) + 1

        await session.flush()
        payment = _serialize_payment(row)
        supplies = await ChartPaymentService.list_supplies(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        payment["supply_items"] = supplies
        return payment

    @staticmethod
    async def clear_field(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        field: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Explicitly set one scalar / list column to NULL.

        Reserved for correction workflows where a previously recorded
        value was wrong and must be erased rather than overwritten.
        Refuses to clear the NEMSIS-Required
        ``primary_method_of_payment_code`` column.
        """
        if field not in _PAYMENT_FIELDS:
            raise ChartPaymentError(
                400,
                "unknown field",
                field=field,
                allowed=list(_PAYMENT_FIELDS),
            )
        if field == "primary_method_of_payment_code":
            raise ChartPaymentError(
                400,
                "primary_method_of_payment_code cannot be cleared; it is NEMSIS-Required",
                field=field,
            )
        stmt = select(ChartPayment).where(
            ChartPayment.tenant_id == tenant_id,
            ChartPayment.chart_id == chart_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ChartPaymentError(
                404, "chart_payment not found", chart_id=chart_id
            )
        setattr(row, field, None)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = user_id
        row.version = (row.version or 1) + 1
        await session.flush()
        payment = _serialize_payment(row)
        supplies = await ChartPaymentService.list_supplies(
            session, tenant_id=tenant_id, chart_id=chart_id
        )
        payment["supply_items"] = supplies
        return payment

    # ---- Supply Used 1:M (ePayment.55/.56) ------------------------------

    @staticmethod
    async def list_supplies(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise ChartPaymentError(400, "tenant_id is required")
        if not chart_id:
            raise ChartPaymentError(400, "chart_id is required")
        stmt = (
            select(ChartPaymentSupplyItem)
            .where(
                ChartPaymentSupplyItem.tenant_id == tenant_id,
                ChartPaymentSupplyItem.chart_id == chart_id,
                ChartPaymentSupplyItem.deleted_at.is_(None),
            )
            .order_by(ChartPaymentSupplyItem.sequence_index, ChartPaymentSupplyItem.id)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialize_supply(r) for r in rows]

    @staticmethod
    async def add_supply(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        supply_item_name: str,
        supply_item_quantity: int,
        sequence_index: int | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartPaymentError(400, "tenant_id is required")
        if not chart_id:
            raise ChartPaymentError(400, "chart_id is required")
        if not supply_item_name or not supply_item_name.strip():
            raise ChartPaymentError(400, "supply_item_name is required")
        if supply_item_quantity is None:
            raise ChartPaymentError(400, "supply_item_quantity is required")
        if not isinstance(supply_item_quantity, int) or supply_item_quantity < 0:
            raise ChartPaymentError(
                400,
                "supply_item_quantity must be a non-negative integer",
                received=supply_item_quantity,
            )

        # Reject duplicate (name) for this chart — the unique constraint
        # would raise anyway, but we surface a clean 409.
        dup_stmt = select(ChartPaymentSupplyItem).where(
            ChartPaymentSupplyItem.tenant_id == tenant_id,
            ChartPaymentSupplyItem.chart_id == chart_id,
            ChartPaymentSupplyItem.supply_item_name == supply_item_name,
            ChartPaymentSupplyItem.deleted_at.is_(None),
        )
        dup = (await session.execute(dup_stmt)).scalar_one_or_none()
        if dup is not None:
            raise ChartPaymentError(
                409,
                "supply_item already exists for this chart",
                supply_item_name=supply_item_name,
            )

        # Auto-assign next sequence_index if caller omitted it.
        if sequence_index is None:
            existing = await ChartPaymentService.list_supplies(
                session, tenant_id=tenant_id, chart_id=chart_id
            )
            sequence_index = (
                max((s["sequence_index"] for s in existing), default=-1) + 1
            )

        now = datetime.now(UTC)
        row = ChartPaymentSupplyItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            chart_id=chart_id,
            supply_item_name=supply_item_name,
            supply_item_quantity=supply_item_quantity,
            sequence_index=sequence_index,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        session.add(row)
        await session.flush()
        return _serialize_supply(row)

    @staticmethod
    async def delete_supply(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        supply_id: str,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise ChartPaymentError(400, "tenant_id is required")
        if not chart_id:
            raise ChartPaymentError(400, "chart_id is required")
        if not supply_id:
            raise ChartPaymentError(400, "supply_id is required")

        stmt = select(ChartPaymentSupplyItem).where(
            ChartPaymentSupplyItem.tenant_id == tenant_id,
            ChartPaymentSupplyItem.chart_id == chart_id,
            ChartPaymentSupplyItem.id == supply_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None or row.deleted_at is not None:
            raise ChartPaymentError(
                404, "supply_item not found", supply_id=supply_id
            )
        now = datetime.now(UTC)
        row.deleted_at = now
        row.updated_at = now
        row.version = (row.version or 1) + 1
        await session.flush()
        return _serialize_supply(row)


__all__ = [
    "ChartPaymentService",
    "ChartPaymentPayload",
    "ChartPaymentError",
    "_PAYMENT_FIELDS",
    "_SCALAR_FIELDS",
    "_LIST_FIELDS",
]
