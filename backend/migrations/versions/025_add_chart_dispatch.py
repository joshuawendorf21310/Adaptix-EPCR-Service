"""025 add epcr_chart_dispatch (NEMSIS eDispatch 1:1 aggregate).

Revision ID: 025
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eDispatch 1:1 child table for charts. All 6
columns are nullable; the chart-finalization gate enforces the
Mandatory/Required-at-National subset via the registry-driven
validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "025"
down_revision = "023"
branch_labels = None
depends_on = None


TABLE = "epcr_chart_dispatch"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def _has_unique(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    constraints = insp.get_unique_constraints(table)
    return any(c["name"] == name for c in constraints)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("dispatch_reason_code", sa.String(16), nullable=True),
            sa.Column("emd_performed_code", sa.String(16), nullable=True),
            sa.Column("emd_determinant_code", sa.String(64), nullable=True),
            sa.Column("dispatch_center_id", sa.String(128), nullable=True),
            sa.Column("dispatch_priority_code", sa.String(16), nullable=True),
            sa.Column("cad_record_id", sa.String(64), nullable=True),
            sa.Column("created_by_user_id", sa.String(64), nullable=True),
            sa.Column("updated_by_user_id", sa.String(64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                name="uq_epcr_chart_dispatch_tenant_chart",
            ),
        )

    if not _has_index(insp, TABLE, "ix_epcr_chart_dispatch_tenant_id"):
        op.create_index(
            "ix_epcr_chart_dispatch_tenant_id",
            TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE, "ix_epcr_chart_dispatch_chart_id"):
        op.create_index(
            "ix_epcr_chart_dispatch_chart_id",
            TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, TABLE, "ix_epcr_chart_dispatch_chart_id"):
        op.drop_index("ix_epcr_chart_dispatch_chart_id", table_name=TABLE)
    if _has_index(insp, TABLE, "ix_epcr_chart_dispatch_tenant_id"):
        op.drop_index("ix_epcr_chart_dispatch_tenant_id", table_name=TABLE)
    if _has_table(insp, TABLE):
        op.drop_table(TABLE)
