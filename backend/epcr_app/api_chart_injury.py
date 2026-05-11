"""NEMSIS eInjury API router.

Tenant-scoped HTTP surface for the chart injury aggregate
(eInjury.01..10) and the Automated Crash Notification Group sub-block
(eInjury.11..29). Every route enforces real authentication via
``get_current_user`` and uses a real database session via
``get_session``. Tenant isolation is delegated to the service layer
and verified at the SQL level.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_injury import project_chart_injury
from epcr_app.services_chart_injury import (
    ChartInjuryAcnPayload,
    ChartInjuryError,
    ChartInjuryPayload,
    ChartInjuryService,
    _ACN_FIELDS,
    _INJURY_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/injury",
    tags=["nemsis-einjury"],
)


class ChartInjuryRequest(BaseModel):
    """Caller request body for PUT /injury (eInjury.01..10).

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE on the per-field path to explicitly clear.
    """

    model_config = ConfigDict(extra="forbid")

    cause_of_injury_codes_json: list[Any] | None = None
    mechanism_of_injury_code: str | None = None
    trauma_triage_high_codes_json: list[Any] | None = None
    trauma_triage_moderate_codes_json: list[Any] | None = None
    vehicle_impact_area_code: str | None = None
    patient_location_in_vehicle_code: str | None = None
    occupant_safety_equipment_codes_json: list[Any] | None = None
    airbag_deployment_code: str | None = None
    height_of_fall_feet: float | None = None
    osha_ppe_used_codes_json: list[Any] | None = None


class ChartInjuryAcnRequest(BaseModel):
    """Caller request body for PUT /injury/acn (eInjury.11..29)."""

    model_config = ConfigDict(extra="forbid")

    acn_system_company: str | None = None
    acn_incident_id: str | None = None
    acn_callback_phone: str | None = None
    acn_incident_at: datetime | None = None
    acn_incident_location: str | None = None
    acn_vehicle_body_type_code: str | None = None
    acn_vehicle_manufacturer: str | None = None
    acn_vehicle_make: str | None = None
    acn_vehicle_model: str | None = None
    acn_vehicle_model_year: int | None = None
    acn_multiple_impacts_code: str | None = None
    acn_delta_velocity: float | None = None
    acn_high_probability_code: str | None = None
    acn_pdof: int | None = None
    acn_rollover_code: str | None = None
    acn_seat_location_code: str | None = None
    seat_occupied_code: str | None = None
    acn_seatbelt_use_code: str | None = None
    acn_airbag_deployed_code: str | None = None


class ChartInjuryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get("", response_model=ChartInjuryResponse)
async def get_chart_injury(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the merged injury + acn record or 404 if not yet recorded."""
    try:
        record = await ChartInjuryService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartInjuryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_injury not recorded", "chart_id": chart_id},
        )
    return record


@router.put("", response_model=ChartInjuryResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_injury(
    chart_id: str,
    body: ChartInjuryRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert eInjury.01..10 columns. Returns the persisted injury record.

    Side effect: after writing the domain row, projects the injury
    aggregate (and ACN block if present) into the registry-driven
    NEMSIS field-values ledger so the dataset XML builder can emit it
    on export.
    """
    try:
        payload = ChartInjuryPayload(**body.model_dump(exclude_unset=False))
        record = await ChartInjuryService.upsert_injury(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=payload,
            user_id=str(user.user_id),
        )
        await project_chart_injury(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartInjuryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.put("/acn", response_model=ChartInjuryResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_injury_acn(
    chart_id: str,
    body: ChartInjuryAcnRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert eInjury.11..29 ACN block. Returns the persisted ACN record.

    The parent injury row must already exist; otherwise a 409 is
    returned. Side effect: re-projects the full injury aggregate to
    the NEMSIS field-values ledger.
    """
    try:
        payload = ChartInjuryAcnPayload(**body.model_dump(exclude_unset=False))
        record = await ChartInjuryService.upsert_acn(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=payload,
            user_id=str(user.user_id),
        )
        await project_chart_injury(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartInjuryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartInjuryResponse)
async def clear_chart_injury_field(
    chart_id: str,
    field_name: str,
    block: str = Query("injury", description="injury or acn"),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific eInjury field to NULL.

    ``block`` selects which sub-aggregate the field belongs to:
    ``injury`` (default, eInjury.01..10) or ``acn`` (eInjury.11..29).
    Reserved for correction workflows where a previously recorded
    value must be erased rather than overwritten.
    """
    if block not in ("injury", "acn"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "unknown block", "block": block, "allowed": ["injury", "acn"]},
        )
    allowed = _INJURY_FIELDS if block == "injury" else _ACN_FIELDS
    if field_name not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown field",
                "field": field_name,
                "block": block,
                "allowed": list(allowed),
            },
        )
    try:
        record = await ChartInjuryService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            block=block,
            user_id=str(user.user_id),
        )
        await project_chart_injury(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartInjuryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
