"""NEMSIS eTimes API router.

Tenant-scoped HTTP surface for the chart event timeline (eTimes.01..17).
Every route enforces real authentication via ``get_current_user`` and
uses a real database session via ``get_session``. Tenant isolation is
delegated to the service layer and verified at the SQL level.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_times import project_chart_times
from epcr_app.services_chart_times import (
    ChartTimesError,
    ChartTimesPayload,
    ChartTimesService,
    _TIME_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/times",
    tags=["nemsis-etimes"],
)


class ChartTimesRequest(BaseModel):
    """Caller request body for PUT /times.

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE on the per-field path to explicitly clear.
    """

    model_config = ConfigDict(extra="forbid")

    psap_call_at: datetime | None = None
    dispatch_notified_at: datetime | None = None
    unit_notified_by_dispatch_at: datetime | None = None
    dispatch_acknowledged_at: datetime | None = None
    unit_en_route_at: datetime | None = None
    unit_on_scene_at: datetime | None = None
    arrived_at_patient_at: datetime | None = None
    transfer_of_ems_care_at: datetime | None = None
    unit_left_scene_at: datetime | None = None
    arrival_landing_area_at: datetime | None = None
    patient_arrived_at_destination_at: datetime | None = None
    destination_transfer_of_care_at: datetime | None = None
    unit_back_in_service_at: datetime | None = None
    unit_canceled_at: datetime | None = None
    unit_back_home_location_at: datetime | None = None
    ems_call_completed_at: datetime | None = None
    unit_arrived_staging_at: datetime | None = None


class ChartTimesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartTimesRequest) -> ChartTimesPayload:
    return ChartTimesPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=ChartTimesResponse)
async def get_chart_times(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart times record or 404 if not yet recorded."""
    try:
        record = await ChartTimesService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartTimesError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_times not recorded", "chart_id": chart_id},
        )
    return record


@router.put("", response_model=ChartTimesResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_times(
    chart_id: str,
    body: ChartTimesRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart times. Returns the persisted record.

    Side effect: after writing the domain row, projects the timeline
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        record = await ChartTimesService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_times(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartTimesError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartTimesResponse)
async def clear_chart_times_field(
    chart_id: str,
    field_name: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific time field to NULL.

    Reserved for correction workflows where a previously recorded time
    must be erased rather than overwritten. The audit trail lives in
    chart versioning.
    """
    if field_name not in _TIME_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "unknown field", "field": field_name, "allowed": list(_TIME_FIELDS)},
        )
    try:
        record = await ChartTimesService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            user_id=str(user.user_id),
        )
        await project_chart_times(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartTimesError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
