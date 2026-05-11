"""Migration 006: add chart workflow authority surfaces.

Creates tables for address intelligence, interventions, clinical notes,
protocol recommendations, and derived chart outputs.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	"""Create workflow authority tables owned by the ePCR domain."""

	op.create_table(
		"epcr_chart_addresses",
		sa.Column("id", sa.String(length=36), nullable=False),
		sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
		sa.Column("tenant_id", sa.String(length=36), nullable=False),
		sa.Column("raw_text", sa.Text(), nullable=False),
		sa.Column("street_line_one", sa.String(length=255), nullable=True),
		sa.Column("street_line_two", sa.String(length=255), nullable=True),
		sa.Column("city", sa.String(length=100), nullable=True),
		sa.Column("state", sa.String(length=32), nullable=True),
		sa.Column("postal_code", sa.String(length=20), nullable=True),
		sa.Column("county", sa.String(length=100), nullable=True),
		sa.Column("latitude", sa.Float(), nullable=True),
		sa.Column("longitude", sa.Float(), nullable=True),
		sa.Column("validation_state", sa.String(length=32), nullable=False, server_default="needs_review"),
		sa.Column("intelligence_source", sa.String(length=64), nullable=False),
		sa.Column("intelligence_detail", sa.Text(), nullable=True),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
		sa.PrimaryKeyConstraint("id"),
		sa.UniqueConstraint("chart_id"),
        if_not_exists=True)
	op.create_index("ix_epcr_chart_addresses_chart_id", "epcr_chart_addresses", ["chart_id"])
	op.create_index("ix_epcr_chart_addresses_tenant_id", "epcr_chart_addresses", ["tenant_id"])

	op.create_table(
		"epcr_interventions",
		sa.Column("id", sa.String(length=36), nullable=False),
		sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
		sa.Column("tenant_id", sa.String(length=36), nullable=False),
		sa.Column("category", sa.String(length=64), nullable=False),
		sa.Column("name", sa.String(length=128), nullable=False),
		sa.Column("indication", sa.Text(), nullable=False),
		sa.Column("intent", sa.Text(), nullable=False),
		sa.Column("expected_response", sa.Text(), nullable=False),
		sa.Column("actual_response", sa.Text(), nullable=True),
		sa.Column("reassessment_due_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("protocol_family", sa.String(length=32), nullable=False, server_default="general"),
		sa.Column("snomed_code", sa.String(length=32), nullable=True),
		sa.Column("icd10_code", sa.String(length=32), nullable=True),
		sa.Column("rxnorm_code", sa.String(length=32), nullable=True),
		sa.Column("export_state", sa.String(length=32), nullable=False, server_default="pending_mapping"),
		sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("provider_id", sa.String(length=255), nullable=False),
		sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
	op.create_index("ix_epcr_interventions_chart_id", "epcr_interventions", ["chart_id"])
	op.create_index("ix_epcr_interventions_tenant_id", "epcr_interventions", ["tenant_id"])

	op.create_table(
		"epcr_clinical_notes",
		sa.Column("id", sa.String(length=36), nullable=False),
		sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
		sa.Column("tenant_id", sa.String(length=36), nullable=False),
		sa.Column("raw_text", sa.Text(), nullable=False),
		sa.Column("source", sa.String(length=64), nullable=False),
		sa.Column("provenance_json", sa.Text(), nullable=True),
		sa.Column("derived_summary", sa.Text(), nullable=False),
		sa.Column("review_state", sa.String(length=32), nullable=False, server_default="pending_review"),
		sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("provider_id", sa.String(length=255), nullable=False),
		sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
	op.create_index("ix_epcr_clinical_notes_chart_id", "epcr_clinical_notes", ["chart_id"])
	op.create_index("ix_epcr_clinical_notes_tenant_id", "epcr_clinical_notes", ["tenant_id"])

	op.create_table(
		"epcr_protocol_recommendations",
		sa.Column("id", sa.String(length=36), nullable=False),
		sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
		sa.Column("tenant_id", sa.String(length=36), nullable=False),
		sa.Column("protocol_family", sa.String(length=32), nullable=False, server_default="general"),
		sa.Column("title", sa.String(length=255), nullable=False),
		sa.Column("rationale", sa.Text(), nullable=False),
		sa.Column("action_priority", sa.Integer(), nullable=False, server_default="1"),
		sa.Column("evidence_json", sa.Text(), nullable=True),
		sa.Column("state", sa.String(length=32), nullable=False, server_default="open"),
		sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
		sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
	op.create_index("ix_epcr_protocol_recommendations_chart_id", "epcr_protocol_recommendations", ["chart_id"])
	op.create_index("ix_epcr_protocol_recommendations_tenant_id", "epcr_protocol_recommendations", ["tenant_id"])

	op.create_table(
		"epcr_derived_outputs",
		sa.Column("id", sa.String(length=36), nullable=False),
		sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
		sa.Column("tenant_id", sa.String(length=36), nullable=False),
		sa.Column("output_type", sa.String(length=32), nullable=False),
		sa.Column("content_text", sa.Text(), nullable=False),
		sa.Column("source_revision", sa.String(length=64), nullable=False),
		sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("generated_by_user_id", sa.String(length=255), nullable=False),
		sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
	op.create_index("ix_epcr_derived_outputs_chart_id", "epcr_derived_outputs", ["chart_id"])
	op.create_index("ix_epcr_derived_outputs_tenant_id", "epcr_derived_outputs", ["tenant_id"])


def downgrade() -> None:
	"""Drop workflow authority tables."""

	op.drop_index("ix_epcr_derived_outputs_tenant_id", table_name="epcr_derived_outputs")
	op.drop_index("ix_epcr_derived_outputs_chart_id", table_name="epcr_derived_outputs")
	op.drop_table("epcr_derived_outputs")

	op.drop_index("ix_epcr_protocol_recommendations_tenant_id", table_name="epcr_protocol_recommendations")
	op.drop_index("ix_epcr_protocol_recommendations_chart_id", table_name="epcr_protocol_recommendations")
	op.drop_table("epcr_protocol_recommendations")

	op.drop_index("ix_epcr_clinical_notes_tenant_id", table_name="epcr_clinical_notes")
	op.drop_index("ix_epcr_clinical_notes_chart_id", table_name="epcr_clinical_notes")
	op.drop_table("epcr_clinical_notes")

	op.drop_index("ix_epcr_interventions_tenant_id", table_name="epcr_interventions")
	op.drop_index("ix_epcr_interventions_chart_id", table_name="epcr_interventions")
	op.drop_table("epcr_interventions")

	op.drop_index("ix_epcr_chart_addresses_tenant_id", table_name="epcr_chart_addresses")
	op.drop_index("ix_epcr_chart_addresses_chart_id", table_name="epcr_chart_addresses")
	op.drop_table("epcr_chart_addresses")
