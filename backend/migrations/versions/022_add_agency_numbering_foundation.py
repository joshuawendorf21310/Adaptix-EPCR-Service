"""022 add agency profiles and deterministic incident numbering foundation

Revision ID: 022
Revises: 021
Create Date: 2026-05-09

Adds agency onboarding storage required by the numbering policy, the
tenant+agency+year numbering sequence table, and the chart identifier
columns for incident / response / PCR / billing numbers.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


AGENCY_TABLE = "agency_profiles"
SEQUENCE_TABLE = "epcr_numbering_sequences"
CHART_TABLE = "epcr_charts"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_column(insp, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def _has_unique_constraint(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(uc.get("name") == name for uc in insp.get_unique_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, AGENCY_TABLE):
        op.create_table(
            AGENCY_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("agency_code", sa.String(12), nullable=False),
            sa.Column("agency_name", sa.String(255), nullable=False),
            sa.Column("agency_type", sa.String(64), nullable=True),
            sa.Column("state", sa.String(8), nullable=True),
            sa.Column("operational_mode", sa.String(64), nullable=True),
            sa.Column("billing_mode", sa.String(64), nullable=True),
            sa.Column("numbering_policy_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "agency_code", name="uq_agency_profiles_tenant_agency_code"),
        )
        op.create_index("idx_agency_profiles_tenant_id", AGENCY_TABLE, ["tenant_id"])
        op.create_index("idx_agency_profiles_agency_code", AGENCY_TABLE, ["agency_code"])

    if not _has_table(insp, SEQUENCE_TABLE):
        op.create_table(
            SEQUENCE_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("agency_code", sa.String(12), nullable=False),
            sa.Column("sequence_year", sa.Integer(), nullable=False),
            sa.Column("next_incident_sequence", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint(
                "tenant_id",
                "agency_code",
                "sequence_year",
                name="uq_epcr_numbering_sequences_scope",
            ),
        )
        op.create_index("idx_epcr_numbering_sequences_tenant", SEQUENCE_TABLE, ["tenant_id", "agency_code", "sequence_year"])

    chart_columns = [
        ("agency_code", sa.String(12)),
        ("incident_year", sa.Integer()),
        ("incident_sequence", sa.Integer()),
        ("response_sequence", sa.Integer()),
        ("pcr_sequence", sa.Integer()),
        ("billing_sequence", sa.Integer()),
        ("incident_number", sa.String(64)),
        ("response_number", sa.String(72)),
        ("pcr_number", sa.String(76)),
        ("billing_case_number", sa.String(80)),
        ("cad_incident_number", sa.String(64)),
        ("external_incident_number", sa.String(64)),
    ]
    for column_name, column_type in chart_columns:
        if not _has_column(insp, CHART_TABLE, column_name):
            with op.batch_alter_table(CHART_TABLE) as batch_op:
                batch_op.add_column(sa.Column(column_name, column_type, nullable=True))

    unique_indexes = [
        ("uq_epcr_charts_incident_number", ["tenant_id", "incident_number"]),
        ("uq_epcr_charts_response_number", ["tenant_id", "response_number"]),
        ("uq_epcr_charts_pcr_number", ["tenant_id", "pcr_number"]),
        ("uq_epcr_charts_billing_case_number", ["tenant_id", "billing_case_number"]),
    ]
    for index_name, columns in unique_indexes:
        if not _has_index(insp, CHART_TABLE, index_name):
            op.create_index(
                index_name,
                CHART_TABLE,
                columns,
                unique=True,
                sqlite_where=sa.text("deleted_at IS NULL"),
                postgresql_where=sa.text("deleted_at IS NULL"),
            )

    if _has_column(insp, CHART_TABLE, "call_number") and _has_column(insp, CHART_TABLE, "cad_incident_number"):
        op.execute(
            sa.text(
                "UPDATE epcr_charts SET cad_incident_number = call_number WHERE cad_incident_number IS NULL AND call_number IS NOT NULL"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for index_name in (
        "uq_epcr_charts_billing_case_number",
        "uq_epcr_charts_pcr_number",
        "uq_epcr_charts_response_number",
        "uq_epcr_charts_incident_number",
    ):
        if _has_index(insp, CHART_TABLE, index_name):
            op.drop_index(index_name, table_name=CHART_TABLE)

    for column_name in (
        "external_incident_number",
        "cad_incident_number",
        "billing_case_number",
        "pcr_number",
        "response_number",
        "incident_number",
        "billing_sequence",
        "pcr_sequence",
        "response_sequence",
        "incident_sequence",
        "incident_year",
        "agency_code",
    ):
        if _has_column(insp, CHART_TABLE, column_name):
            with op.batch_alter_table(CHART_TABLE) as batch_op:
                batch_op.drop_column(column_name)

    if _has_table(insp, SEQUENCE_TABLE):
        op.drop_table(SEQUENCE_TABLE)
    if _has_table(insp, AGENCY_TABLE):
        op.drop_table(AGENCY_TABLE)