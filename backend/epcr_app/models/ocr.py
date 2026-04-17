"""OCR job and field extraction ORM models for the care (epcr) domain.

These models own the full OCR lifecycle within the care domain:
job submission, per-field candidate extraction with confidence scoring,
human review states, and approval/rejection records.

OCR is initiated from transport document artifacts (PCS, AOB, face sheets).
Approved fields are promoted into transport_structured_extractions for
mapping into care encounter and NEMSIS binding records.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from epcr_app.models import Base


class OcrSourceType(str, Enum):
    """Source document type submitted for OCR extraction."""

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


class OcrJob(Base):
    """An OCR processing job for a transport or care document.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        source_type: Type of document submitted.
        document_id: ID of the transport document or signed artifact.
        transport_request_id: Optional cross-domain transport request reference.
        chart_id: Optional care chart this job is linked to.
        s3_key: S3 key for the source PDF.
        status: Current job status.
        requested_by_user_id: User who submitted the job.
        submitted_at: Job submission timestamp.
        extraction_completed_at: Timestamp when provider returned results.
        reviewed_at: Timestamp when operator completed review.
        reviewer_user_id: User who performed review.
        failure_reason: Reason if status is failed.
    """

    __tablename__ = "ocr_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(SQLEnum(OcrSourceType), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    transport_request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    chart_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(OcrJobStatus), nullable=False, default=OcrJobStatus.QUEUED, index=True
    )
    requested_by_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    extraction_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewer_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    sources: Mapped[list[OcrSource]] = relationship(
        "OcrSource", back_populates="job", cascade="all, delete-orphan"
    )
    results: Mapped[list[OcrResult]] = relationship(
        "OcrResult", back_populates="job", cascade="all, delete-orphan"
    )
    field_candidates: Mapped[list[OcrFieldCandidate]] = relationship(
        "OcrFieldCandidate", back_populates="job", cascade="all, delete-orphan"
    )


class OcrSource(Base):
    """Metadata for a source document page submitted to an OCR job.

    Attributes:
        id: UUID primary key.
        job_id: FK to the parent OcrJob.
        page_number: Page number within the source document.
        s3_key: S3 key for the page image or PDF slice.
        submitted_at: Submission timestamp.
    """

    __tablename__ = "ocr_sources"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    job: Mapped[OcrJob] = relationship("OcrJob", back_populates="sources")


class OcrResult(Base):
    """Raw extraction result from the OCR provider for a job.

    Stores the raw provider response for audit and replay purposes.
    Field candidates are parsed from this result.

    Attributes:
        id: UUID primary key.
        job_id: FK to the parent OcrJob.
        provider: OCR provider name.
        raw_response: Raw JSON response from provider.
        field_count: Number of fields extracted.
        received_at: Timestamp when result was received.
    """

    __tablename__ = "ocr_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    field_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    job: Mapped[OcrJob] = relationship("OcrJob", back_populates="results")


class OcrFieldCandidate(Base):
    """A single extracted field candidate from an OCR job.

    Attributes:
        id: UUID primary key.
        job_id: FK to the parent OcrJob.
        field_name: Standardized field name.
        extracted_value: Raw extracted value string.
        normalized_value: Provider-normalized value if available.
        confidence: Confidence tier (high, medium, low, unresolved).
        confidence_score: Numeric confidence score (0.0-1.0).
        page_number: Source page number.
        bounding_box: JSON-serialized bounding box coordinates.
        alternative_values: JSON-serialized list of alternative extracted values.
        review_status: 'pending', 'approved', 'corrected', 'rejected'.
        corrected_value: Operator-supplied corrected value.
        reviewer_note: Operator review note.
        reviewed_at: Timestamp of operator review.
    """

    __tablename__ = "ocr_field_candidates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    extracted_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(
        SQLEnum(OcrFieldConfidence), nullable=False, default=OcrFieldConfidence.UNRESOLVED
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bounding_box: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alternative_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    corrected_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    job: Mapped[OcrJob] = relationship("OcrJob", back_populates="field_candidates")

    reviews: Mapped[list[OcrFieldReview]] = relationship(
        "OcrFieldReview", back_populates="candidate", cascade="all, delete-orphan"
    )


class OcrFieldReview(Base):
    """Immutable audit record for a single field candidate review action.

    Attributes:
        id: UUID primary key.
        candidate_id: FK to the reviewed OcrFieldCandidate.
        job_id: Denormalized FK to the parent OcrJob.
        reviewer_user_id: User who performed the review.
        action: 'approved', 'corrected', or 'rejected'.
        corrected_value: Value used if action is corrected.
        reviewer_note: Review note.
        reviewed_at: Review timestamp.
    """

    __tablename__ = "ocr_field_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ocr_field_candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reviewer_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    corrected_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    candidate: Mapped[OcrFieldCandidate] = relationship("OcrFieldCandidate", back_populates="reviews")
