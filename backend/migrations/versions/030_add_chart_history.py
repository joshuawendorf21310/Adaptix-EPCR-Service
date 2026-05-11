"""030 add epcr_chart_history_* (NEMSIS eHistory aggregate).

Revision ID: 030
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eHistory child tables for charts:

    epcr_chart_history_meta                 (1:1 single-row meta)
    epcr_chart_history_allergies            (1:M medication + env/food)
    epcr_chart_history_surgical             (1:M medical/surgical history)
    epcr_chart_history_current_medications  (1:M current meds + dose info)
    epcr_chart_history_immunizations        (1:M immunizations)

All columns are nullable where NEMSIS permits absence; required
columns (the discriminator on allergies, the code on surgical and
medications, the type code on immunizations) are NOT NULL. The
chart-finalization gate enforces the Required-at-National subset via
the registry-driven validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "030"
down_revision = "023"
branch_labels = None
depends_on = None


META_TABLE = "epcr_chart_history_meta"
ALLERGIES_TABLE = "epcr_chart_history_allergies"
SURGICAL_TABLE = "epcr_chart_history_surgical"
MEDS_TABLE = "epcr_chart_history_current_medications"
IMMUN_TABLE = "epcr_chart_history_immunizations"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def _audit_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, META_TABLE):
        op.create_table(
            META_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("barriers_to_care_codes_json", sa.JSON(), nullable=True),
            sa.Column("advance_directives_codes_json", sa.JSON(), nullable=True),
            sa.Column("medical_history_obtained_from_codes_json", sa.JSON(), nullable=True),
            sa.Column("alcohol_drug_use_codes_json", sa.JSON(), nullable=True),
            sa.Column("practitioner_last_name", sa.String(120), nullable=True),
            sa.Column("practitioner_first_name", sa.String(120), nullable=True),
            sa.Column("practitioner_middle_name", sa.String(120), nullable=True),
            sa.Column("pregnancy_code", sa.String(16), nullable=True),
            sa.Column("last_oral_intake_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("emergency_information_form_code", sa.String(16), nullable=True),
            *_audit_columns(),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                name="uq_epcr_chart_history_meta_tenant_chart",
            ),
        )

    if not _has_index(insp, META_TABLE, "ix_epcr_chart_history_meta_tenant_id"):
        op.create_index(
            "ix_epcr_chart_history_meta_tenant_id",
            META_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, META_TABLE, "ix_epcr_chart_history_meta_chart_id"):
        op.create_index(
            "ix_epcr_chart_history_meta_chart_id",
            META_TABLE,
            ["chart_id"],
        )

    if not _has_table(insp, ALLERGIES_TABLE):
        op.create_table(
            ALLERGIES_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("allergy_kind", sa.String(16), nullable=False),
            sa.Column("allergy_code", sa.String(64), nullable=False),
            sa.Column("allergy_text", sa.String(255), nullable=True),
            sa.Column(
                "sequence_index",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            *_audit_columns(),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "allergy_kind",
                "allergy_code",
                name="uq_epcr_chart_history_allergies_tenant_chart_kind_code",
            ),
        )

    if not _has_index(insp, ALLERGIES_TABLE, "ix_epcr_chart_history_allergies_tenant_id"):
        op.create_index(
            "ix_epcr_chart_history_allergies_tenant_id",
            ALLERGIES_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, ALLERGIES_TABLE, "ix_epcr_chart_history_allergies_chart_id"):
        op.create_index(
            "ix_epcr_chart_history_allergies_chart_id",
            ALLERGIES_TABLE,
            ["chart_id"],
        )

    if not _has_table(insp, SURGICAL_TABLE):
        op.create_table(
            SURGICAL_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("condition_code", sa.String(64), nullable=False),
            sa.Column("condition_text", sa.String(255), nullable=True),
            sa.Column(
                "sequence_index",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            *_audit_columns(),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "condition_code",
                name="uq_epcr_chart_history_surgical_tenant_chart_code",
            ),
        )

    if not _has_index(insp, SURGICAL_TABLE, "ix_epcr_chart_history_surgical_tenant_id"):
        op.create_index(
            "ix_epcr_chart_history_surgical_tenant_id",
            SURGICAL_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, SURGICAL_TABLE, "ix_epcr_chart_history_surgical_chart_id"):
        op.create_index(
            "ix_epcr_chart_history_surgical_chart_id",
            SURGICAL_TABLE,
            ["chart_id"],
        )

    if not _has_table(insp, MEDS_TABLE):
        op.create_table(
            MEDS_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("drug_code", sa.String(64), nullable=False),
            sa.Column("dose_value", sa.String(32), nullable=True),
            sa.Column("dose_unit_code", sa.String(16), nullable=True),
            sa.Column("route_code", sa.String(16), nullable=True),
            sa.Column("frequency_code", sa.String(32), nullable=True),
            sa.Column(
                "sequence_index",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            *_audit_columns(),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "drug_code",
                name="uq_epcr_chart_history_current_medications_tenant_chart_drug",
            ),
        )

    if not _has_index(insp, MEDS_TABLE, "ix_epcr_chart_history_current_medications_tenant_id"):
        op.create_index(
            "ix_epcr_chart_history_current_medications_tenant_id",
            MEDS_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, MEDS_TABLE, "ix_epcr_chart_history_current_medications_chart_id"):
        op.create_index(
            "ix_epcr_chart_history_current_medications_chart_id",
            MEDS_TABLE,
            ["chart_id"],
        )

    if not _has_table(insp, IMMUN_TABLE):
        op.create_table(
            IMMUN_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("immunization_type_code", sa.String(16), nullable=False),
            sa.Column("immunization_year", sa.Integer(), nullable=True),
            sa.Column(
                "sequence_index",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            *_audit_columns(),
        )

    if not _has_index(insp, IMMUN_TABLE, "ix_epcr_chart_history_immunizations_tenant_id"):
        op.create_index(
            "ix_epcr_chart_history_immunizations_tenant_id",
            IMMUN_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, IMMUN_TABLE, "ix_epcr_chart_history_immunizations_chart_id"):
        op.create_index(
            "ix_epcr_chart_history_immunizations_chart_id",
            IMMUN_TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table, indexes in (
        (
            IMMUN_TABLE,
            [
                "ix_epcr_chart_history_immunizations_chart_id",
                "ix_epcr_chart_history_immunizations_tenant_id",
            ],
        ),
        (
            MEDS_TABLE,
            [
                "ix_epcr_chart_history_current_medications_chart_id",
                "ix_epcr_chart_history_current_medications_tenant_id",
            ],
        ),
        (
            SURGICAL_TABLE,
            [
                "ix_epcr_chart_history_surgical_chart_id",
                "ix_epcr_chart_history_surgical_tenant_id",
            ],
        ),
        (
            ALLERGIES_TABLE,
            [
                "ix_epcr_chart_history_allergies_chart_id",
                "ix_epcr_chart_history_allergies_tenant_id",
            ],
        ),
        (
            META_TABLE,
            [
                "ix_epcr_chart_history_meta_chart_id",
                "ix_epcr_chart_history_meta_tenant_id",
            ],
        ),
    ):
        for ix in indexes:
            if _has_index(insp, table, ix):
                op.drop_index(ix, table_name=table)
        if _has_table(insp, table):
            op.drop_table(table)
