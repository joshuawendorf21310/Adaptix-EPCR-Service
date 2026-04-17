"""Add NEMSIS export lifecycle tables with full audit trail.

Revision ID: 002
Revises: 001
Create Date: 2026-04-12

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create nemsis_export_attempts and nemsis_export_events tables."""
    # NEMSIS export attempts: lifecycle and state management
    op.create_table(
        "epcr_nemsis_export_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, index=True),
        sa.Column("failure_type", sa.String(50), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("trigger_source", sa.String(50), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, default=0),
        sa.Column(
            "supersedes_export_id",
            sa.String(36),
            sa.ForeignKey("epcr_nemsis_export_attempts.id"),
            nullable=True,
        ),
        sa.Column(
            "superseded_by_export_id",
            sa.String(36),
            sa.ForeignKey("epcr_nemsis_export_attempts.id"),
            nullable=True,
        ),
        # Readiness snapshot (immutable at attempt creation time)
        sa.Column("ready_for_export", sa.Boolean(), nullable=False),
        sa.Column("blocker_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("compliance_percentage", sa.Float(), nullable=True),
        sa.Column(
            "missing_mandatory_fields",
            sa.JSON() if hasattr(sa, "JSON") else sa.Text(),
            nullable=True,
        ),
        # Artifact metadata
        sa.Column("artifact_file_name", sa.String(255), nullable=True),
        sa.Column("artifact_mime_type", sa.String(100), nullable=True),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=True),
        sa.Column("artifact_storage_key", sa.String(500), nullable=True),
        sa.Column("artifact_checksum_sha256", sa.String(64), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Indexes for common queries
        sa.Index("idx_epcr_nemsis_export_chart_id_created", "chart_id", "created_at"),
        sa.Index(
            "idx_epcr_nemsis_export_tenant_created",
            "tenant_id",
            "created_at",
        ),
        sa.Index("idx_epcr_nemsis_export_status", "status"),
    )

    # NEMSIS export events: audit trail for lifecycle transitions
    op.create_table(
        "epcr_nemsis_export_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "export_id",
            sa.String(36),
            sa.ForeignKey("epcr_nemsis_export_attempts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("from_status", sa.String(50), nullable=True),
        sa.Column("to_status", sa.String(50), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            sa.JSON() if hasattr(sa, "JSON") else sa.Text(),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Index for audit trail queries
        sa.Index("idx_epcr_nemsis_event_export_created", "export_id", "created_at"),
    )

    op.create_table(
        "epcr_nemsis_export_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("exported_by_user_id", sa.String(255), nullable=False),
        sa.Column("export_status", sa.String(20), nullable=False),
        sa.Column("export_payload_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "epcr_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop nemsis export tables."""
    op.drop_table("epcr_audit_log")
    op.drop_table("epcr_nemsis_export_history")
    op.drop_table("epcr_nemsis_export_events")
    op.drop_table("epcr_nemsis_export_attempts")
