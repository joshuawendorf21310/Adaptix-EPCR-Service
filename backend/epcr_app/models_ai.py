"""AI clinical intelligence ORM models.

Persists all AI-generated outputs for narrative generation, billing readiness,
QA flag detection, and clinical documentation prompts.

Safety invariants enforced at the model level:
- ai_signed is always False — AI may never sign a chart
- ai_marked_complete is always False — AI may never finalize a chart
- review_status on narratives always starts "pending" requiring human action
"""
from __future__ import annotations

from datetime import datetime, UTC
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
)

# Use database-agnostic JSON so tests run on SQLite; JSONB behaviour is
# preserved at the driver level by asyncpg in production (same pattern as
# models_export.py).
JSONB = JSON

from epcr_app.models import Base


class AiNarrativeGeneration(Base):
    """Persisted AI narrative generation result awaiting human review.

    Every generated narrative starts with review_status="pending" and
    human_review_required=True. The final_text column remains NULL until
    a provider explicitly accepts or edits the narrative.
    """

    __tablename__ = "epcr_ai_narrative_generations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    chart_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    narrative_type = Column(String(64), nullable=False)
    # "structured" | "chronological" | "billing_support" | "transfer_handoff" |
    # "receiving_nurse" | "physician" | "qa_qi" | "critical_care" |
    # "cardiac_arrest" | "refusal"
    generated_text = Column(Text, nullable=False)
    source_fields_json = Column(JSONB, nullable=False, default=dict)
    missing_fields_json = Column(JSONB, nullable=False, default=list)
    warnings_json = Column(JSONB, nullable=False, default=list)
    model_used = Column(String(128), nullable=True)
    human_review_required = Column(Boolean, nullable=False, default=True)
    review_status = Column(String(32), nullable=False, default="pending")
    # "pending" | "accepted" | "edited" | "rejected" | "regenerated"
    reviewed_by = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    final_text = Column(Text, nullable=True)  # NULL until a provider acts
    created_by = Column(String(36), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    # Safety invariants — ALWAYS False; enforced by __init__ and __setattr__
    ai_signed = Column(Boolean, nullable=False, default=False)
    ai_marked_complete = Column(Boolean, nullable=False, default=False)

    def __init__(self, **kwargs):
        # Strip out any attempt to set safety columns to True before super()
        kwargs["ai_signed"] = False
        kwargs["ai_marked_complete"] = False
        super().__init__(**kwargs)


class AiBillingReadiness(Base):
    """Persisted AI billing readiness assessment for a chart."""

    __tablename__ = "epcr_ai_billing_readiness"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    chart_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    assessed_at = Column(DateTime(timezone=True), nullable=False)
    assessed_by = Column(String(36), nullable=False)
    score = Column(Integer, nullable=False)  # 0-100
    missing_fields_json = Column(JSONB, default=list)
    warnings_json = Column(JSONB, default=list)
    blockers_json = Column(JSONB, default=list)
    cms_service_level_risk = Column(String(128), nullable=True)
    medical_necessity_complete = Column(Boolean, nullable=False, default=False)
    pcs_required = Column(Boolean, nullable=False, default=False)
    pcs_complete = Column(Boolean, nullable=False, default=False)
    mileage_documented = Column(Boolean, nullable=False, default=False)
    signature_complete = Column(Boolean, nullable=False, default=False)
    origin_destination_complete = Column(Boolean, nullable=False, default=False)


class AiQaFlag(Base):
    """Persisted AI-detected QA flag for a chart.

    Flags are created by the AI engine and must be resolved by a human
    provider before the chart can be finalized.
    """

    __tablename__ = "epcr_ai_qa_flags"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    chart_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    flag_type = Column(String(64), nullable=False)
    # "missing_reassessment" | "contradictory_values" | "impossible_vitals" |
    # "high_risk_no_reassessment" | "airway_unconfirmed" | "vent_no_settings" |
    # "arrest_no_timeline" | "refusal_no_capacity" | "controlled_substance_audit" |
    # "blood_product_no_verification" | "missing_weight_pediatric" |
    # "duplicate_timestamp" | "time_order_contradiction" |
    # "allergy_medication_conflict" | "lab_abnormal_unmentioned"
    severity = Column(String(16), nullable=False)  # "blocker" | "warning" | "info"
    field_path = Column(String(128), nullable=True)  # e.g. "eVitals.06"
    description = Column(Text, nullable=False)
    suggested_action = Column(Text, nullable=True)
    resolved = Column(Boolean, nullable=False, default=False)
    resolved_by = Column(String(36), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_note = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    created_by_system = Column(Boolean, nullable=False, default=True)


class AiClinicalPrompt(Base):
    """Persisted AI-generated clinical documentation prompt.

    Prompts are context-aware nudges surfaced to the provider during charting.
    They are dismissed or acted upon; neither action finalises any chart data.
    """

    __tablename__ = "epcr_ai_clinical_prompts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    chart_id = Column(String(36), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    trigger_event = Column(String(128), nullable=False)
    prompt_type = Column(String(64), nullable=False)
    # "reassessment_required" | "missing_field" | "protocol_check" |
    # "intervention_followup" | "medication_response_needed" |
    # "contradiction_detected" | "billing_advisory" | "qa_advisory"
    protocol_pack = Column(String(32), nullable=True)  # "ACLS", "RSI", etc.
    prompt_text = Column(Text, nullable=False)
    field_references_json = Column(JSONB, default=list)
    dismissed = Column(Boolean, nullable=False, default=False)
    dismissed_by = Column(String(36), nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    acted_upon = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
