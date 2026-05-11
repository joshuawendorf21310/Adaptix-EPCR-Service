"""Migration 008: add signature artifact authority.

Creates authoritative chart completion signature storage for direct mobile
capture and fallback ingest flows.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	"""Create authoritative signature artifact storage."""

	op.create_table(
		"epcr_signature_artifacts",
		sa.Column("id", sa.String(length=36), nullable=False),
		sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
		sa.Column("tenant_id", sa.String(length=36), nullable=False),
		sa.Column("source_domain", sa.String(length=50), nullable=False),
		sa.Column("source_capture_id", sa.String(length=36), nullable=False),
		sa.Column("incident_id", sa.String(length=36), nullable=True),
		sa.Column("page_id", sa.String(length=36), nullable=True),
		sa.Column("signature_class", sa.String(length=100), nullable=False),
		sa.Column("signature_method", sa.String(length=50), nullable=False),
		sa.Column("workflow_policy", sa.String(length=64), nullable=False),
		sa.Column("policy_pack_version", sa.String(length=120), nullable=False),
		sa.Column("payer_class", sa.String(length=80), nullable=False),
		sa.Column("jurisdiction_country", sa.String(length=8), nullable=False),
		sa.Column("jurisdiction_state", sa.String(length=8), nullable=False),
		sa.Column("signer_identity", sa.String(length=255), nullable=True),
		sa.Column("signer_relationship", sa.String(length=100), nullable=True),
		sa.Column("signer_authority_basis", sa.String(length=120), nullable=True),
		sa.Column("patient_capable_to_sign", sa.Boolean(), nullable=True),
		sa.Column("incapacity_reason", sa.String(length=500), nullable=True),
		sa.Column("receiving_facility", sa.String(length=255), nullable=True),
		sa.Column("receiving_clinician_name", sa.String(length=255), nullable=True),
		sa.Column("receiving_role_title", sa.String(length=120), nullable=True),
		sa.Column("transfer_of_care_time", sa.DateTime(timezone=True), nullable=True),
		sa.Column("transfer_exception_reason_code", sa.String(length=64), nullable=True),
		sa.Column("transfer_exception_reason_detail", sa.String(length=500), nullable=True),
		sa.Column("signature_on_file_reference", sa.String(length=120), nullable=True),
		sa.Column("ambulance_employee_exception", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("receiving_facility_verification_status", sa.String(length=40), nullable=False, server_default="not_required"),
		sa.Column("signature_artifact_data_url", sa.Text(), nullable=True),
		sa.Column("compliance_decision", sa.String(length=80), nullable=False),
		sa.Column("compliance_why", sa.String(length=500), nullable=False),
		sa.Column("missing_requirements_json", sa.Text(), nullable=False, server_default="[]"),
		sa.Column("billing_readiness_effect", sa.String(length=40), nullable=False),
		sa.Column("chart_completion_effect", sa.String(length=40), nullable=False),
		sa.Column("retention_requirements_json", sa.Text(), nullable=False, server_default="[]"),
		sa.Column("ai_decision_explanation_json", sa.Text(), nullable=False, server_default="{}"),
		sa.Column("transfer_etimes12_recorded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("wards_export_safe", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("nemsis_export_safe", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("created_by_user_id", sa.String(length=255), nullable=False),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
		sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
	op.create_index("ix_epcr_signature_artifacts_chart_id", "epcr_signature_artifacts", ["chart_id"])
	op.create_index("ix_epcr_signature_artifacts_tenant_id", "epcr_signature_artifacts", ["tenant_id"])
	op.create_index("ix_epcr_signature_artifacts_source_capture_id", "epcr_signature_artifacts", ["source_capture_id"])
	op.create_index("ix_epcr_signature_artifacts_signature_class", "epcr_signature_artifacts", ["signature_class"])
	op.create_index("ix_epcr_signature_artifacts_compliance_decision", "epcr_signature_artifacts", ["compliance_decision"])


def downgrade() -> None:
	"""Drop signature artifact authority storage."""

	op.drop_index("ix_epcr_signature_artifacts_compliance_decision", table_name="epcr_signature_artifacts")
	op.drop_index("ix_epcr_signature_artifacts_signature_class", table_name="epcr_signature_artifacts")
	op.drop_index("ix_epcr_signature_artifacts_source_capture_id", table_name="epcr_signature_artifacts")
	op.drop_index("ix_epcr_signature_artifacts_tenant_id", table_name="epcr_signature_artifacts")
	op.drop_index("ix_epcr_signature_artifacts_chart_id", table_name="epcr_signature_artifacts")
	op.drop_table("epcr_signature_artifacts")