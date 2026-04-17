"""Migration 004: add NEMSIS submission pipeline tables.

Creates nemsis_resource_packs, nemsis_pack_files, nemsis_submission_results,
nemsis_submission_status_history, and nemsis_cs_scenarios. These tables
support resource pack lifecycle, state submission workflow, and 2026 TAC
compliance studio scenario execution.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create NEMSIS submission pipeline tables in dependency order."""

    op.create_table(
        "nemsis_resource_packs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("pack_type", sa.String(length=64), nullable=False),
        sa.Column("nemsis_version", sa.String(length=32), nullable=False, server_default="3.5.1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("s3_bucket", sa.String(length=255), nullable=True),
        sa.Column("s3_prefix", sa.String(length=1024), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nemsis_resource_packs_tenant_id", "nemsis_resource_packs", ["tenant_id"])
    op.create_index("ix_nemsis_resource_packs_status", "nemsis_resource_packs", ["status"])
    op.create_index(
        "ix_nemsis_resource_packs_tenant_status",
        "nemsis_resource_packs",
        ["tenant_id", "status"],
    )

    op.create_table(
        "nemsis_pack_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "pack_id",
            sa.String(length=36),
            sa.ForeignKey("nemsis_resource_packs.id"),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("file_role", sa.String(length=64), nullable=True),
        sa.Column("s3_key", sa.String(length=1024), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nemsis_pack_files_pack_id", "nemsis_pack_files", ["pack_id"])

    op.create_table(
        "nemsis_submission_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column("export_id", sa.String(length=36), nullable=True),
        sa.Column("submission_number", sa.String(length=64), nullable=False),
        sa.Column("state_endpoint_url", sa.String(length=2048), nullable=True),
        sa.Column("submission_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("xml_s3_bucket", sa.String(length=255), nullable=True),
        sa.Column("xml_s3_key", sa.String(length=1024), nullable=True),
        sa.Column("ack_s3_bucket", sa.String(length=255), nullable=True),
        sa.Column("ack_s3_key", sa.String(length=1024), nullable=True),
        sa.Column("response_s3_bucket", sa.String(length=255), nullable=True),
        sa.Column("response_s3_key", sa.String(length=1024), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("soap_message_id", sa.String(length=255), nullable=True),
        sa.Column("soap_response_code", sa.String(length=32), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("comparison_report_ref", sa.String(length=1024), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nemsis_submission_results_tenant_id", "nemsis_submission_results", ["tenant_id"])
    op.create_index("ix_nemsis_submission_results_chart_id", "nemsis_submission_results", ["chart_id"])
    op.create_index(
        "ix_nemsis_submission_results_chart_status",
        "nemsis_submission_results",
        ["chart_id", "submission_status"],
    )
    op.create_index(
        "ix_nemsis_submission_results_tenant_status",
        "nemsis_submission_results",
        ["tenant_id", "submission_status"],
    )

    op.create_table(
        "nemsis_submission_status_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "submission_id",
            sa.String(length=36),
            sa.ForeignKey("nemsis_submission_results.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload_snapshot_json", sa.Text(), nullable=True),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_nemsis_submission_status_history_submission_id",
        "nemsis_submission_status_history",
        ["submission_id"],
    )
    op.create_index(
        "ix_nemsis_submission_status_history_tenant_id",
        "nemsis_submission_status_history",
        ["tenant_id"],
    )

    op.create_table(
        "nemsis_cs_scenarios",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("scenario_code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("asset_s3_bucket", sa.String(length=255), nullable=True),
        sa.Column("asset_s3_key", sa.String(length=1024), nullable=True),
        sa.Column("asset_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="available"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_submission_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nemsis_cs_scenarios_scenario_code", "nemsis_cs_scenarios", ["scenario_code"], unique=True)
    op.create_index(
        "ix_nemsis_cs_scenarios_year_category",
        "nemsis_cs_scenarios",
        ["year", "category"],
    )


def downgrade() -> None:
    """Drop all NEMSIS submission pipeline indexes and tables in reverse dependency order."""
    op.drop_index("ix_nemsis_cs_scenarios_year_category", table_name="nemsis_cs_scenarios")
    op.drop_index("ix_nemsis_cs_scenarios_scenario_code", table_name="nemsis_cs_scenarios")
    op.drop_table("nemsis_cs_scenarios")

    op.drop_index(
        "ix_nemsis_submission_status_history_tenant_id",
        table_name="nemsis_submission_status_history",
    )
    op.drop_index(
        "ix_nemsis_submission_status_history_submission_id",
        table_name="nemsis_submission_status_history",
    )
    op.drop_table("nemsis_submission_status_history")

    op.drop_index(
        "ix_nemsis_submission_results_tenant_status",
        table_name="nemsis_submission_results",
    )
    op.drop_index(
        "ix_nemsis_submission_results_chart_status",
        table_name="nemsis_submission_results",
    )
    op.drop_index("ix_nemsis_submission_results_chart_id", table_name="nemsis_submission_results")
    op.drop_index("ix_nemsis_submission_results_tenant_id", table_name="nemsis_submission_results")
    op.drop_table("nemsis_submission_results")

    op.drop_index("ix_nemsis_pack_files_pack_id", table_name="nemsis_pack_files")
    op.drop_table("nemsis_pack_files")

    op.drop_index(
        "ix_nemsis_resource_packs_tenant_status",
        table_name="nemsis_resource_packs",
    )
    op.drop_index("ix_nemsis_resource_packs_status", table_name="nemsis_resource_packs")
    op.drop_index("ix_nemsis_resource_packs_tenant_id", table_name="nemsis_resource_packs")
    op.drop_table("nemsis_resource_packs")
