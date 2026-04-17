"""NEMSIS export lifecycle service with state machine, persistence, and audit."""
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from adaptix_contracts.schemas.nemsis_exports import (
    ExportArtifactMetadata,
    ExportAttemptDetail,
    ExportAttemptSummary,
    ExportDetailResponse,
    ExportFailureType,
    ExportHistoryResponse,
    ExportLifecycleStatus,
    ExportReadinessSnapshot,
    ExportTriggerSource,
    GenerateExportRequest,
    GenerateExportResponse,
    RetryExportRequest,
    RetryExportResponse,
)
from epcr_app.models import Chart, NemsisMappingRecord
from epcr_app.models_export import NemsisExportAttempt, NemsisExportEvent
from epcr_app.nemsis_xml_builder import NemsisXmlBuilder
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator

logger = logging.getLogger(__name__)

_VALIDATOR = NemsisXSDValidator()


def _get_s3_bucket() -> str:
    """Return the configured S3 bucket name for NEMSIS export artifacts.

    Raises:
        RuntimeError: If no S3 bucket environment variable is set.

    Returns:
        S3 bucket name string.
    """
    bucket = os.environ.get("NEMSIS_EXPORT_S3_BUCKET") or os.environ.get("FILES_S3_BUCKET")
    if not bucket:
        raise RuntimeError(
            "NEMSIS_EXPORT_S3_BUCKET is not configured. "
            "Set this environment variable to persist NEMSIS export artifacts."
        )
    return bucket


