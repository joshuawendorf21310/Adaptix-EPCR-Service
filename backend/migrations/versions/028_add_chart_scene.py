"""028 add epcr_chart_scene and epcr_chart_scene_other_agencies.

Revision ID: 028
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 eScene child tables for charts:

* ``epcr_chart_scene`` (1:1) — the once-per-chart scene metadata
  covering eScene.01, .05..23 (minus the multi-row group).
* ``epcr_chart_scene_other_agencies`` (1:M) — the repeating "Other EMS or
  Public Safety Agencies at Scene" group (eScene.02/.03/.04/.24/.25).

All eScene columns are nullable; the chart-finalization gate enforces
the Required-at-National subset via the registry-driven validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "028"
down_revision = "023"
branch_labels = None
depends_on = None


SCENE_TABLE = "epcr_chart_scene"
AGENCIES_TABLE = "epcr_chart_scene_other_agencies"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, SCENE_TABLE):
        op.create_table(
            SCENE_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("first_ems_unit_indicator_code", sa.String(16), nullable=True),
            sa.Column(
                "initial_responder_arrived_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("number_of_patients", sa.Integer(), nullable=True),
            sa.Column("mci_indicator_code", sa.String(16), nullable=True),
            sa.Column("mci_triage_classification_code", sa.String(16), nullable=True),
            sa.Column("incident_location_type_code", sa.String(16), nullable=True),
            sa.Column("incident_facility_code", sa.String(64), nullable=True),
            sa.Column("scene_lat", sa.Float(), nullable=True),
            sa.Column("scene_long", sa.Float(), nullable=True),
            sa.Column("scene_usng", sa.String(64), nullable=True),
            sa.Column("incident_facility_name", sa.String(255), nullable=True),
            sa.Column("mile_post_or_major_roadway", sa.String(255), nullable=True),
            sa.Column("incident_street_address", sa.String(255), nullable=True),
            sa.Column("incident_apartment", sa.String(64), nullable=True),
            sa.Column("incident_city", sa.String(120), nullable=True),
            sa.Column("incident_state", sa.String(8), nullable=True),
            sa.Column("incident_zip", sa.String(16), nullable=True),
            sa.Column("scene_cross_street", sa.String(255), nullable=True),
            sa.Column("incident_county", sa.String(120), nullable=True),
            sa.Column(
                "incident_country",
                sa.String(8),
                nullable=True,
                server_default=sa.text("'US'"),
            ),
            sa.Column("incident_census_tract", sa.String(32), nullable=True),
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
            sa.Column(
                "version", sa.Integer(), nullable=False, server_default=sa.text("1")
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                name="uq_epcr_chart_scene_tenant_chart",
            ),
        if_not_exists=True)

    if not _has_index(insp, SCENE_TABLE, "ix_epcr_chart_scene_tenant_id"):
        op.create_index(
            "ix_epcr_chart_scene_tenant_id", SCENE_TABLE, ["tenant_id"]
        )
    if not _has_index(insp, SCENE_TABLE, "ix_epcr_chart_scene_chart_id"):
        op.create_index(
            "ix_epcr_chart_scene_chart_id", SCENE_TABLE, ["chart_id"]
        )

    if not _has_table(insp, AGENCIES_TABLE):
        op.create_table(
            AGENCIES_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("agency_id", sa.String(64), nullable=False),
            sa.Column("other_service_type_code", sa.String(16), nullable=False),
            sa.Column(
                "first_to_provide_patient_care_indicator",
                sa.String(16),
                nullable=True,
            ),
            sa.Column("patient_care_handoff_code", sa.String(16), nullable=True),
            sa.Column(
                "sequence_index",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
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
            sa.Column(
                "version", sa.Integer(), nullable=False, server_default=sa.text("1")
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "agency_id",
                name="uq_epcr_chart_scene_other_agencies_tenant_chart_agency",
            ),
        if_not_exists=True)

    if not _has_index(
        insp, AGENCIES_TABLE, "ix_epcr_chart_scene_other_agencies_tenant_id"
    ):
        op.create_index(
            "ix_epcr_chart_scene_other_agencies_tenant_id",
            AGENCIES_TABLE,
            ["tenant_id"],
        )
    if not _has_index(
        insp, AGENCIES_TABLE, "ix_epcr_chart_scene_other_agencies_chart_id"
    ):
        op.create_index(
            "ix_epcr_chart_scene_other_agencies_chart_id",
            AGENCIES_TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(
        insp, AGENCIES_TABLE, "ix_epcr_chart_scene_other_agencies_chart_id"
    ):
        op.drop_index(
            "ix_epcr_chart_scene_other_agencies_chart_id", table_name=AGENCIES_TABLE
        )
    if _has_index(
        insp, AGENCIES_TABLE, "ix_epcr_chart_scene_other_agencies_tenant_id"
    ):
        op.drop_index(
            "ix_epcr_chart_scene_other_agencies_tenant_id", table_name=AGENCIES_TABLE
        )
    if _has_table(insp, AGENCIES_TABLE):
        op.drop_table(AGENCIES_TABLE)

    if _has_index(insp, SCENE_TABLE, "ix_epcr_chart_scene_chart_id"):
        op.drop_index("ix_epcr_chart_scene_chart_id", table_name=SCENE_TABLE)
    if _has_index(insp, SCENE_TABLE, "ix_epcr_chart_scene_tenant_id"):
        op.drop_index("ix_epcr_chart_scene_tenant_id", table_name=SCENE_TABLE)
    if _has_table(insp, SCENE_TABLE):
        op.drop_table(SCENE_TABLE)
