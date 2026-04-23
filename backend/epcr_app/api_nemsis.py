from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.models import NemsisMappingRecord
from epcr_app.services import ChartService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/epcr/nemsis", tags=["nemsis-validation"])


# 🔒 MUST match builder + FIELD_RULES
NEMSIS_FIELD_SECTIONS: dict[str, str] = {
    "eRecord": "Record",
    "eResponse": "Response",
    "eTimes": "Times",
    "ePatient": "Patient",
    "eSituation": "Situation",
    "eHistory": "History",
    "eVitals": "Vitals",
    "eMedications": "Medications",
    "eProcedures": "Procedures",
    "eNarrative": "Narrative",
    "eDisposition": "Disposition",
    "eIncident": "Incident",
}


class BlockerDetail(BaseModel):
    type: str
    field: str
    message: str
    jump_target: str | None = None


class ValidationResponse(BaseModel):
    valid: bool
    chart_id: str
    state_code: str
    mapped_elements: int
    blockers: list[BlockerDetail]
    warnings: list[BlockerDetail]
    timestamp: str


class ReadinessResponse(BaseModel):
    chart_id: str
    ready_for_export: bool
    blockers: list[BlockerDetail]
    warnings: list[BlockerDetail]
    mapped_elements: int


class MappingSummaryResponse(BaseModel):
    chart_id: str
    total_mappings: int
    by_section: dict[str, int]
    by_status: dict[str, int]


class ExportPreviewResponse(BaseModel):
    chart_id: str
    nemsis_version: str
    state_dataset: str | None
    mapped_elements: int
    blockers: list[BlockerDetail]
    warnings: list[BlockerDetail]
    can_export: bool
    estimated_xml_size_bytes: int


def _require_header(value: str | None, name: str) -> str:
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} header required",
        )
    return value.strip()


def _build_blockers(missing_fields: list[str]) -> list[BlockerDetail]:
    return [
        BlockerDetail(
            type="blocker",
            field=field,
            message=f"Mandatory NEMSIS field '{field}' is not populated",
            jump_target=field,
        )
        for field in missing_fields
    ]


def _section_from_field(nemsis_field: str) -> str:
    prefix = nemsis_field.split(".")[0]
    return NEMSIS_FIELD_SECTIONS.get(prefix, "Other")


@router.get("/mapping-summary", response_model=MappingSummaryResponse)
async def get_mapping_summary(
    chart_id: str = Query(...),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    from epcr_app.models import Chart

    chart = (
        await session.execute(
            select(Chart).where(
                and_(
                    Chart.id == chart_id,
                    Chart.tenant_id == tenant_id,
                    Chart.deleted_at.is_(None),
                )
            )
        )
    ).scalars().first()

    if not chart:
        raise HTTPException(404, f"Chart {chart_id} not found")

    mappings = (
        await session.execute(
            select(NemsisMappingRecord).where(
                NemsisMappingRecord.chart_id == chart_id
            )
        )
    ).scalars().all()

    by_section: dict[str, int] = {}
    populated = 0
    unmapped = 0

    for m in mappings:
        field = m.nemsis_field

        if not field:
            continue

        section = _section_from_field(field)
        by_section[section] = by_section.get(section, 0) + 1

        value = m.nemsis_value

        if value is not None and str(value).strip() != "":
            populated += 1
        else:
            unmapped += 1

    return MappingSummaryResponse(
        chart_id=chart_id,
        total_mappings=len(mappings),
        by_section=by_section,
        by_status={"populated": populated, "unmapped": unmapped},
    )


@router.post("/validate", response_model=ValidationResponse)
async def validate_chart(
    chart_id: str = Query(...),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    compliance = await ChartService.check_nemsis_compliance(
        session=session,
        tenant_id=tenant_id,
        chart_id=chart_id,
    )

    blockers = _build_blockers(compliance["missing_mandatory_fields"])

    return ValidationResponse(
        valid=compliance["is_fully_compliant"],
        chart_id=chart_id,
        state_code="NEMSIS-3.5.1",
        mapped_elements=compliance["mandatory_fields_filled"],
        blockers=blockers,
        warnings=[],
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )


@router.get("/readiness", response_model=ReadinessResponse)
async def get_readiness(
    chart_id: str = Query(...),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    compliance = await ChartService.check_nemsis_compliance(
        session=session,
        tenant_id=tenant_id,
        chart_id=chart_id,
    )

    blockers = _build_blockers(compliance["missing_mandatory_fields"])

    return ReadinessResponse(
        chart_id=chart_id,
        ready_for_export=compliance["is_fully_compliant"],
        blockers=blockers,
        warnings=[],
        mapped_elements=compliance["mandatory_fields_filled"],
    )


@router.get("/export-preview", response_model=ExportPreviewResponse)
async def get_export_preview(
    chart_id: str = Query(...),
    state_dataset: str | None = Query(default=None),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    compliance = await ChartService.check_nemsis_compliance(
        session=session,
        tenant_id=tenant_id,
        chart_id=chart_id,
    )

    blockers = _build_blockers(compliance["missing_mandatory_fields"])

    # 🔒 Preview reflects real export gate
    can_export = compliance["is_fully_compliant"]

    return ExportPreviewResponse(
        chart_id=chart_id,
        nemsis_version="3.5.1",
        state_dataset=state_dataset,
        mapped_elements=compliance["mandatory_fields_filled"],
        blockers=blockers,
        warnings=[],
        can_export=can_export,
        estimated_xml_size_bytes=0,
    )
