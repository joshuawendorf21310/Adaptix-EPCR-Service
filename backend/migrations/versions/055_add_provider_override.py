"""055 add epcr_provider_override for AuditTrail + ProviderOverride pillar.

Revision ID: 055
Revises: 043
Create Date: 2026-05-12

Creates the ``epcr_provider_override`` table that backs the canonical
provider-override audit record for validation warnings, lock blockers,
state/agency required fields, and rejected AI suggestions. The
``reason_text`` column is REQUIRED with a minimum length of 8
characters enforced via a portable CHECK constraint; the application
layer (``ProviderOverrideService.record``) additionally enforces this
to surface a structured error before the row is staged.

Portable across PostgreSQL and SQLite (used by the test harness).
Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


TABLE = "epcr_provider_override"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id", sa.String(length=36), nullable=False
        ),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("field_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column(
            "overrode_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("overrode_by", sa.String(length=255), nullable=False),
        sa.Column("supervisor_id", sa.String(length=64), nullable=True),
        sa.Column(
            "supervisor_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.CheckConstraint(
            "length(reason_text) >= 8",
            name="ck_epcr_provider_override_reason_min_length",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_provider_override_tenant_id", TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_provider_override_chart_id", TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_provider_override_kind", TABLE, ["kind"]
    )
    op.create_index(
        "ix_epcr_provider_override_tenant_chart",
        TABLE,
        ["tenant_id", "chart_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_provider_override_tenant_chart", table_name=TABLE
    )
    op.drop_index("ix_epcr_provider_override_kind", table_name=TABLE)
    op.drop_index("ix_epcr_provider_override_chart_id", table_name=TABLE)
    op.drop_index("ix_epcr_provider_override_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
