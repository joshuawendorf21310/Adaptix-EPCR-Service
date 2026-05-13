"""051 add epcr_icd10_documentation_suggestion for ICD-10 specificity prompts

Revision ID: 051
Revises: 043
Create Date: 2026-05-12

Creates ``epcr_icd10_documentation_suggestion`` -- the persistence table
for the ICD-10 *documentation specificity prompt* pillar. The table
holds **prompts**, never auto-assigned diagnoses. ``candidate_codes_json``
is a JSON-encoded list of ``{"code","description"}`` suggestions
displayed to the clinician; ``provider_selected_code`` is populated
**only** by an explicit provider acknowledgement.

Reversible: ``downgrade()`` drops indexes then the table. Schema is
portable across PostgreSQL and SQLite; the test harness exercises the
SQLite path.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


TABLE = "epcr_icd10_documentation_suggestion"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column("complaint_text", sa.Text(), nullable=True),
        sa.Column("prompt_kind", sa.String(length=48), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("candidate_codes_json", sa.Text(), nullable=True),
        sa.Column(
            "provider_acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("provider_selected_code", sa.String(length=32), nullable=True),
        sa.Column("provider_selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_icd10_doc_suggestion_tenant_id", TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_icd10_doc_suggestion_chart_id", TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_icd10_doc_suggestion_prompt_kind", TABLE, ["prompt_kind"]
    )
    op.create_index(
        "ix_epcr_icd10_doc_suggestion_tenant_chart",
        TABLE,
        ["tenant_id", "chart_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_icd10_doc_suggestion_tenant_chart", table_name=TABLE
    )
    op.drop_index(
        "ix_epcr_icd10_doc_suggestion_prompt_kind", table_name=TABLE
    )
    op.drop_index("ix_epcr_icd10_doc_suggestion_chart_id", table_name=TABLE)
    op.drop_index("ix_epcr_icd10_doc_suggestion_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
