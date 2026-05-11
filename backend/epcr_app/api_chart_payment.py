"""NEMSIS ePayment API router.

Tenant-scoped HTTP surface for the chart payment section
(ePayment.01..60, excluding the v3.5.1-undefined .43). The Supply Used
repeating group (ePayment.55/.56) is exposed as a 1:M sub-resource at
``/supplies``. Every route enforces real authentication via
``get_current_user`` and uses a real database session via
``get_session``. Tenant isolation is delegated to the service layer and
verified at the SQL level.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_payment import project_chart_payment
from epcr_app.services_chart_payment import (
    ChartPaymentError,
    ChartPaymentPayload,
    ChartPaymentService,
    _PAYMENT_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/payment",
    tags=["nemsis-epayment"],
)


class ChartPaymentRequest(BaseModel):
    """Caller request body for PUT /payment.

    ``primary_method_of_payment_code`` must be supplied the first time
    payment is recorded (NEMSIS-Required, NOT NULL in storage).
    Every other field is optional; omitting a field retains its
    current value. Use DELETE on the per-field path to explicitly clear.
    """

    model_config = ConfigDict(extra="forbid")

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


class ChartPaymentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class SupplyItemRequest(BaseModel):
    """Caller request body for POST /payment/supplies."""

    model_config = ConfigDict(extra="forbid")

    supply_item_name: str = Field(..., min_length=1, max_length=255)
    supply_item_quantity: int = Field(..., ge=0)
    sequence_index: int | None = Field(default=None, ge=0)


class SupplyItemResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartPaymentRequest) -> ChartPaymentPayload:
    return ChartPaymentPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=ChartPaymentResponse)
async def get_chart_payment(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart payment record (with embedded supply items) or 404."""
    try:
        record = await ChartPaymentService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartPaymentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "chart_payment not recorded",
                "chart_id": chart_id,
            },
        )
    return record


@router.put("", response_model=ChartPaymentResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_payment(
    chart_id: str,
    body: ChartPaymentRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart payment scalars / lists. Returns the persisted record.

    Side effect: after writing the domain row, projects the payment +
    supply items into the registry-driven NEMSIS field-values ledger so
    the dataset XML builder can emit it on export.
    """
    try:
        record = await ChartPaymentService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_payment(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartPaymentError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.post(
    "/supplies",
    response_model=SupplyItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_chart_payment_supply(
    chart_id: str,
    body: SupplyItemRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one Supply Used row (ePayment.55 + ePayment.56 pair)."""
    try:
        record = await ChartPaymentService.add_supply(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            supply_item_name=body.supply_item_name,
            supply_item_quantity=body.supply_item_quantity,
            sequence_index=body.sequence_index,
        )
        await project_chart_payment(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartPaymentError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/supplies/{supply_id}", response_model=SupplyItemResponse)
async def delete_chart_payment_supply(
    chart_id: str,
    supply_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one Supply Used row."""
    try:
        record = await ChartPaymentService.delete_supply(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            supply_id=supply_id,
        )
        await project_chart_payment(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartPaymentError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartPaymentResponse)
async def clear_chart_payment_field(
    chart_id: str,
    field_name: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific payment scalar/list field to NULL.

    Reserved for correction workflows where a previously recorded
    value must be erased rather than overwritten. The
    NEMSIS-Required ``primary_method_of_payment_code`` cannot be
    cleared. The audit trail lives in chart versioning.
    """
    if field_name not in _PAYMENT_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown field",
                "field": field_name,
                "allowed": list(_PAYMENT_FIELDS),
            },
        )
    try:
        record = await ChartPaymentService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            user_id=str(user.user_id),
        )
        await project_chart_payment(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartPaymentError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
