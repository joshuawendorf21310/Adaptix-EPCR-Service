"""047 add sentence evidence + AI audit event tables.

Revision ID: 047
Revises: 043
Create Date: 2026-05-12

Creates the ``epcr_sentence_evidence`` and ``epcr_ai_audit_event`` tables
that back the AI-evidence-link pillar (SentenceEvidenceService). The
schema is portable across PostgreSQL and SQLite (used by the test
harness); enum-like columns are stored as portable strings with their
canonical value sets enforced at the application layer (see
``epcr_app.services.sentence_evidence_service``).

Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``.
Fully reversible.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


SENTENCE_EVIDENCE = "epcr_sentence_evidence"
AI_AUDIT_EVENT = "epcr_ai_audit_event"


def upgrade() -> None:
    op.create_table(
        SENTENCE_EVIDENCE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        # narrative_id is a soft FK (no constraint) — narratives may live
        # in a separate, opaque store (see ai_narrative_service.py).
        sa.Column("narrative_id", sa.String(length=64), nullable=True),
        sa.Column("sentence_index", sa.Integer(), nullable=False),
        sa.Column("sentence_text", sa.Text(), nullable=False),
        sa.Column("evidence_kind", sa.String(length=32), nullable=False),
        sa.Column("evidence_ref_id", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column(
            "provider_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_epcr_sentence_evidence_confidence_range",
        ),
        sa.CheckConstraint(
            "sentence_index >= 0",
            name="ck_epcr_sentence_evidence_sentence_index_nonneg",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_sentence_evidence_tenant_id", SENTENCE_EVIDENCE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_sentence_evidence_chart_id", SENTENCE_EVIDENCE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_sentence_evidence_narrative_id",
        SENTENCE_EVIDENCE,
        ["narrative_id"],
    )
    op.create_index(
        "ix_epcr_sentence_evidence_tenant_chart",
        SENTENCE_EVIDENCE,
        ["tenant_id", "chart_id"],
    )

    op.create_table(
        AI_AUDIT_EVENT,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column("event_kind", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_ai_audit_event_tenant_id", AI_AUDIT_EVENT, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_ai_audit_event_chart_id", AI_AUDIT_EVENT, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_ai_audit_event_event_kind", AI_AUDIT_EVENT, ["event_kind"]
    )
    op.create_index(
        "ix_epcr_ai_audit_event_tenant_chart",
        AI_AUDIT_EVENT,
        ["tenant_id", "chart_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_ai_audit_event_tenant_chart", table_name=AI_AUDIT_EVENT
    )
    op.drop_index(
        "ix_epcr_ai_audit_event_event_kind", table_name=AI_AUDIT_EVENT
    )
    op.drop_index("ix_epcr_ai_audit_event_chart_id", table_name=AI_AUDIT_EVENT)
    op.drop_index("ix_epcr_ai_audit_event_tenant_id", table_name=AI_AUDIT_EVENT)
    op.drop_table(AI_AUDIT_EVENT)

    op.drop_index(
        "ix_epcr_sentence_evidence_tenant_chart",
        table_name=SENTENCE_EVIDENCE,
    )
    op.drop_index(
        "ix_epcr_sentence_evidence_narrative_id",
        table_name=SENTENCE_EVIDENCE,
    )
    op.drop_index(
        "ix_epcr_sentence_evidence_chart_id", table_name=SENTENCE_EVIDENCE
    )
    op.drop_index(
        "ix_epcr_sentence_evidence_tenant_id", table_name=SENTENCE_EVIDENCE
    )
    op.drop_table(SENTENCE_EVIDENCE)
