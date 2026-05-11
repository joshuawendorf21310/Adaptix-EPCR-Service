"""039 add intervention NEMSIS eProcedures extension tables.

Revision ID: 039
Revises: 023
Create Date: 2026-05-10

Adds two tables to carry NEMSIS v3.5.1 eProcedures attributes that the
existing :class:`ClinicalIntervention` row does not cover:

* ``epcr_intervention_nemsis_ext`` — 1:1 side-car keyed by
  ``intervention_id`` carrying eProcedures.02/05/06/10/11/12/13/14.
* ``epcr_intervention_complications`` — 1:M repeating element
  eProcedures.07 (Procedure Complication).

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "039"
down_revision = "023"
branch_labels = None
depends_on = None


EXT_TABLE = "epcr_intervention_nemsis_ext"
COMP_TABLE = "epcr_intervention_complications"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, EXT_TABLE):
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
                "intervention_id",
                sa.String(36),
                sa.ForeignKey("epcr_interventions.id"),
                nullable=False,
            ),
            sa.Column("prior_to_ems_indicator_code", sa.String(16), nullable=True),
            sa.Column("number_of_attempts", sa.Integer(), nullable=True),
            sa.Column("procedure_successful_code", sa.String(16), nullable=True),
            sa.Column("ems_professional_type_code", sa.String(16), nullable=True),
            sa.Column("authorization_code", sa.String(16), nullable=True),
            sa.Column("authorizing_physician_last_name", sa.String(120), nullable=True),
            sa.Column("authorizing_physician_first_name", sa.String(120), nullable=True),
            sa.Column("by_another_unit_indicator_code", sa.String(16), nullable=True),
            sa.Column("pre_existing_indicator_code", sa.String(16), nullable=True),
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
                "intervention_id",
                name="uq_epcr_intervention_nemsis_ext_tenant_intervention",
            ),
        )

    if not _has_index(insp, EXT_TABLE, "ix_epcr_intervention_nemsis_ext_tenant_id"):
        op.create_index(
            "ix_epcr_intervention_nemsis_ext_tenant_id",
            EXT_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, EXT_TABLE, "ix_epcr_intervention_nemsis_ext_chart_id"):
        op.create_index(
            "ix_epcr_intervention_nemsis_ext_chart_id",
            EXT_TABLE,
            ["chart_id"],
        )
    if not _has_index(insp, EXT_TABLE, "ix_epcr_intervention_nemsis_ext_intervention_id"):
        op.create_index(
            "ix_epcr_intervention_nemsis_ext_intervention_id",
            EXT_TABLE,
            ["intervention_id"],
        )

    if not _has_table(insp, COMP_TABLE):
        op.create_table(
            COMP_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column(
                "intervention_id",
                sa.String(36),
                sa.ForeignKey("epcr_interventions.id"),
                nullable=False,
            ),
            sa.Column("complication_code", sa.String(16), nullable=False),
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
                "intervention_id",
                "complication_code",
                name="uq_epcr_intervention_complications_tenant_intervention_code",
            ),
        )

    if not _has_index(insp, COMP_TABLE, "ix_epcr_intervention_complications_tenant_id"):
        op.create_index(
            "ix_epcr_intervention_complications_tenant_id",
            COMP_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, COMP_TABLE, "ix_epcr_intervention_complications_chart_id"):
        op.create_index(
            "ix_epcr_intervention_complications_chart_id",
            COMP_TABLE,
            ["chart_id"],
        )
    if not _has_index(insp, COMP_TABLE, "ix_epcr_intervention_complications_intervention_id"):
        op.create_index(
            "ix_epcr_intervention_complications_intervention_id",
            COMP_TABLE,
            ["intervention_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for ix in (
        "ix_epcr_intervention_complications_intervention_id",
        "ix_epcr_intervention_complications_chart_id",
        "ix_epcr_intervention_complications_tenant_id",
    ):
        if _has_index(insp, COMP_TABLE, ix):
            op.drop_index(ix, table_name=COMP_TABLE)
    if _has_table(insp, COMP_TABLE):
        op.drop_table(COMP_TABLE)

    for ix in (
        "ix_epcr_intervention_nemsis_ext_intervention_id",
        "ix_epcr_intervention_nemsis_ext_chart_id",
        "ix_epcr_intervention_nemsis_ext_tenant_id",
    ):
        if _has_index(insp, EXT_TABLE, ix):
            op.drop_index(ix, table_name=EXT_TABLE)
    if _has_table(insp, EXT_TABLE):
        op.drop_table(EXT_TABLE)
