"""045 add epcr_ecustom_field_definition + epcr_ecustom_field_value.

Revision ID: 045
Revises: 043
Create Date: 2026-05-12

Creates the two tables that back the ECustomFieldService pillar:

- ``epcr_ecustom_field_definition``: tenant/agency-scoped definitions of
  agency-defined NEMSIS custom data elements.
- ``epcr_ecustom_field_value``: per-chart captured values for those
  definitions, with a JSON ``value_json`` column shared across all
  ``data_type`` variants and a ``validation_result_json`` cache.

Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``.
Portable across PostgreSQL and SQLite (the test harness uses SQLite);
enum-like columns are stored as portable strings whose canonical value
sets are enforced in ``epcr_app.services.ecustom_field_validation``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "045"
down_revision = "043"
branch_labels = None
depends_on = None


DEFINITION_TABLE = "epcr_ecustom_field_definition"
VALUE_TABLE = "epcr_ecustom_field_value"


def upgrade() -> None:
    op.create_table(
        DEFINITION_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("agency_id", sa.String(length=36), nullable=False),
        sa.Column("field_key", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("allowed_values_json", sa.Text(), nullable=True),
        sa.Column(
            "required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("conditional_rule_json", sa.Text(), nullable=True),
        sa.Column("nemsis_relationship", sa.String(length=128), nullable=True),
        sa.Column("state_profile", sa.String(length=64), nullable=True),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "retired",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "agency_id",
            "field_key",
            "version",
            name="uq_epcr_ecustom_field_definition_key_version",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_ecustom_field_definition_tenant_id",
        DEFINITION_TABLE,
        ["tenant_id"],
    )
    op.create_index(
        "ix_epcr_ecustom_field_definition_agency_id",
        DEFINITION_TABLE,
        ["agency_id"],
    )
    op.create_index(
        "ix_epcr_ecustom_field_definition_tenant_agency_key",
        DEFINITION_TABLE,
        ["tenant_id", "agency_id", "field_key"],
    )

    op.create_table(
        VALUE_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column(
            "field_definition_id",
            sa.String(length=36),
            sa.ForeignKey(f"{DEFINITION_TABLE}.id"),
            nullable=False,
        ),
        sa.Column("value_json", sa.Text(), nullable=True),
        sa.Column("validation_result_json", sa.Text(), nullable=True),
        sa.Column("audit_user_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "chart_id",
            "field_definition_id",
            name="uq_epcr_ecustom_field_value_chart_definition",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_ecustom_field_value_tenant_id", VALUE_TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_ecustom_field_value_chart_id", VALUE_TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_ecustom_field_value_field_definition_id",
        VALUE_TABLE,
        ["field_definition_id"],
    )
    op.create_index(
        "ix_epcr_ecustom_field_value_tenant_chart",
        VALUE_TABLE,
        ["tenant_id", "chart_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_ecustom_field_value_tenant_chart", table_name=VALUE_TABLE
    )
    op.drop_index(
        "ix_epcr_ecustom_field_value_field_definition_id",
        table_name=VALUE_TABLE,
    )
    op.drop_index(
        "ix_epcr_ecustom_field_value_chart_id", table_name=VALUE_TABLE
    )
    op.drop_index(
        "ix_epcr_ecustom_field_value_tenant_id", table_name=VALUE_TABLE
    )
    op.drop_table(VALUE_TABLE)

    op.drop_index(
        "ix_epcr_ecustom_field_definition_tenant_agency_key",
        table_name=DEFINITION_TABLE,
    )
    op.drop_index(
        "ix_epcr_ecustom_field_definition_agency_id",
        table_name=DEFINITION_TABLE,
    )
    op.drop_index(
        "ix_epcr_ecustom_field_definition_tenant_id",
        table_name=DEFINITION_TABLE,
    )
    op.drop_table(DEFINITION_TABLE)
