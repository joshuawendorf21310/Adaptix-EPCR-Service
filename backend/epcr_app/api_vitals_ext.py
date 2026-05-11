"""NEMSIS eVitals extension API router.

Tenant-scoped HTTP surface for the per-Vitals-row NEMSIS extension
aggregate (the 27 eVitals elements not modeled by the legacy
``epcr_vitals`` table, plus the GCS-qualifier and reperfusion-checklist
repeating groups). Every route enforces real authentication via
``get_current_user`` and uses a real database session via
``get_session``. Tenant isolation is delegated to the service layer
and verified at the SQL level.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_vitals_ext import project_vitals_ext
from epcr_app.services_vitals_ext import (
    VitalsExtError,
    VitalsExtPayload,
    VitalsExtService,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/vitals/{vitals_id}/ext",
    tags=["nemsis-evitals-ext"],
)


class VitalsExtRequest(BaseModel):
    """Caller request body for PUT /ext.

    Every field is optional. Omitting a field leaves its current value
    intact on update.
    """

    model_config = ConfigDict(extra="forbid")

    obtained_prior_to_ems_code: str | None = None
    cardiac_rhythm_codes_json: list[str] | None = None
    ecg_type_code: str | None = None
    ecg_interpretation_method_codes_json: list[str] | None = None
    blood_pressure_method_code: str | None = None
    mean_arterial_pressure: int | None = None
    heart_rate_method_code: str | None = None
    pulse_rhythm_code: str | None = None
    respiratory_effort_code: str | None = None
    etco2: int | None = None
    carbon_monoxide_ppm: float | None = None
    gcs_eye_code: str | None = None
    gcs_verbal_code: str | None = None
    gcs_motor_code: str | None = None
    gcs_total: int | None = None
    temperature_method_code: str | None = None
    avpu_code: str | None = None
    pain_score: int | None = None
    pain_scale_type_code: str | None = None
    stroke_scale_result_code: str | None = None
    stroke_scale_type_code: str | None = None
    stroke_scale_score: int | None = None
    apgar_score: int | None = None
    revised_trauma_score: int | None = None


class GcsQualifierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qualifier_code: str = Field(min_length=1, max_length=16)
    sequence_index: int = 0


class ReperfusionItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_code: str = Field(min_length=1, max_length=16)
    sequence_index: int = 0


class VitalsExtResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: VitalsExtRequest) -> VitalsExtPayload:
    return VitalsExtPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=VitalsExtResponse)
async def get_vitals_ext(
    chart_id: str,
    vitals_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the eVitals extension aggregate (ext + gcs + reperfusion).

    Returns 404 when no extension data has been recorded for the
    target vitals row.
    """
    try:
        record = await VitalsExtService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
        )
    except VitalsExtError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "vitals_ext not recorded",
                "chart_id": chart_id,
                "vitals_id": vitals_id,
            },
        )
    return record


@router.put("", response_model=VitalsExtResponse, status_code=status.HTTP_200_OK)
async def upsert_vitals_ext(
    chart_id: str,
    vitals_id: str,
    body: VitalsExtRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert the eVitals extension scalars + JSON list columns.

    Side effect: after writing the domain row, projects the extension
    into the registry-driven NEMSIS field-values ledger so the dataset
    XML builder can emit it on export.
    """
    try:
        record = await VitalsExtService.upsert_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_vitals_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except VitalsExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.post(
    "/gcs-qualifiers",
    response_model=VitalsExtResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_gcs_qualifier(
    chart_id: str,
    vitals_id: str,
    body: GcsQualifierRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add (or upsert) one GCS qualifier (eVitals.22) for the vitals row."""
    try:
        record = await VitalsExtService.add_gcs_qualifier(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
            qualifier_code=body.qualifier_code,
            sequence_index=body.sequence_index,
            user_id=str(user.user_id),
        )
        await project_vitals_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except VitalsExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete(
    "/gcs-qualifiers/{row_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_gcs_qualifier(
    chart_id: str,
    vitals_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Hard-delete one GCS qualifier row (correction path)."""
    try:
        removed = await VitalsExtService.delete_gcs_qualifier(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
            row_id=row_id,
        )
        if not removed:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "gcs_qualifier not found",
                    "id": row_id,
                },
            )
        await session.commit()
    except VitalsExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return {"deleted": True, "id": row_id}


@router.post(
    "/reperfusion-items",
    response_model=VitalsExtResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_reperfusion_item(
    chart_id: str,
    vitals_id: str,
    body: ReperfusionItemRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add (or upsert) one reperfusion-checklist item (eVitals.31)."""
    try:
        record = await VitalsExtService.add_reperfusion_item(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
            item_code=body.item_code,
            sequence_index=body.sequence_index,
            user_id=str(user.user_id),
        )
        await project_vitals_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except VitalsExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete(
    "/reperfusion-items/{row_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_reperfusion_item(
    chart_id: str,
    vitals_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Hard-delete one reperfusion-checklist row (correction path)."""
    try:
        removed = await VitalsExtService.delete_reperfusion_item(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            vitals_id=vitals_id,
            row_id=row_id,
        )
        if not removed:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "reperfusion_item not found",
                    "id": row_id,
                },
            )
        await session.commit()
    except VitalsExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return {"deleted": True, "id": row_id}


__all__ = ["router"]
