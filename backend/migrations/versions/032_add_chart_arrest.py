"""032 add epcr_chart_arrest (NEMSIS eArrest 1:1 aggregate).

Revision ID: 032
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eArrest 1:1 child table for charts. The row is
only populated when cardiac arrest is indicated. Only
``cardiac_arrest_code`` (eArrest.01) is NOT NULL on the row itself; all
other columns are nullable because not every arrest captures every
element. The chart-finalization gate enforces the
Mandatory/Required-at-National/Conditional subset via the
registry-driven validator.

The four ``*_codes_json`` columns hold JSON arrays of NEMSIS code
values (1:M repeating-group lists) projected into separate ledger
rows by the projection layer.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "032"
down_revision = "023"
branch_labels = None
depends_on = None


TABLE = "epcr_chart_arrest"


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
            sa.Column("cardiac_arrest_code", sa.String(16), nullable=False),
            sa.Column("etiology_code", sa.String(16), nullable=True),
            sa.Column("resuscitation_attempted_codes_json", sa.JSON(), nullable=True),
            sa.Column("witnessed_by_codes_json", sa.JSON(), nullable=True),
            sa.Column("aed_use_prior_code", sa.String(16), nullable=True),
            sa.Column("cpr_type_codes_json", sa.JSON(), nullable=True),
            sa.Column("hypothermia_indicator_code", sa.String(16), nullable=True),
            sa.Column("first_monitored_rhythm_code", sa.String(16), nullable=True),
            sa.Column("rosc_codes_json", sa.JSON(), nullable=True),
            sa.Column("neurological_outcome_code", sa.String(16), nullable=True),
            sa.Column("arrest_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resuscitation_discontinued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reason_discontinued_code", sa.String(16), nullable=True),
            sa.Column("rhythm_on_arrival_code", sa.String(16), nullable=True),
            sa.Column("end_of_event_code", sa.String(16), nullable=True),
            sa.Column("initial_cpr_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("who_first_cpr_code", sa.String(16), nullable=True),
            sa.Column("who_first_aed_code", sa.String(16), nullable=True),
            sa.Column("who_first_defib_code", sa.String(16), nullable=True),
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
                name="uq_epcr_chart_arrest_tenant_chart",
            ),
        )

    if not _has_index(insp, TABLE, "ix_epcr_chart_arrest_tenant_id"):
        op.create_index(
            "ix_epcr_chart_arrest_tenant_id",
            TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE, "ix_epcr_chart_arrest_chart_id"):
        op.create_index(
            "ix_epcr_chart_arrest_chart_id",
            TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, TABLE, "ix_epcr_chart_arrest_chart_id"):
        op.drop_index("ix_epcr_chart_arrest_chart_id", table_name=TABLE)
    if _has_index(insp, TABLE, "ix_epcr_chart_arrest_tenant_id"):
        op.drop_index("ix_epcr_chart_arrest_tenant_id", table_name=TABLE)
    if _has_table(insp, TABLE):
        op.drop_table(TABLE)
