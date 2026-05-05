from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models import NemsisMappingRecord
from epcr_app.nemsis.service import AllergyVerticalSliceService
from epcr_app.services_export import NemsisExportService
from epcr_app.services import ChartService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epcr/nemsis",
    tags=["nemsis-validation"],
)


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


class AllergyVerticalSliceRequest(BaseModel):
    case_id: str = "2025-EMS-1-Allergy_v351"
    integration_enabled: bool = False
    patient_care_report_number: str = "PCR-ALLERGY-2025-0001"
    software_creator: str = "Adaptix EPCR Service"
    software_name: str = "Adaptix EPCR Allergy CTA Slice"
    software_version: str = "3.5.1"


class AllergyVerticalSliceResponse(BaseModel):
    case_id: str
    tactical_test_key: str
    demographic_values: dict[str, object]
    artifact_path: str
    unresolved_placeholders: list[str]
    repeated_group_counts_before: dict[str, int]
    repeated_group_counts_after: dict[str, int]
    xsd_validation: dict[str, object]
    schematron_validation: dict[str, object]
    cta_submission: dict[str, object]
    xsd_result_path: str
    schematron_result_path: str
    fidelity_result_path: str
    cta_request_path: str
    cta_response_path: str
    cta_parsed_result_path: str


def _tenant_id(current_user: CurrentUser) -> str:
    """Return the authenticated tenant identifier from JWT context."""
    return str(current_user.tenant_id)


def _build_blockers(missing_fields: list[str]) -> list[BlockerDetail]:
    return [
        BlockerDetail(
            type="blocker",
            field=field,
            message=(
                f"Mandatory NEMSIS field '{field}' is not populated"
                if "." in field
                else f"Runtime export prerequisite '{field}' is not configured"
            ),
            jump_target=field if "." in field else None,
        )
        for field in missing_fields
    ]


def _section_from_field(nemsis_field: str) -> str:
    prefix = nemsis_field.split(".")[0]
    return NEMSIS_FIELD_SECTIONS.get(prefix, "Other")


@router.get("/mapping-summary", response_model=MappingSummaryResponse)
async def get_mapping_summary(
    chart_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant_id = _tenant_id(current_user)

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
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant_id = _tenant_id(current_user)

    compliance = await ChartService.check_nemsis_compliance(
        session=session,
        tenant_id=tenant_id,
        chart_id=chart_id,
    )

    snapshot = await NemsisExportService._snapshot(session, chart_id, tenant_id)
    blockers = _build_blockers(list(snapshot.missing_mandatory_fields))

    return ValidationResponse(
        valid=snapshot.ready_for_export,
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
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant_id = _tenant_id(current_user)

    compliance = await ChartService.check_nemsis_compliance(
        session=session,
        tenant_id=tenant_id,
        chart_id=chart_id,
    )

    snapshot = await NemsisExportService._snapshot(session, chart_id, tenant_id)
    blockers = _build_blockers(list(snapshot.missing_mandatory_fields))

    return ReadinessResponse(
        chart_id=chart_id,
        ready_for_export=snapshot.ready_for_export,
        blockers=blockers,
        warnings=[],
        mapped_elements=compliance["mandatory_fields_filled"],
    )


@router.get("/export-preview", response_model=ExportPreviewResponse)
async def get_export_preview(
    chart_id: str = Query(...),
    state_dataset: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant_id = _tenant_id(current_user)

    compliance = await ChartService.check_nemsis_compliance(
        session=session,
        tenant_id=tenant_id,
        chart_id=chart_id,
    )

    snapshot = await NemsisExportService._snapshot(session, chart_id, tenant_id)
    blockers = _build_blockers(list(snapshot.missing_mandatory_fields))

    # 🔒 Preview reflects real export gate
    can_export = snapshot.ready_for_export

    return ExportPreviewResponse(
        chart_id=chart_id,
        nemsis_version="3.5.1",
        state_dataset=state_dataset,
        mapped_elements=compliance["mandatory_fields_filled"],
        blockers=blockers,
        warnings=[],
        can_export=can_export,
        estimated_xml_size_bytes=max(1024, compliance["mandatory_fields_filled"] * 180),
    )


@router.post("/vertical-slice/allergy", response_model=AllergyVerticalSliceResponse)
async def build_allergy_vertical_slice(
    payload: AllergyVerticalSliceRequest,
):
    """Build the locked official Allergy CTA vertical slice end to end.

    Args:
        payload: Runtime settings for the single supported Allergy case.

    Returns:
        AllergyVerticalSliceResponse: Full artifact, validation, and CTA evidence payload.

    Raises:
        HTTPException: If the vertical slice fails.
    """

    service = AllergyVerticalSliceService()
    try:
        result = await service.run(
            case_id=payload.case_id,
            integration_enabled=payload.integration_enabled,
            patient_care_report_number=payload.patient_care_report_number,
            software_creator=payload.software_creator,
            software_name=payload.software_name,
            software_version=payload.software_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - surfaced truthfully to caller
        logger.exception("Allergy vertical slice execution failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Allergy vertical slice failed: {exc}",
        ) from exc
    return AllergyVerticalSliceResponse(**result.to_dict())
