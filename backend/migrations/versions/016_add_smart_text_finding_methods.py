"""Add Smart Text Box system and epcr_finding_methods table.

Revision ID: 016
Revises: 015
Create Date: 2026-05-03

Adds:
- epcr_smart_text_sessions: Smart text composition sessions with raw text preservation
- epcr_smart_text_proposals: Structured extraction proposals (never auto-accepted)
- epcr_smart_text_audit: Immutable audit records for proposal actions
- epcr_finding_methods: Reference table for finding detection methods
"""
from alembic import op
import sqlalchemy as sa


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "epcr_smart_text_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("text_source", sa.String(64), nullable=False),
        sa.Column("context_section", sa.String(64), nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    op.create_index("ix_epcr_smart_text_sessions_chart_id", "epcr_smart_text_sessions", ["chart_id"])

    op.create_table(
        "epcr_smart_text_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("epcr_smart_text_sessions.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("raw_source_text", sa.Text, nullable=False),
        sa.Column("span_start", sa.Integer, nullable=True),
        sa.Column("span_end", sa.Integer, nullable=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_label", sa.String(255), nullable=False),
        sa.Column("entity_payload_json", sa.Text, nullable=False),
        sa.Column("target_chart_field", sa.String(128), nullable=True),
        sa.Column("target_chart_section", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("suggested_binding_json", sa.Text, nullable=True),
        sa.Column("proposal_state", sa.String(64), nullable=False, server_default="pending_review"),
        sa.Column("reviewer_id", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("edited_entity_json", sa.Text, nullable=True),
        sa.Column("accepted_chart_record_id", sa.String(36), nullable=True),
        sa.Column("accepted_chart_record_type", sa.String(64), nullable=True),
        sa.Column("is_contradiction", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("contradiction_detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        if_not_exists=True)
    op.create_index("ix_epcr_smart_text_proposals_session_id", "epcr_smart_text_proposals", ["session_id"])
    op.create_index("ix_epcr_smart_text_proposals_chart_id", "epcr_smart_text_proposals", ["chart_id"])

    op.create_table(
        "epcr_smart_text_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("proposal_id", sa.String(36), sa.ForeignKey("epcr_smart_text_proposals.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("before_state", sa.String(64), nullable=True),
        sa.Column("after_state", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "epcr_finding_methods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("method_code", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("requires_review", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        if_not_exists=True)

    # Seed canonical finding methods
    op.bulk_insert(
        sa.table(
            "epcr_finding_methods",
            sa.column("id", sa.String),
            sa.column("method_code", sa.String),
            sa.column("display_name", sa.String),
            sa.column("requires_review", sa.Boolean),
            sa.column("is_active", sa.Boolean),
            sa.column("sort_order", sa.Integer),
        ),
        [
            {"id": "00000000-0000-0000-0001-000000000001", "method_code": "direct_observation", "display_name": "Direct Observation", "requires_review": False, "is_active": True, "sort_order": 1},
            {"id": "00000000-0000-0000-0001-000000000002", "method_code": "palpation", "display_name": "Palpation", "requires_review": False, "is_active": True, "sort_order": 2},
            {"id": "00000000-0000-0000-0001-000000000003", "method_code": "auscultation", "display_name": "Auscultation", "requires_review": False, "is_active": True, "sort_order": 3},
            {"id": "00000000-0000-0000-0001-000000000004", "method_code": "device_reading", "display_name": "Device Reading", "requires_review": False, "is_active": True, "sort_order": 4},
            {"id": "00000000-0000-0000-0001-000000000005", "method_code": "vision_proposal", "display_name": "Vision Proposal", "requires_review": True, "is_active": True, "sort_order": 5},
            {"id": "00000000-0000-0000-0001-000000000006", "method_code": "voice_proposal", "display_name": "Voice Proposal", "requires_review": True, "is_active": True, "sort_order": 6},
            {"id": "00000000-0000-0000-0001-000000000007", "method_code": "smart_text_proposal", "display_name": "Smart Text Proposal", "requires_review": True, "is_active": True, "sort_order": 7},
            {"id": "00000000-0000-0000-0001-000000000008", "method_code": "neurological_exam", "display_name": "Neurological Exam", "requires_review": False, "is_active": True, "sort_order": 8},
            {"id": "00000000-0000-0000-0001-000000000009", "method_code": "percussion", "display_name": "Percussion", "requires_review": False, "is_active": True, "sort_order": 9},
        ]
    )


def downgrade() -> None:
    op.drop_table("epcr_finding_methods")
    op.drop_table("epcr_smart_text_audit")
    op.drop_table("epcr_smart_text_proposals")
    op.drop_table("epcr_smart_text_sessions")
