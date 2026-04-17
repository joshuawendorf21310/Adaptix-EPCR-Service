"""NEMSIS export API routes with full lifecycle endpoints."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
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
from epcr_app.services_export import NemsisExportService

router = APIRouter(prefix="/api/v1/epcr/nemsis", tags=["nemsis-exports"])


def require_header(value: str | None, name: str) -> str:
    """Validate and extract required header value."""
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} header required",
        )
    return value.strip()


@router.post("/export-generate", response_model=GenerateExportResponse, status_code=201)
async def generate_export(
    request: GenerateExportRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> GenerateExportResponse:
    """Generate NEMSIS export with readiness validation and lifecycle state.
    
    Creates export attempt with full audit trail. If chart is not ready,
    returns blocked status. If ready, proceeds through generation states.
    """
    tenant_id = require_header(x_tenant_id, "X-Tenant-ID")
    user_id = require_header(x_user_id, "X-User-ID")

    return await NemsisExportService.generate_export(
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
        request=request,
    )


@router.get("/export-history", response_model=ExportHistoryResponse, status_code=200)
async def get_export_history(
    chart_id: str = Query(..., description="Chart identifier"),
    limit: int = Query(20, ge=1, le=100, description="Result limit"),
    offset: int = Query(0, ge=0, description="Result offset"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> ExportHistoryResponse:
    """Get paginated export history for chart with total count.
    
    Returns all attempts ordered by creation time (newest first).
    """
    tenant_id = require_header(x_tenant_id, "X-Tenant-ID")

    return await NemsisExportService.get_export_history(
        session=session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        limit=limit,
        offset=offset,
    )


@router.get("/export/{export_id}", response_model=ExportDetailResponse, status_code=200)
async def get_export_detail(
    export_id: int,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> ExportDetailResponse:
    """Get full export detail with readiness snapshot, artifact, and failure reason.
    
    Provides complete inspection view for operator review and audit.
    """
    tenant_id = require_header(x_tenant_id, "X-Tenant-ID")

    return await NemsisExportService.get_export_detail(
        session=session,
        tenant_id=tenant_id,
        export_id=export_id,
    )


@router.post("/export/{export_id}/retry", response_model=RetryExportResponse, status_code=201)
async def retry_export(
    export_id: int,
    request: RetryExportRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    session: AsyncSession = Depends(get_session),
) -> RetryExportResponse:
    """Retry failed export with readiness re-check.
    
    Only generation_error, storage_error, timeout, and unknown failures are retryable.
    Creates new attempt with retry count incremented. If chart no longer ready,
    returns blocked status in new attempt.
    """
    tenant_id = require_header(x_tenant_id, "X-Tenant-ID")
    user_id = require_header(x_user_id, "X-User-ID")

    return await NemsisExportService.retry_export(
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
        export_id=export_id,
        request=request,
    )
