"""041 — add Medical Director, QA, and QI module tables.

Revision ID: 041
Revises: 040
Create Date: 2026-05-10

Adds all tables for the three connected clinical governance modules:
  - QATriggerConfiguration
  - QACaseRecord
  - QAScore
  - QAReviewFinding
  - PeerReview
  - PeerReviewAssignment
  - MedicalDirectorReview
  - MedicalDirectorNote
  - ClinicalVariance
  - ProtocolDocument
  - ProtocolVersion
  - ProtocolAcknowledgment
  - StandingOrder
  - StandingOrderVersion
  - EducationFollowUp
  - ProviderFeedback
  - ProviderAcknowledgment
  - QIInitiative
  - QIInitiativeMetric
  - QIActionItem
  - QICommitteeReview
  - QATrendAggregation
  - QualityAuditEvent
  - AccreditationEvidencePackage
  - QualityDashboardSnapshot
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    def create_if_missing(table_name: str, *cols: sa.Column, **kw) -> None:
        if table_name not in existing:
            op.create_table(table_name, *cols, **kw)

    # -- qa_trigger_configurations ------------------------------------------
    create_if_missing(
        "qa_trigger_configurations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("trigger_key", sa.String(128), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("trigger_label", sa.String(255), nullable=False),
        sa.Column("priority", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("condition_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "trigger_key", name="uq_qa_trigger_tenant_key"),
    )
    op.create_index("ix_qa_trigger_tenant", "qa_trigger_configurations", ["tenant_id"])

    # -- qa_case_records -------------------------------------------------------
    create_if_missing(
        "qa_case_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("agency_id", sa.String(36), nullable=True),
        sa.Column("source_chart_id", sa.String(36), nullable=False),
        sa.Column("case_number", sa.String(64), nullable=False),
        sa.Column("trigger_key", sa.String(128), nullable=False),
        sa.Column("trigger_type", sa.String(64), nullable=False),
        sa.Column("priority", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("status", sa.String(64), nullable=False, server_default="new"),
        sa.Column("assigned_to", sa.String(36), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("qa_score", sa.Float(), nullable=True),
        sa.Column("score_version", sa.String(32), nullable=True),
        sa.Column("findings_json", sa.Text(), nullable=True, server_default="[]"),
        sa.Column("education_assigned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("education_assignment_id", sa.String(36), nullable=True),
        sa.Column("medical_director_escalated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("medical_director_escalation_id", sa.String(36), nullable=True),
        sa.Column("provider_feedback_id", sa.String(36), nullable=True),
        sa.Column("closure_notes", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_qa_case_tenant_id", "qa_case_records", ["tenant_id"])
    op.create_index("ix_qa_case_tenant_status", "qa_case_records", ["tenant_id", "status"])
    op.create_index("ix_qa_case_tenant_reviewer", "qa_case_records", ["tenant_id", "assigned_to"])
    op.create_index("ix_qa_case_tenant_chart", "qa_case_records", ["tenant_id", "source_chart_id"])
    op.create_index("ix_qa_case_case_number", "qa_case_records", ["case_number"])

    # -- qa_scores -------------------------------------------------------------
    create_if_missing(
        "qa_scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("qa_case_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("score_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("documentation_quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("protocol_adherence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("timeliness_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("clinical_quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("operational_quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("composite_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("documentation_weight", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("protocol_weight", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("timeliness_weight", sa.Float(), nullable=False, server_default="0.15"),
        sa.Column("clinical_weight", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("operational_weight", sa.Float(), nullable=False, server_default="0.10"),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("context_flags_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("call_complexity_adjustment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_finalized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qa_score_tenant", "qa_scores", ["tenant_id"])
    op.create_index("ix_qa_score_case", "qa_scores", ["qa_case_id"])

    # -- qa_review_findings ----------------------------------------------------
    create_if_missing(
        "qa_review_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("qa_case_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("finding_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False, server_default="minor"),
        sa.Column("domain", sa.String(64), nullable=False, server_default="documentation"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("chart_reference_json", sa.Text(), nullable=True, server_default="{}"),
        sa.Column("education_recommended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("process_improvement_recommended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("medical_director_review_recommended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("provider_response", sa.Text(), nullable=True),
        sa.Column("provider_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qa_finding_tenant", "qa_review_findings", ["tenant_id"])
    op.create_index("ix_qa_finding_tenant_case", "qa_review_findings", ["tenant_id", "qa_case_id"])

    # -- peer_reviews ----------------------------------------------------------
    create_if_missing(
        "peer_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("qa_case_id", sa.String(36), nullable=False),
        sa.Column("source_chart_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("assignor_id", sa.String(36), nullable=False),
        sa.Column("is_blind", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("conflict_of_interest_checked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("workload_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="assigned"),
        sa.Column("strengths_notes", sa.Text(), nullable=True),
        sa.Column("improvement_notes", sa.Text(), nullable=True),
        sa.Column("education_recommendation", sa.Text(), nullable=True),
        sa.Column("process_improvement_suggestion", sa.Text(), nullable=True),
        sa.Column("exemplary_care_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reviewer_signature", sa.String(512), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_peer_review_tenant", "peer_reviews", ["tenant_id"])
    op.create_index("ix_peer_review_tenant_case", "peer_reviews", ["tenant_id", "qa_case_id"])
    op.create_index("ix_peer_review_tenant_reviewer", "peer_reviews", ["tenant_id", "reviewer_id"])

    # -- peer_review_assignments -----------------------------------------------
    create_if_missing(
        "peer_review_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("peer_review_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("chart_provider_id", sa.String(36), nullable=False),
        sa.Column("crew_member_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_conflict", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("conflict_reason", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_peer_review_assignment_tenant", "peer_review_assignments", ["tenant_id"])
    op.create_index("ix_peer_review_assignment_review", "peer_review_assignments", ["peer_review_id"])

    # -- medical_director_reviews ----------------------------------------------
    create_if_missing(
        "medical_director_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("qa_case_id", sa.String(36), nullable=False),
        sa.Column("source_chart_id", sa.String(36), nullable=False),
        sa.Column("medical_director_id", sa.String(36), nullable=False),
        sa.Column("escalated_by", sa.String(36), nullable=False),
        sa.Column("escalation_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("review_type", sa.String(64), nullable=False, server_default="qa_escalation"),
        sa.Column("finding_classification", sa.String(64), nullable=True),
        sa.Column("protocol_deviation_identified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("exemplary_care_identified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("education_recommended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("protocol_revision_recommended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("agency_leadership_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("clarification_requested_from", sa.String(36), nullable=True),
        sa.Column("clarification_request_notes", sa.Text(), nullable=True),
        sa.Column("clarification_response", sa.Text(), nullable=True),
        sa.Column("clarification_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_md_review_tenant", "medical_director_reviews", ["tenant_id"])
    op.create_index("ix_md_review_tenant_status", "medical_director_reviews", ["tenant_id", "status"])
    op.create_index("ix_md_review_tenant_md", "medical_director_reviews", ["tenant_id", "medical_director_id"])
    op.create_index("ix_md_review_qa_case", "medical_director_reviews", ["qa_case_id"])

    # -- medical_director_notes ------------------------------------------------
    create_if_missing(
        "medical_director_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("medical_director_review_id", sa.String(36), nullable=False),
        sa.Column("source_chart_id", sa.String(36), nullable=False),
        sa.Column("author_id", sa.String(36), nullable=False),
        sa.Column("author_role", sa.String(64), nullable=False),
        sa.Column("note_type", sa.String(64), nullable=False, server_default="finding"),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("finding_type", sa.String(64), nullable=True),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_md_note_tenant", "medical_director_notes", ["tenant_id"])
    op.create_index("ix_md_note_tenant_review", "medical_director_notes", ["tenant_id", "medical_director_review_id"])

    # -- clinical_variances ----------------------------------------------------
    create_if_missing(
        "clinical_variances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("qa_case_id", sa.String(36), nullable=True),
        sa.Column("source_chart_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("unit_id", sa.String(36), nullable=True),
        sa.Column("incident_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("variance_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False, server_default="minor"),
        sa.Column("clinical_context", sa.Text(), nullable=False),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("provider_response", sa.Text(), nullable=True),
        sa.Column("education_assigned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("education_assignment_id", sa.String(36), nullable=True),
        sa.Column("qi_initiative_id", sa.String(36), nullable=True),
        sa.Column("trend_category", sa.String(128), nullable=True),
        sa.Column("closure_status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_clinical_variance_tenant", "clinical_variances", ["tenant_id"])
    op.create_index("ix_clinical_variance_tenant_type", "clinical_variances", ["tenant_id", "variance_type"])
    op.create_index("ix_clinical_variance_tenant_provider", "clinical_variances", ["tenant_id", "provider_id"])

    # -- protocol_documents ----------------------------------------------------
    create_if_missing(
        "protocol_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("protocol_code", sa.String(64), nullable=False),
        sa.Column("protocol_name", sa.String(255), nullable=False),
        sa.Column("protocol_category", sa.String(64), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("acknowledgment_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("linked_qa_trigger_keys_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "protocol_code", name="uq_protocol_tenant_code"),
    )
    op.create_index("ix_protocol_document_tenant", "protocol_documents", ["tenant_id"])

    # -- protocol_versions -----------------------------------------------------
    create_if_missing(
        "protocol_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("protocol_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.String(32), nullable=False),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expiration_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_url", sa.String(1024), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("medical_director_approval_id", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("linked_standing_order_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("linked_documentation_pack_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("scope_applicability_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_protocol_version_tenant", "protocol_versions", ["tenant_id"])
    op.create_index("ix_protocol_version_protocol", "protocol_versions", ["protocol_id"])

    # -- protocol_acknowledgments ----------------------------------------------
    create_if_missing(
        "protocol_acknowledgments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("protocol_version_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_signature", sa.String(512), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "protocol_version_id", "provider_id",
            name="uq_protocol_ack_tenant_version_provider",
        ),
    )
    op.create_index("ix_protocol_ack_tenant", "protocol_acknowledgments", ["tenant_id"])
    op.create_index("ix_protocol_ack_version", "protocol_acknowledgments", ["protocol_version_id"])
    op.create_index("ix_protocol_ack_provider", "protocol_acknowledgments", ["provider_id"])

    # -- standing_orders -------------------------------------------------------
    create_if_missing(
        "standing_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("order_code", sa.String(64), nullable=False),
        sa.Column("order_name", sa.String(255), nullable=False),
        sa.Column("order_type", sa.String(64), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("medical_director_id", sa.String(36), nullable=True),
        sa.Column("linked_protocol_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("linked_medication_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("linked_procedure_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("linked_qa_trigger_keys_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("linked_documentation_requirement_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("acknowledgment_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("agency_applicability_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("scope_applicability_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "order_code", name="uq_standing_order_tenant_code"),
    )
    op.create_index("ix_standing_order_tenant", "standing_orders", ["tenant_id"])

    # -- standing_order_versions -----------------------------------------------
    create_if_missing(
        "standing_order_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("standing_order_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.String(32), nullable=False),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiration_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_url", sa.String(1024), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("medical_director_approval_id", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_standing_order_version_tenant", "standing_order_versions", ["tenant_id"])
    op.create_index("ix_standing_order_version_order", "standing_order_versions", ["standing_order_id"])

    # -- education_followups ---------------------------------------------------
    create_if_missing(
        "education_followups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("assigned_by", sa.String(36), nullable=False),
        sa.Column("assigned_by_role", sa.String(64), nullable=False),
        sa.Column("qa_case_id", sa.String(36), nullable=True),
        sa.Column("medical_director_review_id", sa.String(36), nullable=True),
        sa.Column("qi_initiative_id", sa.String(36), nullable=True),
        sa.Column("education_type", sa.String(64), nullable=False, server_default="remedial"),
        sa.Column("education_title", sa.String(255), nullable=False),
        sa.Column("education_description", sa.Text(), nullable=True),
        sa.Column("education_resource_url", sa.String(1024), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_acknowledgment_id", sa.String(36), nullable=True),
        sa.Column("effectiveness_measured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("effectiveness_metric_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="assigned"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_education_tenant", "education_followups", ["tenant_id"])
    op.create_index("ix_education_tenant_provider", "education_followups", ["tenant_id", "provider_id"])
    op.create_index("ix_education_tenant_status", "education_followups", ["tenant_id", "status"])

    # -- provider_feedbacks ----------------------------------------------------
    create_if_missing(
        "provider_feedbacks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("sent_by", sa.String(36), nullable=False),
        sa.Column("sent_by_role", sa.String(64), nullable=False),
        sa.Column("qa_case_id", sa.String(36), nullable=True),
        sa.Column("medical_director_review_id", sa.String(36), nullable=True),
        sa.Column("feedback_type", sa.String(64), nullable=False, server_default="informational"),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_response", sa.Text(), nullable=True),
        sa.Column("provider_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="sent"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_feedback_tenant", "provider_feedbacks", ["tenant_id"])
    op.create_index("ix_provider_feedback_tenant_provider", "provider_feedbacks", ["tenant_id", "provider_id"])

    # -- provider_acknowledgments ----------------------------------------------
    create_if_missing(
        "provider_acknowledgments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("acknowledgment_type", sa.String(64), nullable=False),
        sa.Column("reference_id", sa.String(36), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signature", sa.String(512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_ack_tenant", "provider_acknowledgments", ["tenant_id"])
    op.create_index("ix_provider_ack_provider", "provider_acknowledgments", ["tenant_id", "provider_id"])
    op.create_index("ix_provider_ack_reference", "provider_acknowledgments", ["reference_id"])

    # -- qi_initiatives --------------------------------------------------------
    create_if_missing(
        "qi_initiatives",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("initiative_title", sa.String(255), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("source_trend_description", sa.Text(), nullable=False),
        sa.Column("baseline_metric_value", sa.Float(), nullable=True),
        sa.Column("baseline_metric_label", sa.String(255), nullable=True),
        sa.Column("target_metric_value", sa.Float(), nullable=True),
        sa.Column("target_metric_label", sa.String(255), nullable=True),
        sa.Column("current_metric_value", sa.Float(), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_completion_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("stakeholder_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("intervention_plan", sa.Text(), nullable=False),
        sa.Column("education_linkage_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("protocol_linkage_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("dashboard_metric_keys_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(64), nullable=False, server_default="identified"),
        sa.Column("outcome_summary", sa.Text(), nullable=True),
        sa.Column("effectiveness_measurement", sa.Text(), nullable=True),
        sa.Column("closure_notes", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accreditation_evidence_included", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qi_initiative_tenant", "qi_initiatives", ["tenant_id"])
    op.create_index("ix_qi_initiative_tenant_status", "qi_initiatives", ["tenant_id", "status"])
    op.create_index("ix_qi_initiative_tenant_owner", "qi_initiatives", ["tenant_id", "owner_id"])

    # -- qi_initiative_metrics -------------------------------------------------
    create_if_missing(
        "qi_initiative_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("initiative_id", sa.String(36), nullable=False),
        sa.Column("metric_key", sa.String(128), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("metric_label", sa.String(255), nullable=False),
        sa.Column("measurement_period", sa.String(32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.String(36), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qi_metric_tenant", "qi_initiative_metrics", ["tenant_id"])
    op.create_index("ix_qi_metric_tenant_initiative", "qi_initiative_metrics", ["tenant_id", "initiative_id"])

    # -- qi_action_items -------------------------------------------------------
    create_if_missing(
        "qi_action_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("initiative_id", sa.String(36), nullable=False),
        sa.Column("action_title", sa.String(255), nullable=False),
        sa.Column("action_description", sa.Text(), nullable=False),
        sa.Column("assigned_to", sa.String(36), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("completion_notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qi_action_tenant", "qi_action_items", ["tenant_id"])
    op.create_index("ix_qi_action_tenant_initiative", "qi_action_items", ["tenant_id", "initiative_id"])

    # -- qi_committee_reviews --------------------------------------------------
    create_if_missing(
        "qi_committee_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("meeting_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chair_id", sa.String(36), nullable=False),
        sa.Column("attendee_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("agenda_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("minutes_text", sa.Text(), nullable=True),
        sa.Column("action_items_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="scheduled"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qi_committee_tenant", "qi_committee_reviews", ["tenant_id"])

    # -- qa_trend_aggregations -------------------------------------------------
    create_if_missing(
        "qa_trend_aggregations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("period_type", sa.String(16), nullable=False, server_default="month"),
        sa.Column("total_charts_reviewed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_qa_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_open_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_overdue_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_qa_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_documentation_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_protocol_adherence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_timeliness_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_clinical_quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_operational_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("trigger_breakdown_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("finding_type_breakdown_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("education_assignments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("education_completions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("medical_director_escalations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("peer_reviews_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_loop_completions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "period", name="uq_qa_trend_tenant_period"),
    )
    op.create_index("ix_qa_trend_tenant", "qa_trend_aggregations", ["tenant_id"])

    # -- quality_audit_events --------------------------------------------------
    create_if_missing(
        "quality_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("actor_role", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("reference_type", sa.String(64), nullable=False),
        sa.Column("reference_id", sa.String(36), nullable=False),
        sa.Column("source_chart_id", sa.String(36), nullable=True),
        sa.Column("event_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.String(36), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quality_audit_tenant", "quality_audit_events", ["tenant_id"])
    op.create_index("ix_quality_audit_tenant_type", "quality_audit_events", ["tenant_id", "event_type"])
    op.create_index("ix_quality_audit_tenant_actor", "quality_audit_events", ["tenant_id", "actor_id"])
    op.create_index("ix_quality_audit_tenant_ref", "quality_audit_events", ["tenant_id", "reference_id"])
    op.create_index("ix_quality_audit_occurred_at", "quality_audit_events", ["tenant_id", "occurred_at"])

    # -- accreditation_evidence_packages ---------------------------------------
    create_if_missing(
        "accreditation_evidence_packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("package_name", sa.String(255), nullable=False),
        sa.Column("accreditation_type", sa.String(64), nullable=False, server_default="internal_audit"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("generated_by", sa.String(36), nullable=False),
        sa.Column("qa_evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("qi_evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("peer_review_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("education_completion_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("protocol_compliance_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("audit_log_export_url", sa.String(1024), nullable=True),
        sa.Column("package_export_url", sa.String(1024), nullable=True),
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accreditation_tenant", "accreditation_evidence_packages", ["tenant_id"])

    # -- quality_dashboard_snapshots -------------------------------------------
    create_if_missing(
        "quality_dashboard_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("snapshot_type", sa.String(64), nullable=False),
        sa.Column("snapshot_data_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quality_snapshot_tenant", "quality_dashboard_snapshots", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("quality_dashboard_snapshots")
    op.drop_table("accreditation_evidence_packages")
    op.drop_table("quality_audit_events")
    op.drop_table("qa_trend_aggregations")
    op.drop_table("qi_committee_reviews")
    op.drop_table("qi_action_items")
    op.drop_table("qi_initiative_metrics")
    op.drop_table("qi_initiatives")
    op.drop_table("provider_acknowledgments")
    op.drop_table("provider_feedbacks")
    op.drop_table("education_followups")
    op.drop_table("standing_order_versions")
    op.drop_table("standing_orders")
    op.drop_table("protocol_acknowledgments")
    op.drop_table("protocol_versions")
    op.drop_table("protocol_documents")
    op.drop_table("clinical_variances")
    op.drop_table("medical_director_notes")
    op.drop_table("medical_director_reviews")
    op.drop_table("peer_review_assignments")
    op.drop_table("peer_reviews")
    op.drop_table("qa_review_findings")
    op.drop_table("qa_scores")
    op.drop_table("qa_case_records")
    op.drop_table("qa_trigger_configurations")
