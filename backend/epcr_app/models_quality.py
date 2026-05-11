"""Quality module ORM models: Medical Director, QA, and QI.

All models enforce tenant isolation via tenant_id on every table.
Medical Director notes, QA findings, and peer review notes are stored
as separate review artifacts — they never modify original clinical documentation.
Every state-changing operation must create a QualityAuditEvent.
"""
from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

from epcr_app.models import Base


# ---------------------------------------------------------------------------
# QA Trigger Configuration
# ---------------------------------------------------------------------------

class QATriggerConfiguration(Base):
    """Configurable QA trigger rules per agency/tenant.

    trigger_key examples: "cardiac_arrest", "intubation", "rsi",
    "medication_error", "pediatric_critical", "refusal", "sentinel_event".
    Mandatory triggers cannot be deactivated via the API.
    """

    __tablename__ = "qa_trigger_configurations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "trigger_key", name="uq_qa_trigger_tenant_key"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    trigger_key = Column(String(128), nullable=False)
    trigger_type = Column(String(32), nullable=False)  # "mandatory" | "optional"
    trigger_label = Column(String(255), nullable=False)
    priority = Column(String(32), nullable=False, default="standard")  # "critical"|"high"|"standard"|"low"
    is_active = Column(Boolean, nullable=False, default=True)
    condition_json = Column(Text, nullable=False, default="{}")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# QA Case Record
# ---------------------------------------------------------------------------

