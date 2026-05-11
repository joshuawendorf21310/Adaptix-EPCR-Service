"""NEMSIS eSituation API router.

Tenant-scoped HTTP surface for the chart situation (eSituation.01..20).
Every route enforces real authentication via ``get_current_user`` and
uses a real database session via ``get_session``. Tenant isolation is
delegated to the service layer and verified at the SQL level.

Route map (prefix ``/api/v1/epcr/charts/{chart_id}/situation``):

- ``GET    ""``                          -- read the 1:1 row
- ``PUT    ""``                          -- upsert the 1:1 row
- ``DELETE "/{field_name}"``             -- clear one scalar column
- ``GET    "/other-symptoms"``           -- list eSituation.10
- ``POST   "/other-symptoms"``           -- add one eSituation.10 row
- ``DELETE "/other-symptoms/{row_id}"``  -- soft-delete one row
- ``GET    "/secondary-impressions"``    -- list eSituation.12
- ``POST   "/secondary-impressions"``    -- add one eSituation.12 row
- ``DELETE "/secondary-impressions/{row_id}"`` -- soft-delete one row
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_situation import project_chart_situation
from epcr_app.services_chart_situation import (
    ChartSituationError,
    ChartSituationOtherSymptomPayload,
    ChartSituationOtherSymptomService,
    ChartSituationPayload,
    ChartSituationSecondaryImpressionPayload,
    ChartSituationSecondaryImpressionService,
    ChartSituationService,
    _SITUATION_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/situation",
    tags=["nemsis-esituation"],
)


# ---------- 1:1 scalar row ----------


class ChartSituationRequest(BaseModel):
    """Caller request body for PUT /situation.

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE on the per-field path to explicitly clear.
    """

    model_config = ConfigDict(extra="forbid")

    symptom_onset_at: datetime | None = None
    possible_injury_indicator_code: str | None = None
    complaint_type_code: str | None = None
    complaint_text: str | None = None
    complaint_duration_value: int | None = None
    complaint_duration_units_code: str | None = None
    chief_complaint_anatomic_code: str | None = None
    chief_complaint_organ_system_code: str | None = None
    primary_symptom_code: str | None = None
    provider_primary_impression_code: str | None = None
    initial_patient_acuity_code: str | None = None
    work_related_indicator_code: str | None = None
    patient_industry_code: str | None = None
    patient_occupation_code: str | None = None
    patient_activity_code: str | None = None
    last_known_well_at: datetime | None = None
    transfer_justification_code: str | None = None
    interfacility_transfer_reason_code: str | None = None


class ChartSituationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartSituationRequest) -> ChartSituationPayload:
    return ChartSituationPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=ChartSituationResponse)
async def get_chart_situation(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart situation record or 404 if not yet recorded."""
    try:
        record = await ChartSituationService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartSituationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_situation not recorded", "chart_id": chart_id},
        )
    return record


@router.put("", response_model=ChartSituationResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_situation(
    chart_id: str,
    body: ChartSituationRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart situation. Returns the persisted record.

    Side effect: after writing the domain row, projects the situation
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        record = await ChartSituationService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_situation(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSituationError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartSituationResponse)
async def clear_chart_situation_field(
    chart_id: str,
    field_name: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific situation field to NULL.

    Reserved for correction workflows where a previously recorded
    situation value must be erased rather than overwritten. The audit
    trail lives in chart versioning.
    """
    if field_name not in _SITUATION_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown field",
                "field": field_name,
                "allowed": list(_SITUATION_FIELDS),
            },
        )
    try:
        record = await ChartSituationService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            user_id=str(user.user_id),
        )
        await project_chart_situation(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSituationError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


# ---------- eSituation.10 Other Associated Symptoms (1:M) ----------


class OtherSymptomCreateRequest(BaseModel):
    """Caller request body for POST /situation/other-symptoms."""

    model_config = ConfigDict(extra="forbid")

    symptom_code: str = Field(..., min_length=1)
    sequence_index: int = Field(default=0, ge=0)


class OtherSymptomResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get("/other-symptoms", response_model=list[OtherSymptomResponse])
async def list_other_symptoms(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """List all Other Associated Symptoms recorded for the chart."""
    try:
        rows = await ChartSituationOtherSymptomService.list_for_chart(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartSituationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return rows


@router.post(
    "/other-symptoms",
    response_model=OtherSymptomResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_other_symptom(
    chart_id: str,
    body: OtherSymptomCreateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one Other Associated Symptom to the chart."""
    try:
        record = await ChartSituationOtherSymptomService.add(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=ChartSituationOtherSymptomPayload(
                symptom_code=body.symptom_code,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_situation(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSituationError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/other-symptoms/{row_id}", response_model=OtherSymptomResponse)
async def delete_other_symptom(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one Other Associated Symptom row."""
    try:
        record = await ChartSituationOtherSymptomService.soft_delete(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            user_id=str(user.user_id),
        )
        await project_chart_situation(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSituationError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


# ---------- eSituation.12 Provider's Secondary Impressions (1:M) ----------


class SecondaryImpressionCreateRequest(BaseModel):
    """Caller request body for POST /situation/secondary-impressions."""

    model_config = ConfigDict(extra="forbid")

    impression_code: str = Field(..., min_length=1)
    sequence_index: int = Field(default=0, ge=0)


class SecondaryImpressionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get(
    "/secondary-impressions",
    response_model=list[SecondaryImpressionResponse],
)
async def list_secondary_impressions(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """List all Provider's Secondary Impressions recorded for the chart."""
    try:
        rows = await ChartSituationSecondaryImpressionService.list_for_chart(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartSituationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return rows


@router.post(
    "/secondary-impressions",
    response_model=SecondaryImpressionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_secondary_impression(
    chart_id: str,
    body: SecondaryImpressionCreateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one Provider's Secondary Impression to the chart."""
    try:
        record = await ChartSituationSecondaryImpressionService.add(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=ChartSituationSecondaryImpressionPayload(
                impression_code=body.impression_code,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_situation(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSituationError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete(
    "/secondary-impressions/{row_id}",
    response_model=SecondaryImpressionResponse,
)
async def delete_secondary_impression(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one Provider's Secondary Impression row."""
    try:
        record = await ChartSituationSecondaryImpressionService.soft_delete(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            user_id=str(user.user_id),
        )
        await project_chart_situation(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSituationError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
