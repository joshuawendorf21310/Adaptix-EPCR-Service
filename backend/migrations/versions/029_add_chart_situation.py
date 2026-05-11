"""029 add epcr_chart_situation (NEMSIS eSituation 1:1 + two 1:M children).

Revision ID: 029
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eSituation aggregate tables for charts:

- ``epcr_chart_situation`` (1:1, eSituation.01..09, .11, .13..20)
- ``epcr_chart_situation_other_symptoms`` (1:M, eSituation.10)
- ``epcr_chart_situation_secondary_impressions`` (1:M, eSituation.12)

All scalar columns on the 1:1 row are nullable; the chart-finalization
gate enforces the Required-at-National subset via the registry-driven
validator, not at the column level.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "029"
down_revision = "023"
branch_labels = None
depends_on = None


TABLE_MAIN = "epcr_chart_situation"
TABLE_SYMPTOMS = "epcr_chart_situation_other_symptoms"
TABLE_IMPRESSIONS = "epcr_chart_situation_secondary_impressions"


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

    # 1:1 eSituation scalar table
    if not _has_table(insp, TABLE_MAIN):
        op.create_table(
            TABLE_MAIN,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("symptom_onset_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("possible_injury_indicator_code", sa.String(16), nullable=True),
            sa.Column("complaint_type_code", sa.String(16), nullable=True),
            sa.Column("complaint_text", sa.Text(), nullable=True),
            sa.Column("complaint_duration_value", sa.Integer(), nullable=True),
            sa.Column("complaint_duration_units_code", sa.String(16), nullable=True),
            sa.Column("chief_complaint_anatomic_code", sa.String(16), nullable=True),
            sa.Column("chief_complaint_organ_system_code", sa.String(16), nullable=True),
            sa.Column("primary_symptom_code", sa.String(32), nullable=True),
            sa.Column("provider_primary_impression_code", sa.String(32), nullable=True),
            sa.Column("initial_patient_acuity_code", sa.String(16), nullable=True),
            sa.Column("work_related_indicator_code", sa.String(16), nullable=True),
            sa.Column("patient_industry_code", sa.String(16), nullable=True),
            sa.Column("patient_occupation_code", sa.String(16), nullable=True),
            sa.Column("patient_activity_code", sa.String(16), nullable=True),
            sa.Column("last_known_well_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("transfer_justification_code", sa.String(16), nullable=True),
            sa.Column("interfacility_transfer_reason_code", sa.String(16), nullable=True),
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
                name="uq_epcr_chart_situation_tenant_chart",
            ),
        )

    if not _has_index(insp, TABLE_MAIN, "ix_epcr_chart_situation_tenant_id"):
        op.create_index(
            "ix_epcr_chart_situation_tenant_id",
            TABLE_MAIN,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE_MAIN, "ix_epcr_chart_situation_chart_id"):
        op.create_index(
            "ix_epcr_chart_situation_chart_id",
            TABLE_MAIN,
            ["chart_id"],
        )

    # 1:M eSituation.10 Other Associated Symptoms
    if not _has_table(insp, TABLE_SYMPTOMS):
        op.create_table(
            TABLE_SYMPTOMS,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("symptom_code", sa.String(32), nullable=False),
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
                "symptom_code",
                name="uq_epcr_chart_situation_other_symptoms_tenant_chart_code",
            ),
        )

    if not _has_index(insp, TABLE_SYMPTOMS, "ix_epcr_chart_situation_other_symptoms_tenant_id"):
        op.create_index(
            "ix_epcr_chart_situation_other_symptoms_tenant_id",
            TABLE_SYMPTOMS,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE_SYMPTOMS, "ix_epcr_chart_situation_other_symptoms_chart_id"):
        op.create_index(
            "ix_epcr_chart_situation_other_symptoms_chart_id",
            TABLE_SYMPTOMS,
            ["chart_id"],
        )

    # 1:M eSituation.12 Provider's Secondary Impressions
    if not _has_table(insp, TABLE_IMPRESSIONS):
        op.create_table(
            TABLE_IMPRESSIONS,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("impression_code", sa.String(32), nullable=False),
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
                "impression_code",
                name="uq_epcr_chart_situation_secondary_impressions_tenant_chart_code",
            ),
        )

    if not _has_index(insp, TABLE_IMPRESSIONS, "ix_epcr_chart_situation_secondary_impressions_tenant_id"):
        op.create_index(
            "ix_epcr_chart_situation_secondary_impressions_tenant_id",
            TABLE_IMPRESSIONS,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE_IMPRESSIONS, "ix_epcr_chart_situation_secondary_impressions_chart_id"):
        op.create_index(
            "ix_epcr_chart_situation_secondary_impressions_chart_id",
            TABLE_IMPRESSIONS,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, TABLE_IMPRESSIONS, "ix_epcr_chart_situation_secondary_impressions_chart_id"):
        op.drop_index(
            "ix_epcr_chart_situation_secondary_impressions_chart_id",
            table_name=TABLE_IMPRESSIONS,
        )
    if _has_index(insp, TABLE_IMPRESSIONS, "ix_epcr_chart_situation_secondary_impressions_tenant_id"):
        op.drop_index(
            "ix_epcr_chart_situation_secondary_impressions_tenant_id",
            table_name=TABLE_IMPRESSIONS,
        )
    if _has_table(insp, TABLE_IMPRESSIONS):
        op.drop_table(TABLE_IMPRESSIONS)

    if _has_index(insp, TABLE_SYMPTOMS, "ix_epcr_chart_situation_other_symptoms_chart_id"):
        op.drop_index(
            "ix_epcr_chart_situation_other_symptoms_chart_id",
            table_name=TABLE_SYMPTOMS,
        )
    if _has_index(insp, TABLE_SYMPTOMS, "ix_epcr_chart_situation_other_symptoms_tenant_id"):
        op.drop_index(
            "ix_epcr_chart_situation_other_symptoms_tenant_id",
            table_name=TABLE_SYMPTOMS,
        )
    if _has_table(insp, TABLE_SYMPTOMS):
        op.drop_table(TABLE_SYMPTOMS)

    if _has_index(insp, TABLE_MAIN, "ix_epcr_chart_situation_chart_id"):
        op.drop_index("ix_epcr_chart_situation_chart_id", table_name=TABLE_MAIN)
    if _has_index(insp, TABLE_MAIN, "ix_epcr_chart_situation_tenant_id"):
        op.drop_index("ix_epcr_chart_situation_tenant_id", table_name=TABLE_MAIN)
    if _has_table(insp, TABLE_MAIN):
        op.drop_table(TABLE_MAIN)
