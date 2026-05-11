"""NEMSIS eArrest API router.

Tenant-scoped HTTP surface for the chart cardiac arrest section
(eArrest.01..22). Every route enforces real authentication via
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
from epcr_app.projection_chart_arrest import project_chart_arrest
from epcr_app.services_chart_arrest import (
    ChartArrestError,
    ChartArrestPayload,
    ChartArrestService,
    _ARREST_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/arrest",
    tags=["nemsis-earrest"],
)


class ChartArrestRequest(BaseModel):
    """Caller request body for PUT /arrest.

    Every field is optional except ``cardiac_arrest_code`` on initial
    insert (enforced by the service). Omitting a field leaves its
    current value intact. Use DELETE on the per-field path to
    explicitly clear a nullable column.
    """

    model_config = ConfigDict(extra="forbid")

    cardiac_arrest_code: str | None = None
    etiology_code: str | None = None
    resuscitation_attempted_codes_json: list[str] | None = None
    witnessed_by_codes_json: list[str] | None = None
    aed_use_prior_code: str | None = None
    cpr_type_codes_json: list[str] | None = None
    hypothermia_indicator_code: str | None = None
    first_monitored_rhythm_code: str | None = None
    rosc_codes_json: list[str] | None = None
    neurological_outcome_code: str | None = None
    arrest_at: datetime | None = None
    resuscitation_discontinued_at: datetime | None = None
    reason_discontinued_code: str | None = None
    rhythm_on_arrival_code: str | None = None
    end_of_event_code: str | None = None
    initial_cpr_at: datetime | None = None
    who_first_cpr_code: str | None = None
    who_first_aed_code: str | None = None
    who_first_defib_code: str | None = None


class ChartArrestResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartArrestRequest) -> ChartArrestPayload:
    return ChartArrestPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=ChartArrestResponse)
async def get_chart_arrest(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart arrest record or 404 if not yet recorded."""
    try:
        record = await ChartArrestService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartArrestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_arrest not recorded", "chart_id": chart_id},
        )
    return record


@router.put("", response_model=ChartArrestResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_arrest(
    chart_id: str,
    body: ChartArrestRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart arrest. Returns the persisted record.

    Side effect: after writing the domain row, projects the arrest
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        record = await ChartArrestService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_arrest(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartArrestError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartArrestResponse)
async def clear_chart_arrest_field(
    chart_id: str,
    field_name: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific arrest field to NULL.

    Reserved for correction workflows where a previously recorded
    arrest value must be erased rather than overwritten. The audit
    trail lives in chart versioning.
    """
    if field_name not in _ARREST_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown field",
                "field": field_name,
                "allowed": list(_ARREST_FIELDS),
            },
        )
    try:
        record = await ChartArrestService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            user_id=str(user.user_id),
        )
        await project_chart_arrest(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartArrestError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
