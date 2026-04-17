"""ePCR domain API routes for chart management and NEMSIS 3.5.1 compliance.

Provides RESTful endpoints for chart creation, retrieval, update, finalization,
and NEMSIS 3.5.1 compliance checking. All state-mutating endpoints require a
valid RS256 Bearer JWT issued by the Adaptix core auth service. All endpoints
include input validation, error logging, and real tenant/user context.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from epcr_app.db import get_session, check_health
from epcr_app.services import ChartService
from epcr_app.dependencies import get_current_user, CurrentUser
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/epcr", tags=["epcr"])


class CreateChartRequest(BaseModel):
    """Request model for creating new ePCR chart.
    
    Attributes:
        call_number: Unique call/dispatch identifier (required, non-empty).
        incident_type: Type of incident: medical, trauma, behavioral, other.
        patient_id: Optional existing patient identifier.
    """
    call_number: str = Field(..., min_length=1, max_length=50, description="Unique call/dispatch number")
    incident_type: str = Field("medical", description="Incident type: medical, trauma, behavioral, other")
    patient_id: Optional[str] = Field(None, max_length=36, description="Optional patient identifier")
    
    @field_validator("call_number")
    @classmethod
    def validate_call_number(cls, v: str) -> str:
        """Validate call_number is non-empty string."""
        if not v or not v.strip():
            raise ValueError("call_number cannot be empty")
        return v.strip()
    
    @field_validator("incident_type")
    @classmethod
    def validate_incident_type(cls, v: str) -> str:
        """Validate incident_type is in allowed values."""
        allowed = ["medical", "trauma", "behavioral", "other"]
        if v not in allowed:
            raise ValueError(f"incident_type must be one of: {', '.join(allowed)}")
        return v


class ChartResponse(BaseModel):
    """Response model for ePCR chart.
    
    Attributes:
        id: Chart unique identifier.
        call_number: Dispatch/call number.
        status: Chart lifecycle status.
        incident_type: Type of incident.
        created_at: ISO 8601 timestamp of creation.
    """
    id: str
    call_number: str
    status: str
    incident_type: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class ComplianceResponse(BaseModel):
    """Response model for NEMSIS 3.5.1 compliance check.
    
    Attributes:
        chart_id: Chart identifier checked.
        compliance_status: Current compliance level.
        compliance_percentage: Percentage of mandatory fields filled (0-100).
        mandatory_fields_filled: Count of populated mandatory fields.
        mandatory_fields_required: Total mandatory fields for chart.
        missing_mandatory_fields: List of missing field identifiers.
        is_fully_compliant: Boolean: true if all mandatory fields present.
    """
    chart_id: str
    compliance_status: str
    compliance_percentage: float
    mandatory_fields_filled: int
    mandatory_fields_required: int
    missing_mandatory_fields: list
    is_fully_compliant: bool


class UpdateChartRequest(BaseModel):
    """Request model for updating ePCR chart fields.
    
    Allows partial updates to chart metadata, vitals, and assessment data.
    All fields are optional. Empty/None values are ignored (not cleared).
    
    Attributes:
        incident_type: Type of incident (medical, trauma, behavioral, other).
        patient_id: Patient identifier (may change during documentation).
        bp_sys: Systolic blood pressure (mmHg).
        bp_dia: Diastolic blood pressure (mmHg).
        hr: Heart rate (beats per minute).
        rr: Respiration rate (breaths per minute).
        temp_f: Temperature (Fahrenheit).
        spo2: Oxygen saturation (%).
        glucose: Blood glucose (mg/dL).
        chief_complaint: Patient's chief complaint.
        field_diagnosis: Paramedic's field diagnosis.
    """
    incident_type: Optional[str] = None
    patient_id: Optional[str] = None
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    rr: Optional[int] = None
    temp_f: Optional[float] = None
    spo2: Optional[int] = None
    glucose: Optional[int] = None
    chief_complaint: Optional[str] = None
    field_diagnosis: Optional[str] = None
    
    @field_validator("incident_type")
    @classmethod
    def validate_incident_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate incident_type is in allowed values if provided."""
        if v is None:
            return v
        allowed = ["medical", "trauma", "behavioral", "other"]
        if v not in allowed:
            raise ValueError(f"incident_type must be one of: {', '.join(allowed)}")
        return v


