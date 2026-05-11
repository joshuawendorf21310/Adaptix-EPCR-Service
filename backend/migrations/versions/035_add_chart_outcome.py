"""035 add epcr_chart_outcome (NEMSIS eOutcome 1:1 aggregate).

Revision ID: 035
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eOutcome 1:1 child table for charts. Outcome
elements are populated post-hoc from receiving-facility feedback;
every column is nullable on the row itself. The chart-finalization
gate enforces NEMSIS Required/Conditional subsets via the
registry-driven validator.

The four ``*_codes_json`` columns hold JSON arrays of ICD-10 / SNOMED
code values (1:M repeating-group lists) projected into separate ledger
rows by the projection layer.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "035"
down_revision = "023"
branch_labels = None
depends_on = None


TABLE = "epcr_chart_outcome"


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

    if not _has_table(insp, TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("emergency_department_disposition_code", sa.String(16), nullable=True),
            sa.Column("hospital_disposition_code", sa.String(16), nullable=True),
            sa.Column("emergency_department_diagnosis_codes_json", sa.JSON(), nullable=True),
            sa.Column("hospital_admission_diagnosis_codes_json", sa.JSON(), nullable=True),
            sa.Column("hospital_procedures_performed_codes_json", sa.JSON(), nullable=True),
            sa.Column("trauma_registry_incident_id", sa.String(64), nullable=True),
            sa.Column("hospital_outcome_at_discharge_code", sa.String(16), nullable=True),
            sa.Column(
                "patient_disposition_from_emergency_department_at",
                sa.String(255),
                nullable=True,
            ),
            sa.Column("emergency_department_arrival_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("emergency_department_admit_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("emergency_department_discharge_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hospital_admit_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hospital_discharge_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("icu_admit_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("icu_discharge_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hospital_length_of_stay_days", sa.Integer(), nullable=True),
            sa.Column("icu_length_of_stay_days", sa.Integer(), nullable=True),
            sa.Column("final_patient_acuity_code", sa.String(16), nullable=True),
            sa.Column("cause_of_death_codes_json", sa.JSON(), nullable=True),
            sa.Column("date_of_death", sa.DateTime(timezone=True), nullable=True),
            sa.Column("medical_record_number", sa.String(64), nullable=True),
            sa.Column("receiving_facility_record_number", sa.String(64), nullable=True),
            sa.Column("referred_to_facility_code", sa.String(64), nullable=True),
            sa.Column("referred_to_facility_name", sa.String(255), nullable=True),
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
                name="uq_epcr_chart_outcome_tenant_chart",
            ),
        if_not_exists=True)

    if not _has_index(insp, TABLE, "ix_epcr_chart_outcome_tenant_id"):
        op.create_index(
            "ix_epcr_chart_outcome_tenant_id",
            TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE, "ix_epcr_chart_outcome_chart_id"):
        op.create_index(
            "ix_epcr_chart_outcome_chart_id",
            TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, TABLE, "ix_epcr_chart_outcome_chart_id"):
        op.drop_index("ix_epcr_chart_outcome_chart_id", table_name=TABLE)
    if _has_index(insp, TABLE, "ix_epcr_chart_outcome_tenant_id"):
        op.drop_index("ix_epcr_chart_outcome_tenant_id", table_name=TABLE)
    if _has_table(insp, TABLE):
        op.drop_table(TABLE)
