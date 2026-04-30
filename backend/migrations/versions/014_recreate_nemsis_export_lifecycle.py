"""014 recreate nemsis export attempts + events to match ORM

Revision ID: 014_recreate_nemsis_export_lifecycle
Revises: 013_chart_narrative_version
Create Date: 2026-04-29

The original 002_add_nemsis_export_lifecycle migration created
`epcr_nemsis_export_attempts` and `epcr_nemsis_export_events` with a
varchar(36) primary key and a slimmer column list than the ORM in
`epcr_app.models_export` defines. The deployed schema is missing:

  epcr_nemsis_export_attempts: message, requested_at, started_at,
    completed_at, created_by_user_id, version, deleted_at
  epcr_nemsis_export_events: export_attempt_id (real FK), severity,
    payload, version, deleted_at

and the id types disagree with the ORM (BigInteger autoincrement vs
varchar(36)).

Both tables are empty after a clean rebuild + seed, so the truthful fix
is to drop and recreate them to match the ORM contract exactly. If rows
exist they are preserved by the guard at the top of upgrade().
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "014_recreate_nemsis_export_lifecycle"
down_revision = "013_chart_narrative_version"
branch_labels = None
depends_on = None


def _table_row_count(bind, table: str) -> int:
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return 0
    res = bind.execute(sa.text(f"SELECT count(*) FROM {table}"))
    return int(res.scalar() or 0)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Refuse to run if either table has rows (data loss guard).
    if _table_row_count(bind, "epcr_nemsis_export_attempts") > 0:
        raise RuntimeError(
            "epcr_nemsis_export_attempts has rows; refuse to recreate. "
            "Backfill columns manually instead of running this migration."
        )
    if _table_row_count(bind, "epcr_nemsis_export_events") > 0:
        raise RuntimeError(
            "epcr_nemsis_export_events has rows; refuse to recreate."
        )

    if insp.has_table("epcr_nemsis_export_events"):
        op.drop_table("epcr_nemsis_export_events")
    if insp.has_table("epcr_nemsis_export_attempts"):
        op.drop_table("epcr_nemsis_export_attempts")

    op.create_table(
        "epcr_nemsis_export_attempts",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("chart_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_type", sa.Text(), nullable=False, server_default="none"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("trigger_source", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "supersedes_export_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("epcr_nemsis_export_attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "superseded_by_export_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("epcr_nemsis_export_attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ready_for_export", sa.Boolean(), nullable=False),
        sa.Column("blocker_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compliance_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("missing_mandatory_fields", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("artifact_file_name", sa.Text(), nullable=True),
        sa.Column("artifact_mime_type", sa.Text(), nullable=True),
        sa.Column("artifact_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("artifact_storage_key", sa.Text(), nullable=True),
        sa.Column("artifact_checksum_sha256", sa.Text(), nullable=True),
        sa.Column("xsd_valid", sa.Boolean(), nullable=True),
        sa.Column("schematron_valid", sa.Boolean(), nullable=True),
        sa.Column("validator_errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("validator_warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("validator_asset_version", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_nemsis_export_attempts_chart_id", "epcr_nemsis_export_attempts", ["chart_id"])
    op.create_index(
        "idx_nemsis_export_attempts_tenant_chart",
        "epcr_nemsis_export_attempts",
        ["tenant_id", "chart_id"],
    )
    op.create_index("idx_nemsis_export_attempts_status", "epcr_nemsis_export_attempts", ["status"])
    op.create_index("idx_nemsis_export_attempts_created_at", "epcr_nemsis_export_attempts", ["created_at"])
    op.create_index(
        "idx_nemsis_export_attempts_chart_created_desc",
        "epcr_nemsis_export_attempts",
        ["chart_id", "created_at"],
    )
    op.create_index("ix_attempts_tenant_id", "epcr_nemsis_export_attempts", ["tenant_id"])
    op.create_index("ix_attempts_chart_id", "epcr_nemsis_export_attempts", ["chart_id"])
    op.create_index("ix_attempts_status", "epcr_nemsis_export_attempts", ["status"])
    op.create_index("ix_attempts_deleted_at", "epcr_nemsis_export_attempts", ["deleted_at"])

    op.create_table(
        "epcr_nemsis_export_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "export_attempt_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("epcr_nemsis_export_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("chart_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_events_export_attempt_id",
        "epcr_nemsis_export_events",
        ["export_attempt_id"],
    )
    op.create_index("ix_events_tenant_id", "epcr_nemsis_export_events", ["tenant_id"])
    op.create_index("ix_events_chart_id", "epcr_nemsis_export_events", ["chart_id"])


def downgrade() -> None:
    op.drop_table("epcr_nemsis_export_events")
    op.drop_table("epcr_nemsis_export_attempts")
