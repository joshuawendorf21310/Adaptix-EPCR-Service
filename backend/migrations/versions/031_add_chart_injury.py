"""031 add epcr_chart_injury + epcr_chart_injury_acn (NEMSIS eInjury).

Revision ID: 031
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eInjury 1:1 child table for charts (eInjury.01
..10) plus the 1:1 Automated Crash Notification Group sub-aggregate
(eInjury.11..29). All non-key columns are nullable; the chart-
finalization gate enforces any Mandatory/Required-at-National subsets
via the registry-driven validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "031"
down_revision = "023"
branch_labels = None
depends_on = None


INJURY_TABLE = "epcr_chart_injury"
ACN_TABLE = "epcr_chart_injury_acn"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, INJURY_TABLE):
        op.create_table(
            INJURY_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("cause_of_injury_codes_json", sa.JSON(), nullable=True),
            sa.Column("mechanism_of_injury_code", sa.String(16), nullable=True),
            sa.Column("trauma_triage_high_codes_json", sa.JSON(), nullable=True),
            sa.Column("trauma_triage_moderate_codes_json", sa.JSON(), nullable=True),
            sa.Column("vehicle_impact_area_code", sa.String(16), nullable=True),
            sa.Column("patient_location_in_vehicle_code", sa.String(16), nullable=True),
            sa.Column("occupant_safety_equipment_codes_json", sa.JSON(), nullable=True),
            sa.Column("airbag_deployment_code", sa.String(16), nullable=True),
            sa.Column("height_of_fall_feet", sa.Float(), nullable=True),
            sa.Column("osha_ppe_used_codes_json", sa.JSON(), nullable=True),
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
                name="uq_epcr_chart_injury_tenant_chart",
            ),
        if_not_exists=True)

    if not _has_index(insp, INJURY_TABLE, "ix_epcr_chart_injury_tenant_id"):
        op.create_index(
            "ix_epcr_chart_injury_tenant_id",
            INJURY_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, INJURY_TABLE, "ix_epcr_chart_injury_chart_id"):
        op.create_index(
            "ix_epcr_chart_injury_chart_id",
            INJURY_TABLE,
            ["chart_id"],
        )

    # Refresh inspector after first table creation so ACN FK checks see it.
    insp = sa.inspect(bind)

    if not _has_table(insp, ACN_TABLE):
        op.create_table(
            ACN_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column(
                "injury_id",
                sa.String(36),
                sa.ForeignKey("epcr_chart_injury.id"),
                nullable=False,
            ),
            sa.Column("acn_system_company", sa.String(255), nullable=True),
            sa.Column("acn_incident_id", sa.String(64), nullable=True),
            sa.Column("acn_callback_phone", sa.String(32), nullable=True),
            sa.Column("acn_incident_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acn_incident_location", sa.String(255), nullable=True),
            sa.Column("acn_vehicle_body_type_code", sa.String(16), nullable=True),
            sa.Column("acn_vehicle_manufacturer", sa.String(120), nullable=True),
            sa.Column("acn_vehicle_make", sa.String(120), nullable=True),
            sa.Column("acn_vehicle_model", sa.String(120), nullable=True),
            sa.Column("acn_vehicle_model_year", sa.Integer(), nullable=True),
            sa.Column("acn_multiple_impacts_code", sa.String(16), nullable=True),
            sa.Column("acn_delta_velocity", sa.Float(), nullable=True),
            sa.Column("acn_high_probability_code", sa.String(16), nullable=True),
            sa.Column("acn_pdof", sa.Integer(), nullable=True),
            sa.Column("acn_rollover_code", sa.String(16), nullable=True),
            sa.Column("acn_seat_location_code", sa.String(16), nullable=True),
            sa.Column("seat_occupied_code", sa.String(16), nullable=True),
            sa.Column("acn_seatbelt_use_code", sa.String(16), nullable=True),
            sa.Column("acn_airbag_deployed_code", sa.String(16), nullable=True),
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
                name="uq_epcr_chart_injury_acn_tenant_chart",
            ),
            sa.UniqueConstraint(
                "injury_id",
                name="uq_epcr_chart_injury_acn_injury",
            ),
        if_not_exists=True)

    if not _has_index(insp, ACN_TABLE, "ix_epcr_chart_injury_acn_tenant_id"):
        op.create_index(
            "ix_epcr_chart_injury_acn_tenant_id",
            ACN_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, ACN_TABLE, "ix_epcr_chart_injury_acn_chart_id"):
        op.create_index(
            "ix_epcr_chart_injury_acn_chart_id",
            ACN_TABLE,
            ["chart_id"],
        )
    if not _has_index(insp, ACN_TABLE, "ix_epcr_chart_injury_acn_injury_id"):
        op.create_index(
            "ix_epcr_chart_injury_acn_injury_id",
            ACN_TABLE,
            ["injury_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, ACN_TABLE, "ix_epcr_chart_injury_acn_injury_id"):
        op.drop_index("ix_epcr_chart_injury_acn_injury_id", table_name=ACN_TABLE)
    if _has_index(insp, ACN_TABLE, "ix_epcr_chart_injury_acn_chart_id"):
        op.drop_index("ix_epcr_chart_injury_acn_chart_id", table_name=ACN_TABLE)
    if _has_index(insp, ACN_TABLE, "ix_epcr_chart_injury_acn_tenant_id"):
        op.drop_index("ix_epcr_chart_injury_acn_tenant_id", table_name=ACN_TABLE)
    if _has_table(insp, ACN_TABLE):
        op.drop_table(ACN_TABLE)

    insp = sa.inspect(bind)

    if _has_index(insp, INJURY_TABLE, "ix_epcr_chart_injury_chart_id"):
        op.drop_index("ix_epcr_chart_injury_chart_id", table_name=INJURY_TABLE)
    if _has_index(insp, INJURY_TABLE, "ix_epcr_chart_injury_tenant_id"):
        op.drop_index("ix_epcr_chart_injury_tenant_id", table_name=INJURY_TABLE)
    if _has_table(insp, INJURY_TABLE):
        op.drop_table(INJURY_TABLE)
