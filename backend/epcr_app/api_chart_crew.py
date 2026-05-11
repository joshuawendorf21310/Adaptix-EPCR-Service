"""NEMSIS eCrew API router.

Tenant-scoped HTTP surface for chart crew members (eCrew.01..03).
Every route enforces real authentication via ``get_current_user`` and
uses a real database session via ``get_session``. Tenant isolation is
delegated to the service layer and verified at the SQL level.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_crew import project_chart_crew
from epcr_app.services_chart_crew import (
    ChartCrewError,
    ChartCrewPayload,
    ChartCrewService,
    ChartCrewUpdate,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/crew",
    tags=["nemsis-ecrew"],
)


class CrewMemberCreateRequest(BaseModel):
    """Caller request body for POST /crew."""

    model_config = ConfigDict(extra="forbid")

    crew_member_id: str = Field(..., min_length=1)
    crew_member_level_code: str = Field(..., min_length=1)
    crew_member_response_role_code: str = Field(..., min_length=1)
    sequence_index: int = Field(default=0, ge=0)


class CrewMemberUpdateRequest(BaseModel):
    """Caller request body for PATCH /crew/{row_id}."""

    model_config = ConfigDict(extra="forbid")

    crew_member_level_code: str | None = None
    crew_member_response_role_code: str | None = None
    sequence_index: int | None = Field(default=None, ge=0)


class CrewMemberResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get("", response_model=list[CrewMemberResponse])
async def list_chart_crew(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """List all crew members for the chart, ordered by sequence_index."""
    try:
        rows = await ChartCrewService.list_for_chart(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartCrewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return rows


@router.post("", response_model=CrewMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_chart_crew_member(
    chart_id: str,
    body: CrewMemberCreateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one crew member to the chart.

    Side effect: after writing the domain row, projects the crew roster
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        record = await ChartCrewService.add(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=ChartCrewPayload(
                crew_member_id=body.crew_member_id,
                crew_member_level_code=body.crew_member_level_code,
                crew_member_response_role_code=body.crew_member_response_role_code,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_crew(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartCrewError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.patch("/{row_id}", response_model=CrewMemberResponse)
async def update_chart_crew_member(
    chart_id: str,
    row_id: str,
    body: CrewMemberUpdateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Update one crew member's level/role/sequence."""
    try:
        record = await ChartCrewService.update(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            payload=ChartCrewUpdate(
                crew_member_level_code=body.crew_member_level_code,
                crew_member_response_role_code=body.crew_member_response_role_code,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_crew(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartCrewError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{row_id}", response_model=CrewMemberResponse)
async def delete_chart_crew_member(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one crew member from the chart."""
    try:
        record = await ChartCrewService.soft_delete(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            user_id=str(user.user_id),
        )
        await project_chart_crew(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartCrewError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
