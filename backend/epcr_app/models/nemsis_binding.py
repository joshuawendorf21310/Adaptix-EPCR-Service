"""Gravity-level NEMSIS field binding and export readiness ORM models.

These models own the shared NEMSIS 3.5.1 binding, review, provenance,
and export-readiness snapshot infrastructure for extracted and normalized
clinical/operational data across the platform.

This layer is not care-owned. Domain services may reference these records
by ID and may project readiness or binding outcomes into their own bounded
contexts, but the mapping substrate itself is shared infrastructure.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from epcr_app.models import Base


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class NemsisBindingStatus(str, Enum):
    """Lifecycle status of a NEMSIS field binding."""

    PENDING = "pending"
    MAPPED = "mapped"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"


class NemsisBindingReviewAction(str, Enum):
    """Immutable review action recorded against a NEMSIS binding."""

    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"


class NemsisFieldBinding(Base):
    """Binding between a structured source value and a NEMSIS 3.5.1 element.

    Created when an approved extraction or normalized source value is mapped
    to its corresponding NEMSIS element. The binding records both the source
    value and the mapped NEMSIS value for auditability, remapping, and export.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        chart_id: Optional consuming-domain record identifier.
        extraction_id: Optional source extraction identifier.
        nemsis_element: NEMSIS 3.5.1 element identifier, for example ePatient.02.
        source_field_name: Name of the source extracted or normalized field.
        extracted_value: Raw value from the source system or extraction.
        mapped_value: NEMSIS-formatted mapped value.
        status: Binding lifecycle status.
        confidence_score: Confidence of the mapping from 0.0 to 1.0.
        mapped_at: Timestamp when mapping was applied.
        reviewed_by_user_id: User who reviewed the binding.
        reviewed_at: Timestamp of review.
        override_reason: Reason when an override was applied.
    """

    __tablename__ = "nemsis_field_bindings"
    __table_args__ = (
        Index(
            "ix_nemsis_field_bindings_tenant_chart_status",
            "tenant_id",
            "chart_id",
            "status",
        ),
        Index(
            "ix_nemsis_field_bindings_tenant_extraction",
            "tenant_id",
            "extraction_id",
        ),
        Index(
            "ix_nemsis_field_bindings_tenant_element_status",
            "tenant_id",
            "nemsis_element",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chart_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    extraction_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    nemsis_element: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_field_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    extracted_value: Mapped[str] = mapped_column(Text, nullable=False)
    mapped_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[NemsisBindingStatus] = mapped_column(
        SQLEnum(NemsisBindingStatus, name="nemsis_binding_status"),
        nullable=False,
        default=NemsisBindingStatus.PENDING,
        index=True,
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mapped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class NemsisBindingReview(Base):
    """Immutable audit record for a NEMSIS binding review action.

    Attributes:
        id: UUID primary key.
        binding_id: ID of the reviewed NemsisFieldBinding.
        reviewer_user_id: User who reviewed the binding.
        action: Approved, rejected, or overridden.
        override_value: Value used when action is overridden.
        reason: Review reason or note.
        reviewed_at: Review timestamp.
    """

    __tablename__ = "nemsis_binding_reviews"
    __table_args__ = (
        Index("ix_nemsis_binding_reviews_binding_reviewed_at", "binding_id", "reviewed_at"),
        Index("ix_nemsis_binding_reviews_reviewer_reviewed_at", "reviewer_user_id", "reviewed_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reviewer_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    action: Mapped[NemsisBindingReviewAction] = mapped_column(
        SQLEnum(NemsisBindingReviewAction, name="nemsis_binding_review_action"),
        nullable=False,
        index=True,
    )
    override_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )


class NemsisExportReadinessSnapshot(Base):
    """Point-in-time NEMSIS export readiness snapshot for a record.

    Records readiness state at a specific moment, including binding
    completion, missing required elements, and overall export eligibility.
    The newest snapshot for a given tenant and chart_id is the current state.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        chart_id: Consuming-domain record identifier.
        export_ready: True when required NEMSIS elements are bound and approved.
        required_elements_count: Count of required NEMSIS elements.
        bound_elements_count: Count of approved/bound elements.
        missing_elements: JSON-serialized list of missing required element IDs.
        blocking_count: Count of unresolved blocking elements.
        evaluated_at: Snapshot creation timestamp.
    """

    __tablename__ = "nemsis_export_readiness_snapshots"
    __table_args__ = (
        Index(
            "ix_nemsis_export_readiness_snapshots_tenant_chart_evaluated_at",
            "tenant_id",
            "chart_id",
            "evaluated_at",
        ),
        Index(
            "ix_nemsis_export_readiness_snapshots_tenant_export_ready",
            "tenant_id",
            "export_ready",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chart_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    export_ready: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    required_elements_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    bound_elements_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    missing_elements: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocking_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )


class NemsisBindingSourceLink(Base):
    """Provenance link between a NEMSIS binding and its upstream source.

    Records which upstream request and extraction produced a specific
    NEMSIS binding, enabling traceability from exported NEMSIS output
    back to the originating source record.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        binding_id: ID of the NemsisFieldBinding.
        chart_id: Optional consuming-domain record identifier.
        transport_request_id: Optional upstream request identifier.
        extraction_id: Optional source extraction identifier.
        linked_at: Timestamp when the provenance link was established.
    """

    __tablename__ = "nemsis_binding_source_links"
    __table_args__ = (
        Index(
            "ix_nemsis_binding_source_links_tenant_binding",
            "tenant_id",
            "binding_id",
        ),
        Index(
            "ix_nemsis_binding_source_links_tenant_transport_request",
            "tenant_id",
            "transport_request_id",
        ),
        Index(
            "ix_nemsis_binding_source_links_tenant_extraction",
            "tenant_id",
            "extraction_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    chart_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    transport_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    extraction_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
