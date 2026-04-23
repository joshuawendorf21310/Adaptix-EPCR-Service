"""Gravity-level OCR ORM models.

These models own the generic OCR lifecycle across the platform:
job submission, source document registration, provider result capture,
per-field candidate extraction, and immutable human review audit records.

This layer is domain-agnostic. Domain services may reference OCR jobs by ID
and may project approved fields into their own bounded-context models, but
they do not own the OCR substrate itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from epcr_app.models import Base


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class OcrSourceType(str, Enum):
    """Source document classification submitted for OCR extraction."""

    PCS = "pcs"
    AOB = "aob"
    PHYSICIAN_CERTIFICATION = "physician_certification"
    TRANSPORT_CONSENT = "transport_consent"
    FACE_SHEET = "face_sheet"
    PRIOR_AUTHORIZATION = "prior_authorization"
    OTHER = "other"


class OcrJobStatus(str, Enum):
    """Processing lifecycle status for an OCR job."""

    QUEUED = "queued"
    PROCESSING = "processing"
    EXTRACTION_COMPLETE = "extraction_complete"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class OcrFieldConfidence(str, Enum):
    """Confidence tier for an extracted field candidate."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNRESOLVED = "unresolved"


class OcrFieldReviewAction(str, Enum):
    """Review action applied to a field candidate."""

    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class OcrFieldReviewStatus(str, Enum):
    """Current mutable review state of a field candidate."""

    PENDING = "pending"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class OcrJob(Base):
    """A platform OCR processing job for a submitted document.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        source_type: Type of document submitted.
        document_id: ID of the source document or signed artifact.
        transport_request_id: Optional external reference ID.
        chart_id: Optional external encounter/reference ID.
        s3_key: S3 key for the submitted source document.
        status: Current OCR job lifecycle status.
        requested_by_user_id: User who submitted the job.
        submitted_at: Submission timestamp.
        extraction_completed_at: Timestamp when provider extraction completed.
        reviewed_at: Timestamp when human review completed.
        reviewer_user_id: User who completed review.
        failure_reason: Failure reason if the job failed.
    """

    __tablename__ = "ocr_jobs"
    __table_args__ = (
        Index("ix_ocr_jobs_tenant_status_submitted_at", "tenant_id", "status", "submitted_at"),
        Index("ix_ocr_jobs_tenant_document_id", "tenant_id", "document_id"),
        Index("ix_ocr_jobs_tenant_transport_request_id", "tenant_id", "transport_request_id"),
        Index("ix_ocr_jobs_tenant_chart_id", "tenant_id", "chart_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[OcrSourceType] = mapped_column(
        SQLEnum(OcrSourceType, name="ocr_source_type"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    transport_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chart_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[OcrJobStatus] = mapped_column(
        SQLEnum(OcrJobStatus, name="ocr_job_status"),
        nullable=False,
        default=OcrJobStatus.QUEUED,
        index=True,
    )
    requested_by_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    extraction_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewer_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    sources: Mapped[list["OcrSource"]] = relationship(
        "OcrSource",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    result: Mapped["OcrResult | None"] = relationship(
        "OcrResult",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    field_candidates: Mapped[list["OcrFieldCandidate"]] = relationship(
        "OcrFieldCandidate",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class OcrSource(Base):
    """Metadata for a source page or slice submitted to an OCR job."""

    __tablename__ = "ocr_sources"
    __table_args__ = (
        Index("ix_ocr_sources_job_page_number", "job_id", "page_number"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ocr_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )

    job: Mapped["OcrJob"] = relationship("OcrJob", back_populates="sources")


class OcrResult(Base):
    """Raw provider extraction result for an OCR job.

    Stores the raw provider response for audit, replay, and re-parsing.
    There is exactly one canonical provider result row per OCR job.
    """

    __tablename__ = "ocr_results"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ocr_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    field_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )

    job: Mapped["OcrJob"] = relationship("OcrJob", back_populates="result")


class OcrFieldCandidate(Base):
    """A single extracted field candidate produced from an OCR job."""

    __tablename__ = "ocr_field_candidates"
    __table_args__ = (
        Index("ix_ocr_field_candidates_job_field_name", "job_id", "field_name"),
        Index("ix_ocr_field_candidates_job_review_status", "job_id", "review_status"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ocr_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    extracted_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[OcrFieldConfidence] = mapped_column(
        SQLEnum(OcrFieldConfidence, name="ocr_field_confidence"),
        nullable=False,
        default=OcrFieldConfidence.UNRESOLVED,
        index=True,
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bounding_box: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternative_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[OcrFieldReviewStatus] = mapped_column(
        SQLEnum(OcrFieldReviewStatus, name="ocr_field_review_status"),
        nullable=False,
        default=OcrFieldReviewStatus.PENDING,
        index=True,
    )
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    job: Mapped["OcrJob"] = relationship("OcrJob", back_populates="field_candidates")
    reviews: Mapped[list["OcrFieldReview"]] = relationship(
        "OcrFieldReview",
        back_populates="candidate",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class OcrFieldReview(Base):
    """Immutable audit record for a single field review action."""

    __tablename__ = "ocr_field_reviews"
    __table_args__ = (
        Index("ix_ocr_field_reviews_candidate_reviewed_at", "candidate_id", "reviewed_at"),
        Index("ix_ocr_field_reviews_job_reviewed_at", "job_id", "reviewed_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ocr_field_candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reviewer_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[OcrFieldReviewAction] = mapped_column(
        SQLEnum(OcrFieldReviewAction, name="ocr_field_review_action"),
        nullable=False,
        index=True,
    )
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )

    candidate: Mapped["OcrFieldCandidate"] = relationship(
        "OcrFieldCandidate",
        back_populates="reviews",
    )