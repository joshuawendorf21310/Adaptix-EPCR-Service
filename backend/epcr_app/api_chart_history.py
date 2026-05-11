"""NEMSIS eHistory API router.

Tenant-scoped HTTP surface for the chart medical history aggregate
(eHistory.01..20). One composite GET, one meta PUT, and four
POST/DELETE pairs for the 1:M children. Every route enforces real
authentication via ``get_current_user`` and uses a real database
session via ``get_session``. Tenant isolation is delegated to the
service layer and verified at the SQL level.

Every write side-effects a re-projection into the registry-driven
NEMSIS field-values ledger so the dataset XML builder can emit the
section on export.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.projection_chart_history import project_chart_history
from epcr_app.services_chart_history import (
    ALLERGY_KINDS,
    AllergyPayload,
    ChartHistoryAllergyService,
    ChartHistoryCurrentMedicationService,
    ChartHistoryError,
    ChartHistoryImmunizationService,
    ChartHistoryMetaPayload,
    ChartHistoryMetaService,
    ChartHistoryService,
    ChartHistorySurgicalService,
    CurrentMedicationPayload,
    ImmunizationPayload,
    SurgicalPayload,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/history",
    tags=["nemsis-ehistory"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MetaUpsertRequest(BaseModel):
    """Caller request body for PUT /history/meta."""

    model_config = ConfigDict(extra="forbid")

    barriers_to_care_codes_json: list[str] | None = None
    advance_directives_codes_json: list[str] | None = None
    medical_history_obtained_from_codes_json: list[str] | None = None
    alcohol_drug_use_codes_json: list[str] | None = None
    practitioner_last_name: str | None = None
    practitioner_first_name: str | None = None
    practitioner_middle_name: str | None = None
    pregnancy_code: str | None = None
    last_oral_intake_at: datetime | None = None
    emergency_information_form_code: str | None = None


class AllergyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allergy_kind: str = Field(..., min_length=1)
    allergy_code: str = Field(..., min_length=1)
    allergy_text: str | None = None
    sequence_index: int = Field(default=0, ge=0)


class SurgicalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_code: str = Field(..., min_length=1)
    condition_text: str | None = None
    sequence_index: int = Field(default=0, ge=0)


class CurrentMedicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drug_code: str = Field(..., min_length=1)
    dose_value: str | None = None
    dose_unit_code: str | None = None
    route_code: str | None = None
    frequency_code: str | None = None
    sequence_index: int = Field(default=0, ge=0)


class ImmunizationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    immunization_type_code: str = Field(..., min_length=1)
    immunization_year: int | None = Field(default=None, ge=0)
    sequence_index: int = Field(default=0, ge=0)


class HistoryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Composite read
# ---------------------------------------------------------------------------


@router.get("", response_model=HistoryResponse)
async def get_chart_history(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the composite eHistory payload (meta + 4 child collections)."""
    try:
        return await ChartHistoryService.get_composite(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartHistoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# ---------------------------------------------------------------------------
# Meta upsert
# ---------------------------------------------------------------------------


@router.put("/meta", response_model=HistoryResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_history_meta(
    chart_id: str,
    body: MetaUpsertRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert the eHistory meta (1:1) row. Returns the persisted record."""
    try:
        record = await ChartHistoryMetaService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=ChartHistoryMetaPayload(**body.model_dump(exclude_unset=False)),
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


# ---------------------------------------------------------------------------
# Allergies
# ---------------------------------------------------------------------------


@router.post(
    "/allergies",
    response_model=HistoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_chart_history_allergy(
    chart_id: str,
    body: AllergyCreateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one allergy (medication or environmental/food) to the chart."""
    if body.allergy_kind not in ALLERGY_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "invalid allergy_kind",
                "allowed": list(ALLERGY_KINDS),
                "received": body.allergy_kind,
            },
        )
    try:
        record = await ChartHistoryAllergyService.add(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=AllergyPayload(
                allergy_kind=body.allergy_kind,
                allergy_code=body.allergy_code,
                allergy_text=body.allergy_text,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


@router.delete("/allergies/{row_id}", response_model=HistoryResponse)
async def delete_chart_history_allergy(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one allergy from the chart."""
    try:
        record = await ChartHistoryAllergyService.soft_delete(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


# ---------------------------------------------------------------------------
# Medical/Surgical history
# ---------------------------------------------------------------------------


@router.post(
    "/surgical",
    response_model=HistoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_chart_history_surgical(
    chart_id: str,
    body: SurgicalCreateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one medical/surgical condition (eHistory.08) to the chart."""
    try:
        record = await ChartHistorySurgicalService.add(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=SurgicalPayload(
                condition_code=body.condition_code,
                condition_text=body.condition_text,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


@router.delete("/surgical/{row_id}", response_model=HistoryResponse)
async def delete_chart_history_surgical(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one medical/surgical condition from the chart."""
    try:
        record = await ChartHistorySurgicalService.soft_delete(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


# ---------------------------------------------------------------------------
# Current medications
# ---------------------------------------------------------------------------


@router.post(
    "/medications",
    response_model=HistoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_chart_history_medication(
    chart_id: str,
    body: CurrentMedicationCreateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one current medication (eHistory.12/.13/.14/.15/.20) to the chart."""
    try:
        record = await ChartHistoryCurrentMedicationService.add(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=CurrentMedicationPayload(
                drug_code=body.drug_code,
                dose_value=body.dose_value,
                dose_unit_code=body.dose_unit_code,
                route_code=body.route_code,
                frequency_code=body.frequency_code,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


@router.delete("/medications/{row_id}", response_model=HistoryResponse)
async def delete_chart_history_medication(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one current medication from the chart."""
    try:
        record = await ChartHistoryCurrentMedicationService.soft_delete(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


# ---------------------------------------------------------------------------
# Immunizations
# ---------------------------------------------------------------------------


@router.post(
    "/immunizations",
    response_model=HistoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_chart_history_immunization(
    chart_id: str,
    body: ImmunizationCreateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Add one immunization (eHistory.10/.11) to the chart."""
    try:
        record = await ChartHistoryImmunizationService.add(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=ImmunizationPayload(
                immunization_type_code=body.immunization_type_code,
                immunization_year=body.immunization_year,
                sequence_index=body.sequence_index,
            ),
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


@router.delete("/immunizations/{row_id}", response_model=HistoryResponse)
async def delete_chart_history_immunization(
    chart_id: str,
    row_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete one immunization from the chart."""
    try:
        record = await ChartHistoryImmunizationService.soft_delete(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            row_id=row_id,
            user_id=str(user.user_id),
        )
        await project_chart_history(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartHistoryError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return record


__all__ = ["router"]
