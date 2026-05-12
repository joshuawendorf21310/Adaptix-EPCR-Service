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
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS epcr_protocols (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL,
            title            TEXT NOT NULL,
            category         TEXT,
            version          TEXT NOT NULL DEFAULT '1.0',
            status           TEXT NOT NULL DEFAULT 'active',
            effective_date   TIMESTAMPTZ,
            retired_date     TIMESTAMPTZ,
            content          TEXT,
            source_reference TEXT,
            created_by       UUID,
            updated_by       UUID,
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            updated_at       TIMESTAMPTZ
        )
    """))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_epcr_protocols_tenant_id ON epcr_protocols (tenant_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_epcr_protocols_status ON epcr_protocols (tenant_id, status)"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS epcr_protocols"))
