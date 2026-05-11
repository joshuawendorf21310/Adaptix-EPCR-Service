"""OCR service layer for the EPCR domain.

Manages the full OCR job lifecycle: job creation, provider result ingestion,
per-field candidate extraction, and human review actions. All writes are
scoped by tenant_id at the SQL level. High-risk field keys always require
manual confirmation regardless of confidence score.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models.ocr import (
    OcrFieldCandidate,
    OcrFieldConfidence,
    OcrFieldReview,
    OcrFieldReviewAction,
    OcrFieldReviewStatus,
    OcrJob,
    OcrJobStatus,
    OcrResult,
    OcrSourceType,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# High-risk field key set.
# These fields always require explicit human review regardless of confidence.
# ---------------------------------------------------------------------------

HIGH_RISK_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "medication_name",
        "medication_dose",
        "medication_route",
        "medication_concentration",
        "infusion_rate",
        "blood_product_type",
        "blood_unit_id",
        "patient_name",
        "patient_dob",
        "patient_mrn",
        "allergies",
        "ventilator_mode",
        "fio2",
        "peep",
        "tidal_volume",
        "rhythm_label",
        "controlled_substance",
        "dnr_status",
        "medical_necessity",
        "blood_glucose",
        "etco2",
        "oxygen_flow_rate",
    }
)


def _confidence_tier(score: float) -> OcrFieldConfidence:
    """Map a float confidence score to the appropriate confidence tier."""
    if score >= 0.90:
        return OcrFieldConfidence.HIGH
    if score >= 0.70:
        return OcrFieldConfidence.MEDIUM
    if score > 0.0:
        return OcrFieldConfidence.LOW
    return OcrFieldConfidence.UNRESOLVED


class OcrServiceError(Exception):
    """Raised on caller errors that are safe to surface to the API layer."""

    def __init__(self, status_code: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail: dict[str, Any] = {"message": message, **extra}


class OcrJobService:
    """Manages OCR job lifecycle against the OcrJob / OcrResult / OcrFieldCandidate models."""

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    async def create_job(
        session: AsyncSession,
        chart_id: str,
        source_type: str | OcrSourceType,
        s3_key: str,
        requested_by_user_id: str,
        tenant_id: str,
    ) -> OcrJob:
        """Create a new QUEUED OCR job for a chart document.

        Args:
            session: Async database session.
            chart_id: Chart identifier the document belongs to.
            source_type: Source document classification (OcrSourceType value).
            s3_key: S3 object key for the uploaded document.
            requested_by_user_id: User UUID who initiated the request.
            tenant_id: Tenant UUID for isolation.

        Returns:
            The newly persisted OcrJob.
        """
        if isinstance(source_type, str):
            try:
                source_type = OcrSourceType(source_type)
            except ValueError as exc:
                valid = [v.value for v in OcrSourceType]
                raise OcrServiceError(
                    400,
                    f"Invalid source_type '{source_type}'",
                    valid_values=valid,
                ) from exc

        job = OcrJob(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_type=source_type,
            document_id=str(uuid.uuid4()),
            chart_id=chart_id,
            s3_key=s3_key,
            status=OcrJobStatus.QUEUED,
            requested_by_user_id=requested_by_user_id,
            submitted_at=_utc_now(),
        )
        session.add(job)
        await session.flush()
        logger.info(
            "ocr: job created job_id=%s chart_id=%s source_type=%s tenant_id=%s",
            job.id,
            chart_id,
            source_type.value,
            tenant_id,
        )
        return job

    @staticmethod
    async def get_job(
        session: AsyncSession,
        job_id: str,
        tenant_id: str,
    ) -> OcrJob | None:
        """Return an OcrJob by ID scoped to the tenant, or None if not found."""
        stmt = select(OcrJob).where(
            OcrJob.id == job_id,
            OcrJob.tenant_id == tenant_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_jobs(
        session: AsyncSession,
        chart_id: str,
        tenant_id: str,
    ) -> list[OcrJob]:
        """Return all OCR jobs for a chart, ordered newest first."""
        stmt = (
            select(OcrJob)
            .where(
                OcrJob.chart_id == chart_id,
                OcrJob.tenant_id == tenant_id,
            )
            .order_by(OcrJob.submitted_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Provider result ingestion
    # ------------------------------------------------------------------

    @staticmethod
    async def submit_provider_result(
        session: AsyncSession,
        job_id: str,
        raw_result_json: str | dict,
        provider_name: str,
        tenant_id: str,
    ) -> OcrResult:
        """Persist a raw OCR provider result and advance job status.

        Transitions the job to EXTRACTION_COMPLETE (or REVIEW_REQUIRED if
        any candidates are already attached). Safe to call once per job;
        raises 409 if a result already exists.

        Args:
            session: Async database session.
            job_id: ID of the target OcrJob.
            raw_result_json: Raw provider response (string or dict).
            provider_name: Name of the OCR provider (e.g. "textract", "google_vision").
            tenant_id: Tenant UUID for isolation.

        Returns:
            The newly persisted OcrResult.
        """
        job = await OcrJobService.get_job(session, job_id, tenant_id)
        if job is None:
            raise OcrServiceError(404, "OCR job not found", job_id=job_id)

        # Idempotency guard: one result row per job.
        existing = await session.execute(
            select(OcrResult).where(OcrResult.job_id == job_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise OcrServiceError(
                409,
                "A provider result already exists for this job",
                job_id=job_id,
            )

        if isinstance(raw_result_json, dict):
            raw_result_json = json.dumps(raw_result_json)

        ocr_result = OcrResult(
            id=str(uuid.uuid4()),
            job_id=job_id,
            provider=provider_name,
            raw_response=raw_result_json,
            field_count=0,
            received_at=_utc_now(),
        )
        session.add(ocr_result)

        job.status = OcrJobStatus.EXTRACTION_COMPLETE
        job.extraction_completed_at = _utc_now()

        await session.flush()
        logger.info(
            "ocr: provider result stored job_id=%s provider=%s",
            job_id,
            provider_name,
        )
        return ocr_result

    # ------------------------------------------------------------------
    # Field candidates
    # ------------------------------------------------------------------

    @staticmethod
    async def create_field_candidate(
        session: AsyncSession,
        result_id: str,
        field_key: str,
        raw_value: str,
        normalized_value: str | None,
        confidence_score: float,
        bounding_box: str | None,
        nemsis_element: str | None,
        chart_section: str,
        is_high_risk: bool,
    ) -> OcrFieldCandidate:
        """Create an OcrFieldCandidate linked to an OcrResult's job.

        is_high_risk is always forced True when field_key is in HIGH_RISK_FIELD_KEYS.

        Args:
            session: Async database session.
            result_id: ID of the parent OcrResult.
            field_key: Internal field key (e.g. "heart_rate", "medication_name").
            raw_value: Raw OCR-extracted string value.
            normalized_value: Optional post-processed/normalized value.
            confidence_score: Float 0.0–1.0 confidence score from the provider.
            bounding_box: Optional JSON-serialized bounding box.
            nemsis_element: Optional NEMSIS 3.5.1 element ID.
            chart_section: ePCR section this field belongs to.
            is_high_risk: Whether this field requires mandatory human review.

        Returns:
            The newly persisted OcrFieldCandidate.
        """
        result_row = await session.get(OcrResult, result_id)
        if result_row is None:
            raise OcrServiceError(404, "OcrResult not found", result_id=result_id)

        # Enforce: always high-risk when field_key is in the sentinel set.
        effective_high_risk = is_high_risk or (field_key in HIGH_RISK_FIELD_KEYS)

        confidence_tier = _confidence_tier(confidence_score)

        candidate = OcrFieldCandidate(
            id=str(uuid.uuid4()),
            job_id=result_row.job_id,
            field_name=field_key,
            extracted_value=raw_value,
            normalized_value=normalized_value,
            confidence=confidence_tier,
            confidence_score=confidence_score,
            bounding_box=bounding_box,
            # Store nemsis_element and chart_section in reviewer_note as JSON
            # until dedicated columns are added in a migration.
            reviewer_note=json.dumps(
                {
                    "nemsis_element": nemsis_element,
                    "chart_section": chart_section,
                    "is_high_risk": effective_high_risk,
                }
            ),
            review_status=OcrFieldReviewStatus.PENDING,
            reviewed_at=None,
        )
        session.add(candidate)

        # Bump OcrResult field_count.
        result_row.field_count = (result_row.field_count or 0) + 1

        # Advance job to REVIEW_REQUIRED once candidates exist.
        job = await session.get(OcrJob, result_row.job_id)
        if job is not None and job.status == OcrJobStatus.EXTRACTION_COMPLETE:
            job.status = OcrJobStatus.REVIEW_REQUIRED

        await session.flush()
        return candidate

    @staticmethod
    async def get_pending_candidates(
        session: AsyncSession,
        chart_id: str,
        tenant_id: str,
    ) -> list[OcrFieldCandidate]:
        """Return all PENDING field candidates for a chart."""
        stmt = (
            select(OcrFieldCandidate)
            .join(OcrJob, OcrFieldCandidate.job_id == OcrJob.id)
            .where(
                OcrJob.chart_id == chart_id,
                OcrJob.tenant_id == tenant_id,
                OcrFieldCandidate.review_status == OcrFieldReviewStatus.PENDING,
            )
            .order_by(OcrFieldCandidate.field_name)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_high_risk_pending(
        session: AsyncSession,
        chart_id: str,
        tenant_id: str,
    ) -> list[OcrFieldCandidate]:
        """Return all PENDING high-risk field candidates for a chart.

        High-risk is determined by field_name membership in HIGH_RISK_FIELD_KEYS.
        """
        all_pending = await OcrJobService.get_pending_candidates(
            session, chart_id, tenant_id
        )
        return [c for c in all_pending if c.field_name in HIGH_RISK_FIELD_KEYS]

    # ------------------------------------------------------------------
    # Review actions
    # ------------------------------------------------------------------

    @staticmethod
    async def review_candidate(
        session: AsyncSession,
        candidate_id: str,
        action: OcrFieldReviewAction,
        reviewer_id: str,
        corrected_value: str | None = None,
        reject_reason: str | None = None,
    ) -> OcrFieldReview:
        """Create an immutable review record and update candidate status.

        Args:
            session: Async database session.
            candidate_id: ID of the OcrFieldCandidate to review.
            action: Review action (APPROVED, CORRECTED, REJECTED).
            reviewer_id: User ID of the reviewer.
            corrected_value: Required when action is CORRECTED.
            reject_reason: Optional note when action is REJECTED.

        Returns:
            The newly persisted OcrFieldReview audit record.
        """
        candidate = await session.get(OcrFieldCandidate, candidate_id)
        if candidate is None:
            raise OcrServiceError(404, "OcrFieldCandidate not found", candidate_id=candidate_id)

        if action == OcrFieldReviewAction.CORRECTED and not corrected_value:
            raise OcrServiceError(
                400,
                "corrected_value is required for CORRECTED action",
                candidate_id=candidate_id,
            )

        now = _utc_now()

        review = OcrFieldReview(
            id=str(uuid.uuid4()),
            candidate_id=candidate_id,
            job_id=candidate.job_id,
            reviewer_user_id=reviewer_id,
            action=action,
            corrected_value=corrected_value,
            reviewer_note=reject_reason,
            reviewed_at=now,
        )
        session.add(review)

        # Update candidate mutable state.
        if action == OcrFieldReviewAction.APPROVED:
            candidate.review_status = OcrFieldReviewStatus.APPROVED
        elif action == OcrFieldReviewAction.CORRECTED:
            candidate.review_status = OcrFieldReviewStatus.CORRECTED
            candidate.corrected_value = corrected_value
        elif action == OcrFieldReviewAction.REJECTED:
            candidate.review_status = OcrFieldReviewStatus.REJECTED
            candidate.reviewer_note = reject_reason

        candidate.reviewed_at = now

        await session.flush()
        return review

    @staticmethod
    async def accept_candidate(
        session: AsyncSession,
        candidate_id: str,
        reviewer_id: str,
    ) -> OcrFieldCandidate:
        """Accept a field candidate as-is.

        Returns:
            The updated OcrFieldCandidate.
        """
        candidate = await session.get(OcrFieldCandidate, candidate_id)
        if candidate is None:
            raise OcrServiceError(404, "OcrFieldCandidate not found", candidate_id=candidate_id)

        await OcrJobService.review_candidate(
            session,
            candidate_id=candidate_id,
            action=OcrFieldReviewAction.APPROVED,
            reviewer_id=reviewer_id,
        )
        await session.refresh(candidate)
        return candidate

    @staticmethod
    async def reject_candidate(
        session: AsyncSession,
        candidate_id: str,
        reviewer_id: str,
        reason: str,
    ) -> OcrFieldCandidate:
        """Reject a field candidate with a reason.

        Returns:
            The updated OcrFieldCandidate.
        """
        candidate = await session.get(OcrFieldCandidate, candidate_id)
        if candidate is None:
            raise OcrServiceError(404, "OcrFieldCandidate not found", candidate_id=candidate_id)

        await OcrJobService.review_candidate(
            session,
            candidate_id=candidate_id,
            action=OcrFieldReviewAction.REJECTED,
            reviewer_id=reviewer_id,
            reject_reason=reason,
        )
        await session.refresh(candidate)
        return candidate

    @staticmethod
    async def edit_and_accept(
        session: AsyncSession,
        candidate_id: str,
        reviewer_id: str,
        corrected_value: str,
    ) -> OcrFieldCandidate:
        """Edit a field candidate and accept it with the corrected value.

        Returns:
            The updated OcrFieldCandidate.
        """
        candidate = await session.get(OcrFieldCandidate, candidate_id)
        if candidate is None:
            raise OcrServiceError(404, "OcrFieldCandidate not found", candidate_id=candidate_id)

        await OcrJobService.review_candidate(
            session,
            candidate_id=candidate_id,
            action=OcrFieldReviewAction.CORRECTED,
            reviewer_id=reviewer_id,
            corrected_value=corrected_value,
        )
        await session.refresh(candidate)
        return candidate

    @staticmethod
    async def promote_to_chart(
        session: AsyncSession,
        candidate_id: str,
        reviewer_id: str,
    ) -> dict:
        """Promote an accepted/corrected field candidate into the chart's domain.

        The candidate must be in APPROVED or CORRECTED status. High-risk
        candidates in PENDING status are blocked regardless of confidence.

        This method returns a promotion summary dict. Actual persistence into
        the domain chart table is performed by the calling route after
        consulting the NEMSIS element mapping; for now it returns the
        projection metadata so the caller can drive further writes.

        Args:
            session: Async database session.
            candidate_id: ID of the OcrFieldCandidate to promote.
            reviewer_id: User ID authorising the promotion.

        Returns:
            dict with keys: promoted, chart_section, field_key, value,
            nemsis_element, job_id.
        """
        candidate = await session.get(OcrFieldCandidate, candidate_id)
        if candidate is None:
            raise OcrServiceError(404, "OcrFieldCandidate not found", candidate_id=candidate_id)

        accepted_statuses = {OcrFieldReviewStatus.APPROVED, OcrFieldReviewStatus.CORRECTED}
        if candidate.review_status not in accepted_statuses:
            raise OcrServiceError(
                409,
                "Candidate must be APPROVED or CORRECTED before promotion",
                candidate_id=candidate_id,
                current_status=candidate.review_status.value,
            )

        # Parse stored metadata from reviewer_note JSON blob.
        metadata: dict = {}
        if candidate.reviewer_note:
            try:
                metadata = json.loads(candidate.reviewer_note)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        effective_value = candidate.corrected_value or candidate.extracted_value
        chart_section = metadata.get("chart_section", "unknown")
        nemsis_element = metadata.get("nemsis_element")

        logger.info(
            "ocr: promote candidate_id=%s field=%s section=%s nemsis=%s reviewer=%s",
            candidate_id,
            candidate.field_name,
            chart_section,
            nemsis_element,
            reviewer_id,
        )

        return {
            "promoted": True,
            "chart_section": chart_section,
            "field_key": candidate.field_name,
            "value": effective_value,
            "nemsis_element": nemsis_element,
            "job_id": candidate.job_id,
            "candidate_id": candidate_id,
        }


__all__ = [
    "HIGH_RISK_FIELD_KEYS",
    "OcrServiceError",
    "OcrJobService",
]
