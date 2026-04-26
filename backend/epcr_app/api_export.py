"""NEMSIS export API routes with full lifecycle endpoints."""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from adaptix_contracts.schemas.nemsis_exports import (
    ExportDetailResponse,
    ExportHistoryResponse,
    GenerateExportRequest,
    GenerateExportResponse,
    RetryExportRequest,
    RetryExportResponse,
)
from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.services_export import NemsisExportService

router = APIRouter(prefix="/api/v1/epcr/nemsis", tags=["nemsis-exports"])


@router.post("/export-generate", response_model=GenerateExportResponse, status_code=201)
async def generate_export(
    request: GenerateExportRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GenerateExportResponse:
    """Generate NEMSIS export with readiness validation and lifecycle state.
    
    Creates export attempt with full audit trail. If chart is not ready,
    returns blocked status. If ready, proceeds through generation states.
    """
    return await NemsisExportService.generate_export(
        session=session,
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.user_id),
        request=request,
    )


@router.get("/export-history", response_model=ExportHistoryResponse, status_code=200)
async def get_export_history(
    chart_id: str = Query(..., description="Chart identifier"),
    limit: int = Query(20, ge=1, le=100, description="Result limit"),
    offset: int = Query(0, ge=0, description="Result offset"),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ExportHistoryResponse:
    """Get paginated export history for chart with total count.
    
    Returns all attempts ordered by creation time (newest first).
    """
    return await NemsisExportService.get_export_history(
        session=session,
        tenant_id=str(current_user.tenant_id),
        chart_id=chart_id,
        limit=limit,
        offset=offset,
    )


@router.get("/export/{export_id}", response_model=ExportDetailResponse, status_code=200)
async def get_export_detail(
    export_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ExportDetailResponse:
    """Get full export detail with readiness snapshot, artifact, and failure reason.
    
    Provides complete inspection view for operator review and audit.
    """
    return await NemsisExportService.get_export_detail(
        session=session,
        tenant_id=str(current_user.tenant_id),
        export_id=export_id,
    )


@router.post("/export/{export_id}/retry", response_model=RetryExportResponse, status_code=201)
async def retry_export(
    export_id: int,
    request: RetryExportRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RetryExportResponse:
    """Retry failed export with readiness re-check.
    
    Only generation_error, storage_error, timeout, and unknown failures are retryable.
    Creates new attempt with retry count incremented. If chart no longer ready,
    returns blocked status in new attempt.
    """
    return await NemsisExportService.retry_export(
        session=session,
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.user_id),
        export_id=export_id,
        request=request,
    )


@router.get("/export/{export_id}/artifact", status_code=200)
async def get_export_artifact(
    export_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Return the raw XML artifact bytes and checksum for an export attempt."""
    xml_bytes, file_name, mime_type, checksum = await NemsisExportService.get_export_artifact(
        session=session,
        tenant_id=str(current_user.tenant_id),
        export_id=export_id,
    )
    return Response(
        content=xml_bytes,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "X-Checksum-SHA256": checksum,
        },
    )