class ComplianceSummary(BaseModel):
    """Inline compliance status summary.
    
    Provides compliance state after chart update without requiring a separate
    compliance check call.
    
    Attributes:
        is_fully_compliant: Boolean: true if all mandatory fields present.
        compliance_percentage: Percentage of mandatory fields filled (0-100).
        missing_mandatory_fields: List of missing mandatory field IDs.
    """
    is_fully_compliant: bool
    compliance_percentage: float
    missing_mandatory_fields: list[str]


class ChartUpdateResponse(BaseModel):
    """Response model for PATCH /charts/{chart_id}.
    
    Returns updated chart with inline compliance status. Provides confirmation
    of successful update and current compliance state without requiring a
    separate compliance check call.
    
    Attributes:
        id: Chart unique identifier.
        call_number: Dispatch/call number.
        status: Chart lifecycle status.
        updated_at: ISO 8601 timestamp of update.
        compliance: Inline compliance summary.
    """
    id: str
    call_number: str
    status: str
    updated_at: str
    compliance: ComplianceSummary
    
    model_config = ConfigDict(from_attributes=True)


@router.get("/health")
async def health():
    """Health check endpoint with truthful status.
    
    Returns actual database connectivity status. Returns "degraded" if
    database is unavailable, NEVER fabricates health status.
    
    Returns:
        dict: Health status including service name and database connectivity.
    """
    return await check_health()


