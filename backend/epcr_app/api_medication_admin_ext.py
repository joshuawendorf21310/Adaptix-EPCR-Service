"""NEMSIS eMedications additions API router.

Tenant-scoped HTTP surface for the per-medication NEMSIS additions
(eMedications.02/.08/.10/.11/.12/.13). Every route enforces real
authentication via ``get_current_user`` and uses a real database
session via ``get_session``. Tenant isolation is delegated to the
service layer and verified at the SQL level.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_medication_admin_ext import project_medication_admin_ext
from epcr_app.services_medication_admin_ext import (
    MedicationAdminExtError,
    MedicationAdminExtPayload,
    MedicationAdminExtService,
    MedicationComplicationPayload,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/medications/{medication_admin_id}/ext",
    tags=["nemsis-emedications"],
)


class MedicationAdminExtRequest(BaseModel):
    """Request body for PUT /ext.

    Every field is optional; omitted (``None``) fields retain their
    current persisted value. NEMSIS element bindings:

        eMedications.02 prior_to_ems_indicator_code
        eMedications.10 ems_professional_type_code
        eMedications.11 authorization_code
        eMedications.12 authorizing_physician_last_name / _first_name
        eMedications.13 by_another_unit_indicator_code
    """

    model_config = ConfigDict(extra="forbid")

    prior_to_ems_indicator_code: str | None = None
    ems_professional_type_code: str | None = None
    authorization_code: str | None = None
    authorizing_physician_last_name: str | None = None
    authorizing_physician_first_name: str | None = None
    by_another_unit_indicator_code: str | None = None


class MedicationComplicationRequest(BaseModel):
    """Request body for POST /ext/complications."""

    model_config = ConfigDict(extra="forbid")

    complication_code: str = Field(..., min_length=1)
    sequence_index: int = Field(0, ge=0)


class MedicationAdminExtResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _payload_from_request(req: MedicationAdminExtRequest) -> MedicationAdminExtPayload:
    return MedicationAdminExtPayload(**req.model_dump(exclude_unset=False))


@router.get("", response_model=MedicationAdminExtResponse)
async def get_medication_admin_ext(
    chart_id: str,
    medication_admin_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return ext + complications for one medication, 404 if neither exist."""
    try:
        record = await MedicationAdminExtService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            medication_admin_id=medication_admin_id,
        )
    except MedicationAdminExtError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "medication_admin_ext not recorded",
                "chart_id": chart_id,
                "medication_admin_id": medication_admin_id,
            },
        )
    return record


@router.put("", response_model=MedicationAdminExtResponse, status_code=status.HTTP_200_OK)
async def upsert_medication_admin_ext(
    chart_id: str,
    medication_admin_id: str,
    body: MedicationAdminExtRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert NEMSIS-additive scalars for one medication.

    Side effect: after writing the domain row, projects into the
    registry-driven NEMSIS field-values ledger so the dataset XML
    builder can emit eMedications.02/.10/.11/.12/.13 on export.
    """
    try:
        record = await MedicationAdminExtService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            medication_admin_id=medication_admin_id,
            payload=_payload_from_request(body),
            user_id=str(user.user_id),
        )
        await project_medication_admin_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            medication_admin_id=medication_admin_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except MedicationAdminExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.post(
    "/complications",
    response_model=MedicationAdminExtResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_medication_complication(
    chart_id: str,
    medication_admin_id: str,
    body: MedicationComplicationRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one eMedications.08 Medication Complication row (1:M)."""
    try:
        record = await MedicationAdminExtService.add_complication(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            medication_admin_id=medication_admin_id,
            payload=MedicationComplicationPayload(
                complication_code=body.complication_code,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_medication_admin_ext(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            medication_admin_id=medication_admin_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except MedicationAdminExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete(
    "/complications/{complication_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_medication_complication(
    chart_id: str,
    medication_admin_id: str,
    complication_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Hard-delete one eMedications.08 complication row."""
    try:
        removed = await MedicationAdminExtService.delete_complication(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            medication_admin_id=medication_admin_id,
            complication_id=complication_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except MedicationAdminExtError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "complication not found",
                "complication_id": complication_id,
            },
        )
    return {"removed": True, "complication_id": complication_id}


__all__ = ["router"]