class NemsisExportService:
    """Export lifecycle management with state transitions, retry logic, and audit."""

    @staticmethod
    async def _build_and_store_artifact(
        session: AsyncSession,
        *,
        chart_id: str,
        tenant_id: str,
        attempt_id: int,
    ) -> tuple[bytes, str, str]:
        """Build real NEMSIS 3.5.1 XML, validate it, upload to S3, return artifact data.

        Args:
            session: Active database session.
            chart_id: Chart identifier.
            tenant_id: Tenant identifier.
            attempt_id: Export attempt identifier used in the S3 storage key.

        Returns:
            Tuple of (xml_bytes, storage_key, sha256_hex).

        Raises:
            ValueError: If chart is not found, or if generated XML fails XSD/Schematron
                validation and assets are configured.
            RuntimeError: If S3 bucket is not configured.
            ClientError: If S3 upload fails.
        """
        chart_result = await session.execute(
            select(Chart).where(
                Chart.id == chart_id,
                Chart.tenant_id == tenant_id,
            )
        )
        chart = chart_result.scalar_one_or_none()
        if chart is None:
            raise ValueError(f"Chart {chart_id} not found for tenant {tenant_id}")

        mapping_result = await session.execute(
            select(NemsisMappingRecord).where(
                NemsisMappingRecord.chart_id == chart_id,
                NemsisMappingRecord.tenant_id == tenant_id,
            )
        )
        mapping_records = list(mapping_result.scalars().all())

        builder = NemsisXmlBuilder(chart=chart, mapping_records=mapping_records)
        xml_bytes, xml_warnings = builder.build()

        if xml_warnings:
            logger.warning(
                "NEMSIS XML built with %d NOT_RECORDED fields for chart %s: %s",
                len(xml_warnings),
                chart_id,
                xml_warnings,
            )

        validation = _VALIDATOR.validate_xml(xml_bytes)
        if not validation.get("validation_skipped", False) and not validation.get("valid", False):
            xsd_errs = validation.get("xsd_errors", [])
            sch_errs = validation.get("schematron_errors", [])
            all_errs = xsd_errs + sch_errs
            raise ValueError(
                f"Generated NEMSIS XML failed validation ({len(all_errs)} errors): "
                + "; ".join(all_errs[:5])
            )

        bucket = _get_s3_bucket()
        storage_key = f"nemsis/{tenant_id}/{chart_id}/{attempt_id}.xml"
        s3_client = boto3.client("s3")
        try:
            s3_client.put_object(
                Bucket=bucket,
                Key=storage_key,
                Body=xml_bytes,
                ContentType="application/xml",
                ServerSideEncryption="AES256",
            )
        except ClientError as exc:
            raise ClientError(exc.response, exc.operation_name) from exc

        checksum = NemsisXmlBuilder.compute_sha256(xml_bytes)
        logger.info(
            "NEMSIS artifact stored: bucket=%s key=%s size=%d sha256=%s",
            bucket,
            storage_key,
            len(xml_bytes),
            checksum[:16] + "…",
        )
        return xml_bytes, storage_key, checksum

    @staticmethod
    async def _create_event(
        session: AsyncSession,
        *,
        export_attempt_id: int,
        tenant_id: str,
        chart_id: str,
        event_type: str,
        message: str,
        from_status: str | None = None,
        to_status: str | None = None,
        detail: dict | None = None,
        user_id: str | None = None,
    ) -> None:
        """Create audit event for export attempt state change."""
        session.add(
            NemsisExportEvent(
                export_attempt_id=export_attempt_id,
                tenant_id=tenant_id,
                chart_id=chart_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                message=message,
                detail=detail or {},
                created_by_user_id=user_id,
            )
        )
        logger.debug(
            f"Export event: attempt={export_attempt_id}, type={event_type}, "
            f"from={from_status}, to={to_status}"
        )

    @staticmethod
    async def _get_readiness_snapshot(
        session: AsyncSession,
        *,
        chart_id: str,
        tenant_id: str,
    ) -> ExportReadinessSnapshot:
        """Fetch current readiness state as immutable snapshot."""
        from epcr_app.services import ChartService

        readiness = await ChartService.check_nemsis_compliance(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
        )

        return ExportReadinessSnapshot(
            ready_for_export=readiness.get("is_fully_compliant", False),
            blocker_count=len(readiness.get("missing_mandatory_fields", [])),
            warning_count=0,
            compliance_percentage=readiness.get("compliance_percentage"),
            missing_mandatory_fields=readiness.get("missing_mandatory_fields", []),
        )

    @staticmethod
    def _to_summary(row: NemsisExportAttempt) -> ExportAttemptSummary:
        """Convert ORM row to summary model."""
        return ExportAttemptSummary(
            export_id=row.id,
            chart_id=row.chart_id,
            status=ExportLifecycleStatus(row.status),
            failure_type=ExportFailureType(row.failure_type),
            message=row.message,
            trigger_source=ExportTriggerSource(row.trigger_source),
            retry_count=row.retry_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_detail(row: NemsisExportAttempt) -> ExportAttemptDetail:
        """Convert ORM row to detail model."""
        artifact = None
        if row.artifact_storage_key or row.artifact_file_name:
            artifact = ExportArtifactMetadata(
                file_name=row.artifact_file_name,
                mime_type=row.artifact_mime_type,
                size_bytes=row.artifact_size_bytes,
                storage_key=row.artifact_storage_key,
                checksum_sha256=row.artifact_checksum_sha256,
            )

        return ExportAttemptDetail(
            export_id=row.id,
            chart_id=row.chart_id,
            tenant_id=row.tenant_id,
            status=ExportLifecycleStatus(row.status),
            failure_type=ExportFailureType(row.failure_type),
            message=row.message,
            failure_reason=row.failure_reason,
            trigger_source=ExportTriggerSource(row.trigger_source),
            retry_count=row.retry_count,
            supersedes_export_id=row.supersedes_export_id,
            superseded_by_export_id=row.superseded_by_export_id,
            readiness_snapshot=ExportReadinessSnapshot(
                ready_for_export=row.ready_for_export,
                blocker_count=row.blocker_count,
                warning_count=row.warning_count,
                compliance_percentage=float(row.compliance_percentage)
                if row.compliance_percentage is not None
                else None,
                missing_mandatory_fields=row.missing_mandatory_fields or [],
            ),
            artifact=artifact,
            created_at=row.created_at,
            updated_at=row.updated_at,
            requested_at=row.requested_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )

    @staticmethod
    async def _persist_attempt(
        session: AsyncSession,
        *,
        tenant_id: str,
        user_id: str,
        chart_id: str,
        status: ExportLifecycleStatus,
        failure_type: ExportFailureType,
        message: str,
        failure_reason: str | None,
        trigger_source: ExportTriggerSource,
        retry_count: int,
        snapshot: ExportReadinessSnapshot,
        supersedes_export_id: int | None = None,
    ) -> NemsisExportAttempt:
        """Create and persist new export attempt with initial event."""
        now = datetime.now(timezone.utc)
        row = NemsisExportAttempt(
            tenant_id=tenant_id,
            chart_id=chart_id,
            status=status.value,
            failure_type=failure_type.value,
            message=message,
            failure_reason=failure_reason,
            trigger_source=trigger_source.value,
            retry_count=retry_count,
            supersedes_export_id=supersedes_export_id,
            ready_for_export=snapshot.ready_for_export,
            blocker_count=snapshot.blocker_count,
            warning_count=snapshot.warning_count,
            compliance_percentage=snapshot.compliance_percentage,
            missing_mandatory_fields=snapshot.missing_mandatory_fields,
            requested_at=now,
            created_by_user_id=user_id,
        )
        session.add(row)
        await session.flush()

        await NemsisExportService._create_event(
            session,
            export_attempt_id=row.id,
            tenant_id=tenant_id,
            chart_id=chart_id,
            event_type="attempt_created",
            from_status=None,
            to_status=row.status,
            message=message,
            detail={"failure_type": failure_type.value},
            user_id=user_id,
        )
        logger.info(
            f"Export attempt created: id={row.id}, chart={chart_id}, "
            f"status={status.value}, ready={snapshot.ready_for_export}"
        )
        return row

    @staticmethod
    async def generate_export(
        session: AsyncSession,
        *,
        tenant_id: str,
        user_id: str,
        request: GenerateExportRequest,
    ) -> GenerateExportResponse:
        """Generate export with readiness check and state lifecycle."""
        snapshot = await NemsisExportService._get_readiness_snapshot(
            session=session,
            chart_id=request.chart_id,
            tenant_id=tenant_id,
        )

        if not snapshot.ready_for_export:
            logger.warning(
                f"Export blocked for chart {request.chart_id}: "
                f"{snapshot.blocker_count} blockers"
            )
            blocked = await NemsisExportService._persist_attempt(
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                chart_id=request.chart_id,
                status=ExportLifecycleStatus.BLOCKED,
                failure_type=ExportFailureType.READINESS_BLOCKED,
                message="Export blocked by readiness requirements.",
                failure_reason="Chart is not ready for export.",
                trigger_source=request.trigger_source,
                retry_count=0,
                snapshot=snapshot,
            )
            await session.commit()
            return GenerateExportResponse(
                export_id=blocked.id,
                chart_id=blocked.chart_id,
                success=False,
                blocked=True,
                status=ExportLifecycleStatus.BLOCKED,
                failure_type=ExportFailureType.READINESS_BLOCKED,
                message=blocked.message,
                failure_reason=blocked.failure_reason,
                retry_count=blocked.retry_count,
                readiness_snapshot=snapshot,
                artifact=None,
                created_at=blocked.created_at,
                updated_at=blocked.updated_at,
            )

        attempt = await NemsisExportService._persist_attempt(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            chart_id=request.chart_id,
            status=ExportLifecycleStatus.GENERATION_REQUESTED,
            failure_type=ExportFailureType.NONE,
            message="Export generation requested.",
            failure_reason=None,
            trigger_source=request.trigger_source,
            retry_count=0,
            snapshot=snapshot,
        )

        previous_status = attempt.status
        attempt.status = ExportLifecycleStatus.GENERATION_IN_PROGRESS.value
        attempt.started_at = datetime.now(timezone.utc)
        attempt.message = "Export generation in progress."

        await NemsisExportService._create_event(
            session,
            export_attempt_id=attempt.id,
            tenant_id=tenant_id,
            chart_id=attempt.chart_id,
            event_type="generation_started",
            from_status=previous_status,
            to_status=attempt.status,
            message=attempt.message,
            user_id=user_id,
        )

        try:
            xml_bytes, storage_key, checksum = await NemsisExportService._build_and_store_artifact(
                session,
                chart_id=request.chart_id,
                tenant_id=tenant_id,
                attempt_id=attempt.id,
            )
            now = datetime.now(timezone.utc)

            attempt.status = ExportLifecycleStatus.GENERATION_SUCCEEDED.value
            attempt.failure_type = ExportFailureType.NONE.value
            attempt.failure_reason = None
            attempt.message = "Export generation succeeded."
            attempt.completed_at = now
            attempt.artifact_file_name = f"{request.chart_id}.xml"
            attempt.artifact_mime_type = "application/xml"
            attempt.artifact_size_bytes = len(xml_bytes)
            attempt.artifact_storage_key = storage_key
            attempt.artifact_checksum_sha256 = checksum

            await NemsisExportService._create_event(
                session,
                export_attempt_id=attempt.id,
                tenant_id=tenant_id,
                chart_id=attempt.chart_id,
                event_type="generation_completed",
                from_status=ExportLifecycleStatus.GENERATION_IN_PROGRESS.value,
                to_status=attempt.status,
                message=attempt.message,
                detail={"artifact_storage_key": attempt.artifact_storage_key},
                user_id=user_id,
            )
            await session.commit()
            logger.info(f"Export generation succeeded: attempt={attempt.id}, chart={request.chart_id}")

            return GenerateExportResponse(
                export_id=attempt.id,
                chart_id=attempt.chart_id,
                success=True,
                blocked=False,
                status=ExportLifecycleStatus.GENERATION_SUCCEEDED,
                failure_type=ExportFailureType.NONE,
                message=attempt.message,
                failure_reason=None,
                retry_count=attempt.retry_count,
                readiness_snapshot=snapshot,
                artifact=ExportArtifactMetadata(
                    file_name=attempt.artifact_file_name,
                    mime_type=attempt.artifact_mime_type,
                    size_bytes=attempt.artifact_size_bytes,
                    storage_key=attempt.artifact_storage_key,
                    checksum_sha256=attempt.artifact_checksum_sha256,
                ),
                created_at=attempt.created_at,
                updated_at=attempt.updated_at,
            )
        except Exception as exc:
            attempt.status = ExportLifecycleStatus.GENERATION_FAILED.value
            attempt.failure_type = ExportFailureType.GENERATION_ERROR.value
            attempt.failure_reason = str(exc)
            attempt.message = "Export generation failed."
            attempt.completed_at = datetime.now(timezone.utc)

            await NemsisExportService._create_event(
                session,
                export_attempt_id=attempt.id,
                tenant_id=tenant_id,
                chart_id=attempt.chart_id,
                event_type="generation_failed",
                from_status=ExportLifecycleStatus.GENERATION_IN_PROGRESS.value,
                to_status=attempt.status,
                message=attempt.message,
                detail={"error": str(exc)},
                user_id=user_id,
            )
            await session.commit()
            logger.error(
                f"Export generation failed: attempt={attempt.id}, chart={request.chart_id}, "
                f"error={str(exc)}"
            )

            return GenerateExportResponse(
                export_id=attempt.id,
                chart_id=attempt.chart_id,
                success=False,
                blocked=False,
                status=ExportLifecycleStatus.GENERATION_FAILED,
                failure_type=ExportFailureType.GENERATION_ERROR,
                message=attempt.message,
                failure_reason=attempt.failure_reason,
                retry_count=attempt.retry_count,
                readiness_snapshot=snapshot,
                artifact=None,
                created_at=attempt.created_at,
                updated_at=attempt.updated_at,
            )

    @staticmethod
    async def get_export_history(
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        limit: int,
        offset: int,
    ) -> ExportHistoryResponse:
        """Get paginated export history with total count."""
        total_result = await session.execute(
            select(func.count(NemsisExportAttempt.id)).where(
                NemsisExportAttempt.tenant_id == tenant_id,
                NemsisExportAttempt.chart_id == chart_id,
            )
        )
        total_count = int(total_result.scalar() or 0)

        result = await session.execute(
            select(NemsisExportAttempt)
            .where(
                NemsisExportAttempt.tenant_id == tenant_id,
                NemsisExportAttempt.chart_id == chart_id,
            )
            .order_by(NemsisExportAttempt.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = list(result.scalars().all())

        logger.debug(
            f"Export history retrieved: chart={chart_id}, total={total_count}, "
            f"limit={limit}, offset={offset}"
        )
        return ExportHistoryResponse(
            chart_id=chart_id,
            total_count=total_count,
            limit=limit,
            offset=offset,
            exports=[NemsisExportService._to_summary(row) for row in rows],
        )

    @staticmethod
    async def get_export_detail(
        session: AsyncSession,
        *,
        tenant_id: str,
        export_id: int,
    ) -> ExportDetailResponse:
        """Get full export detail with readiness snapshot and artifact."""
        result = await session.execute(
            select(NemsisExportAttempt).where(
                NemsisExportAttempt.id == export_id,
                NemsisExportAttempt.tenant_id == tenant_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            logger.warning(f"Export not found: id={export_id}, tenant={tenant_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export attempt not found")

        logger.debug(f"Export detail retrieved: id={export_id}, chart={row.chart_id}")
        return ExportDetailResponse(export=NemsisExportService._to_detail(row))

    @staticmethod
    async def retry_export(
        session: AsyncSession,
        *,
        tenant_id: str,
        user_id: str,
        export_id: int,
        request: RetryExportRequest,
    ) -> RetryExportResponse:
        """Retry failed export with readiness re-check."""
        result = await session.execute(
            select(NemsisExportAttempt).where(
                NemsisExportAttempt.id == export_id,
                NemsisExportAttempt.tenant_id == tenant_id,
            )
        )
        original = result.scalar_one_or_none()
        if original is None:
            logger.warning(f"Original export not found for retry: id={export_id}, tenant={tenant_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Original export attempt not found",
            )

        if original.status != ExportLifecycleStatus.GENERATION_FAILED.value:
            logger.warning(
                f"Retry not allowed: attempt={export_id}, status={original.status} "
                f"(only generation_failed allowed)"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only failed export attempts may be retried",
            )

        if original.failure_type not in {
            ExportFailureType.GENERATION_ERROR.value,
            ExportFailureType.STORAGE_ERROR.value,
            ExportFailureType.TIMEOUT.value,
            ExportFailureType.UNKNOWN.value,
        }:
            logger.warning(
                f"Retry not allowed: attempt={export_id}, "
                f"failure_type={original.failure_type} (not retryable)"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This export failure type is not retryable",
            )

        snapshot = await NemsisExportService._get_readiness_snapshot(
            session=session,
            chart_id=original.chart_id,
            tenant_id=tenant_id,
        )

        new_retry_count = original.retry_count + 1

        if not snapshot.ready_for_export:
            logger.warning(
                f"Retry blocked by readiness: attempt={export_id}, "
                f"chart={original.chart_id}, blockers={snapshot.blocker_count}"
            )
            blocked_retry = await NemsisExportService._persist_attempt(
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                chart_id=original.chart_id,
                status=ExportLifecycleStatus.BLOCKED,
                failure_type=ExportFailureType.READINESS_BLOCKED,
                message="Retry blocked by readiness requirements.",
                failure_reason="Chart is no longer ready for export.",
                trigger_source=request.trigger_source,
                retry_count=new_retry_count,
                snapshot=snapshot,
                supersedes_export_id=original.id,
            )
            original.superseded_by_export_id = blocked_retry.id
            await session.commit()

            return RetryExportResponse(
                original_export_id=original.id,
                new_export_id=blocked_retry.id,
                success=False,
                blocked=True,
                status=ExportLifecycleStatus.BLOCKED,
                failure_type=ExportFailureType.READINESS_BLOCKED,
                message=blocked_retry.message,
                failure_reason=blocked_retry.failure_reason,
                retry_count=blocked_retry.retry_count,
                readiness_snapshot=snapshot,
                created_at=blocked_retry.created_at,
                updated_at=blocked_retry.updated_at,
            )

        retry_attempt = await NemsisExportService._persist_attempt(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            chart_id=original.chart_id,
            status=ExportLifecycleStatus.GENERATION_REQUESTED,
            failure_type=ExportFailureType.NONE,
            message="Retry requested for failed export.",
            failure_reason=None,
            trigger_source=request.trigger_source,
            retry_count=new_retry_count,
            snapshot=snapshot,
            supersedes_export_id=original.id,
        )
        original.superseded_by_export_id = retry_attempt.id
        await session.flush()

        try:
            retry_attempt.status = ExportLifecycleStatus.GENERATION_IN_PROGRESS.value
            retry_attempt.started_at = datetime.now(timezone.utc)

            xml_bytes, storage_key, checksum = await NemsisExportService._build_and_store_artifact(
                session,
                chart_id=original.chart_id,
                tenant_id=tenant_id,
                attempt_id=retry_attempt.id,
            )

            retry_attempt.status = ExportLifecycleStatus.GENERATION_SUCCEEDED.value
            retry_attempt.message = "Retry generation succeeded."
            retry_attempt.completed_at = datetime.now(timezone.utc)
            retry_attempt.artifact_file_name = f"{retry_attempt.chart_id}.xml"
            retry_attempt.artifact_mime_type = "application/xml"
            retry_attempt.artifact_size_bytes = len(xml_bytes)
            retry_attempt.artifact_storage_key = storage_key
            retry_attempt.artifact_checksum_sha256 = checksum

            await NemsisExportService._create_event(
                session,
                export_attempt_id=retry_attempt.id,
                tenant_id=tenant_id,
                chart_id=retry_attempt.chart_id,
                event_type="retry_completed",
                from_status=ExportLifecycleStatus.GENERATION_IN_PROGRESS.value,
                to_status=retry_attempt.status,
                message=retry_attempt.message,
                user_id=user_id,
            )
            await session.commit()
            logger.info(
                f"Retry generation succeeded: original={original.id}, "
                f"new={retry_attempt.id}, chart={original.chart_id}"
            )

            return RetryExportResponse(
                original_export_id=original.id,
                new_export_id=retry_attempt.id,
                success=True,
                blocked=False,
                status=ExportLifecycleStatus.GENERATION_SUCCEEDED,
                failure_type=ExportFailureType.NONE,
                message=retry_attempt.message,
                failure_reason=None,
                retry_count=retry_attempt.retry_count,
                readiness_snapshot=snapshot,
                created_at=retry_attempt.created_at,
                updated_at=retry_attempt.updated_at,
            )
        except Exception as exc:
            retry_attempt.status = ExportLifecycleStatus.GENERATION_FAILED.value
            retry_attempt.failure_type = ExportFailureType.GENERATION_ERROR.value
            retry_attempt.failure_reason = str(exc)
            retry_attempt.message = "Retry generation failed."
            retry_attempt.completed_at = datetime.now(timezone.utc)

            await NemsisExportService._create_event(
                session,
                export_attempt_id=retry_attempt.id,
                tenant_id=tenant_id,
                chart_id=retry_attempt.chart_id,
                event_type="retry_failed",
                from_status=ExportLifecycleStatus.GENERATION_IN_PROGRESS.value,
                to_status=retry_attempt.status,
                message=retry_attempt.message,
                detail={"error": str(exc)},
                user_id=user_id,
            )
            await session.commit()
            logger.error(
                f"Retry generation failed: original={original.id}, "
                f"new={retry_attempt.id}, chart={original.chart_id}, error={str(exc)}"
            )

            return RetryExportResponse(
                original_export_id=original.id,
                new_export_id=retry_attempt.id,
                success=False,
                blocked=False,
                status=ExportLifecycleStatus.GENERATION_FAILED,
                failure_type=ExportFailureType.GENERATION_ERROR,
                message=retry_attempt.message,
                failure_reason=retry_attempt.failure_reason,
                retry_count=retry_attempt.retry_count,
                readiness_snapshot=snapshot,
                created_at=retry_attempt.created_at,
                updated_at=retry_attempt.updated_at,
            )
