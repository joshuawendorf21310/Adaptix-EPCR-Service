"""Add epcr_protocols table.

Revision ID: 042
Revises: 041
Create Date: 2026-05-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "epcr_protocols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.String(512), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_epcr_protocols_tenant_id", "epcr_protocols", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_epcr_protocols_tenant_status", "epcr_protocols", ["tenant_id", "status"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_epcr_protocols_tenant_status", table_name="epcr_protocols")
    op.drop_index("ix_epcr_protocols_tenant_id", table_name="epcr_protocols")
    op.drop_table("epcr_protocols")