class QACaseRecord(Base):
    """Central QA case record linking a source ePCR chart to a review lifecycle.

    Lifecycle: new → assigned → in_review → provider_clarification →
    medical_director_escalated → findings_documented → education_assigned →
    closed | appealed
    """

    __tablename__ = "qa_case_records"
    __table_args__ = (
        Index("ix_qa_case_tenant_status", "tenant_id", "status"),
        Index("ix_qa_case_tenant_reviewer", "tenant_id", "assigned_to"),
        Index("ix_qa_case_tenant_chart", "tenant_id", "source_chart_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    agency_id = Column(String(36), nullable=True)
    source_chart_id = Column(String(36), nullable=False, index=True)
    case_number = Column(String(64), nullable=False, index=True)  # QA-{prefix}-{YYYYMM}-{seq}
    trigger_key = Column(String(128), nullable=False)
    trigger_type = Column(String(64), nullable=False)  # "automatic"|"random"|"supervisor"|...
    priority = Column(String(32), nullable=False, default="standard")
    status = Column(String(64), nullable=False, default="new")
    assigned_to = Column(String(36), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    qa_score = Column(Float, nullable=True)
    score_version = Column(String(32), nullable=True)
    findings_json = Column(Text, nullable=True, default="[]")
    education_assigned = Column(Boolean, nullable=False, default=False)
    education_assignment_id = Column(String(36), nullable=True)
    medical_director_escalated = Column(Boolean, nullable=False, default=False)
    medical_director_escalation_id = Column(String(36), nullable=True)
    provider_feedback_id = Column(String(36), nullable=True)
    closure_notes = Column(Text, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(String(36), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# QA Score
# ---------------------------------------------------------------------------

class QAScore(Base):
    """Weighted QA score across five standardized domains.

    score_version preserves the scoring model in use at review time.
    Historical scores must not be altered when the scoring model changes.
    """

    __tablename__ = "qa_scores"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    qa_case_id = Column(String(36), nullable=False, index=True)
    reviewer_id = Column(String(36), nullable=False)
    score_version = Column(String(32), nullable=False, default="v1")
    documentation_quality_score = Column(Float, nullable=False, default=0.0)
    protocol_adherence_score = Column(Float, nullable=False, default=0.0)
    timeliness_score = Column(Float, nullable=False, default=0.0)
    clinical_quality_score = Column(Float, nullable=False, default=0.0)
    operational_quality_score = Column(Float, nullable=False, default=0.0)
    composite_score = Column(Float, nullable=False, default=0.0)
    documentation_weight = Column(Float, nullable=False, default=0.25)
    protocol_weight = Column(Float, nullable=False, default=0.25)
    timeliness_weight = Column(Float, nullable=False, default=0.15)
    clinical_weight = Column(Float, nullable=False, default=0.25)
    operational_weight = Column(Float, nullable=False, default=0.10)
    reviewer_notes = Column(Text, nullable=True)
    context_flags_json = Column(Text, nullable=False, default="{}")
    call_complexity_adjustment = Column(Float, nullable=False, default=0.0)
    is_finalized = Column(Boolean, nullable=False, default=False)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# QA Review Finding
# ---------------------------------------------------------------------------

class QAReviewFinding(Base):
    """Individual finding attached to a QA case.

    Findings are review artifacts — they never modify the source ePCR chart.
    """

    __tablename__ = "qa_review_findings"
    __table_args__ = (
        Index("ix_qa_finding_tenant_case", "tenant_id", "qa_case_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    qa_case_id = Column(String(36), nullable=False, index=True)
    reviewer_id = Column(String(36), nullable=False)
    finding_type = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False, default="minor")
    domain = Column(String(64), nullable=False, default="documentation")
    description = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=True)
    chart_reference_json = Column(Text, nullable=True, default="{}")
    education_recommended = Column(Boolean, nullable=False, default=False)
    process_improvement_recommended = Column(Boolean, nullable=False, default=False)
    medical_director_review_recommended = Column(Boolean, nullable=False, default=False)
    status = Column(String(32), nullable=False, default="open")
    provider_response = Column(Text, nullable=True)
    provider_responded_at = Column(DateTime(timezone=True), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Peer Review
# ---------------------------------------------------------------------------

class PeerReview(Base):
    """Peer review record for a QA case.

    Protected review: reviewer cannot be the chart provider or crew member.
    peer_review_id must not be reviewable by the chart's crew.
    is_protected=True means review notes are shielded from non-authorized access.
    """

    __tablename__ = "peer_reviews"
    __table_args__ = (
        Index("ix_peer_review_tenant_case", "tenant_id", "qa_case_id"),
        Index("ix_peer_review_tenant_reviewer", "tenant_id", "reviewer_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    qa_case_id = Column(String(36), nullable=False, index=True)
    source_chart_id = Column(String(36), nullable=False)
    reviewer_id = Column(String(36), nullable=False)
    assignor_id = Column(String(36), nullable=False)
    is_blind = Column(Boolean, nullable=False, default=False)
    conflict_of_interest_checked = Column(Boolean, nullable=False, default=False)
    workload_score = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="assigned")
    strengths_notes = Column(Text, nullable=True)
    improvement_notes = Column(Text, nullable=True)
    education_recommendation = Column(Text, nullable=True)
    process_improvement_suggestion = Column(Text, nullable=True)
    exemplary_care_flag = Column(Boolean, nullable=False, default=False)
    reviewer_signature = Column(String(512), nullable=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)
    is_protected = Column(Boolean, nullable=False, default=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Peer Review Assignment (conflict-of-interest tracking)
# ---------------------------------------------------------------------------

class PeerReviewAssignment(Base):
    """Tracks assignment metadata and conflict-of-interest verification for peer review."""

    __tablename__ = "peer_review_assignments"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    peer_review_id = Column(String(36), nullable=False, index=True)
    reviewer_id = Column(String(36), nullable=False)
    chart_provider_id = Column(String(36), nullable=False)
    crew_member_ids_json = Column(Text, nullable=False, default="[]")
    is_conflict = Column(Boolean, nullable=False, default=False)
    conflict_reason = Column(Text, nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Medical Director Review
# ---------------------------------------------------------------------------

class MedicalDirectorReview(Base):
    """Medical director review record for escalated or high-risk cases.

    MD reviews are separate from original clinical documentation.
    MedicalDirectorNotes are stored as child records — never in the chart.
    """

    __tablename__ = "medical_director_reviews"
    __table_args__ = (
        Index("ix_md_review_tenant_status", "tenant_id", "status"),
        Index("ix_md_review_tenant_md", "tenant_id", "medical_director_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    qa_case_id = Column(String(36), nullable=False, index=True)
    source_chart_id = Column(String(36), nullable=False)
    medical_director_id = Column(String(36), nullable=False)
    escalated_by = Column(String(36), nullable=False)
    escalation_reason = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    review_type = Column(String(64), nullable=False, default="qa_escalation")
    finding_classification = Column(String(64), nullable=True)
    protocol_deviation_identified = Column(Boolean, nullable=False, default=False)
    exemplary_care_identified = Column(Boolean, nullable=False, default=False)
    education_recommended = Column(Boolean, nullable=False, default=False)
    protocol_revision_recommended = Column(Boolean, nullable=False, default=False)
    agency_leadership_flag = Column(Boolean, nullable=False, default=False)
    clarification_requested_from = Column(String(36), nullable=True)
    clarification_request_notes = Column(Text, nullable=True)
    clarification_response = Column(Text, nullable=True)
    clarification_responded_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Medical Director Note (protected artifact — never modifies chart)
# ---------------------------------------------------------------------------

class MedicalDirectorNote(Base):
    """Protected medical director note stored separately from clinical documentation.

    is_protected=True — access restricted to medical director, assistant
    medical director, and system admins. Original chart data is never altered.
    """

    __tablename__ = "medical_director_notes"
    __table_args__ = (
        Index("ix_md_note_tenant_review", "tenant_id", "medical_director_review_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    medical_director_review_id = Column(String(36), nullable=False, index=True)
    source_chart_id = Column(String(36), nullable=False)
    author_id = Column(String(36), nullable=False)
    author_role = Column(String(64), nullable=False)
    note_type = Column(String(64), nullable=False, default="finding")
    note_text = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=True)
    finding_type = Column(String(64), nullable=True)
    is_protected = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Clinical Variance
# ---------------------------------------------------------------------------

class ClinicalVariance(Base):
    """Clinical variance record — tracks deviations, adverse events, near misses, and exemplary care."""

    __tablename__ = "clinical_variances"
    __table_args__ = (
        Index("ix_clinical_variance_tenant_type", "tenant_id", "variance_type"),
        Index("ix_clinical_variance_tenant_provider", "tenant_id", "provider_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    qa_case_id = Column(String(36), nullable=True)
    source_chart_id = Column(String(36), nullable=False)
    provider_id = Column(String(36), nullable=False)
    unit_id = Column(String(36), nullable=True)
    incident_datetime = Column(DateTime(timezone=True), nullable=False)
    variance_type = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False, default="minor")
    clinical_context = Column(Text, nullable=False)
    reviewer_notes = Column(Text, nullable=True)
    provider_response = Column(Text, nullable=True)
    education_assigned = Column(Boolean, nullable=False, default=False)
    education_assignment_id = Column(String(36), nullable=True)
    qi_initiative_id = Column(String(36), nullable=True)
    trend_category = Column(String(128), nullable=True)
    closure_status = Column(String(32), nullable=False, default="open")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Protocol Document + Version + Acknowledgment
# ---------------------------------------------------------------------------

class ProtocolDocument(Base):
    """Agency protocol document — top-level container for versioned protocols."""

    __tablename__ = "protocol_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "protocol_code", name="uq_protocol_tenant_code"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    protocol_code = Column(String(64), nullable=False)
    protocol_name = Column(String(255), nullable=False)
    protocol_category = Column(String(64), nullable=False)
    current_version_id = Column(String(36), nullable=True)
    status = Column(String(32), nullable=False, default="draft")
    acknowledgment_required = Column(Boolean, nullable=False, default=False)
    linked_qa_trigger_keys_json = Column(Text, nullable=False, default="[]")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class ProtocolVersion(Base):
    """Versioned protocol content with effective and expiration dates."""

    __tablename__ = "protocol_versions"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    protocol_id = Column(String(36), nullable=False, index=True)
    version_number = Column(String(32), nullable=False)
    effective_date = Column(DateTime(timezone=True), nullable=False)
    expiration_date = Column(DateTime(timezone=True), nullable=True)
    content_url = Column(String(1024), nullable=True)
    content_text = Column(Text, nullable=True)
    medical_director_approval_id = Column(String(36), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False, default="draft")
    linked_standing_order_ids_json = Column(Text, nullable=False, default="[]")
    linked_documentation_pack_ids_json = Column(Text, nullable=False, default="[]")
    scope_applicability_json = Column(Text, nullable=False, default="{}")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class ProtocolAcknowledgment(Base):
    """Provider acknowledgment of a protocol version."""

    __tablename__ = "protocol_acknowledgments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "protocol_version_id", "provider_id",
            name="uq_protocol_ack_tenant_version_provider",
        ),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    protocol_version_id = Column(String(36), nullable=False, index=True)
    provider_id = Column(String(36), nullable=False, index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=False)
    provider_signature = Column(String(512), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Standing Order + Version
# ---------------------------------------------------------------------------

class StandingOrder(Base):
    """Standing order — authorizes specific clinical interventions for providers."""

    __tablename__ = "standing_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_code", name="uq_standing_order_tenant_code"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    order_code = Column(String(64), nullable=False)
    order_name = Column(String(255), nullable=False)
    order_type = Column(String(64), nullable=False)
    current_version_id = Column(String(36), nullable=True)
    status = Column(String(32), nullable=False, default="draft")
    medical_director_id = Column(String(36), nullable=True)
    linked_protocol_ids_json = Column(Text, nullable=False, default="[]")
    linked_medication_ids_json = Column(Text, nullable=False, default="[]")
    linked_procedure_ids_json = Column(Text, nullable=False, default="[]")
    linked_qa_trigger_keys_json = Column(Text, nullable=False, default="[]")
    linked_documentation_requirement_ids_json = Column(Text, nullable=False, default="[]")
    acknowledgment_required = Column(Boolean, nullable=False, default=False)
    agency_applicability_json = Column(Text, nullable=False, default="{}")
    scope_applicability_json = Column(Text, nullable=False, default="{}")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class StandingOrderVersion(Base):
    """Versioned standing order content."""

    __tablename__ = "standing_order_versions"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    standing_order_id = Column(String(36), nullable=False, index=True)
    version_number = Column(String(32), nullable=False)
    effective_date = Column(DateTime(timezone=True), nullable=False)
    review_date = Column(DateTime(timezone=True), nullable=True)
    expiration_date = Column(DateTime(timezone=True), nullable=True)
    content_url = Column(String(1024), nullable=True)
    content_text = Column(Text, nullable=True)
    medical_director_approval_id = Column(String(36), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False, default="draft")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Education Follow-Up
# ---------------------------------------------------------------------------

class EducationFollowUp(Base):
    """Education assignment linked to a QA case, MD review, or QI initiative."""

    __tablename__ = "education_followups"
    __table_args__ = (
        Index("ix_education_tenant_provider", "tenant_id", "provider_id"),
        Index("ix_education_tenant_status", "tenant_id", "status"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    provider_id = Column(String(36), nullable=False, index=True)
    assigned_by = Column(String(36), nullable=False)
    assigned_by_role = Column(String(64), nullable=False)
    qa_case_id = Column(String(36), nullable=True)
    medical_director_review_id = Column(String(36), nullable=True)
    qi_initiative_id = Column(String(36), nullable=True)
    education_type = Column(String(64), nullable=False, default="remedial")
    education_title = Column(String(255), nullable=False)
    education_description = Column(Text, nullable=True)
    education_resource_url = Column(String(1024), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    provider_acknowledgment_id = Column(String(36), nullable=True)
    effectiveness_measured = Column(Boolean, nullable=False, default=False)
    effectiveness_metric_json = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="assigned")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Provider Feedback
# ---------------------------------------------------------------------------

class ProviderFeedback(Base):
    """Provider feedback record — protected, auditable, not disciplinary by default."""

    __tablename__ = "provider_feedbacks"
    __table_args__ = (
        Index("ix_provider_feedback_tenant_provider", "tenant_id", "provider_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    provider_id = Column(String(36), nullable=False, index=True)
    sent_by = Column(String(36), nullable=False)
    sent_by_role = Column(String(64), nullable=False)
    qa_case_id = Column(String(36), nullable=True)
    medical_director_review_id = Column(String(36), nullable=True)
    feedback_type = Column(String(64), nullable=False, default="informational")
    subject = Column(String(255), nullable=False)
    message_text = Column(Text, nullable=False)
    is_protected = Column(Boolean, nullable=False, default=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    provider_response = Column(Text, nullable=True)
    provider_responded_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False, default="sent")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Provider Acknowledgment
# ---------------------------------------------------------------------------

class ProviderAcknowledgment(Base):
    """Tracks provider acknowledgment of education, feedback, protocol, and standing order."""

    __tablename__ = "provider_acknowledgments"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    provider_id = Column(String(36), nullable=False, index=True)
    acknowledgment_type = Column(String(64), nullable=False)
    reference_id = Column(String(36), nullable=False, index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=False)
    signature = Column(String(512), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# QI Initiative
# ---------------------------------------------------------------------------

class QIInitiative(Base):
    """Quality improvement initiative with closed-loop lifecycle tracking.

    Lifecycle: identified → baseline_measured → goal_defined →
    intervention_planned → active → follow_up → outcome_measured →
    sustained_monitoring → closed | reopened
    """

    __tablename__ = "qi_initiatives"
    __table_args__ = (
        Index("ix_qi_initiative_tenant_status", "tenant_id", "status"),
        Index("ix_qi_initiative_tenant_owner", "tenant_id", "owner_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    initiative_title = Column(String(255), nullable=False)
    category = Column(String(128), nullable=False)
    source_trend_description = Column(Text, nullable=False)
    baseline_metric_value = Column(Float, nullable=True)
    baseline_metric_label = Column(String(255), nullable=True)
    target_metric_value = Column(Float, nullable=True)
    target_metric_label = Column(String(255), nullable=True)
    current_metric_value = Column(Float, nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=False)
    target_completion_date = Column(DateTime(timezone=True), nullable=True)
    owner_id = Column(String(36), nullable=False)
    stakeholder_ids_json = Column(Text, nullable=False, default="[]")
    intervention_plan = Column(Text, nullable=False)
    education_linkage_ids_json = Column(Text, nullable=False, default="[]")
    protocol_linkage_ids_json = Column(Text, nullable=False, default="[]")
    dashboard_metric_keys_json = Column(Text, nullable=False, default="[]")
    status = Column(String(64), nullable=False, default="identified")
    outcome_summary = Column(Text, nullable=True)
    effectiveness_measurement = Column(Text, nullable=True)
    closure_notes = Column(Text, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    accreditation_evidence_included = Column(Boolean, nullable=False, default=False)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# QI Initiative Metric (time-series measurements)
# ---------------------------------------------------------------------------

class QIInitiativeMetric(Base):
    """Time-series metric measurement for a QI initiative."""

    __tablename__ = "qi_initiative_metrics"
    __table_args__ = (
        Index("ix_qi_metric_tenant_initiative", "tenant_id", "initiative_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    initiative_id = Column(String(36), nullable=False, index=True)
    metric_key = Column(String(128), nullable=False)
    metric_value = Column(Float, nullable=False)
    metric_label = Column(String(255), nullable=False)
    measurement_period = Column(String(32), nullable=False)  # "2025-Q1", "2025-04"
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    recorded_by = Column(String(36), nullable=False)
    notes = Column(Text, nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# QI Action Item
# ---------------------------------------------------------------------------

class QIActionItem(Base):
    """Action item within a QI initiative."""

    __tablename__ = "qi_action_items"
    __table_args__ = (
        Index("ix_qi_action_tenant_initiative", "tenant_id", "initiative_id"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    initiative_id = Column(String(36), nullable=False, index=True)
    action_title = Column(String(255), nullable=False)
    action_description = Column(Text, nullable=False)
    assigned_to = Column(String(36), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False, default="open")
    completion_notes = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# QI Committee Review
# ---------------------------------------------------------------------------

class QICommitteeReview(Base):
    """QI committee meeting record with agenda, minutes, and action items."""

    __tablename__ = "qi_committee_reviews"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    meeting_date = Column(DateTime(timezone=True), nullable=False)
    chair_id = Column(String(36), nullable=False)
    attendee_ids_json = Column(Text, nullable=False, default="[]")
    agenda_json = Column(Text, nullable=False, default="[]")
    minutes_text = Column(Text, nullable=True)
    action_items_json = Column(Text, nullable=False, default="[]")
    status = Column(String(32), nullable=False, default="scheduled")
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# QA Trend Aggregation (computed, idempotent upsert by tenant+period)
# ---------------------------------------------------------------------------

class QATrendAggregation(Base):
    """Computed trend aggregation for a reporting period."""

    __tablename__ = "qa_trend_aggregations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period", name="uq_qa_trend_tenant_period"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    period = Column(String(32), nullable=False)
    period_type = Column(String(16), nullable=False, default="month")
    total_charts_reviewed = Column(Integer, nullable=False, default=0)
    total_qa_cases = Column(Integer, nullable=False, default=0)
    total_open_cases = Column(Integer, nullable=False, default=0)
    total_overdue_cases = Column(Integer, nullable=False, default=0)
    avg_qa_score = Column(Float, nullable=False, default=0.0)
    avg_documentation_score = Column(Float, nullable=False, default=0.0)
    avg_protocol_adherence_score = Column(Float, nullable=False, default=0.0)
    avg_timeliness_score = Column(Float, nullable=False, default=0.0)
    avg_clinical_quality_score = Column(Float, nullable=False, default=0.0)
    avg_operational_score = Column(Float, nullable=False, default=0.0)
    trigger_breakdown_json = Column(Text, nullable=False, default="{}")
    finding_type_breakdown_json = Column(Text, nullable=False, default="{}")
    education_assignments = Column(Integer, nullable=False, default=0)
    education_completions = Column(Integer, nullable=False, default=0)
    medical_director_escalations = Column(Integer, nullable=False, default=0)
    peer_reviews_completed = Column(Integer, nullable=False, default=0)
    closed_loop_completions = Column(Integer, nullable=False, default=0)
    computed_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Quality Audit Event (every state-changing operation creates one)
# ---------------------------------------------------------------------------

class QualityAuditEvent(Base):
    """Immutable audit event for every quality module state change.

    Every mutation in the quality module must create a QualityAuditEvent.
    Audit events are append-only — never updated or deleted.
    """

    __tablename__ = "quality_audit_events"
    __table_args__ = (
        Index("ix_quality_audit_tenant_type", "tenant_id", "event_type"),
        Index("ix_quality_audit_tenant_actor", "tenant_id", "actor_id"),
        Index("ix_quality_audit_tenant_ref", "tenant_id", "reference_id"),
        Index("ix_quality_audit_occurred_at", "tenant_id", "occurred_at"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    actor_id = Column(String(36), nullable=False)
    actor_role = Column(String(64), nullable=False)
    event_type = Column(String(128), nullable=False)
    reference_type = Column(String(64), nullable=False)
    reference_id = Column(String(36), nullable=False)
    source_chart_id = Column(String(36), nullable=True)
    event_metadata_json = Column(Text, nullable=False, default="{}")
    correlation_id = Column(String(36), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Accreditation Evidence Package
# ---------------------------------------------------------------------------

class AccreditationEvidencePackage(Base):
    """Compiled accreditation evidence package from real quality module data."""

    __tablename__ = "accreditation_evidence_packages"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    package_name = Column(String(255), nullable=False)
    accreditation_type = Column(String(64), nullable=False, default="internal_audit")
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    generated_by = Column(String(36), nullable=False)
    qa_evidence_json = Column(Text, nullable=False, default="{}")
    qi_evidence_json = Column(Text, nullable=False, default="{}")
    peer_review_summary_json = Column(Text, nullable=False, default="{}")
    education_completion_json = Column(Text, nullable=False, default="{}")
    protocol_compliance_json = Column(Text, nullable=False, default="{}")
    audit_log_export_url = Column(String(1024), nullable=True)
    package_export_url = Column(String(1024), nullable=True)
    compiled_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


# ---------------------------------------------------------------------------
# Quality Dashboard Snapshot
# ---------------------------------------------------------------------------

class QualityDashboardSnapshot(Base):
    """Cached dashboard snapshot for a reporting period.

    snapshot_type: "medical_director" | "qa" | "qi" | "agency_leadership" | "provider_feedback"
    Dashboard endpoints should compute real data; snapshots support historical views.
    """

    __tablename__ = "quality_dashboard_snapshots"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), index=True, nullable=False)
    snapshot_type = Column(String(64), nullable=False)
    snapshot_data_json = Column(Text, nullable=False, default="{}")
    period = Column(String(32), nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
