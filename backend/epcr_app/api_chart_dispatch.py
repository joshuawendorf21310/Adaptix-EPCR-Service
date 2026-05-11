"""NEMSIS eDispatch API router.

Tenant-scoped HTTP surface for the chart dispatch (eDispatch.01..06).
Every route enforces real authentication via ``get_current_user`` and
uses a real database session via ``get_session``. Tenant isolation is
delegated to the service layer and verified at the SQL level.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_dispatch import project_chart_dispatch
from epcr_app.services_chart_dispatch import (
    ChartDispatchError,
    ChartDispatchPayload,
    ChartDispatchService,
    _DISPATCH_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/dispatch",
    tags=["nemsis-edispatch"],
)


class ChartDispatchRequest(BaseModel):
    """Caller request body for PUT /dispatch.

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE on the per-field path to explicitly clear.
    """

    model_config = ConfigDict(extra="forbid")

    dispatch_reason_code: str | None = None
    emd_performed_code: str | None = None
    emd_determinant_code: str | None = None
    dispatch_center_id: str | None = None
    dispatch_priority_code: str | None = None
    cad_record_id: str | None = None


class ChartDispatchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartDispatchRequest) -> ChartDispatchPayload:
    return ChartDispatchPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=ChartDispatchResponse)
async def get_chart_dispatch(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart dispatch record or 404 if not yet recorded."""
    try:
        record = await ChartDispatchService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartDispatchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_dispatch not recorded", "chart_id": chart_id},
        )
    return record


@router.put("", response_model=ChartDispatchResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_dispatch(
    chart_id: str,
    body: ChartDispatchRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart dispatch. Returns the persisted record.

    Side effect: after writing the domain row, projects the dispatch
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        record = await ChartDispatchService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_dispatch(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartDispatchError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartDispatchResponse)
async def clear_chart_dispatch_field(
    chart_id: str,
    field_name: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific dispatch field to NULL.

    Reserved for correction workflows where a previously recorded
    dispatch value must be erased rather than overwritten. The audit
    trail lives in chart versioning.
    """
    if field_name not in _DISPATCH_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown field",
                "field": field_name,
                "allowed": list(_DISPATCH_FIELDS),
            },
        )
    try:
        record = await ChartDispatchService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            user_id=str(user.user_id),
        )
        await project_chart_dispatch(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartDispatchError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
