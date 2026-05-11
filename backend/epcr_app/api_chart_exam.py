"""NEMSIS eExam API router.

Tenant-scoped HTTP surface for the chart physical exam (eExam.01..51). The
1:1 exam record is served via GET/PUT/DELETE on the root path.

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


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/v1/epcr/charts/{chart_id}/exam",
    tags=["nemsis-eexam"],
)


class ChartExamCreate(BaseModel):
    """Caller request body for PUT /exam.

    Every field is optional. Omitting a field leaves its current value
    intact. Use DELETE to explicitly clear the exam record.
    """

    model_config = ConfigDict(extra="forbid")

    skin_assessment_code: str | None = None         # eExam.01
    skin_color_code: str | None = None              # eExam.02
    skin_moisture_code: str | None = None           # eExam.03
    head_assessment_code: str | None = None         # eExam.04
    head_trauma_codes: list[str] = []               # eExam.05 (multi)
    facial_assessment_code: str | None = None       # eExam.07
    neck_assessment_code: str | None = None         # eExam.10
    chest_assessment_codes: list[str] = []          # eExam.13 (multi)
    lung_assessment_codes: list[str] = []           # eExam.15 (multi)
    abdominal_assessment_codes: list[str] = []      # eExam.19 (multi)
    pelvic_assessment_code: str | None = None       # eExam.22
    back_spine_assessment_code: str | None = None   # eExam.25
    extremity_assessment_codes: list[str] = []      # eExam.29 (multi)
    neuro_mental_status_code: str | None = None     # eExam.36
    neuro_loc_code: str | None = None               # eExam.37
    neuro_orientation_codes: list[str] = []         # eExam.38 (multi)
    stroke_scale_code: str | None = None            # eExam.45
    stroke_scale_score: int | None = None
    facial_droop: bool | None = None
    arm_drift: bool | None = None
    speech_abnormal: bool | None = None
    pediatric_airway_code: str | None = None        # eExam.51


class ChartExamResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get("", response_model=ChartExamResponse)
async def get_chart_exam(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the chart exam record or 404 if not yet recorded."""
    from epcr_app.services_chart_exam import ChartExamError, ChartExamService

    try:
        record = await ChartExamService.get(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
        )
    except ChartExamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "chart_exam not recorded", "chart_id": chart_id},
        )
    return record


@router.put("", response_model=ChartExamResponse, status_code=status.HTTP_200_OK)
async def upsert_chart_exam(
    chart_id: str,
    body: ChartExamCreate = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upsert chart exam data. Returns the persisted record.

    All fields are optional. Unset fields are left unchanged. The full
    record is returned after the write so callers always see current state.
    """
    from epcr_app.services_chart_exam import ChartExamError, ChartExamPayload, ChartExamService

    payload = ChartExamPayload(**body.model_dump(exclude_unset=False))
    try:
        record = await ChartExamService.upsert(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            payload=payload,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartExamError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


@router.delete("", status_code=status.HTTP_200_OK)
async def clear_chart_exam(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Clear the entire exam record for this chart.

    Reserved for correction workflows where a previously recorded exam
    must be fully erased. The audit trail lives in chart versioning.
    Returns the cleared (nulled) record.
    """
    from epcr_app.services_chart_exam import ChartExamError, ChartExamService

    try:
        record = await ChartExamService.clear(
            session,
            tenant_id=str(user.tenant_id),
            chart_id=chart_id,
            user_id=str(user.user_id),
        )
        await session.commit()
    except ChartExamError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return record


__all__ = ["router"]
