"""053 add Multi-Patient Incident + Link tables.

Revision ID: 053
Revises: 043
Create Date: 2026-05-12

Creates the two tables backing the :class:`MultiPatientService` pillar:

- ``epcr_multi_patient_incident``: scene-level parent row representing a
  multi-patient event (MCI, multi-victim MVA, fire rescue). Aggregates
  shared context (scene address, mechanism, hazards, mci_flag,
  patient_count).
- ``epcr_multi_patient_link``: per-patient association between the
  parent incident and an ePCR chart, with provider-assigned label
  ('A', 'B', ...), triage color, acuity, transport priority, and
  destination. The ``chart_id`` column is a *soft* FK (string, no DB
  FOREIGN KEY) so cross-tenant archival and incident merges/splits do
  not require cascade rules. Soft delete via ``removed_at``.

Schema is portable across PostgreSQL and SQLite (test harness).
Idempotent + drift-safe via ``if_not_exists=True``.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


INCIDENT_TABLE = "epcr_multi_patient_incident"
LINK_TABLE = "epcr_multi_patient_link"


def upgrade() -> None:
    op.create_table(
        INCIDENT_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "parent_incident_number", sa.String(length=64), nullable=False
        ),
        sa.Column("scene_address_json", sa.Text(), nullable=True),
        sa.Column(
            "mci_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "patient_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("mechanism", sa.String(length=128), nullable=True),
        sa.Column("hazards_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "patient_count >= 0",
            name="ck_epcr_multi_patient_incident_patient_count_nonneg",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_multi_patient_incident_tenant_id",
        INCIDENT_TABLE,
        ["tenant_id"],
    )
    op.create_index(
        "ix_epcr_multi_patient_incident_parent_incident_number",
        INCIDENT_TABLE,
        ["parent_incident_number"],
    )
    op.create_index(
        "ix_epcr_multi_patient_incident_tenant_parent",
        INCIDENT_TABLE,
        ["tenant_id", "parent_incident_number"],
    )

    op.create_table(
        LINK_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "multi_incident_id",
            sa.String(length=36),
            sa.ForeignKey(f"{INCIDENT_TABLE}.id"),
            nullable=False,
        ),
        sa.Column("chart_id", sa.String(length=36), nullable=False),
        sa.Column("patient_label", sa.String(length=32), nullable=False),
        sa.Column("triage_category", sa.String(length=16), nullable=True),
        sa.Column("acuity", sa.String(length=32), nullable=True),
        sa.Column("transport_priority", sa.String(length=32), nullable=True),
        sa.Column("destination_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index(
        "ix_epcr_multi_patient_link_tenant_id", LINK_TABLE, ["tenant_id"]
    )
    op.create_index(
        "ix_epcr_multi_patient_link_multi_incident_id",
        LINK_TABLE,
        ["multi_incident_id"],
    )
    op.create_index(
        "ix_epcr_multi_patient_link_chart_id", LINK_TABLE, ["chart_id"]
    )
    op.create_index(
        "ix_epcr_multi_patient_link_removed_at",
        LINK_TABLE,
        ["removed_at"],
    )
    op.create_index(
        "ix_epcr_multi_patient_link_tenant_chart",
        LINK_TABLE,
        ["tenant_id", "chart_id"],
    )
    op.create_index(
        "ix_epcr_multi_patient_link_tenant_incident",
        LINK_TABLE,
        ["tenant_id", "multi_incident_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_epcr_multi_patient_link_tenant_incident", table_name=LINK_TABLE
    )
    op.drop_index(
        "ix_epcr_multi_patient_link_tenant_chart", table_name=LINK_TABLE
    )
    op.drop_index(
        "ix_epcr_multi_patient_link_removed_at", table_name=LINK_TABLE
    )
    op.drop_index(
        "ix_epcr_multi_patient_link_chart_id", table_name=LINK_TABLE
    )
    op.drop_index(
        "ix_epcr_multi_patient_link_multi_incident_id", table_name=LINK_TABLE
    )
    op.drop_index(
        "ix_epcr_multi_patient_link_tenant_id", table_name=LINK_TABLE
    )
    op.drop_table(LINK_TABLE)

    op.drop_index(
        "ix_epcr_multi_patient_incident_tenant_parent",
        table_name=INCIDENT_TABLE,
    )
    op.drop_index(
        "ix_epcr_multi_patient_incident_parent_incident_number",
        table_name=INCIDENT_TABLE,
    )
    op.drop_index(
        "ix_epcr_multi_patient_incident_tenant_id", table_name=INCIDENT_TABLE
    )
    op.drop_table(INCIDENT_TABLE)
