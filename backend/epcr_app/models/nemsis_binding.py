"""Care domain NEMSIS field binding and transport binding ORM models.

These models own the NEMSIS 3.5.1 field binding layer for fields derived
from transport and OCR sources. They are subordinate to the existing
NEMSIS compliance tracking in epcr_app.models and provide the linkage
between structured transport extractions and NEMSIS-mapped output.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from epcr_app.models import Base


class NemsisBidingStatus(str, Enum):
    """Status of a NEMSIS field binding."""

    PENDING = "pending"
    MAPPED = "mapped"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDE = "override"


class NemsisFieldBinding(Base):
    """A binding between a structured extracted value and a NEMSIS 3.5.1 field.

    Created when an approved OCR or transport extraction is mapped to
    its corresponding NEMSIS element. The binding records both the source
    value and the mapped NEMSIS value for audit and re-mapping support.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        chart_id: Care chart this binding belongs to.
        extraction_id: FK to the TransportStructuredExtraction source.
        nemsis_element: NEMSIS 3.5.1 element identifier (e.g., ePatient.02).
        source_field_name: Name of the source extracted field.
        extracted_value: Raw value from extraction.
        mapped_value: NEMSIS-formatted mapped value.
        status: Binding lifecycle status.
        confidence_score: Confidence of the mapping (0.0-1.0).
        mapped_at: Timestamp when mapping was applied.
        reviewed_by_user_id: User who reviewed the binding.
        reviewed_at: Timestamp of review.
        override_reason: Reason if status is override.
    """

    __tablename__ = "nemsis_field_bindings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chart_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    extraction_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    nemsis_element: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    extracted_value: Mapped[str] = mapped_column(Text, nullable=False)
    mapped_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(NemsisBidingStatus), nullable=False, default=NemsisBidingStatus.PENDING, index=True
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mapped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class NemsisBindingReview(Base):
    """Immutable audit record for a NEMSIS binding review action.

    Attributes:
        id: UUID primary key.
        binding_id: FK to the NemsisFieldBinding reviewed.
        reviewer_user_id: User who reviewed the binding.
        action: 'approved', 'rejected', or 'override'.
        override_value: Value used if action is override.
        reason: Review reason or note.
        reviewed_at: Review timestamp.
    """

    __tablename__ = "nemsis_binding_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reviewer_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    override_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class NemsisExportReadinessSnapshot(Base):
    """Point-in-time NEMSIS export readiness snapshot for a chart.

    Records the readiness state at a specific moment, including binding
    completion, missing required elements, and overall export eligibility.
    The most recent snapshot per chart is the current readiness state.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        chart_id: Care chart evaluated.
        export_ready: True when all required NEMSIS elements are bound and approved.
        required_elements_count: Count of required NEMSIS elements.
        bound_elements_count: Count with approved bindings.
        missing_elements: JSON-serialized list of missing required element IDs.
        blocking_count: Count of unresolved required elements.
        evaluated_at: Snapshot creation timestamp.
    """

    __tablename__ = "nemsis_export_readiness_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chart_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    export_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    required_elements_count: Mapped[int] = mapped_column(nullable=False, default=0)
    bound_elements_count: Mapped[int] = mapped_column(nullable=False, default=0)
    missing_elements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocking_count: Mapped[int] = mapped_column(nullable=False, default=0)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class CareNemsisTransportBindingLink(Base):
    """Link between a care NEMSIS binding and its transport source.

    Records which transport request and extraction produced a specific
    NEMSIS binding, enabling full traceability from NEMSIS output back
    to the transport document source.

    Attributes:
        id: UUID primary key.
        binding_id: FK to the NemsisFieldBinding.
        chart_id: Care chart ID.
        transport_request_id: Cross-domain TransportLink request ID.
        extraction_id: TransportStructuredExtraction ID.
        linked_at: Timestamp when the link was established.
    """

    __tablename__ = "epcr_nemsis_transport_binding_links"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    binding_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    chart_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    transport_request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    extraction_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
