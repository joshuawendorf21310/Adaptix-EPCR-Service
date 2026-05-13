"""048 add Repeat Patient match + Prior Chart Reference tables.

Revision ID: 048
Revises: 043
Create Date: 2026-05-12

Creates two tables backing the RepeatPatientService pillar:

- ``epcr_repeat_patient_match``: candidate matches discovered between a
  chart's current patient context and previously-known patient profiles
  in the tenant, with confidence + reason JSON, and a provider review
  workflow controlling whether values may be carried forward.
- ``epcr_prior_chart_reference``: lightweight snapshot rows linking a
  current chart to previously-documented charts for the same identity,
  exposing chief complaint and disposition for quick clinician review.

The FK columns to ``epcr_patient_profiles.id`` and ``epcr_charts.id`` are
intentionally *soft* (string column, no enforced FOREIGN KEY clause) so
tenant-scoped registry merges and historical-archive replays do not need
hard cascades.

Schema is portable across PostgreSQL and SQLite (test harness). Idempotent
+ drift-safe via ``if_not_exists=True``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


MATCH_TABLE = "epcr_repeat_patient_match"
PRIOR_TABLE = "epcr_prior_chart_reference"


def upgrade() -> None:
    op.create_table(
        MATCH_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("chart_id", sa.String(length=36), nullable=False),
        sa.Column("matched_profile_id", sa.String(length=36), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("match_reason_json", sa.Text(), nullable=False),
        sa.Column(
            "reviewed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "carry_forward_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_epcr_repeat_patient_match_confidence_range",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_repeat_patient_match_tenant_id",
        MATCH_TABLE,
        ["tenant_id"],
    )
    op.create_index(
        "ix_epcr_repeat_patient_match_chart_id",
        MATCH_TABLE,
        ["chart_id"],
    )
    op.create_index(
        "ix_epcr_repeat_patient_match_matched_profile_id",
        MATCH_TABLE,
        ["matched_profile_id"],
    )
    op.create_index(
        "ix_epcr_repeat_patient_match_tenant_chart",
        MATCH_TABLE,
        ["tenant_id", "chart_id"],
    )

    op.create_table(
        PRIOR_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("chart_id", sa.String(length=36), nullable=False),
        sa.Column("prior_chart_id", sa.String(length=36), nullable=False),
        sa.Column("encounter_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chief_complaint", sa.String(length=255), nullable=True),
        sa.Column("disposition", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_prior_chart_reference_tenant_id",
        PRIOR_TABLE,
        ["tenant_id"],
    )
    op.create_index(
        "ix_epcr_prior_chart_reference_chart_id",
        PRIOR_TABLE,
        ["chart_id"],
    )
    op.create_index(
        "ix_epcr_prior_chart_reference_prior_chart_id",
        PRIOR_TABLE,
        ["prior_chart_id"],
    )
    op.create_index(
        "ix_epcr_prior_chart_reference_tenant_chart",
        PRIOR_TABLE,
        ["tenant_id", "chart_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_prior_chart_reference_tenant_chart", table_name=PRIOR_TABLE
    )
    op.drop_index(
        "ix_epcr_prior_chart_reference_prior_chart_id", table_name=PRIOR_TABLE
    )
    op.drop_index(
        "ix_epcr_prior_chart_reference_chart_id", table_name=PRIOR_TABLE
    )
    op.drop_index(
        "ix_epcr_prior_chart_reference_tenant_id", table_name=PRIOR_TABLE
    )
    op.drop_table(PRIOR_TABLE)

    op.drop_index(
        "ix_epcr_repeat_patient_match_tenant_chart", table_name=MATCH_TABLE
    )
    op.drop_index(
        "ix_epcr_repeat_patient_match_matched_profile_id",
        table_name=MATCH_TABLE,
    )
    op.drop_index(
        "ix_epcr_repeat_patient_match_chart_id", table_name=MATCH_TABLE
    )
    op.drop_index(
        "ix_epcr_repeat_patient_match_tenant_id", table_name=MATCH_TABLE
    )
    op.drop_table(MATCH_TABLE)
