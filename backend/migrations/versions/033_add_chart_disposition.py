"""033 add epcr_chart_disposition (NEMSIS eDisposition 1:1 aggregate).

Revision ID: 033
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eDisposition 1:1 child table for charts. All
columns are nullable in the schema; the chart-finalization gate
enforces NEMSIS Mandatory (eDisposition.12) and Required-at-National
(eDisposition.16, eDisposition.18) subsets via the registry-driven
validator.

The ``*_codes_json`` columns hold JSON arrays of NEMSIS code values
(1:M repeating-group lists) projected into separate ledger rows by
the projection layer.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "033"
down_revision = "023"
branch_labels = None
depends_on = None


TABLE = "epcr_chart_disposition"


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
            # eDisposition.01..08 — destination identification + address
            sa.Column("destination_name", sa.String(255), nullable=True),
            sa.Column("destination_code", sa.String(64), nullable=True),
            sa.Column("destination_address", sa.String(255), nullable=True),
            sa.Column("destination_city", sa.String(120), nullable=True),
            sa.Column("destination_county", sa.String(120), nullable=True),
            sa.Column("destination_state", sa.String(8), nullable=True),
            sa.Column("destination_zip", sa.String(16), nullable=True),
            sa.Column("destination_country", sa.String(8), nullable=True),
            # eDisposition.09..10 (1:M)
            sa.Column("hospital_capability_codes_json", sa.JSON(), nullable=True),
            sa.Column(
                "reason_for_choosing_destination_codes_json",
                sa.JSON(),
                nullable=True,
            ),
            # eDisposition.11..12
            sa.Column("type_of_destination_code", sa.String(16), nullable=True),
            sa.Column(
                "incident_patient_disposition_code", sa.String(16), nullable=True
            ),
            # eDisposition.13..14
            sa.Column(
                "transport_mode_from_scene_code", sa.String(16), nullable=True
            ),
            sa.Column(
                "additional_transport_descriptors_codes_json",
                sa.JSON(),
                nullable=True,
            ),
            # eDisposition.15 (1:M)
            sa.Column(
                "hospital_incapability_codes_json", sa.JSON(), nullable=True
            ),
            # eDisposition.16..18
            sa.Column("transport_disposition_code", sa.String(16), nullable=True),
            sa.Column("reason_not_transported_code", sa.String(16), nullable=True),
            sa.Column("level_of_care_provided_code", sa.String(16), nullable=True),
            # eDisposition.19..21
            sa.Column(
                "position_during_transport_code", sa.String(16), nullable=True
            ),
            sa.Column("condition_at_destination_code", sa.String(16), nullable=True),
            sa.Column("transferred_care_to_code", sa.String(16), nullable=True),
            # eDisposition.22..24 (1:M)
            sa.Column(
                "prearrival_activation_codes_json", sa.JSON(), nullable=True
            ),
            sa.Column(
                "type_of_destination_reason_codes_json", sa.JSON(), nullable=True
            ),
            sa.Column(
                "destination_team_activations_codes_json", sa.JSON(), nullable=True
            ),
            # eDisposition.25
            sa.Column(
                "destination_type_when_reason_code", sa.String(16), nullable=True
            ),
            # eDisposition.27..30 (.26 not defined in v3.5.1)
            sa.Column("crew_disposition_codes_json", sa.JSON(), nullable=True),
            sa.Column("unit_disposition_code", sa.String(16), nullable=True),
            sa.Column("transport_method_code", sa.String(16), nullable=True),
            sa.Column(
                "transport_method_additional_codes_json", sa.JSON(), nullable=True
            ),
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
            sa.Column(
                "version", sa.Integer(), nullable=False, server_default=sa.text("1")
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                name="uq_epcr_chart_disposition_tenant_chart",
            ),
        if_not_exists=True)

    if not _has_index(insp, TABLE, "ix_epcr_chart_disposition_tenant_id"):
        op.create_index(
            "ix_epcr_chart_disposition_tenant_id",
            TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE, "ix_epcr_chart_disposition_chart_id"):
        op.create_index(
            "ix_epcr_chart_disposition_chart_id",
            TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, TABLE, "ix_epcr_chart_disposition_chart_id"):
        op.drop_index("ix_epcr_chart_disposition_chart_id", table_name=TABLE)
    if _has_index(insp, TABLE, "ix_epcr_chart_disposition_tenant_id"):
        op.drop_index("ix_epcr_chart_disposition_tenant_id", table_name=TABLE)
    if _has_table(insp, TABLE):
        op.drop_table(TABLE)
