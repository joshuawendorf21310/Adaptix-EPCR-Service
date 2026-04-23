"""NEMSIS validation API routes.

Provides endpoints for triggering validation, retrieving validation
history, and checking validation status before export.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user, CurrentUser
from epcr_app.services_nemsis_validation import NEMSISValidationService

router = APIRouter(prefix="/nemsis", tags=["nemsis-validation"])


class ValidationResultResponse(BaseModel):
    """Validation result response."""

    id: str
    tenant_id: str
    incident_id: str
    validation_status: str
    error_count: int
    warning_count: int
    errors_json: str | None
    warnings_json: str | None
    validation_summary_json: str | None
    created_at: str
    created_by_user_id: str


class ValidationStatusResponse(BaseModel):
    """Current validation status response."""

    incident_id: str
    has_validation: bool
    validation_status: str | None
    error_count: int
    warning_count: int
    export_blocked: bool
    block_reason: str


class ValidationHistoryResponse(BaseModel):
    """Validation history response."""

    incident_id: str
    total_validations: int
    validations: list[ValidationResultResponse]


class ValidateIncidentRequest(BaseModel):
    """Request to validate an incident."""

    incident_data: dict[str, Any] = Field(
        ..., description="Full incident data for validation"
    )


@router.post("/{incident_id}/validate", response_model=ValidationResultResponse)
def validate_incident(
    incident_id: str,
    request: ValidateIncidentRequest,
    db: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ValidationResultResponse:
    """Run NEMSIS validation on an incident and save results.

    This endpoint runs full NEMSIS 3.5.1 validation on the provided
    incident data and persists the results to the database.

    Args:
        incident_id: Incident/chart UUID
        request: Validation request with incident data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Validation result with errors and warnings

    Raises:
        HTTPException: If validation fails to execute
    """
    service = NEMSISValidationService(db)

    try:
        result = service.run_validation(
            tenant_id=str(current_user.tenant_id),
            incident_id=incident_id,
            incident_data=request.incident_data,
            user_id=str(current_user.user_id),
        )

        return ValidationResultResponse(
            id=result.id,
            tenant_id=result.tenant_id,
            incident_id=result.incident_id,
            validation_status=result.validation_status,
            error_count=result.error_count,
            warning_count=result.warning_count,
            errors_json=result.errors_json,
            warnings_json=result.warnings_json,
            validation_summary_json=result.validation_summary_json,
            created_at=result.created_at.isoformat(),
            created_by_user_id=result.created_by_user_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")


@router.get("/{incident_id}/validation-history", response_model=ValidationHistoryResponse)
def get_validation_history(
    incident_id: str,
    db: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ValidationHistoryResponse:
    """Get validation history for an incident.

    Returns all validation runs for the specified incident, ordered
    by most recent first.

    Args:
        incident_id: Incident/chart UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Validation history with all validation runs
    """
    service = NEMSISValidationService(db)
    repo = service.repo

    history = repo.list_validation_history(tenant_id=str(current_user.tenant_id), incident_id=incident_id)

    validations = [
        ValidationResultResponse(
            id=r.id,
            tenant_id=r.tenant_id,
            incident_id=r.incident_id,
            validation_status=r.validation_status,
            error_count=r.error_count,
            warning_count=r.warning_count,
            errors_json=r.errors_json,
            warnings_json=r.warnings_json,
            validation_summary_json=r.validation_summary_json,
            created_at=r.created_at.isoformat(),
            created_by_user_id=r.created_by_user_id,
        )
        for r in history
    ]

    return ValidationHistoryResponse(
        incident_id=incident_id,
        total_validations=len(validations),
        validations=validations,
    )


@router.get("/{incident_id}/validation-status", response_model=ValidationStatusResponse)
def get_validation_status(
    incident_id: str,
    db: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ValidationStatusResponse:
    """Get current validation status for an incident.

    Returns the most recent validation result and indicates whether
    export is blocked due to validation failures.

    Args:
        incident_id: Incident/chart UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Current validation status and export blocking state
    """
    service = NEMSISValidationService(db)

    result = service.get_cached_validation(tenant_id=str(current_user.tenant_id), incident_id=incident_id)

    if not result:
        return ValidationStatusResponse(
            incident_id=incident_id,
            has_validation=False,
            validation_status=None,
            error_count=0,
            warning_count=0,
            export_blocked=True,
            block_reason="No validation result found. Run validation first.",
        )

    is_blocked, block_reason = service.block_export_if_invalid(
        tenant_id=str(current_user.tenant_id), incident_id=incident_id
    )

    return ValidationStatusResponse(
        incident_id=incident_id,
        has_validation=True,
        validation_status=result.validation_status,
        error_count=result.error_count,
        warning_count=result.warning_count,
        export_blocked=is_blocked,
        block_reason=block_reason,
    )
