"""NEMSIS eOutcome API router.

Tenant-scoped HTTP surface for the chart hospital outcome linkage
(eOutcome.01..24). Every route enforces real authentication via
``get_current_user`` and uses a real database session via
``get_session``. Tenant isolation is delegated to the service layer
and verified at the SQL level.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_outcome import project_chart_outcome
from epcr_app.services_chart_outcome import (
    ChartOutcomeError,
    ChartOutcomePayload,
    ChartOutcomeService,
    _OUTCOME_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/outcome",
    tags=["nemsis-eoutcome"],
)


class ChartOutcomeRequest(BaseModel):
    """Caller request body for PUT /outcome.

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE on the per-field path to explicitly clear.
    """

    model_config = ConfigDict(extra="forbid")

    emergency_department_disposition_code: str | None = None
    hospital_disposition_code: str | None = None
    emergency_department_diagnosis_codes_json: list[str] | None = None
    hospital_admission_diagnosis_codes_json: list[str] | None = None
    hospital_procedures_performed_codes_json: list[str] | None = None
    trauma_registry_incident_id: str | None = None
    hospital_outcome_at_discharge_code: str | None = None
    patient_disposition_from_emergency_department_at: str | None = None
    emergency_department_arrival_at: datetime | None = None
    emergency_department_admit_at: datetime | None = None
    emergency_department_discharge_at: datetime | None = None
    hospital_admit_at: datetime | None = None
    hospital_discharge_at: datetime | None = None
    icu_admit_at: datetime | None = None
    icu_discharge_at: datetime | None = None
    hospital_length_of_stay_days: int | None = None
    icu_length_of_stay_days: int | None = None
    final_patient_acuity_code: str | None = None
    cause_of_death_codes_json: list[str] | None = None
    date_of_death: datetime | None = None
    medical_record_number: str | None = None
    receiving_facility_record_number: str | None = None
    referred_to_facility_code: str | None = None
    referred_to_facility_name: str | None = None


class ChartOutcomeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartOutcomeRequest) -> ChartOutcomePayload:
    return ChartOutcomePayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=ChartOutcomeResponse)
async def get_chart_outcome(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart outcome record or 404 if not yet recorded."""
    try:
        record = await ChartOutcomeService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartOutcomeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_outcome not recorded", "chart_id": chart_id},
        )
    return record


@router.put("", response_model=ChartOutcomeResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_outcome(
    chart_id: str,
    body: ChartOutcomeRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart outcome. Returns the persisted record.

    Side effect: after writing the domain row, projects the outcome
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        record = await ChartOutcomeService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_outcome(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartOutcomeError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartOutcomeResponse)
async def clear_chart_outcome_field(
    chart_id: str,
    field_name: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific outcome field to NULL.

    Reserved for correction workflows where a previously recorded
    outcome value must be erased rather than overwritten. The audit
    trail lives in chart versioning.
    """
    if field_name not in _OUTCOME_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown field",
                "field": field_name,
                "allowed": list(_OUTCOME_FIELDS),
            },
        )
    try:
        record = await ChartOutcomeService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            user_id=str(user.user_id),
        )
        await project_chart_outcome(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartOutcomeError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
