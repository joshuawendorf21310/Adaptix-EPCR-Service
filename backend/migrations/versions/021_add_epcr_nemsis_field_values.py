"""021 add epcr_nemsis_field_values for row-level repeating-group persistence

Revision ID: 021
Revises: 558f23877870
Create Date: 2026-05-09

Adds the canonical row-per-occurrence NEMSIS field-value table that
preserves repeating-group truth (group_path + occurrence_id +
sequence_index) instead of flattening into the dict-aggregated
``chart_field_values`` shape used by ``nemsis_chart_finalization_gate``.

Why row-per-occurrence:
- NEMSIS recurrence (1:M, 0:M) requires that a single element_number can
  be saved multiple times within the same chart, distinguished by
  occurrence_id.
- A uniqueness constraint on (chart_id, element_number) would BREAK
  repeating groups; the ledger uniqueness key must be
  (tenant_id, chart_id, element_number, group_path, occurrence_id).
- Tenant isolation is enforced by the composite uniqueness key and by
  the (tenant_id, chart_id) covering index used by every read path.

Idempotent + drift-safe: each step verifies state via the inspector
before acting (matches conventions in 019/020).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "021"
down_revision = "558f23877870"
branch_labels = None
depends_on = None


TABLE = "epcr_nemsis_field_values"


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("chart_id", sa.String(64), nullable=False),
            sa.Column("section", sa.String(32), nullable=False),
            sa.Column("element_number", sa.String(32), nullable=False),
            sa.Column("element_name", sa.String(255), nullable=False),
            sa.Column("group_path", sa.String(255), nullable=False, server_default=""),
            sa.Column("occurrence_id", sa.String(64), nullable=False, server_default=""),
            sa.Column(
                "sequence_index",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("value_json", sa.JSON(), nullable=True),
            sa.Column(
                "attributes_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "source",
                sa.String(32),
                nullable=False,
                server_default="manual",
            ),
            sa.Column(
                "validation_status",
                sa.String(32),
                nullable=False,
                server_default="unvalidated",
            ),
            sa.Column(
                "validation_issues_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
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
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "element_number",
                "group_path",
                "occurrence_id",
                name="uq_epcr_nemsis_field_values_occurrence",
            ),
        )

    # Indexes (idempotent)
    if not _has_index(insp, TABLE, "idx_epcr_nemsis_field_values_tenant_chart"):
        op.create_index(
            "idx_epcr_nemsis_field_values_tenant_chart",
            TABLE,
            ["tenant_id", "chart_id"],
        )
    if not _has_index(insp, TABLE, "idx_epcr_nemsis_field_values_element"):
        op.create_index(
            "idx_epcr_nemsis_field_values_element",
            TABLE,
            ["tenant_id", "chart_id", "element_number"],
        )
    if not _has_index(insp, TABLE, "idx_epcr_nemsis_field_values_group"):
        op.create_index(
            "idx_epcr_nemsis_field_values_group",
            TABLE,
            ["tenant_id", "chart_id", "group_path", "occurrence_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(insp, TABLE, "idx_epcr_nemsis_field_values_group"):
        op.drop_index("idx_epcr_nemsis_field_values_group", table_name=TABLE)
    if _has_index(insp, TABLE, "idx_epcr_nemsis_field_values_element"):
        op.drop_index("idx_epcr_nemsis_field_values_element", table_name=TABLE)
    if _has_index(insp, TABLE, "idx_epcr_nemsis_field_values_tenant_chart"):
        op.drop_index("idx_epcr_nemsis_field_values_tenant_chart", table_name=TABLE)
    if insp.has_table(TABLE):
        op.drop_table(TABLE)
