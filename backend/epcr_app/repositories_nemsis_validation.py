"""NEMSIS validation result repository.

Provides data access layer for NEMSIS validation results, errors,
and export job tracking with tenant isolation enforcement.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from epcr_app.models_nemsis_validation import (
    NEMSISExportJob,
    NEMSISValidationError,
    NEMSISValidationResult,
    ValidationStatus,
)


class NEMSISValidationRepository:
    """Repository for NEMSIS validation persistence."""

    def __init__(self, db: Session):
        self.db = db

    def save_validation_result(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        validation_status: str,
        errors: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        summary: dict[str, Any],
        created_by_user_id: str,
    ) -> NEMSISValidationResult:
        """Save a new validation result with errors and warnings.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            validation_status: Pass, fail, or warning
            errors: List of error dictionaries
            warnings: List of warning dictionaries
            summary: Validation summary metadata
            created_by_user_id: User who triggered validation

        Returns:
            Persisted NEMSISValidationResult instance
        """
        result = NEMSISValidationResult(
            id=str(uuid4()),
            tenant_id=tenant_id,
            incident_id=incident_id,
            validation_status=validation_status,
            errors_json=json.dumps(errors) if errors else None,
            warnings_json=json.dumps(warnings) if warnings else None,
            validation_summary_json=json.dumps(summary),
            error_count=len(errors),
            warning_count=len(warnings),
            created_by_user_id=created_by_user_id,
            created_at=datetime.now(UTC),
        )

        self.db.add(result)

        # Create detailed error records
        for error_data in errors:
            error = NEMSISValidationError(
                id=str(uuid4()),
                result_id=result.id,
                tenant_id=tenant_id,
                element_id=error_data.get("element_id"),
                error_code=error_data.get("error_code"),
                error_message=error_data.get("message", ""),
                severity="error",
                field_path=error_data.get("field_path"),
                current_value=error_data.get("current_value"),
                expected_value=error_data.get("expected_value"),
                created_at=datetime.now(UTC),
            )
            self.db.add(error)

        # Create warning records
        for warn_data in warnings:
            warning = NEMSISValidationError(
                id=str(uuid4()),
                result_id=result.id,
                tenant_id=tenant_id,
                element_id=warn_data.get("element_id"),
                error_code=warn_data.get("error_code"),
                error_message=warn_data.get("message", ""),
                severity="warning",
                field_path=warn_data.get("field_path"),
                current_value=warn_data.get("current_value"),
                expected_value=warn_data.get("expected_value"),
                created_at=datetime.now(UTC),
            )
            self.db.add(warning)

        self.db.commit()
        self.db.refresh(result)
        return result

    def get_validation_result(
        self, *, tenant_id: str, incident_id: str
    ) -> NEMSISValidationResult | None:
        """Get the most recent validation result for an incident.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID

        Returns:
            Latest validation result or None
        """
        stmt = (
            select(NEMSISValidationResult)
            .where(
                NEMSISValidationResult.tenant_id == tenant_id,
                NEMSISValidationResult.incident_id == incident_id,
                NEMSISValidationResult.deleted_at.is_(None),
            )
            .order_by(NEMSISValidationResult.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def list_validation_history(
        self, *, tenant_id: str, incident_id: str, limit: int = 50
    ) -> list[NEMSISValidationResult]:
        """Get validation history for an incident.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            limit: Maximum number of results

        Returns:
            List of validation results ordered by newest first
        """
        stmt = (
            select(NEMSISValidationResult)
            .where(
                NEMSISValidationResult.tenant_id == tenant_id,
                NEMSISValidationResult.incident_id == incident_id,
                NEMSISValidationResult.deleted_at.is_(None),
            )
            .order_by(NEMSISValidationResult.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_validation_errors(
        self, *, tenant_id: str, result_id: str
    ) -> list[NEMSISValidationError]:
        """Get detailed errors for a validation result.

        Args:
            tenant_id: Tenant UUID
            result_id: Validation result UUID

        Returns:
            List of validation errors and warnings
        """
        stmt = (
            select(NEMSISValidationError)
            .where(
                NEMSISValidationError.tenant_id == tenant_id,
                NEMSISValidationError.result_id == result_id,
                NEMSISValidationError.deleted_at.is_(None),
            )
            .order_by(NEMSISValidationError.severity.desc(), NEMSISValidationError.created_at)
        )
        return list(self.db.execute(stmt).scalars().all())

    def create_export_job(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        validation_result_id: str | None,
        created_by_user_id: str,
    ) -> NEMSISExportJob:
        """Create a new export job.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            validation_result_id: Optional validation result UUID
            created_by_user_id: User who initiated export

        Returns:
            Persisted NEMSISExportJob instance
        """
        job = NEMSISExportJob(
            id=str(uuid4()),
            tenant_id=tenant_id,
            incident_id=incident_id,
            validation_result_id=validation_result_id,
            status="pending",
            created_by_user_id=created_by_user_id,
            created_at=datetime.now(UTC),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def update_export_job_status(
        self,
        *,
        tenant_id: str,
        job_id: str,
        status: str,
        error_message: str | None = None,
        s3_bucket: str | None = None,
        s3_key: str | None = None,
        file_size_bytes: int | None = None,
        sha256: str | None = None,
    ) -> NEMSISExportJob | None:
        """Update export job status and metadata.

        Args:
            tenant_id: Tenant UUID
            job_id: Export job UUID
            status: New status
            error_message: Optional error message
            s3_bucket: Optional S3 bucket
            s3_key: Optional S3 key
            file_size_bytes: Optional file size
            sha256: Optional SHA256 hash

        Returns:
            Updated export job or None if not found
        """
        stmt = select(NEMSISExportJob).where(
            NEMSISExportJob.tenant_id == tenant_id,
            NEMSISExportJob.id == job_id,
            NEMSISExportJob.deleted_at.is_(None),
        )
        job = self.db.execute(stmt).scalars().first()

        if not job:
            return None

        job.status = status
        job.version += 1

        if error_message:
            job.error_message = error_message
            job.failed_at = datetime.now(UTC)
            job.retry_count += 1

        if s3_bucket:
            job.s3_bucket = s3_bucket
        if s3_key:
            job.s3_key = s3_key
        if file_size_bytes:
            job.file_size_bytes = file_size_bytes
        if sha256:
            job.sha256 = sha256

        if status == "exporting" and not job.started_at:
            job.started_at = datetime.now(UTC)
        elif status == "exported":
            job.completed_at = datetime.now(UTC)

        self.db.commit()
        self.db.refresh(job)
        return job

    def get_export_job(self, *, tenant_id: str, job_id: str) -> NEMSISExportJob | None:
        """Get an export job by ID.

        Args:
            tenant_id: Tenant UUID
            job_id: Export job UUID

        Returns:
            Export job or None
        """
        stmt = (
            select(NEMSISExportJob)
            .options(joinedload(NEMSISExportJob.validation_result))
            .where(
                NEMSISExportJob.tenant_id == tenant_id,
                NEMSISExportJob.id == job_id,
                NEMSISExportJob.deleted_at.is_(None),
            )
        )
        return self.db.execute(stmt).scalars().first()

    def list_export_jobs(
        self, *, tenant_id: str, incident_id: str, limit: int = 50
    ) -> list[NEMSISExportJob]:
        """List export jobs for an incident.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            limit: Maximum number of results

        Returns:
            List of export jobs ordered by newest first
        """
        stmt = (
            select(NEMSISExportJob)
            .where(
                NEMSISExportJob.tenant_id == tenant_id,
                NEMSISExportJob.incident_id == incident_id,
                NEMSISExportJob.deleted_at.is_(None),
            )
            .order_by(NEMSISExportJob.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())
