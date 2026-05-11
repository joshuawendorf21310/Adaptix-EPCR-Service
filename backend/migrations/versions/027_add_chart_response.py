"""027 add epcr_chart_response + epcr_chart_response_delays (NEMSIS eResponse).

Revision ID: 027
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eResponse 1:1 metadata aggregate
(``epcr_chart_response``) and the 1:M typed-delay aggregate
(``epcr_chart_response_delays``) for charts. Coded and free-text
columns are nullable; the chart-finalization gate enforces the
Required-and-Mandatory subset via the registry-driven validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "027"
down_revision = "023"
branch_labels = None
depends_on = None


RESPONSE_TABLE = "epcr_chart_response"
DELAYS_TABLE = "epcr_chart_response_delays"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, RESPONSE_TABLE):
        op.create_table(
            RESPONSE_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("agency_number", sa.String(16), nullable=True),
            sa.Column("agency_name", sa.String(255), nullable=True),
            sa.Column("type_of_service_requested_code", sa.String(16), nullable=True),
            sa.Column("standby_purpose_code", sa.String(16), nullable=True),
            sa.Column("unit_transport_capability_code", sa.String(16), nullable=True),
            sa.Column("unit_vehicle_number", sa.String(32), nullable=True),
            sa.Column("unit_call_sign", sa.String(32), nullable=True),
            sa.Column("vehicle_dispatch_address", sa.String(255), nullable=True),
            sa.Column("vehicle_dispatch_lat", sa.Float(), nullable=True),
            sa.Column("vehicle_dispatch_long", sa.Float(), nullable=True),
            sa.Column("vehicle_dispatch_usng", sa.String(64), nullable=True),
            sa.Column("beginning_odometer", sa.Float(), nullable=True),
            sa.Column("on_scene_odometer", sa.Float(), nullable=True),
            sa.Column("destination_odometer", sa.Float(), nullable=True),
            sa.Column("ending_odometer", sa.Float(), nullable=True),
            sa.Column("response_mode_to_scene_code", sa.String(16), nullable=True),
            sa.Column("additional_response_descriptors_json", sa.JSON(), nullable=True),
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
                name="uq_epcr_chart_response_tenant_chart",
            ),
        )

    if not _has_index(insp, RESPONSE_TABLE, "ix_epcr_chart_response_tenant_id"):
        op.create_index(
            "ix_epcr_chart_response_tenant_id",
            RESPONSE_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, RESPONSE_TABLE, "ix_epcr_chart_response_chart_id"):
        op.create_index(
            "ix_epcr_chart_response_chart_id",
            RESPONSE_TABLE,
            ["chart_id"],
        )

    if not _has_table(insp, DELAYS_TABLE):
        op.create_table(
            DELAYS_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("delay_kind", sa.String(16), nullable=False),
            sa.Column("delay_code", sa.String(32), nullable=False),
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
                "delay_kind",
                "delay_code",
                name="uq_chart_response_delays_kind_code",
            ),
        )

    if not _has_index(insp, DELAYS_TABLE, "ix_epcr_chart_response_delays_tenant_id"):
        op.create_index(
            "ix_epcr_chart_response_delays_tenant_id",
            DELAYS_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, DELAYS_TABLE, "ix_epcr_chart_response_delays_chart_id"):
        op.create_index(
            "ix_epcr_chart_response_delays_chart_id",
            DELAYS_TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, DELAYS_TABLE, "ix_epcr_chart_response_delays_chart_id"):
        op.drop_index("ix_epcr_chart_response_delays_chart_id", table_name=DELAYS_TABLE)
    if _has_index(insp, DELAYS_TABLE, "ix_epcr_chart_response_delays_tenant_id"):
        op.drop_index("ix_epcr_chart_response_delays_tenant_id", table_name=DELAYS_TABLE)
    if _has_table(insp, DELAYS_TABLE):
        op.drop_table(DELAYS_TABLE)

    if _has_index(insp, RESPONSE_TABLE, "ix_epcr_chart_response_chart_id"):
        op.drop_index("ix_epcr_chart_response_chart_id", table_name=RESPONSE_TABLE)
    if _has_index(insp, RESPONSE_TABLE, "ix_epcr_chart_response_tenant_id"):
        op.drop_index("ix_epcr_chart_response_tenant_id", table_name=RESPONSE_TABLE)
    if _has_table(insp, RESPONSE_TABLE):
        op.drop_table(RESPONSE_TABLE)
