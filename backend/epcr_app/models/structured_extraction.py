"""Transport structured extraction ORM model.

Defines the canonical structured extraction row promoted from approved OCR.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from epcr_app.models import Base


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class StructuredExtraction(Base):
    """Canonical structured extraction promoted from an approved OCR review."""

    __tablename__ = "transport_structured_extractions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "ocr_job_id",
            name="uq_transport_structured_extractions_tenant_ocr_job_id",
        ),
        Index(
            "ix_transport_structured_extractions_tenant_transport_request_id",
            "tenant_id",
            "transport_request_id",
        ),
        Index(
            "ix_transport_structured_extractions_tenant_chart_id",
            "tenant_id",
            "chart_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ocr_job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    transport_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chart_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    patient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    patient_dob: Mapped[str | None] = mapped_column(String(20), nullable=True)
    patient_mrn: Mapped[str | None] = mapped_column(String(100), nullable=True)
    physician_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    diagnosis_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pickup_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    medical_necessity_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transport_qualifier: Mapped[str | None] = mapped_column(String(100), nullable=True)

    all_fields: Mapped[str] = mapped_column(Text, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    promoted_by_user_id: Mapped[str] = mapped_column(String(255), nullable=False)


# Backward-compatible alias used by some call sites.
TransportStructuredExtraction = StructuredExtraction
