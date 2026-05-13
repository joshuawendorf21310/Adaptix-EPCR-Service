"""054 add epcr_protocol_context for the ProtocolContextService pillar.

Revision ID: 054
Revises: 043
Create Date: 2026-05-12

Creates the ``epcr_protocol_context`` table that backs live protocol
pack engagement (ACLS / PALS / NRP / CCT / ...) on a chart. The schema
is portable across PostgreSQL and SQLite (used by the test harness);
enum-like columns are stored as portable strings with their canonical
value sets enforced at the application layer (see
``epcr_app.services.protocol_context_service``).

Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``
and indexes are created with ``if_not_exists=True``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


TABLE = "epcr_protocol_context"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "chart_id",
            sa.String(length=36),
            sa.ForeignKey("epcr_charts.id"),
            nullable=False,
        ),
        sa.Column("active_pack", sa.String(length=32), nullable=True),
        sa.Column("engaged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engaged_by", sa.String(length=255), nullable=False),
        sa.Column(
            "disengaged_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "required_field_satisfaction_json", sa.Text(), nullable=True
        ),
        sa.Column("pack_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_protocol_context_tenant_id",
        TABLE,
        ["tenant_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_protocol_context_chart_id",
        TABLE,
        ["chart_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_protocol_context_tenant_chart",
        TABLE,
        ["tenant_id", "chart_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_protocol_context_tenant_chart_active",
        TABLE,
        ["tenant_id", "chart_id", "disengaged_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_protocol_context_tenant_chart_active",
        table_name=TABLE,
    )
    op.drop_index(
        "ix_epcr_protocol_context_tenant_chart",
        table_name=TABLE,
    )
    op.drop_index(
        "ix_epcr_protocol_context_chart_id",
        table_name=TABLE,
    )
    op.drop_index(
        "ix_epcr_protocol_context_tenant_id",
        table_name=TABLE,
    )
    op.drop_table(TABLE)
