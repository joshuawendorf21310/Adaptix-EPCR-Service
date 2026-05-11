from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tac_schematron_packages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("package_label", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.String(length=255), nullable=True),
        sa.Column("delete_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        if_not_exists=True)
    op.create_index("ix_tac_schematron_packages_tenant_id", "tac_schematron_packages", ["tenant_id"])
    op.create_index("ix_tac_schematron_packages_status", "tac_schematron_packages", ["status"])
    op.create_index("ix_tac_schematron_packages_deleted_at", "tac_schematron_packages", ["deleted_at"])

    op.create_table(
        "tac_schematron_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("package_id", sa.String(length=36), sa.ForeignKey("tac_schematron_packages.id"), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("xml_root", sa.String(length=128), nullable=True),
        sa.Column("schematron_namespace", sa.String(length=255), nullable=True),
        sa.Column("assertion_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("natural_language_messages_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.String(length=255), nullable=True),
        sa.Column("delete_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        if_not_exists=True)
    op.create_index("ix_tac_schematron_assets_package_id", "tac_schematron_assets", ["package_id"])
    op.create_index("ix_tac_schematron_assets_tenant_id", "tac_schematron_assets", ["tenant_id"])
    op.create_index("ix_tac_schematron_assets_dataset_type", "tac_schematron_assets", ["dataset_type"])
    op.create_index("ix_tac_schematron_assets_sha256", "tac_schematron_assets", ["sha256"])
    op.create_index("ix_tac_schematron_assets_deleted_at", "tac_schematron_assets", ["deleted_at"])

    op.create_table(
        "tac_schematron_audit_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("package_id", sa.String(length=36), sa.ForeignKey("tac_schematron_packages.id"), nullable=False),
        sa.Column("asset_id", sa.String(length=36), sa.ForeignKey("tac_schematron_assets.id"), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        if_not_exists=True)
    op.create_index("ix_tac_schematron_audit_log_tenant_id", "tac_schematron_audit_log", ["tenant_id"])
    op.create_index("ix_tac_schematron_audit_log_package_id", "tac_schematron_audit_log", ["package_id"])
    op.create_index("ix_tac_schematron_audit_log_asset_id", "tac_schematron_audit_log", ["asset_id"])
    op.create_index("ix_tac_schematron_audit_log_action", "tac_schematron_audit_log", ["action"])


def downgrade() -> None:
    op.drop_index("ix_tac_schematron_audit_log_action", table_name="tac_schematron_audit_log")
    op.drop_index("ix_tac_schematron_audit_log_asset_id", table_name="tac_schematron_audit_log")
    op.drop_index("ix_tac_schematron_audit_log_package_id", table_name="tac_schematron_audit_log")
    op.drop_index("ix_tac_schematron_audit_log_tenant_id", table_name="tac_schematron_audit_log")
    op.drop_table("tac_schematron_audit_log")

    op.drop_index("ix_tac_schematron_assets_deleted_at", table_name="tac_schematron_assets")
    op.drop_index("ix_tac_schematron_assets_sha256", table_name="tac_schematron_assets")
    op.drop_index("ix_tac_schematron_assets_dataset_type", table_name="tac_schematron_assets")
    op.drop_index("ix_tac_schematron_assets_tenant_id", table_name="tac_schematron_assets")
    op.drop_index("ix_tac_schematron_assets_package_id", table_name="tac_schematron_assets")
    op.drop_table("tac_schematron_assets")

    op.drop_index("ix_tac_schematron_packages_deleted_at", table_name="tac_schematron_packages")
    op.drop_index("ix_tac_schematron_packages_status", table_name="tac_schematron_packages")
    op.drop_index("ix_tac_schematron_packages_tenant_id", table_name="tac_schematron_packages")
    op.drop_table("tac_schematron_packages")
