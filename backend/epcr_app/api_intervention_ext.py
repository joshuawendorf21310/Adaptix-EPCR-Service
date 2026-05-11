"""NEMSIS eProcedures extension API router.

Tenant-scoped HTTP surface for the per-intervention NEMSIS extension
and its repeating complications child. Every route enforces real
authentication via ``get_current_user`` and uses a real database session
via ``get_session``. Tenant isolation is delegated to the service layer
and verified at the SQL level.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_intervention_ext import project_intervention_ext
from epcr_app.services_intervention_ext import (
    InterventionExtError,
    InterventionExtPayload,
    InterventionExtService,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/procedures/{intervention_id}/ext",
    tags=["nemsis-eprocedures"],
)


class InterventionExtRequest(BaseModel):
    """Caller request body for PUT /ext.

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE /complications/{id} to remove a complication.
    """

    model_config = ConfigDict(extra="forbid")

    prior_to_ems_indicator_code: str | None = None
    number_of_attempts: int | None = None
    procedure_successful_code: str | None = None
    ems_professional_type_code: str | None = None
    authorization_code: str | None = None
    authorizing_physician_last_name: str | None = None
    authorizing_physician_first_name: str | None = None
    by_another_unit_indicator_code: str | None = None
    pre_existing_indicator_code: str | None = None


class ComplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complication_code: str
    sequence_index: int | None = None


class InterventionExtResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: InterventionExtRequest) -> InterventionExtPayload:
    return InterventionExtPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=InterventionExtResponse)
async def get_intervention_ext(
    chart_id: str,
    intervention_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the ext record + complications. 404 if ext is absent."""
    try:
        ext = await InterventionExtService.get(
            session,
            tenant_id=str(user.tenant_id),
            intervention_id=intervention_id,
        )
        complications = await InterventionExtService.list_complications(
            session,
            tenant_id=str(user.tenant_id),
            intervention_id=intervention_id,
        )
    except InterventionExtError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if ext is None and not complications:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "intervention_ext not recorded",
                "intervention_id": intervention_id,
            },
        )
    return {"ext": ext, "complications": complications}


@router.put("", response_model=InterventionExtResponse, status_code=status.HTTP_200_OK)
async def upsert_intervention_ext(
    chart_id: str,
    intervention_id: str,
    body: InterventionExtRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert the ext scalars. Returns the persisted record.

    Side effect: after writing the domain row, projects the eProcedures
    fields into the registry-driven NEMSIS field-values ledger so the
    dataset XML builder can emit them on export.
    """
    try:
        record = await InterventionExtService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            intervention_id=intervention_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_intervention_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            intervention_id=intervention_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except InterventionExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.post(
    "/complications",
    response_model=InterventionExtResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_complication(
    chart_id: str,
    intervention_id: str,
    body: ComplicationRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add a single complication code occurrence (eProcedures.07)."""
    try:
        record = await InterventionExtService.add_complication(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            intervention_id=intervention_id,
            complication_code=body.complication_code,
            sequence_index=body.sequence_index,
            user_id=str(user.user_id),
        )
        await project_intervention_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            intervention_id=intervention_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except InterventionExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete(
    "/complications/{complication_id}",
    response_model=InterventionExtResponse,
)
async def remove_complication(
    chart_id: str,
    intervention_id: str,
    complication_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete a single complication code occurrence."""
    try:
        record = await InterventionExtService.remove_complication(
            session,
            tenant_id=str(user.tenant_id),
            intervention_id=intervention_id,
            complication_id=complication_id,
            user_id=str(user.user_id),
        )
        await project_intervention_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            intervention_id=intervention_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except InterventionExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
