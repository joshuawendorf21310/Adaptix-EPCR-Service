"""049 add prior-ecg reference + provider-attested comparison tables.

Revision ID: 049
Revises: 043
Create Date: 2026-05-12

Introduces two tables that back the EpcrPriorEcgService pillar:

- ``epcr_prior_ecg_reference``: metadata pointer to a prior 12-lead ECG
  available for clinician comparison. Carries no interpretation.
- ``epcr_ecg_comparison_result``: provider-attested comparison row.
  ``provider_confirmed`` MUST be true before any export consumes the
  comparison; ``comparison_state`` is one of a pre-enumerated set of
  values (`similar`, `different`, `unable_to_compare`, `not_relevant`)
  and is chosen by the provider, never inferred by the service.

Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``.
Reversible: ``downgrade`` drops both tables and their indexes.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


REF_TABLE = "epcr_prior_ecg_reference"
CMP_TABLE = "epcr_ecg_comparison_result"


def upgrade() -> None:
    op.create_table(
        REF_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column("prior_chart_id", sa.String(length=36), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("encounter_context", sa.String(length=128), nullable=False),
        sa.Column("image_storage_uri", sa.String(length=512), nullable=True),
        sa.Column(
            "monitor_imported",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_prior_ecg_reference_tenant_id", REF_TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_prior_ecg_reference_chart_id", REF_TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_prior_ecg_reference_prior_chart_id",
        REF_TABLE,
        ["prior_chart_id"],
    )

    op.create_table(
        CMP_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column(
            "prior_ecg_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_prior_ecg_reference.id"),
            nullable=False,
        ),
        sa.Column("comparison_state", sa.String(length=32), nullable=False),
        sa.Column(
            "provider_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_ecg_comparison_result_tenant_id", CMP_TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_ecg_comparison_result_chart_id", CMP_TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_ecg_comparison_result_prior_ecg_id",
        CMP_TABLE,
        ["prior_ecg_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_ecg_comparison_result_prior_ecg_id", table_name=CMP_TABLE
    )
    op.drop_index(
        "ix_epcr_ecg_comparison_result_chart_id", table_name=CMP_TABLE
    )
    op.drop_index(
        "ix_epcr_ecg_comparison_result_tenant_id", table_name=CMP_TABLE
    )
    op.drop_table(CMP_TABLE)

    op.drop_index(
        "ix_epcr_prior_ecg_reference_prior_chart_id", table_name=REF_TABLE
    )
    op.drop_index(
        "ix_epcr_prior_ecg_reference_chart_id", table_name=REF_TABLE
    )
    op.drop_index(
        "ix_epcr_prior_ecg_reference_tenant_id", table_name=REF_TABLE
    )
    op.drop_table(REF_TABLE)
