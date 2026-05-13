"""043 add epcr_anatomical_finding for 3D Physical Assessment module

Revision ID: 043
Revises: 042
Create Date: 2026-05-12

Creates the ``epcr_anatomical_finding`` table that backs the new 3D
Physical Assessment workspace section. The schema is portable across
PostgreSQL and SQLite (used by the test harness); enum-like columns are
stored as portable strings with their canonical value sets enforced at
the application layer (see
``epcr_app.services.anatomical_finding_validation``).

Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


TABLE = "epcr_anatomical_finding"


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
        sa.Column("region_id", sa.String(length=64), nullable=False),
        sa.Column("region_label", sa.String(length=128), nullable=False),
        sa.Column("body_view", sa.String(length=16), nullable=False),
        sa.Column("finding_type", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=True),
        sa.Column("laterality", sa.String(length=32), nullable=True),
        sa.Column("pain_scale", sa.SmallInteger(), nullable=True),
        sa.Column("burn_tbsa_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("cms_pulse", sa.String(length=32), nullable=True),
        sa.Column("cms_motor", sa.String(length=32), nullable=True),
        sa.Column("cms_sensation", sa.String(length=32), nullable=True),
        sa.Column("cms_capillary_refill", sa.String(length=32), nullable=True),
        sa.Column(
            "pertinent_negative",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessed_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.CheckConstraint(
            "pain_scale IS NULL OR (pain_scale >= 0 AND pain_scale <= 10)",
            name="ck_epcr_anatomical_finding_pain_scale_range",
        ),
        sa.CheckConstraint(
            "burn_tbsa_percent IS NULL OR "
            "(burn_tbsa_percent >= 0 AND burn_tbsa_percent <= 100)",
            name="ck_epcr_anatomical_finding_burn_tbsa_range",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_anatomical_finding_chart_id", TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_anatomical_finding_tenant_id", TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_anatomical_finding_region_id", TABLE, ["region_id"]
    )
    op.create_index(
        "ix_epcr_anatomical_finding_deleted_at", TABLE, ["deleted_at"]
    )
    op.create_index(
        "ix_epcr_anatomical_finding_tenant_chart_deleted",
        TABLE,
        ["tenant_id", "chart_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_anatomical_finding_tenant_chart_deleted", table_name=TABLE
    )
    op.drop_index("ix_epcr_anatomical_finding_deleted_at", table_name=TABLE)
    op.drop_index("ix_epcr_anatomical_finding_region_id", table_name=TABLE)
    op.drop_index("ix_epcr_anatomical_finding_tenant_id", table_name=TABLE)
    op.drop_index("ix_epcr_anatomical_finding_chart_id", table_name=TABLE)
    op.drop_table(TABLE)
