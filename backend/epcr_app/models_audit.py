"""Chart-level field audit trail models.

Immutable audit records for every field change and repeat-button event
in any ePCR chart.  These tables are append-only; rows are never updated
or soft-deleted after creation.
"""
from __future__ import annotations

from datetime import datetime, UTC
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    JSON,
    String,
    Text,
)

# Use database-agnostic JSON so tests run on SQLite; JSONB behaviour is
# preserved at the driver level by asyncpg in production.
JSONB = JSON

from epcr_app.models import Base


class ChartFieldAuditEvent(Base):
    """Immutable audit record for every field change in any ePCR chart.

    source_type values
    ------------------
    "manual_entry" | "repeat_button" | "ocr_scan" | "ai_suggestion" |
    "transfer_import" | "device_capture" | "cad_import" |
    "billing_review_edit" | "supervisor_edit" | "system_generated"

    validation_state values
    -----------------------
    "valid" | "warning" | "error"

    export_state values
    -------------------
    "not_exported" | "exported" | "submitted"

    review_state values
    -------------------
    Values from the ReviewState enum (direct_confirmed | proposed |
    accepted | rejected | edited_and_accepted).
    """

    __tablename__ = "epcr_chart_field_audit"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    chart_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)

    # What changed
    section = Column(String(128), nullable=False)          # "eVitals", "eMedications", …
    nemsis_element = Column(String(64), nullable=True)     # "eVitals.06"
    field_key = Column(String(128), nullable=False)        # internal field name
    prior_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    # Source provenance
    source_type = Column(String(64), nullable=False)
    source_artifact_id = Column(String(36), nullable=True)   # OcrJob.id, AiNarrativeGeneration.id, …
    source_artifact_type = Column(String(64), nullable=True) # "ocr_job" | "ai_narrative" | "transfer_packet"

    # Actor
    actor_id = Column(String(36), nullable=False)
    actor_role = Column(String(64), nullable=False)  # role at time of edit

    # State
    reason_for_change = Column(Text, nullable=True)   # required for late entries / supervisor edits
    is_late_entry = Column(Boolean, nullable=False, default=False)
    validation_state = Column(String(32), nullable=True)  # "valid" | "warning" | "error"
    export_state = Column(String(32), nullable=True)      # "not_exported" | "exported" | "submitted"
    review_state = Column(String(64), nullable=True)      # from ReviewState enum

    # Timestamp
    occurred_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    chart_clock_ms = Column(BigInteger, nullable=True)  # chart-relative milliseconds


class ChartRepeatEvent(Base):
    """Records every use of a repeat button — never overwrites prior entries.

    repeat_type values
    ------------------
    "vitals" | "pain_score" | "gcs" | "neuro_check" | "stroke_scale" |
    "lung_sounds" | "cardiac_rhythm" | "etco2" | "blood_glucose" |
    "vent_check" | "pump_check" | "sedation_score" | "restraint_check" |
    "medication_response" | "procedure_reassessment" | "blood_product_check" |
    "transfer_update" | "sepsis_reassessment" | "trauma_reassessment"
    """

    __tablename__ = "epcr_chart_repeat_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    chart_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)

    repeat_type = Column(String(64), nullable=False)
    prior_entry_id = Column(String(36), nullable=True)    # reference to prior entry this repeats
    new_entry_id = Column(String(36), nullable=True)      # reference to the new entry created
    repeated_fields_json = Column(JSONB, nullable=False, default=dict)   # field values copied
    modified_fields_json = Column(JSONB, nullable=False, default=dict)   # what changed vs prior

    actor_id = Column(String(36), nullable=False)
    occurred_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    nemsis_section = Column(String(128), nullable=True)
    validation_state = Column(String(32), nullable=True)


__all__ = ["ChartFieldAuditEvent", "ChartRepeatEvent"]
