"""038 add epcr_medication_admin_ext + epcr_medication_complications.

Revision ID: 038
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eMedications additions tables. The existing
``epcr_medication_administrations`` table already covers eMedications.
01/.03/.04/.05/.06/.07/.09. These new tables add a per-medication-row
1:1 extension for the remaining additive scalars (eMedications.02,
.10, .11, .12, .13) and a 1:M repeating-group child for
eMedications.08 Medication Complication.

All NEMSIS-additive columns are nullable; the chart-finalization gate
enforces Required-at-National (eMedications.02, .08, .10) via the
registry-driven validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "038"
down_revision = "023"
branch_labels = None
depends_on = None


EXT_TABLE = "epcr_medication_admin_ext"
COMP_TABLE = "epcr_medication_complications"


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
                "medication_admin_id",
                sa.String(36),
                sa.ForeignKey("epcr_medication_administrations.id"),
                nullable=False,
                unique=True,
            ),
            sa.Column("prior_to_ems_indicator_code", sa.String(16), nullable=True),
            sa.Column("ems_professional_type_code", sa.String(16), nullable=True),
            sa.Column("authorization_code", sa.String(16), nullable=True),
            sa.Column("authorizing_physician_last_name", sa.String(120), nullable=True),
            sa.Column("authorizing_physician_first_name", sa.String(120), nullable=True),
            sa.Column("by_another_unit_indicator_code", sa.String(16), nullable=True),
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
                "medication_admin_id",
                name="uq_epcr_medication_admin_ext_tenant_med",
            ),
        )

    if not _has_index(insp, EXT_TABLE, "ix_epcr_medication_admin_ext_tenant_id"):
        op.create_index(
            "ix_epcr_medication_admin_ext_tenant_id",
            EXT_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, EXT_TABLE, "ix_epcr_medication_admin_ext_chart_id"):
        op.create_index(
            "ix_epcr_medication_admin_ext_chart_id",
            EXT_TABLE,
            ["chart_id"],
        )
    if not _has_index(insp, EXT_TABLE, "ix_epcr_medication_admin_ext_med_id"):
        op.create_index(
            "ix_epcr_medication_admin_ext_med_id",
            EXT_TABLE,
            ["medication_admin_id"],
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
                "medication_admin_id",
                sa.String(36),
                sa.ForeignKey("epcr_medication_administrations.id"),
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
                "medication_admin_id",
                "complication_code",
                name="uq_epcr_medication_complications_tenant_med_code",
            ),
        )

    if not _has_index(insp, COMP_TABLE, "ix_epcr_medication_complications_tenant_id"):
        op.create_index(
            "ix_epcr_medication_complications_tenant_id",
            COMP_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, COMP_TABLE, "ix_epcr_medication_complications_chart_id"):
        op.create_index(
            "ix_epcr_medication_complications_chart_id",
            COMP_TABLE,
            ["chart_id"],
        )
    if not _has_index(insp, COMP_TABLE, "ix_epcr_medication_complications_med_id"):
        op.create_index(
            "ix_epcr_medication_complications_med_id",
            COMP_TABLE,
            ["medication_admin_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for ix_name in (
        "ix_epcr_medication_complications_med_id",
        "ix_epcr_medication_complications_chart_id",
        "ix_epcr_medication_complications_tenant_id",
    ):
        if _has_index(insp, COMP_TABLE, ix_name):
            op.drop_index(ix_name, table_name=COMP_TABLE)
    if _has_table(insp, COMP_TABLE):
        op.drop_table(COMP_TABLE)

    for ix_name in (
        "ix_epcr_medication_admin_ext_med_id",
        "ix_epcr_medication_admin_ext_chart_id",
        "ix_epcr_medication_admin_ext_tenant_id",
    ):
        if _has_index(insp, EXT_TABLE, ix_name):
            op.drop_index(ix_name, table_name=EXT_TABLE)
    if _has_table(insp, EXT_TABLE):
        op.drop_table(EXT_TABLE)
