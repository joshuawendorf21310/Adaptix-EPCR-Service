"""Chart workspace API router.

Exposes a single high-level chart workspace contract that delegates to the
canonical EPCR chart, NEMSIS, finalization, export, and submission
services. Every route enforces real authentication via
``get_current_user`` and a real database session via ``get_session``. No
fabricated success.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.chart_workspace_service import (
    ALL_SECTIONS,
    ChartWorkspaceError,
    ChartWorkspaceService,
)
from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/chart-workspaces",
    tags=["chart-workspaces"],
)


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    call_number: str | None = None
    incident_type: str = Field(..., min_length=1)
    client_reference_id: str | None = None
    patient_id: str | None = None
    agency_id: str | None = None
    agency_code: str | None = None
    incident_datetime: str | None = None
    cad_incident_number: str | None = None


class UpdateFieldRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: Any = None


def _raise_for_workspace_error(exc: ChartWorkspaceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("", status_code=201)
async def create_chart_workspace(
    payload: CreateWorkspaceRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new chart and return its initial workspace payload."""
    try:
        return await ChartWorkspaceService.create_workspace_chart(
            session, current_user, payload.model_dump(exclude_none=True)
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error creating chart workspace")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to create chart workspace", "error": str(exc)},
        ) from exc


@router.get("/{chart_id}")
async def get_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.get_workspace(session, current_user, chart_id)
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.patch("/{chart_id}/sections/{section}")
async def update_chart_workspace_section(
    chart_id: str,
    section: str,
    payload: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    if section not in ALL_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Unknown workspace section '{section}'", "section": section},
        )
    try:
        return await ChartWorkspaceService.update_workspace_section(
            session, current_user, chart_id, section, payload
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.patch("/{chart_id}/fields/{section}/{field_key}")
async def update_chart_workspace_field(
    chart_id: str,
    section: str,
    field_key: str,
    payload: UpdateFieldRequest = Body(default_factory=UpdateFieldRequest),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    if section not in ALL_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Unknown workspace section '{section}'", "section": section},
        )
    try:
        return await ChartWorkspaceService.update_workspace_field(
            session, current_user, chart_id, section, field_key, payload.value
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.get("/{chart_id}/readiness")
async def get_chart_workspace_readiness(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.get_workspace_readiness(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.post("/{chart_id}/validate")
async def validate_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.validate_workspace(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.post("/{chart_id}/finalize")
async def finalize_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.finalize_workspace(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.post("/{chart_id}/export")
async def export_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.export_workspace(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.post("/{chart_id}/submit")
async def submit_chart_workspace(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.submit_workspace(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)


@router.get("/{chart_id}/status")
async def get_chart_workspace_status(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await ChartWorkspaceService.get_workspace_status(
            session, current_user, chart_id
        )
    except ChartWorkspaceError as exc:
        _raise_for_workspace_error(exc)