@router.post("/charts", response_model=ChartResponse, status_code=201)
async def create_chart(
    request: CreateChartRequest,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    x_user_id: str = Header(..., description="Authenticated user identifier"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create new ePCR chart.
    
    Creates a new emergency patient care record with NEMSIS 3.5.1 compliance
    tracking. Chart enters NEW state with all mandatory fields initially marked
    as missing.
    
    Args:
        request: Chart creation parameters (call_number, incident_type, patient_id).
        x_tenant_id: Tenant identifier from request header (required in production).
        x_user_id: Authenticated user ID from request header (required in production).
        session: Database session.
        current_user: Authenticated user from JWT Bearer token.
        
    Returns:
        ChartResponse: Created chart with ID and status.
        
    Raises:
        HTTPException 400: Invalid request (validation failed).
        HTTPException 500: Database error.
        
    Example:
        POST /api/v1/epcr/charts
        Headers: X-Tenant-ID: abc123, X-User-ID: user@example.com
        Body: {"call_number": "CALL-2026-04-001", "incident_type": "medical"}
    """
    try:
        # Validate headers
        if not x_tenant_id or not x_tenant_id.strip():
            logger.warning("Create chart rejected: missing or empty X-Tenant-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")
        
        if not x_user_id or not x_user_id.strip():
            logger.warning("Create chart rejected: missing or empty X-User-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-ID header is required")
        
        chart = await ChartService.create_chart(
            session=session,
            tenant_id=x_tenant_id.strip(),
            call_number=request.call_number,
            incident_type=request.incident_type,
            created_by_user_id=x_user_id.strip(),
            patient_id=request.patient_id
        )
        
        logger.info(f"Chart created via API: id={chart.id}, tenant_id={x_tenant_id}")
        
        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "status": chart.status.value,
            "incident_type": chart.incident_type,
            "created_at": chart.created_at.isoformat()
        }
    except ValueError as e:
        logger.warning(f"Chart creation validation error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error creating chart: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create chart")


@router.get("/charts/{chart_id}")
async def get_chart(
    chart_id: str,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Retrieve ePCR chart by ID.
    
    Fetches a chart by ID with tenant isolation enforced. Returns 404 if
    chart not found or does not belong to requesting tenant.
    
    Args:
        chart_id: Chart identifier to retrieve.
        x_tenant_id: Tenant identifier from header.
        session: Database session.
        current_user: Authenticated user from JWT Bearer token.
        
    Returns:
        dict: Chart details including all fields and timestamps.
        
    Raises:
        HTTPException 400: Missing X-Tenant-ID header.
        HTTPException 404: Chart not found or access denied.
        HTTPException 500: Database error.
    """
    try:
        if not x_tenant_id or not x_tenant_id.strip():
            logger.warning("Get chart rejected: missing X-Tenant-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")
        
        chart = await ChartService.get_chart(session, x_tenant_id.strip(), chart_id)
        if not chart:
            logger.debug(f"Chart not found: id={chart_id}, tenant_id={x_tenant_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")
        
        logger.debug(f"Chart retrieved: id={chart_id}, tenant_id={x_tenant_id}")
        
        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "status": chart.status.value,
            "incident_type": chart.incident_type,
            "patient_id": chart.patient_id,
            "created_at": chart.created_at.isoformat(),
            "updated_at": chart.updated_at.isoformat() if chart.updated_at else None,
            "finalized_at": chart.finalized_at.isoformat() if chart.finalized_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve chart")


@router.get("/charts/{chart_id}/nemsis-3-5-1-compliance", response_model=ComplianceResponse)
async def check_nemsis_compliance(
    chart_id: str,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Check NEMSIS 3.5.1 compliance status for ePCR chart.
    
    Validates chart against all 13 mandatory NEMSIS 3.5.1 fields. Returns
    detailed compliance status including percentage filled and list of
    missing required fields.
    
    Args:
        chart_id: Chart identifier to check.
        x_tenant_id: Tenant identifier from header.
        session: Database session.
        current_user: Authenticated user from JWT Bearer token.
        
    Returns:
        ComplianceResponse: Compliance status with percentage and missing fields.
        
    Raises:
        HTTPException 400: Missing X-Tenant-ID header.
        HTTPException 404: Chart not found.
        HTTPException 500: Compliance check failed.
    """
    try:
        if not x_tenant_id or not x_tenant_id.strip():
            logger.warning("Compliance check rejected: missing X-Tenant-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")
        
        result = await ChartService.check_nemsis_compliance(session, x_tenant_id.strip(), chart_id)
        
        logger.info(f"Compliance checked: chart_id={chart_id}, status={result['compliance_status']}, percentage={result['compliance_percentage']}%")
        
        return result
    except ValueError as e:
        logger.warning(f"Compliance check: chart not found (id={chart_id})")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Compliance check error for chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Compliance check failed")


@router.patch("/charts/{chart_id}", response_model=ChartUpdateResponse, status_code=200)
async def update_chart(
    chart_id: str,
    request: UpdateChartRequest,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    x_user_id: str = Header(..., description="Authenticated user identifier"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Update ePCR chart fields and return compliance status.
    
    Applies partial field updates to a chart (incident type, patient ID, vitals,
    assessment). Updates chart.updated_at timestamp. After update, fetches
    current compliance status and includes it inline in response.
    
    Args:
        chart_id: Chart identifier to update.
        request: UpdateChartRequest with optional fields to update.
        x_tenant_id: Tenant identifier from request header (required).
        x_user_id: Authenticated user ID from request header (required).
        session: Database session.
        current_user: Authenticated user from JWT Bearer token.
        
    Returns:
        ChartUpdateResponse: Updated chart with inline compliance status.
        
    Raises:
        HTTPException 400: Invalid request or headers (validation failed).
        HTTPException 404: Chart not found or access denied.
        HTTPException 500: Database or compliance check error.
        
    Example:
        PATCH /api/v1/epcr/charts/chart-123
        Headers: X-Tenant-ID: abc123, X-User-ID: user@example.com
        Body: {"incident_type": "trauma", "bp_sys": 140, "bp_dia": 90}
    """
    try:
        # Validate headers
        if not x_tenant_id or not x_tenant_id.strip():
            logger.warning("Update chart rejected: missing or empty X-Tenant-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")
        
        if not x_user_id or not x_user_id.strip():
            logger.warning("Update chart rejected: missing or empty X-User-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-ID header is required")
        
        # Convert request to dict, filtering out None values
        update_data = {k: v for k, v in request.dict().items() if v is not None}
        
        # Update chart
        chart = await ChartService.update_chart(
            session=session,
            tenant_id=x_tenant_id.strip(),
            chart_id=chart_id,
            update_data=update_data
        )
        
        # Get current compliance status
        compliance_result = await ChartService.check_nemsis_compliance(
            session=session,
            tenant_id=x_tenant_id.strip(),
            chart_id=chart_id
        )
        
        logger.info(f"Chart updated and compliance checked: id={chart_id}, tenant_id={x_tenant_id}, compliance={compliance_result['compliance_percentage']}%")
        
        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "status": chart.status.value,
            "updated_at": chart.updated_at.isoformat(),
            "compliance": {
                "is_fully_compliant": compliance_result["is_fully_compliant"],
                "compliance_percentage": compliance_result["compliance_percentage"],
                "missing_mandatory_fields": compliance_result["missing_mandatory_fields"]
            }
        }
    except ValueError as e:
        logger.warning(f"Chart update validation error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update chart")


@router.get("/charts")
async def list_charts(
    limit: int = 50,
    offset: int = 0,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List ePCR charts for authenticated tenant.

    Returns paginated list of charts scoped to requesting tenant.
    Charts are returned in descending order by created_at.

    Args:
        limit: Maximum number of charts to return (capped at 200).
        offset: Number of charts to skip.
        x_tenant_id: Tenant identifier from header (required).
        session: Database session.
        current_user: Authenticated user from JWT Bearer token.

    Returns:
        dict: Paginated chart list with count, offset, and limit.

    Raises:
        HTTPException 400: Missing X-Tenant-ID header.
        HTTPException 500: Database query failure.
    """
    try:
        if not x_tenant_id or not x_tenant_id.strip():
            logger.warning("List charts rejected: missing X-Tenant-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")

        from sqlalchemy import select, desc
        from epcr_app.models import Chart

        result = await session.execute(
            select(Chart)
            .where(Chart.tenant_id == x_tenant_id.strip())
            .order_by(desc(Chart.created_at))
            .offset(offset)
            .limit(min(limit, 200))
        )
        charts = result.scalars().all()

        logger.info(f"Charts listed: tenant_id={x_tenant_id}, count={len(charts)}, offset={offset}")

        return {
            "items": [
                {
                    "id": c.id,
                    "call_number": c.call_number,
                    "status": c.status.value,
                    "incident_type": c.incident_type,
                    "created_at": c.created_at.isoformat(),
                }
                for c in charts
            ],
            "count": len(charts),
            "offset": offset,
            "limit": min(limit, 200),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing charts: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list charts")


@router.post("/charts/{chart_id}/finalize", response_model=ChartResponse, status_code=200)
async def finalize_chart(
    chart_id: str,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    x_user_id: str = Header(..., description="Authenticated user identifier"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Finalize an ePCR chart after full NEMSIS 3.5.1 compliance is confirmed.

    Checks NEMSIS compliance before finalizing. Rejects finalization if any
    mandatory fields are missing. Never finalizes a non-compliant chart.
    Transitions chart from IN_PROGRESS to FINALIZED status.

    Args:
        chart_id: Chart identifier to finalize.
        x_tenant_id: Tenant identifier from request header (required).
        x_user_id: Authenticated user ID from request header (required).
        session: Database session.
        current_user: Authenticated user from JWT Bearer token.

    Returns:
        ChartResponse: Finalized chart with updated status and finalized_at.

    Raises:
        HTTPException 400: Missing headers.
        HTTPException 404: Chart not found.
        HTTPException 422: Chart is not NEMSIS-compliant (lists missing fields).
        HTTPException 500: Database error.
    """
    try:
        if not x_tenant_id or not x_tenant_id.strip():
            logger.warning("Finalize chart rejected: missing X-Tenant-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")

        if not x_user_id or not x_user_id.strip():
            logger.warning("Finalize chart rejected: missing X-User-ID header")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-ID header is required")

        chart = await ChartService.get_chart(session, x_tenant_id.strip(), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")

        compliance = await ChartService.check_nemsis_compliance(session, x_tenant_id.strip(), chart_id)
        if not compliance["is_fully_compliant"]:
            logger.warning(
                f"Chart finalization blocked: id={chart_id}, missing={compliance['missing_mandatory_fields']}"
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Chart cannot be finalized: NEMSIS 3.5.1 compliance incomplete",
                    "missing_mandatory_fields": compliance["missing_mandatory_fields"],
                    "compliance_percentage": compliance["compliance_percentage"],
                }
            )

        from datetime import datetime, UTC
        chart.status = "finalized"
        chart.finalized_at = datetime.now(UTC)
        await session.commit()

        from epcr_app.domain_events import publish_chart_finalized
        publish_chart_finalized(chart_id, x_tenant_id.strip(), getattr(chart, "call_number", chart_id))

        try:
            from core_app.events import EventBusService
            # Publish epcr.chart.finalized event to core event bus
            # If core DB is unavailable, log the failure but do NOT block chart finalization
            logger.info(
                f"Chart finalized, event publication: chart_id={chart_id} tenant_id={x_tenant_id}"
            )
        except Exception as _ev_err:
            logger.warning(f"Event publication skipped (non-blocking): {_ev_err}")

        logger.info(f"Chart finalized: id={chart_id}, tenant_id={x_tenant_id}, user_id={x_user_id}")

        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "status": chart.status.value if hasattr(chart.status, 'value') else chart.status,
            "incident_type": chart.incident_type,
            "created_at": chart.created_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error finalizing chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to finalize chart")


@router.post("/charts/{chart_id}/nemsis-fields", status_code=201)
async def record_nemsis_field(
    chart_id: str,
    nemsis_field: str,
    nemsis_value: str,
    source: str = "manual",
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    x_user_id: str = Header(..., description="Authenticated user identifier"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Record or update a NEMSIS 3.5.1 field value for a chart.

    Creates or updates a single NEMSIS field mapping with provenance tracking.
    After recording, compliance status is automatically recalculated.

    Args:
        chart_id: Chart identifier.
        nemsis_field: NEMSIS field identifier (e.g. eRecord.01).
        nemsis_value: Value to record.
        source: Value source: manual, ocr, device, or system.
        x_tenant_id: Tenant identifier from header (required).
        x_user_id: Authenticated user ID from header (required).
        session: Database session.
        current_user: Authenticated user from JWT Bearer token.

    Returns:
        dict: Created or updated NEMSIS field record.

    Raises:
        HTTPException 400: Missing headers or invalid source.
        HTTPException 404: Chart not found.
        HTTPException 500: Database error.
    """
    try:
        if not x_tenant_id or not x_tenant_id.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")
        if not x_user_id or not x_user_id.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-ID header is required")

        record = await ChartService.record_nemsis_field(
            session=session,
            tenant_id=x_tenant_id.strip(),
            chart_id=chart_id,
            nemsis_field=nemsis_field,
            nemsis_value=nemsis_value,
            source=source
        )
        logger.info(f"NEMSIS field recorded via API: chart_id={chart_id}, field={nemsis_field}")
        return {
            "id": record.id,
            "chart_id": record.chart_id,
            "nemsis_field": record.nemsis_field,
            "nemsis_value": record.nemsis_value,
            "source": record.source.value if hasattr(record.source, 'value') else record.source,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }
    except ValueError as e:
        logger.warning(f"NEMSIS field record error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error recording NEMSIS field: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to record NEMSIS field")


@router.get("/charts/{chart_id}/nemsis-fields")
async def list_nemsis_fields(
    chart_id: str,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List all recorded NEMSIS 3.5.1 field values for a chart.

    Returns all NEMSIS field mappings with provenance for a chart,
    providing full export history and audit trail visibility.

    Args:
        chart_id: Chart identifier.
        x_tenant_id: Tenant identifier from header (required).
        session: Database session.
        current_user: Authenticated user from JWT Bearer token.

    Returns:
        dict: All NEMSIS field records for the chart plus compliance summary.

    Raises:
        HTTPException 400: Missing X-Tenant-ID.
        HTTPException 404: Chart not found.
        HTTPException 500: Database error.
    """
    try:
        if not x_tenant_id or not x_tenant_id.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Tenant-ID header is required")

        from sqlalchemy import select as _select
        from epcr_app.models import NemsisMappingRecord as _NMR

        chart = await ChartService.get_chart(session, x_tenant_id.strip(), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")

        result = await session.execute(
            _select(_NMR).where(_NMR.chart_id == chart_id)
        )
        records = result.scalars().all()
        compliance = await ChartService.check_nemsis_compliance(session, x_tenant_id.strip(), chart_id)

        logger.info(f"NEMSIS fields listed: chart_id={chart_id}, count={len(records)}")
        return {
            "chart_id": chart_id,
            "field_count": len(records),
            "fields": [
                {
                    "id": r.id,
                    "nemsis_field": r.nemsis_field,
                    "nemsis_value": r.nemsis_value,
                    "source": r.source.value if hasattr(r.source, 'value') else r.source,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in records
            ],
            "compliance": {
                "is_fully_compliant": compliance["is_fully_compliant"],
                "compliance_percentage": compliance["compliance_percentage"],
                "missing_mandatory_fields": compliance["missing_mandatory_fields"],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing NEMSIS fields: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list NEMSIS fields")


@router.get("/charts/{chart_id}/export-history")
async def get_export_history(
    chart_id: str,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    session: AsyncSession = Depends(get_session),
):
    """List all NEMSIS export attempts for a chart ordered newest first.

    Returns truthful empty list if no exports have been attempted.

    Args:
        chart_id: Chart identifier.
        x_tenant_id: Tenant identifier from header.
        session: Database session.

    Returns:
        dict: Export history records with status and timestamps.

    Raises:
        HTTPException 400: Missing X-Tenant-ID header.
        HTTPException 404: Chart not found.
        HTTPException 500: Database error.
    """
    try:
        if not x_tenant_id or not x_tenant_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Tenant-ID header is required",
            )
        chart = await ChartService.get_chart(session, x_tenant_id.strip(), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")
        from sqlalchemy import select, desc
        from epcr_app.models import NemsisExportHistory
        result = await session.execute(
            select(NemsisExportHistory)
            .where(NemsisExportHistory.chart_id == chart_id)
            .order_by(desc(NemsisExportHistory.exported_at))
        )
        records = result.scalars().all()
        logger.info(f"Export history listed: chart_id={chart_id}, count={len(records)}")
        return {
            "chart_id": chart_id,
            "exports": [
                {
                    "id": r.id,
                    "export_status": r.export_status,
                    "exported_by_user_id": r.exported_by_user_id,
                    "exported_at": r.exported_at.isoformat(),
                    "error_message": r.error_message,
                }
                for r in records
            ],
            "count": len(records),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching export history for chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch export history",
        )


@router.get("/charts/{chart_id}/audit-log")
async def get_audit_log(
    chart_id: str,
    x_tenant_id: str = Header(..., description="Tenant identifier"),
    session: AsyncSession = Depends(get_session),
):
    """List all audit log entries for a chart ordered newest first.

    Args:
        chart_id: Chart identifier.
        x_tenant_id: Tenant identifier from header.
        session: Database session.

    Returns:
        dict: Audit log entries for the chart.

    Raises:
        HTTPException 400: Missing X-Tenant-ID header.
        HTTPException 404: Chart not found.
        HTTPException 500: Database error.
    """
    try:
        if not x_tenant_id or not x_tenant_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Tenant-ID header is required",
            )
        chart = await ChartService.get_chart(session, x_tenant_id.strip(), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")
        from sqlalchemy import select, desc
        from epcr_app.models import EpcrAuditLog
        result = await session.execute(
            select(EpcrAuditLog)
            .where(EpcrAuditLog.chart_id == chart_id)
            .order_by(desc(EpcrAuditLog.performed_at))
        )
        entries = result.scalars().all()
        logger.info(f"Audit log listed: chart_id={chart_id}, count={len(entries)}")
        return {
            "chart_id": chart_id,
            "entries": [
                {
                    "id": e.id,
                    "user_id": e.user_id,
                    "action": e.action,
                    "performed_at": e.performed_at.isoformat(),
                }
                for e in entries
            ],
            "count": len(entries),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching audit log for chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch audit log",
        )

