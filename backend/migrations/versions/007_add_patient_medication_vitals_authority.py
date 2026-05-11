"""Migration 007: add patient, vitals, impression, and medication authority.

Creates patient profile and medication administration tables, and extends
assessment records with structured impression fields.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	"""Create patient and medication authority surfaces and extend impressions."""

	op.create_table(
		"epcr_patient_profiles",
		sa.Column("id", sa.String(length=36), nullable=False),
		sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
		sa.Column("tenant_id", sa.String(length=36), nullable=False),
		sa.Column("first_name", sa.String(length=120), nullable=True),
		sa.Column("middle_name", sa.String(length=120), nullable=True),
		sa.Column("last_name", sa.String(length=120), nullable=True),
		sa.Column("date_of_birth", sa.String(length=32), nullable=True),
		sa.Column("age_years", sa.Integer(), nullable=True),
		sa.Column("sex", sa.String(length=32), nullable=True),
		sa.Column("phone_number", sa.String(length=32), nullable=True),
		sa.Column("weight_kg", sa.Float(), nullable=True),
		sa.Column("allergies_json", sa.Text(), nullable=True),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
		sa.PrimaryKeyConstraint("id"),
		sa.UniqueConstraint("chart_id"),
        if_not_exists=True)
	op.create_index("ix_epcr_patient_profiles_chart_id", "epcr_patient_profiles", ["chart_id"])
	op.create_index("ix_epcr_patient_profiles_tenant_id", "epcr_patient_profiles", ["tenant_id"])

	op.add_column("epcr_assessments", sa.Column("primary_impression", sa.String(length=255), nullable=True))
	op.add_column("epcr_assessments", sa.Column("secondary_impression", sa.String(length=255), nullable=True))
	op.add_column("epcr_assessments", sa.Column("impression_notes", sa.Text(), nullable=True))
	op.add_column("epcr_assessments", sa.Column("snomed_code", sa.String(length=32), nullable=True))
	op.add_column("epcr_assessments", sa.Column("icd10_code", sa.String(length=32), nullable=True))
	op.add_column("epcr_assessments", sa.Column("acuity", sa.String(length=32), nullable=True))

	op.create_table(
		"epcr_medication_administrations",
		sa.Column("id", sa.String(length=36), nullable=False),
		sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
		sa.Column("tenant_id", sa.String(length=36), nullable=False),
		sa.Column("medication_name", sa.String(length=128), nullable=False),
		sa.Column("rxnorm_code", sa.String(length=32), nullable=True),
		sa.Column("dose_value", sa.String(length=32), nullable=True),
		sa.Column("dose_unit", sa.String(length=32), nullable=True),
		sa.Column("route", sa.String(length=64), nullable=False),
		sa.Column("indication", sa.Text(), nullable=False),
		sa.Column("response", sa.Text(), nullable=True),
		sa.Column("export_state", sa.String(length=32), nullable=False, server_default="pending_mapping"),
		sa.Column("administered_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("administered_by_user_id", sa.String(length=255), nullable=False),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
		sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
	op.create_index("ix_epcr_medication_administrations_chart_id", "epcr_medication_administrations", ["chart_id"])
	op.create_index("ix_epcr_medication_administrations_tenant_id", "epcr_medication_administrations", ["tenant_id"])


def downgrade() -> None:
	"""Drop patient and medication authority surfaces and impression extensions."""

	op.drop_index("ix_epcr_medication_administrations_tenant_id", table_name="epcr_medication_administrations")
	op.drop_index("ix_epcr_medication_administrations_chart_id", table_name="epcr_medication_administrations")
	op.drop_table("epcr_medication_administrations")

	op.drop_column("epcr_assessments", "acuity")
	op.drop_column("epcr_assessments", "icd10_code")
	op.drop_column("epcr_assessments", "snomed_code")
	op.drop_column("epcr_assessments", "impression_notes")
	op.drop_column("epcr_assessments", "secondary_impression")
	op.drop_column("epcr_assessments", "primary_impression")

	op.drop_index("ix_epcr_patient_profiles_tenant_id", table_name="epcr_patient_profiles")
	op.drop_index("ix_epcr_patient_profiles_chart_id", table_name="epcr_patient_profiles")
	op.drop_table("epcr_patient_profiles")