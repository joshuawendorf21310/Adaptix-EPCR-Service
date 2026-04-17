"""epcr (care) domain schema expansion: OCR, transport links, NEMSIS bindings, structured extractions.

Adds all tables for the OCR job lifecycle, care transport linkage,
NEMSIS field binding, and structured extraction promotion.

Revision ID: 003
Revises: 002
Create Date: 2026-04-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create care domain OCR, transport link, and NEMSIS binding tables."""

    op.create_table(
        "ocr_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("transport_request_id", sa.String(length=36), nullable=True),
        sa.Column("chart_id", sa.String(length=36), nullable=True),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("requested_by_user_id", sa.String(length=255), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("extraction_completed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewer_user_id", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ocr_jobs_tenant_id", "ocr_jobs", ["tenant_id"])
    op.create_index("ix_ocr_jobs_status", "ocr_jobs", ["status"])
    op.create_index("ix_ocr_jobs_transport_request_id", "ocr_jobs", ["transport_request_id"])
    op.create_index("ix_ocr_jobs_chart_id", "ocr_jobs", ["chart_id"])

    op.create_table(
        "ocr_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ocr_sources_job_id", "ocr_sources", ["job_id"])

    op.create_table(
        "ocr_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=False),
        sa.Column("field_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ocr_results_job_id", "ocr_results", ["job_id"], unique=True)

    op.create_table(
        "ocr_field_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("ocr_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="unresolved"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bounding_box", sa.Text(), nullable=True),
        sa.Column("alternative_values", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("corrected_value", sa.Text(), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ocr_field_candidates_job_id", "ocr_field_candidates", ["job_id"])
    op.create_index("ix_ocr_field_candidates_review_status", "ocr_field_candidates", ["review_status"])

    op.create_table(
        "ocr_field_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), sa.ForeignKey("ocr_field_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_user_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("corrected_value", sa.Text(), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ocr_field_reviews_candidate_id", "ocr_field_reviews", ["candidate_id"])

    op.create_table(
        "epcr_transport_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("chart_id", sa.String(length=36), nullable=False),
        sa.Column("transport_request_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("linked_by_user_id", sa.String(length=255), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.Column("pcs_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("aob_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("encounter_fields_mapped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mapped_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_epcr_transport_links_tenant_id", "epcr_transport_links", ["tenant_id"])
    op.create_index("ix_epcr_transport_links_chart_id", "epcr_transport_links", ["chart_id"])
    op.create_index("ix_epcr_transport_links_transport_request_id", "epcr_transport_links", ["transport_request_id"], unique=True)

    op.create_table(
        "epcr_encounter_artifact_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("chart_id", sa.String(length=36), nullable=False),
        sa.Column("transport_link_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("signed_artifact_id", sa.String(length=36), nullable=False),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_epcr_encounter_artifact_links_tenant_id", "epcr_encounter_artifact_links", ["tenant_id"])
    op.create_index("ix_epcr_encounter_artifact_links_chart_id", "epcr_encounter_artifact_links", ["chart_id"])

    op.create_table(
        "epcr_ocr_review_queue",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("ocr_job_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("chart_id", sa.String(length=36), nullable=True),
        sa.Column("transport_request_id", sa.String(length=36), nullable=True),
        sa.Column("assigned_to_user_id", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("review_started_at", sa.DateTime(), nullable=True),
        sa.Column("review_completed_at", sa.DateTime(), nullable=True),
        sa.Column("removed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_epcr_ocr_review_queue_tenant_id", "epcr_ocr_review_queue", ["tenant_id"])
    op.create_index("ix_epcr_ocr_review_queue_removed", "epcr_ocr_review_queue", ["removed"])

    op.create_table(
        "nemsis_field_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("chart_id", sa.String(length=36), nullable=False),
        sa.Column("extraction_id", sa.String(length=36), nullable=True),
        sa.Column("nemsis_element", sa.String(length=100), nullable=False),
        sa.Column("source_field_name", sa.String(length=100), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=False),
        sa.Column("mapped_value", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("mapped_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nemsis_field_bindings_tenant_id", "nemsis_field_bindings", ["tenant_id"])
    op.create_index("ix_nemsis_field_bindings_chart_id", "nemsis_field_bindings", ["chart_id"])
    op.create_index("ix_nemsis_field_bindings_status", "nemsis_field_bindings", ["status"])

    op.create_table(
        "nemsis_binding_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_user_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("override_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nemsis_binding_reviews_binding_id", "nemsis_binding_reviews", ["binding_id"])

    op.create_table(
        "nemsis_export_readiness_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("chart_id", sa.String(length=36), nullable=False),
        sa.Column("export_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("required_elements_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bound_elements_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_elements", sa.Text(), nullable=True),
        sa.Column("blocking_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nemsis_export_readiness_snapshots_tenant_id", "nemsis_export_readiness_snapshots", ["tenant_id"])
    op.create_index("ix_nemsis_export_readiness_snapshots_chart_id", "nemsis_export_readiness_snapshots", ["chart_id"])

    op.create_table(
        "epcr_nemsis_transport_binding_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("chart_id", sa.String(length=36), nullable=False),
        sa.Column("transport_request_id", sa.String(length=36), nullable=False),
        sa.Column("extraction_id", sa.String(length=36), nullable=True),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_epcr_nemsis_transport_binding_links_binding_id", "epcr_nemsis_transport_binding_links", ["binding_id"])
    op.create_index("ix_epcr_nemsis_transport_binding_links_chart_id", "epcr_nemsis_transport_binding_links", ["chart_id"])

    op.create_table(
        "transport_structured_extractions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("ocr_job_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("transport_request_id", sa.String(length=36), nullable=True),
        sa.Column("chart_id", sa.String(length=36), nullable=True),
        sa.Column("patient_name", sa.String(length=255), nullable=True),
        sa.Column("patient_dob", sa.String(length=20), nullable=True),
        sa.Column("patient_mrn", sa.String(length=100), nullable=True),
        sa.Column("physician_name", sa.String(length=255), nullable=True),
        sa.Column("diagnosis_codes", sa.Text(), nullable=True),
        sa.Column("pickup_address", sa.Text(), nullable=True),
        sa.Column("destination_address", sa.Text(), nullable=True),
        sa.Column("medical_necessity_statement", sa.Text(), nullable=True),
        sa.Column("signature_date", sa.String(length=20), nullable=True),
        sa.Column("transport_qualifier", sa.String(length=100), nullable=True),
        sa.Column("all_fields", sa.Text(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(), nullable=False),
        sa.Column("promoted_by_user_id", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transport_structured_extractions_tenant_id", "transport_structured_extractions", ["tenant_id"])
    op.create_index("ix_transport_structured_extractions_transport_request_id", "transport_structured_extractions", ["transport_request_id"])


def downgrade() -> None:
    """Drop all tables added in this migration in reverse dependency order."""
    op.drop_table("transport_structured_extractions")
    op.drop_table("epcr_nemsis_transport_binding_links")
    op.drop_table("nemsis_export_readiness_snapshots")
    op.drop_table("nemsis_binding_reviews")
    op.drop_table("nemsis_field_bindings")
    op.drop_table("epcr_ocr_review_queue")
    op.drop_table("epcr_encounter_artifact_links")
    op.drop_table("epcr_transport_links")
    op.drop_table("ocr_field_reviews")
    op.drop_table("ocr_field_candidates")
    op.drop_table("ocr_results")
    op.drop_table("ocr_sources")
    op.drop_table("ocr_jobs")
