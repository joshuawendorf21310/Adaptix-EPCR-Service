"""037 add epcr_vitals_nemsis_ext + GCS qualifiers + reperfusion checklist.

Revision ID: 037
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eVitals extension tables: a per-Vitals-row
1:1 extension aggregate and two 1:M repeating-group children. The
existing ``epcr_vitals`` table (7 legacy columns) is OFF-LIMITS and is
not modified.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "037"
down_revision = "023"
branch_labels = None
depends_on = None


EXT_TABLE = "epcr_vitals_nemsis_ext"
GCS_TABLE = "epcr_vitals_gcs_qualifiers"
RC_TABLE = "epcr_vitals_reperfusion_checklist"


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


def _create_ext(insp) -> None:
    if _has_table(insp, EXT_TABLE):
        return
    op.create_table(
        EXT_TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column(
            "vitals_id",
            sa.String(36),
            sa.ForeignKey("epcr_vitals.id"),
            nullable=False,
        ),
        sa.Column("obtained_prior_to_ems_code", sa.String(16), nullable=True),
        sa.Column("cardiac_rhythm_codes_json", sa.JSON(), nullable=True),
        sa.Column("ecg_type_code", sa.String(16), nullable=True),
        sa.Column(
            "ecg_interpretation_method_codes_json", sa.JSON(), nullable=True
        ),
        sa.Column("blood_pressure_method_code", sa.String(16), nullable=True),
        sa.Column("mean_arterial_pressure", sa.Integer(), nullable=True),
        sa.Column("heart_rate_method_code", sa.String(16), nullable=True),
        sa.Column("pulse_rhythm_code", sa.String(16), nullable=True),
        sa.Column("respiratory_effort_code", sa.String(16), nullable=True),
        sa.Column("etco2", sa.Integer(), nullable=True),
        sa.Column("carbon_monoxide_ppm", sa.Float(), nullable=True),
        sa.Column("gcs_eye_code", sa.String(16), nullable=True),
        sa.Column("gcs_verbal_code", sa.String(16), nullable=True),
        sa.Column("gcs_motor_code", sa.String(16), nullable=True),
        sa.Column("gcs_total", sa.Integer(), nullable=True),
        sa.Column("temperature_method_code", sa.String(16), nullable=True),
        sa.Column("avpu_code", sa.String(16), nullable=True),
        sa.Column("pain_score", sa.Integer(), nullable=True),
        sa.Column("pain_scale_type_code", sa.String(16), nullable=True),
        sa.Column("stroke_scale_result_code", sa.String(16), nullable=True),
        sa.Column("stroke_scale_type_code", sa.String(16), nullable=True),
        sa.Column("stroke_scale_score", sa.Integer(), nullable=True),
        sa.Column("apgar_score", sa.Integer(), nullable=True),
        sa.Column("revised_trauma_score", sa.Integer(), nullable=True),
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
            "vitals_id",
            name="uq_epcr_vitals_nemsis_ext_tenant_vitals",
        ),
        sa.UniqueConstraint(
            "vitals_id",
            name="uq_epcr_vitals_nemsis_ext_vitals_id",
        ),
        if_not_exists=True)


def _create_gcs(insp) -> None:
    if _has_table(insp, GCS_TABLE):
        return
    op.create_table(
        GCS_TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column(
            "vitals_id",
            sa.String(36),
            sa.ForeignKey("epcr_vitals.id"),
            nullable=False,
        ),
        sa.Column("qualifier_code", sa.String(16), nullable=False),
        sa.Column(
            "sequence_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
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
            "vitals_id",
            "qualifier_code",
            name="uq_epcr_vitals_gcs_qualifiers_tenant_vitals_code",
        ),
        if_not_exists=True)


def _create_rc(insp) -> None:
    if _has_table(insp, RC_TABLE):
        return
    op.create_table(
        RC_TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column(
            "vitals_id",
            sa.String(36),
            sa.ForeignKey("epcr_vitals.id"),
            nullable=False,
        ),
        sa.Column("item_code", sa.String(16), nullable=False),
        sa.Column(
            "sequence_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
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
            "vitals_id",
            "item_code",
            name="uq_epcr_vitals_reperfusion_checklist_tenant_vitals_code",
        ),
        if_not_exists=True)


def _create_indexes(insp) -> None:
    pairs = [
        (EXT_TABLE, "ix_epcr_vitals_nemsis_ext_tenant_id", ["tenant_id"]),
        (EXT_TABLE, "ix_epcr_vitals_nemsis_ext_chart_id", ["chart_id"]),
        (EXT_TABLE, "ix_epcr_vitals_nemsis_ext_vitals_id", ["vitals_id"]),
        (GCS_TABLE, "ix_epcr_vitals_gcs_qualifiers_tenant_id", ["tenant_id"]),
        (GCS_TABLE, "ix_epcr_vitals_gcs_qualifiers_chart_id", ["chart_id"]),
        (GCS_TABLE, "ix_epcr_vitals_gcs_qualifiers_vitals_id", ["vitals_id"]),
        (RC_TABLE, "ix_epcr_vitals_reperfusion_checklist_tenant_id", ["tenant_id"]),
        (RC_TABLE, "ix_epcr_vitals_reperfusion_checklist_chart_id", ["chart_id"]),
        (RC_TABLE, "ix_epcr_vitals_reperfusion_checklist_vitals_id", ["vitals_id"]),
    ]
    for table, name, cols in pairs:
        if not _has_index(insp, table, name):
            op.create_index(name, table, cols)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    _create_ext(insp)
    _create_gcs(insp)
    _create_rc(insp)
    # Re-inspect after creates so index gating sees the fresh tables.
    insp = sa.inspect(bind)
    _create_indexes(insp)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    drop_indexes = [
        (EXT_TABLE, "ix_epcr_vitals_nemsis_ext_vitals_id"),
        (EXT_TABLE, "ix_epcr_vitals_nemsis_ext_chart_id"),
        (EXT_TABLE, "ix_epcr_vitals_nemsis_ext_tenant_id"),
        (GCS_TABLE, "ix_epcr_vitals_gcs_qualifiers_vitals_id"),
        (GCS_TABLE, "ix_epcr_vitals_gcs_qualifiers_chart_id"),
        (GCS_TABLE, "ix_epcr_vitals_gcs_qualifiers_tenant_id"),
        (RC_TABLE, "ix_epcr_vitals_reperfusion_checklist_vitals_id"),
        (RC_TABLE, "ix_epcr_vitals_reperfusion_checklist_chart_id"),
        (RC_TABLE, "ix_epcr_vitals_reperfusion_checklist_tenant_id"),
    ]
    for table, name in drop_indexes:
        if _has_index(insp, table, name):
            op.drop_index(name, table_name=table)

    for table in (RC_TABLE, GCS_TABLE, EXT_TABLE):
        if _has_table(insp, table):
            op.drop_table(table)
