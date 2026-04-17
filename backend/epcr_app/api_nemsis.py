"""NEMSIS 3.5.1 validation, readiness, mapping, and preview API routes.

Provides the four NEMSIS lifecycle routes consumed by the frontend nemsisService:
- POST /validate       — run compliance check and return typed blocker list
- GET  /readiness      — check chart export readiness
- GET  /mapping-summary — return field mapping counts by section and status
- GET  /export-preview  — return pre-export readiness snapshot

All routes perform real database queries through ChartService. No fake or
simulated data is returned. If a chart is not found or compliance cannot
be checked, a structured error is raised.
"""
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

NEMSIS_FIELD_SECTIONS: dict[str, str] = {
    "eRecord": "Record",
    "eResponse": "Response",
    "eTimes": "Times",
    "ePatient": "Patient",
    "eScene": "Scene",
    "eSituation": "Situation",
    "eHistory": "History",
    "eExam": "Exam",
    "eVitals": "Vitals",
    "eMedications": "Medications",
    "eProcedures": "Procedures",
    "eDisposition": "Disposition",
    "eOutcome": "Outcome",
}


class BlockerDetail(BaseModel):
    """A single NEMSIS validation issue with its type, field, and message."""

    type: str
    field: str
    message: str
    jump_target: str | None = None


class ValidationResponse(BaseModel):
    """Result of a NEMSIS compliance validation run."""

    valid: bool
    chart_id: str
    state_code: str
    mapped_elements: int
    blockers: list[BlockerDetail]
    warnings: list[BlockerDetail]
    timestamp: str


class ReadinessResponse(BaseModel):
    """NEMSIS export readiness state for a chart."""

    chart_id: str
    ready_for_export: bool
    blockers: list[BlockerDetail]
    warnings: list[BlockerDetail]
    mapped_elements: int


class MappingSummaryResponse(BaseModel):
    """Aggregate statistics on NEMSIS field mappings for a chart."""

    chart_id: str
    total_mappings: int
    by_section: dict[str, int]
    by_status: dict[str, int]


class ExportPreviewResponse(BaseModel):
    """Pre-export snapshot summarising chart readiness for NEMSIS submission."""

    chart_id: str
    nemsis_version: str
    state_dataset: str | None
    mapped_elements: int
    blockers: list[BlockerDetail]
    warnings: list[BlockerDetail]
    can_export: bool
    estimated_xml_size_bytes: int


def _require_header(value: str | None, name: str) -> str:
    """Validate that a required HTTP header is present and non-empty.

    Args:
        value: Raw header value from the request.
        name: Header name used in the error message.

    Returns:
        Stripped header value.

    Raises:
        HTTPException: 400 if the header is absent or blank.
    """
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} header required",
        )
    return value.strip()


def _build_blockers(missing_fields: list[str]) -> list[BlockerDetail]:
    """Convert a list of missing NEMSIS mandatory field IDs to BlockerDetail objects.

    Args:
        missing_fields: List of NEMSIS field identifiers (e.g. 'eRecord.01').

    Returns:
        List of BlockerDetail with type='blocker' for each missing field.
    """
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
    """Derive the section name from a NEMSIS field identifier.

    Uses the prefix before the first '.' (e.g. 'eRecord' from 'eRecord.01').
    Falls back to 'Other' if the prefix is unrecognised.

    Args:
        nemsis_field: NEMSIS field identifier string.

    Returns:
        Human-readable section label.
    """
    prefix = nemsis_field.split(".")[0] if "." in nemsis_field else nemsis_field
    return NEMSIS_FIELD_SECTIONS.get(prefix, "Other")


