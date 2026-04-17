"""Care domain transport link and encounter artifact ORM models.

These models link care encounters to TransportLink records and signed
artifacts. The care domain does not own transport data; it maintains
links by cross-domain ID reference only, preserving the polyrepo boundary.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from epcr_app.models import Base


class CareTransportLink(Base):
    """A link between a care encounter (chart) and a TransportLink request.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        chart_id: ID of the care chart (epcr domain).
        transport_request_id: Cross-domain TransportLink request ID.
        linked_by_user_id: User who established the link.
        linked_at: Timestamp when the link was created.
        pcs_artifact_id: Signed artifact ID for PCS if attached.
        aob_artifact_id: Signed artifact ID for AOB if attached.
        encounter_fields_mapped: True when transport fields have been mapped to the encounter.
        mapped_at: Timestamp when mapping was completed.
    """

    __tablename__ = "epcr_transport_links"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chart_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    transport_request_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    linked_by_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    pcs_artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    aob_artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    encounter_fields_mapped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mapped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CareEncounterArtifactLink(Base):
    """Link between a care encounter and a signed transport artifact.

    Allows billing and care to reference signed artifacts by ID and S3 key
    without pulling transport domain internals.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        chart_id: Care chart ID.
        transport_link_id: FK to CareTransportLink.
        artifact_type: Type classification (pcs, aob, consent, etc.).
        signed_artifact_id: TransportLink signed artifact ID.
        s3_key: S3 key for the signed PDF.
        linked_at: Timestamp when attached.
    """

    __tablename__ = "epcr_encounter_artifact_links"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chart_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    transport_link_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    signed_artifact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class CareOcrReviewQueue(Base):
    """Queue entry for an OCR job awaiting care clinician review.

    Populated when an OcrJob reaches REVIEW_REQUIRED status and the source
    is linked to a care chart. Care reviewers work through this queue to
    approve or correct extracted fields before NEMSIS mapping.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        ocr_job_id: FK to the OcrJob requiring review.
        chart_id: Care chart the review is linked to.
        transport_request_id: Optional transport request reference.
        assigned_to_user_id: Reviewer assigned to this entry.
        priority: Review priority level (high, normal, low).
        queued_at: Timestamp when entry was added.
        review_started_at: Timestamp when reviewer opened the job.
        review_completed_at: Timestamp when review was submitted.
        removed: True when the entry is resolved or cancelled.
    """

    __tablename__ = "epcr_ocr_review_queue"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ocr_job_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    chart_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    transport_request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    assigned_to_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal", index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    review_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
