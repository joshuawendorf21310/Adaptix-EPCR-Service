"""NEMSIS eScene API router.

Tenant-scoped HTTP surface for the chart scene (eScene.01..25). The 1:1
scene metadata is served via GET/PUT/DELETE on the root path; the 1:M
"Other EMS or Public Safety Agencies at Scene" repeating group is served
via POST/DELETE on the ``/other-agencies`` sub-path.

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
from epcr_app.projection_chart_scene import project_chart_scene
from epcr_app.services_chart_scene import (
    ChartSceneError,
    ChartSceneOtherAgencyPayload,
    ChartSceneOtherAgencyService,
    ChartScenePayload,
    ChartSceneService,
    _SCENE_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/scene",
    tags=["nemsis-escene"],
)


class ChartSceneRequest(BaseModel):
    """Caller request body for PUT /scene.

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE on the per-field path to explicitly clear.
    """

    model_config = ConfigDict(extra="forbid")

    first_ems_unit_indicator_code: str | None = None
    initial_responder_arrived_at: datetime | None = None
    number_of_patients: int | None = None
    mci_indicator_code: str | None = None
    mci_triage_classification_code: str | None = None
    incident_location_type_code: str | None = None
    incident_facility_code: str | None = None
    scene_lat: float | None = None
    scene_long: float | None = None
    scene_usng: str | None = None
    incident_facility_name: str | None = None
    mile_post_or_major_roadway: str | None = None
    incident_street_address: str | None = None
    incident_apartment: str | None = None
    incident_city: str | None = None
    incident_state: str | None = None
    incident_zip: str | None = None
    scene_cross_street: str | None = None
    incident_county: str | None = None
    incident_country: str | None = None
    incident_census_tract: str | None = None


class ChartSceneResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class ChartSceneOtherAgencyRequest(BaseModel):
    """Caller request body for POST /scene/other-agencies."""

    model_config = ConfigDict(extra="forbid")

    agency_id: str
    other_service_type_code: str
    first_to_provide_patient_care_indicator: str | None = None
    patient_care_handoff_code: str | None = None
    sequence_index: int = 0


class ChartSceneOtherAgencyResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartSceneRequest) -> ChartScenePayload:
    return ChartScenePayload(**req.model_dump(exclude_unset=False))


def _agency_payload_from_request(
    req: ChartSceneOtherAgencyRequest,
) -> ChartSceneOtherAgencyPayload:
    return ChartSceneOtherAgencyPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=ChartSceneResponse)
async def get_chart_scene(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart scene record or 404 if not yet recorded."""
    try:
        record = await ChartSceneService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartSceneError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_scene not recorded", "chart_id": chart_id},
        )
    return record


@router.put("", response_model=ChartSceneResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_scene(
    chart_id: str,
    body: ChartSceneRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart scene meta. Returns the persisted record.

    Side effect: after writing the domain row, projects the scene meta
    (and any existing other-agency rows) into the registry-driven
    NEMSIS field-values ledger so the dataset XML builder can emit them
    on export.
    """
    try:
        record = await ChartSceneService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_scene(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSceneError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartSceneResponse)
async def clear_chart_scene_field(
    chart_id: str,
    field_name: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific scene field to NULL.

    Reserved for correction workflows where a previously recorded scene
    value must be erased rather than overwritten. The audit trail lives
    in chart versioning. The ``/other-agencies/{id}`` path handles the
    1:M repeating group separately.
    """
    if field_name not in _SCENE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown field",
                "field": field_name,
                "allowed": list(_SCENE_FIELDS),
            },
        )
    try:
        record = await ChartSceneService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            user_id=str(user.user_id),
        )
        await project_chart_scene(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSceneError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.get("/other-agencies")
async def list_chart_scene_other_agencies(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """List other-agency rows for the chart's eScene group."""
    items = await ChartSceneOtherAgencyService.list_for_chart(
        session,
        tenant_id=str(user.tenant_id),
        chart_id=chart_id,
    )
    return {"chart_id": chart_id, "count": len(items), "items": items}


@router.post(
    "/other-agencies",
    response_model=ChartSceneOtherAgencyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_chart_scene_other_agency(
    chart_id: str,
    body: ChartSceneOtherAgencyRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one other-agency row to the chart's eScene group.

    Side effect: projects the scene aggregate (1:1 meta + 1:M agencies)
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit the new occurrence on export.
    """
    try:
        record = await ChartSceneOtherAgencyService.add(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_agency_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_scene(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSceneError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete(
    "/other-agencies/{row_id}",
    response_model=ChartSceneOtherAgencyResponse,
)
async def delete_chart_scene_other_agency(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one other-agency row from the chart's eScene group.

    The corresponding ledger occurrence is NOT actively purged; the
    next projection-on-write run will skip the soft-deleted row, and a
    separate ledger reconciliation pass is responsible for tombstoning.
    """
    try:
        record = await ChartSceneOtherAgencyService.soft_delete(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartSceneError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