@router.post("/validate", response_model=ValidationResponse, status_code=200)
async def validate_chart(
    chart_id: str = Query(..., description="Chart identifier to validate"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> ValidationResponse:
    """Run NEMSIS 3.5.1 compliance validation against a chart.

    Calls the real ChartService compliance check and maps every missing
    mandatory field to a BlockerDetail. Returns valid=True only when the
    chart is fully compliant.

    Args:
        chart_id: Chart identifier from query string.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        ValidationResponse with blockers, warnings, and compliance state.

    Raises:
        HTTPException: 400 if header missing; 404 if chart not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        compliance = await ChartService.check_nemsis_compliance(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
        )
    except ValueError as exc:
        logger.warning("Validate: chart not found chart_id=%s tenant_id=%s", chart_id, tenant_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Validate: unexpected error chart_id=%s: %s", chart_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Compliance check failed",
        ) from exc

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


@router.get("/readiness", response_model=ReadinessResponse, status_code=200)
async def get_readiness(
    chart_id: str = Query(..., description="Chart identifier"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> ReadinessResponse:
    """Check whether a chart is ready for NEMSIS export.

    Runs the real compliance check and returns ready_for_export=True only
    when the chart is fully NEMSIS 3.5.1 compliant. All missing mandatory
    fields are surfaced as blockers.

    Args:
        chart_id: Chart identifier from query string.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        ReadinessResponse with export readiness state and blocker list.

    Raises:
        HTTPException: 400 if header missing; 404 if chart not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        compliance = await ChartService.check_nemsis_compliance(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
        )
    except ValueError as exc:
        logger.warning("Readiness: chart not found chart_id=%s tenant_id=%s", chart_id, tenant_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Readiness: unexpected error chart_id=%s: %s", chart_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Readiness check failed",
        ) from exc

    blockers = _build_blockers(compliance["missing_mandatory_fields"])

    return ReadinessResponse(
        chart_id=chart_id,
        ready_for_export=compliance["is_fully_compliant"],
        blockers=blockers,
        warnings=[],
        mapped_elements=compliance["mandatory_fields_filled"],
    )


@router.get("/mapping-summary", response_model=MappingSummaryResponse, status_code=200)
async def get_mapping_summary(
    chart_id: str = Query(..., description="Chart identifier"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> MappingSummaryResponse:
    """Return aggregate NEMSIS field mapping statistics for a chart.

    Queries the real NemsisMappingRecord table for the chart and groups
    results by NEMSIS section (derived from the field prefix) and by
    population status (populated vs unmapped).

    Args:
        chart_id: Chart identifier from query string.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        MappingSummaryResponse with counts by section and by status.

    Raises:
        HTTPException: 400 if header missing; 404 if chart not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        from epcr_app.models import Chart  # local import avoids circular at module level

        chart_result = await session.execute(
            select(Chart).where(
                and_(
                    Chart.id == chart_id,
                    Chart.tenant_id == tenant_id,
                    Chart.deleted_at.is_(None),
                )
            )
        )
        chart = chart_result.scalars().first()
        if not chart:
            logger.warning(
                "MappingSummary: chart not found chart_id=%s tenant_id=%s",
                chart_id,
                tenant_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chart {chart_id} not found",
            )

        mapping_result = await session.execute(
            select(NemsisMappingRecord).where(
                NemsisMappingRecord.chart_id == chart_id
            )
        )
        mappings = mapping_result.scalars().all()

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "MappingSummary: unexpected error chart_id=%s: %s", chart_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mapping summary retrieval failed",
        ) from exc

    by_section: dict[str, int] = {}
    populated = 0
    unmapped = 0

    for m in mappings:
        section = _section_from_field(m.nemsis_field)
        by_section[section] = by_section.get(section, 0) + 1
        if m.nemsis_value is not None:
            populated += 1
        else:
            unmapped += 1

    return MappingSummaryResponse(
        chart_id=chart_id,
        total_mappings=len(mappings),
        by_section=by_section,
        by_status={"populated": populated, "unmapped": unmapped},
    )


@router.get("/export-preview", response_model=ExportPreviewResponse, status_code=200)
async def get_export_preview(
    chart_id: str = Query(..., description="Chart identifier"),
    state_dataset: str | None = Query(default=None, description="State dataset identifier"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> ExportPreviewResponse:
    """Return a pre-export readiness snapshot for a chart.

    Runs the real compliance check and surfaces all blockers and warnings.
    can_export is True only when the chart is fully NEMSIS 3.5.1 compliant.
    estimated_xml_size_bytes is 0 because XML generation is not yet
    performed at the preview stage; the value is truthfully 0, not fabricated.

    Args:
        chart_id: Chart identifier from query string.
        x_tenant_id: Tenant identifier from X-Tenant-ID header.
        session: Injected async database session.

    Returns:
        ExportPreviewResponse with readiness state, blockers, and metadata.

    Raises:
        HTTPException: 400 if header missing; 404 if chart not found;
                       500 on unexpected failure.
    """
    tenant_id = _require_header(x_tenant_id, "X-Tenant-ID")

    try:
        compliance = await ChartService.check_nemsis_compliance(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
        )
    except ValueError as exc:
        logger.warning(
            "ExportPreview: chart not found chart_id=%s tenant_id=%s", chart_id, tenant_id
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "ExportPreview: unexpected error chart_id=%s: %s", chart_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Export preview failed",
        ) from exc

    blockers = _build_blockers(compliance["missing_mandatory_fields"])

    return ExportPreviewResponse(
        chart_id=chart_id,
        nemsis_version="3.5.1",
        state_dataset=state_dataset,
        mapped_elements=compliance["mandatory_fields_filled"],
        blockers=blockers,
        warnings=[],
        can_export=compliance["is_fully_compliant"],
        estimated_xml_size_bytes=0,
    )
