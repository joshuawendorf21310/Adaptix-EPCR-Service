"""050 add epcr_rxnorm_medication_match for the RxNormMedicationService pillar.

Revision ID: 050
Revises: 043
Create Date: 2026-05-12

Creates the ``epcr_rxnorm_medication_match`` table that backs the
RxNormMedicationService. The table doubles as the local lookup cache for
the live RxNav client: repeated normalizations for the same
``(tenant_id, medication_admin_id)`` reuse a persisted row before
falling back to the live API.

Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``.
Portable across PostgreSQL and SQLite; enum-like columns are stored as
strings and validated at the application layer.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


TABLE = "epcr_rxnorm_medication_match"


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
        # Soft FK: no DB-level constraint to medication_administration.id so
        # the match-log survives archival/soft-delete of source rows.
        sa.Column("medication_admin_id", sa.String(length=36), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.String(length=256), nullable=True),
        sa.Column("rxcui", sa.String(length=32), nullable=True),
        sa.Column("tty", sa.String(length=16), nullable=True),
        sa.Column("dose_form", sa.String(length=64), nullable=True),
        sa.Column("strength", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "provider_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_epcr_rxnorm_match_confidence_range",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_rxnorm_match_tenant_id", TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_rxnorm_match_chart_id", TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_rxnorm_match_rxcui", TABLE, ["rxcui"]
    )
    op.create_index(
        "ix_epcr_rxnorm_match_tenant_chart", TABLE, ["tenant_id", "chart_id"]
    )
    op.create_index(
        "ix_epcr_rxnorm_match_medication_admin",
        TABLE,
        ["medication_admin_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_rxnorm_match_medication_admin", table_name=TABLE
    )
    op.drop_index("ix_epcr_rxnorm_match_tenant_chart", table_name=TABLE)
    op.drop_index("ix_epcr_rxnorm_match_rxcui", table_name=TABLE)
    op.drop_index("ix_epcr_rxnorm_match_chart_id", table_name=TABLE)
    op.drop_index("ix_epcr_rxnorm_match_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
