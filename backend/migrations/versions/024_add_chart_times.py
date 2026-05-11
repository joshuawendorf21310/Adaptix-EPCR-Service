"""024 add epcr_chart_times (NEMSIS eTimes 1:1 aggregate).

Revision ID: 024
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eTimes 1:1 child table for charts. All 17
DateTime columns are nullable; the chart-finalization gate enforces
the Required-at-National subset via the registry-driven validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


TABLE = "epcr_chart_times"


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
            sa.Column("psap_call_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dispatch_notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unit_notified_by_dispatch_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dispatch_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unit_en_route_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unit_on_scene_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("arrived_at_patient_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("transfer_of_ems_care_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unit_left_scene_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("arrival_landing_area_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("patient_arrived_at_destination_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("destination_transfer_of_care_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unit_back_in_service_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unit_canceled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unit_back_home_location_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ems_call_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("unit_arrived_staging_at", sa.DateTime(timezone=True), nullable=True),
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
                name="uq_epcr_chart_times_tenant_chart",
            ),
        )

    if not _has_index(insp, TABLE, "ix_epcr_chart_times_tenant_id"):
        op.create_index(
            "ix_epcr_chart_times_tenant_id",
            TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE, "ix_epcr_chart_times_chart_id"):
        op.create_index(
            "ix_epcr_chart_times_chart_id",
            TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, TABLE, "ix_epcr_chart_times_chart_id"):
        op.drop_index("ix_epcr_chart_times_chart_id", table_name=TABLE)
    if _has_index(insp, TABLE, "ix_epcr_chart_times_tenant_id"):
        op.drop_index("ix_epcr_chart_times_tenant_id", table_name=TABLE)
    if _has_table(insp, TABLE):
        op.drop_table(TABLE)
