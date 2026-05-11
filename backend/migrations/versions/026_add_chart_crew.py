"""026 add epcr_chart_crew_members (NEMSIS eCrew 1:M aggregate).

Revision ID: 026
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eCrew 1:M child table for charts. Each row is
one crew member assigned to the chart. The chart-finalization gate
enforces the Mandatory (eCrew.01/02) and Required (eCrew.03) subset
via the registry-driven validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "026"
down_revision = "023"
branch_labels = None
depends_on = None


TABLE = "epcr_chart_crew_members"


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
            sa.Column("crew_member_id", sa.String(64), nullable=False),
            sa.Column("crew_member_level_code", sa.String(16), nullable=False),
            sa.Column("crew_member_response_role_code", sa.String(16), nullable=False),
            sa.Column("sequence_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
                "crew_member_id",
                name="uq_epcr_chart_crew_members_tenant_chart_member",
            ),
        )

    if not _has_index(insp, TABLE, "ix_epcr_chart_crew_members_tenant_id"):
        op.create_index(
            "ix_epcr_chart_crew_members_tenant_id",
            TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE, "ix_epcr_chart_crew_members_chart_id"):
        op.create_index(
            "ix_epcr_chart_crew_members_chart_id",
            TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, TABLE, "ix_epcr_chart_crew_members_chart_id"):
        op.drop_index("ix_epcr_chart_crew_members_chart_id", table_name=TABLE)
    if _has_index(insp, TABLE, "ix_epcr_chart_crew_members_tenant_id"):
        op.drop_index("ix_epcr_chart_crew_members_tenant_id", table_name=TABLE)
    if _has_table(insp, TABLE):
        op.drop_table(TABLE)
