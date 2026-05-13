"""052 add epcr_map_location_context for Mapbox-backed location pillar

Revision ID: 052
Revises: 043
Create Date: 2026-05-12

Creates the ``epcr_map_location_context`` table that backs the Mapbox
ePCR location pillar (scene, destination, staging, breadcrumb captures
plus optional reverse-geocoded address and classified facility type).

The schema is portable across PostgreSQL and SQLite (used by the test
harness); enum-like columns are stored as portable strings with their
canonical value sets enforced at the application layer (see
``epcr_app.services.map_location_service``).

Idempotent + drift-safe: ``create_table`` uses ``if_not_exists=True``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


TABLE = "epcr_map_location_context"


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
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("address_text", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("accuracy_meters", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "reverse_geocoded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("facility_type", sa.String(length=32), nullable=True),
        sa.Column("distance_meters", sa.Numeric(12, 2), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_map_location_context_tenant_id", TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_map_location_context_chart_id", TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_map_location_context_tenant_chart",
        TABLE,
        ["tenant_id", "chart_id"],
    )
    op.create_index(
        "ix_epcr_map_location_context_chart_kind",
        TABLE,
        ["chart_id", "kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_map_location_context_chart_kind", table_name=TABLE
    )
    op.drop_index(
        "ix_epcr_map_location_context_tenant_chart", table_name=TABLE
    )
    op.drop_index(
        "ix_epcr_map_location_context_chart_id", table_name=TABLE
    )
    op.drop_index(
        "ix_epcr_map_location_context_tenant_id", table_name=TABLE
    )
    op.drop_table(TABLE)
