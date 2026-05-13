"""046 add epcr_smart_text_suggestion for SmartTextService pillar

Revision ID: 046
Revises: 043
Create Date: 2026-05-12

Creates the ``epcr_smart_text_suggestion`` table that backs the new
SmartTextService pillar. Suggestions are sourced from the agency phrase
library, provider favorites, protocols, or AI ingestion, and carry an
explicit ``confidence`` score plus ``compliance_state`` so the workspace
can render them with the appropriate provenance and review affordances.

The schema is portable across PostgreSQL and SQLite (used by the test
harness). ``evidence_link_id`` is intentionally a soft (non-enforced)
reference to ``epcr_sentence_evidence.id``; the actual FK will be wired
once that table is materialized in a downstream slice.

Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


TABLE = "epcr_smart_text_suggestion"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("field_key", sa.String(length=128), nullable=False),
        sa.Column("phrase", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("compliance_state", sa.String(length=16), nullable=False),
        sa.Column("evidence_link_id", sa.String(length=36), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("performed_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_epcr_smart_text_suggestion_confidence_range",
        ),
        sa.CheckConstraint(
            "source IN ('agency_library','provider_favorite','protocol','ai')",
            name="ck_epcr_smart_text_suggestion_source",
        ),
        sa.CheckConstraint(
            "compliance_state IN ('approved','pending','risk')",
            name="ck_epcr_smart_text_suggestion_compliance_state",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_smart_text_suggestion_chart_id", TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_smart_text_suggestion_tenant_id", TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_smart_text_suggestion_tenant_chart_section_field",
        TABLE,
        ["tenant_id", "chart_id", "section", "field_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_smart_text_suggestion_tenant_chart_section_field",
        table_name=TABLE,
    )
    op.drop_index(
        "ix_epcr_smart_text_suggestion_tenant_id", table_name=TABLE
    )
    op.drop_index(
        "ix_epcr_smart_text_suggestion_chart_id", table_name=TABLE
    )
    op.drop_table(TABLE)
