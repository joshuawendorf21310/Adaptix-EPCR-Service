"""Add ePCR Fire incident link receipts."""

from alembic import op
import sqlalchemy as sa

revision = "012_add_fire_incident_links"
down_revision = "011_patient_state_timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "epcr_fire_incident_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("chart_id", sa.String(length=36), nullable=True),
        sa.Column("fire_incident_id", sa.String(length=36), nullable=False),
        sa.Column("fire_incident_number", sa.String(length=50), nullable=False),
        sa.Column("fire_address", sa.Text(), nullable=False),
        sa.Column("fire_incident_type", sa.String(length=100), nullable=False),
        sa.Column("link_status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chart_id"], ["epcr_charts.id"]),
    )
    op.create_index("ix_epcr_fire_incident_links_tenant_id", "epcr_fire_incident_links", ["tenant_id"])
    op.create_index("ix_epcr_fire_incident_links_fire_incident_id", "epcr_fire_incident_links", ["fire_incident_id"])


def downgrade() -> None:
    op.drop_index("ix_epcr_fire_incident_links_fire_incident_id", table_name="epcr_fire_incident_links")
    op.drop_index("ix_epcr_fire_incident_links_tenant_id", table_name="epcr_fire_incident_links")
    op.drop_table("epcr_fire_incident_links")