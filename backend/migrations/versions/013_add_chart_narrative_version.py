"""013 add narrative + version + deleted_at where ORM expects them

Revision ID: 013_chart_narrative_version
Revises: 012_add_fire_incident_links
Create Date: 2026-04-29

The ORM defines `version` (Integer NOT NULL DEFAULT 1) and `deleted_at`
(timestamptz NULL) on most chart-scoped tables, plus `narrative` on
`epcr_charts`, but no migration ever added them to the deployed schema.
This caused `UndefinedColumnError` on every chart fetch, mapping fetch,
export pipeline call, and audit query after a clean rebuild.

This migration introspects each table at runtime and adds only the
columns that are actually missing (idempotent + drift-safe).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "013_chart_narrative_version"
down_revision = "012_add_fire_incident_links"
branch_labels = None
depends_on = None


TABLES_VERSION_AND_DELETED_AT = [
    "epcr_ar_anchors",
    "epcr_ar_sessions",
    "epcr_assessment_findings",
    "epcr_audit_log",
    "epcr_chart_addresses",
    "epcr_clinical_notes",
    "epcr_derived_outputs",
    "epcr_interventions",
    "epcr_medication_administrations",
    "epcr_nemsis_compliance",
    "epcr_nemsis_export_history",
    "epcr_nemsis_mappings",
    "epcr_patient_profiles",
    "epcr_protocol_recommendations",
    "epcr_signature_artifacts",
    "epcr_visual_overlays",
]

TABLES_VERSION_ONLY = [
    "epcr_assessments",
    "epcr_vitals",
]


def _ensure_column(insp, table: str, column_name: str, column: sa.Column) -> None:
    if not insp.has_table(table):
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column_name in cols:
        return
    op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    _ensure_column(insp, "epcr_charts", "narrative", sa.Column("narrative", sa.Text(), nullable=True))
    _ensure_column(
        insp,
        "epcr_charts",
        "version",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )

    for tbl in TABLES_VERSION_AND_DELETED_AT:
        _ensure_column(
            insp,
            tbl,
            "version",
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )
        _ensure_column(
            insp,
            tbl,
            "deleted_at",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    for tbl in TABLES_VERSION_ONLY:
        _ensure_column(
            insp,
            tbl,
            "version",
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    def _drop(table: str, column_name: str) -> None:
        if not insp.has_table(table):
            return
        cols = {c["name"] for c in insp.get_columns(table)}
        if column_name in cols:
            op.drop_column(table, column_name)

    for tbl in TABLES_VERSION_ONLY:
        _drop(tbl, "version")
    for tbl in TABLES_VERSION_AND_DELETED_AT:
        _drop(tbl, "deleted_at")
        _drop(tbl, "version")
    _drop("epcr_charts", "version")
    _drop("epcr_charts", "narrative")
