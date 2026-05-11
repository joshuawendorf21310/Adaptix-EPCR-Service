"""023 add patient registry foundation

Revision ID: 023
Revises: 022
Create Date: 2026-05-10

Adds the repeat-patient registry foundation, accelerator import audit,
duplicate candidate storage, merge audit, and alias persistence.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "patient_registry_profiles"):
        op.create_table(
            "patient_registry_profiles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("canonical_patient_key", sa.String(64), nullable=True),
            sa.Column("first_name", sa.String(120), nullable=True),
            sa.Column("middle_name", sa.String(120), nullable=True),
            sa.Column("last_name", sa.String(120), nullable=True),
            sa.Column("first_name_norm", sa.String(120), nullable=True),
            sa.Column("last_name_norm", sa.String(120), nullable=True),
            sa.Column("date_of_birth", sa.String(32), nullable=True),
            sa.Column("sex", sa.String(32), nullable=True),
            sa.Column("phone_last4", sa.String(4), nullable=True),
            sa.Column("primary_phone_hash", sa.String(64), nullable=True),
            sa.Column("merged_into_patient_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=True),
            sa.Column("ai_assisted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.UniqueConstraint("tenant_id", "canonical_patient_key", name="uq_patient_registry_profiles_tenant_canonical_key"),
        if_not_exists=True)
        op.create_index("idx_patient_registry_profiles_tenant_id", "patient_registry_profiles", ["tenant_id"])
        op.create_index("idx_patient_registry_profiles_canonical_patient_key", "patient_registry_profiles", ["canonical_patient_key"])

    if not _has_table(insp, "patient_registry_identifiers"):
        op.create_table(
            "patient_registry_identifiers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("patient_registry_profile_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=False),
            sa.Column("identifier_type", sa.String(32), nullable=False),
            sa.Column("identifier_hash", sa.String(64), nullable=False),
            sa.Column("identifier_last4", sa.String(16), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("source_chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.UniqueConstraint(
                "patient_registry_profile_id",
                "identifier_type",
                "identifier_hash",
                name="uq_patient_registry_identifiers_profile_identifier",
            ),
        if_not_exists=True)
        op.create_index("idx_patient_registry_identifiers_tenant_id", "patient_registry_identifiers", ["tenant_id"])
        op.create_index("idx_patient_registry_identifiers_identifier_hash", "patient_registry_identifiers", ["identifier_hash"])

    if not _has_table(insp, "patient_registry_chart_links"):
        op.create_table(
            "patient_registry_chart_links",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("patient_registry_profile_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=False),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("link_status", sa.String(32), nullable=False, server_default=sa.text("'linked'")),
            sa.Column("confidence_status", sa.String(32), nullable=True),
            sa.Column("linked_by_user_id", sa.String(255), nullable=True),
            sa.Column("rejected_reason", sa.Text(), nullable=True),
            sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.UniqueConstraint("chart_id", name="uq_patient_registry_chart_links_chart_id"),
        if_not_exists=True)
        op.create_index("idx_patient_registry_chart_links_tenant_id", "patient_registry_chart_links", ["tenant_id"])

    if not _has_table(insp, "epcr_charting_accelerator_imports"):
        op.create_table(
            "epcr_charting_accelerator_imports",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("source_chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("section_name", sa.String(64), nullable=False),
            sa.Column("dedupe_key", sa.String(128), nullable=False),
            sa.Column("imported_fields_json", sa.Text(), nullable=True),
            sa.Column("provider_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("confirmed_by_user_id", sa.String(255), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.UniqueConstraint(
                "chart_id",
                "source_chart_id",
                "section_name",
                "dedupe_key",
                name="uq_epcr_charting_accelerator_imports_scope",
            ),
        if_not_exists=True)
        op.create_index("idx_epcr_charting_accelerator_imports_tenant_id", "epcr_charting_accelerator_imports", ["tenant_id"])

    if not _has_table(insp, "patient_registry_merge_candidates"):
        op.create_table(
            "patient_registry_merge_candidates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("left_patient_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=False),
            sa.Column("right_patient_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=False),
            sa.Column("confidence_status", sa.String(32), nullable=False),
            sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("requires_human_review", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("match_reasons_json", sa.Text(), nullable=True),
            sa.Column("conflicting_signals_json", sa.Text(), nullable=True),
            sa.Column("review_status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
            sa.Column("reviewed_by_user_id", sa.String(255), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.UniqueConstraint(
                "tenant_id",
                "left_patient_id",
                "right_patient_id",
                name="uq_patient_registry_merge_candidates_pair",
            ),
        if_not_exists=True)
        op.create_index("idx_patient_registry_merge_candidates_tenant_id", "patient_registry_merge_candidates", ["tenant_id"])

    if not _has_table(insp, "patient_registry_merge_audit"):
        op.create_table(
            "patient_registry_merge_audit",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("canonical_patient_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=False),
            sa.Column("merged_patient_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("merged_by_user_id", sa.String(255), nullable=False),
            sa.Column("merged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rolled_back_by_user_id", sa.String(255), nullable=True),
            sa.Column("rollback_snapshot_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        if_not_exists=True)
        op.create_index("idx_patient_registry_merge_audit_tenant_id", "patient_registry_merge_audit", ["tenant_id"])

    if not _has_table(insp, "patient_registry_aliases"):
        op.create_table(
            "patient_registry_aliases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("canonical_patient_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=False),
            sa.Column("alias_patient_id", sa.String(36), sa.ForeignKey("patient_registry_profiles.id"), nullable=False),
            sa.Column("alias_reason", sa.String(64), nullable=False),
            sa.Column("created_by_user_id", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.UniqueConstraint("tenant_id", "alias_patient_id", name="uq_patient_registry_aliases_tenant_alias"),
        if_not_exists=True)
        op.create_index("idx_patient_registry_aliases_tenant_id", "patient_registry_aliases", ["tenant_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in (
        "patient_registry_aliases",
        "patient_registry_merge_audit",
        "patient_registry_merge_candidates",
        "epcr_charting_accelerator_imports",
        "patient_registry_chart_links",
        "patient_registry_identifiers",
        "patient_registry_profiles",
    ):
        if _has_table(insp, table):
            op.drop_table(table)