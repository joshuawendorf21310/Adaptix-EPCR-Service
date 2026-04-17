"""Care domain transport structured extraction ORM model.

Stores the promoted, structured field values from an approved OCR job.
These are the clean, validated fields ready for NEMSIS binding and
encounter mapping — not raw candidates, but operator-approved values.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from epcr_app.models import Base


class TransportStructuredExtraction(Base):
    """Structured field extraction record promoted from an approved OCR job.

    Created when an OcrJob review is approved and fields are promoted.
    Contains the clean, operator-validated field values as a structured
    JSON blob plus individual high-priority fields as indexed columns
    for fast querying.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant identifier.
        ocr_job_id: FK to the source OcrJob.
        transport_request_id: Cross-domain transport request reference.
        chart_id: Optional care chart this extraction is linked to.
        patient_name: Extracted patient name.
        patient_dob: Extracted patient date of birth.
        patient_mrn: Extracted medical record number.
        physician_name: Extracted certifying physician name.
        diagnosis_codes: JSON-serialized list of extracted diagnosis codes.
        pickup_address: Extracted pickup address.
        destination_address: Extracted destination address.
        medical_necessity_statement: Extracted medical necessity text.
        signature_date: Extracted signature date from document.
        transport_qualifier: Extracted transport level qualifier.
        all_fields: JSON-serialized dict of all approved extracted fields.
        promoted_at: Timestamp when promotion occurred.
        promoted_by_user_id: User who approved the OCR review.
    """

    __tablename__ = "transport_structured_extractions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ocr_job_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    transport_request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    chart_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    patient_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    patient_dob: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    patient_mrn: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    physician_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    diagnosis_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pickup_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    destination_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    medical_necessity_statement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signature_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    transport_qualifier: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    all_fields: Mapped[str] = mapped_column(Text, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    promoted_by_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
