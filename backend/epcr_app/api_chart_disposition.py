"""NEMSIS eDisposition API router.

Tenant-scoped HTTP surface for the chart disposition section
(eDisposition.01..30, excluding the v3.5.1-undefined .26). Every route
enforces real authentication via ``get_current_user`` and uses a real
database session via ``get_session``. Tenant isolation is delegated to
the service layer and verified at the SQL level.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_disposition import project_chart_disposition
from epcr_app.services_chart_disposition import (
    ChartDispositionError,
    ChartDispositionPayload,
    ChartDispositionService,
    _DISPOSITION_FIELDS,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/disposition",
    tags=["nemsis-edisposition"],
)


class ChartDispositionRequest(BaseModel):
    """Caller request body for PUT /disposition.

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE on the per-field path to explicitly clear.
    """

    model_config = ConfigDict(extra="forbid")

    # Scalars (eDisposition.01..08, .11..13, .16..21, .25, .28..29)
    destination_name: str | None = None
    destination_code: str | None = None
    destination_address: str | None = None
    destination_city: str | None = None
    destination_county: str | None = None
    destination_state: str | None = None
    destination_zip: str | None = None
    destination_country: str | None = None
    type_of_destination_code: str | None = None
    incident_patient_disposition_code: str | None = None
    transport_mode_from_scene_code: str | None = None
    transport_disposition_code: str | None = None
    reason_not_transported_code: str | None = None
    level_of_care_provided_code: str | None = None
    position_during_transport_code: str | None = None
    condition_at_destination_code: str | None = None
    transferred_care_to_code: str | None = None
    destination_type_when_reason_code: str | None = None
    unit_disposition_code: str | None = None
    transport_method_code: str | None = None

    # JSON list columns (1:M) — eDisposition.09/.10/.14/.15/.22/.23/.24/.27/.30
    hospital_capability_codes_json: list[str] | None = None
    reason_for_choosing_destination_codes_json: list[str] | None = None
    additional_transport_descriptors_codes_json: list[str] | None = None
    hospital_incapability_codes_json: list[str] | None = None
    prearrival_activation_codes_json: list[str] | None = None
    type_of_destination_reason_codes_json: list[str] | None = None
    destination_team_activations_codes_json: list[str] | None = None
    crew_disposition_codes_json: list[str] | None = None
    transport_method_additional_codes_json: list[str] | None = None


class ChartDispositionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: ChartDispositionRequest) -> ChartDispositionPayload:
    return ChartDispositionPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=ChartDispositionResponse)
async def get_chart_disposition(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart disposition record or 404 if not yet recorded."""
    try:
        record = await ChartDispositionService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartDispositionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "chart_disposition not recorded",
                "chart_id": chart_id,
            },
        )
    return record


@router.put("", response_model=ChartDispositionResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_disposition(
    chart_id: str,
    body: ChartDispositionRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart disposition. Returns the persisted record.

    Side effect: after writing the domain row, projects the disposition
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        record = await ChartDispositionService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_chart_disposition(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartDispositionError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("/{field_name}", response_model=ChartDispositionResponse)
async def clear_chart_disposition_field(
    chart_id: str,
    field_name: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear one specific disposition field to NULL.

    Reserved for correction workflows where a previously recorded
    value must be erased rather than overwritten. The audit trail
    lives in chart versioning.
    """
    if field_name not in _DISPOSITION_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "unknown field",
                "field": field_name,
                "allowed": list(_DISPOSITION_FIELDS),
            },
        )
    try:
        record = await ChartDispositionService.clear_field(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            field=field_name,
            user_id=str(user.user_id),
        )
        await project_chart_disposition(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartDispositionError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
