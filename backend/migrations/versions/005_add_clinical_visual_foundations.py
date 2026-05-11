"""Migration 005: add structured clinical visual assessment foundations.

Creates tables for structured assessment findings, governed visual overlays,
ARCOS sessions, and ARCOS anatomical anchors.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create clinical visual foundation tables."""

    op.create_table(
        "epcr_assessment_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("anatomy", sa.String(length=64), nullable=False),
        sa.Column("system", sa.String(length=64), nullable=False),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("laterality", sa.String(length=32), nullable=True),
        sa.Column("evolution", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("characteristics_json", sa.Text(), nullable=True),
        sa.Column("detection_method", sa.String(length=64), nullable=False),
        sa.Column("review_state", sa.String(length=32), nullable=False, server_default="direct_confirmed"),
        sa.Column("provider_id", sa.String(length=255), nullable=False),
        sa.Column("source_artifact_ids_json", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
    op.create_index("ix_epcr_assessment_findings_chart_id", "epcr_assessment_findings", ["chart_id"])
    op.create_index("ix_epcr_assessment_findings_tenant_id", "epcr_assessment_findings", ["tenant_id"])

    op.create_table(
        "epcr_visual_overlays",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("finding_id", sa.String(length=36), sa.ForeignKey("epcr_assessment_findings.id"), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("patient_model", sa.String(length=32), nullable=False),
        sa.Column("anatomical_view", sa.String(length=32), nullable=False),
        sa.Column("overlay_type", sa.String(length=64), nullable=False),
        sa.Column("anchor_region", sa.String(length=64), nullable=False),
        sa.Column("geometry_reference", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("evolution", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("review_state", sa.String(length=32), nullable=False, server_default="direct_confirmed"),
        sa.Column("provider_id", sa.String(length=255), nullable=False),
        sa.Column("evidence_artifact_ids_json", sa.Text(), nullable=True),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
    op.create_index("ix_epcr_visual_overlays_chart_id", "epcr_visual_overlays", ["chart_id"])
    op.create_index("ix_epcr_visual_overlays_finding_id", "epcr_visual_overlays", ["finding_id"])
    op.create_index("ix_epcr_visual_overlays_tenant_id", "epcr_visual_overlays", ["tenant_id"])

    op.create_table(
        "epcr_ar_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chart_id", sa.String(length=36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("patient_model", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("started_by_user_id", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
    op.create_index("ix_epcr_ar_sessions_chart_id", "epcr_ar_sessions", ["chart_id"])
    op.create_index("ix_epcr_ar_sessions_tenant_id", "epcr_ar_sessions", ["tenant_id"])

    op.create_table(
        "epcr_ar_anchors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("epcr_ar_sessions.id"), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("anatomy", sa.String(length=64), nullable=False),
        sa.Column("anatomical_view", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("anchored_by_user_id", sa.String(length=255), nullable=False),
        sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True)
    op.create_index("ix_epcr_ar_anchors_session_id", "epcr_ar_anchors", ["session_id"])
    op.create_index("ix_epcr_ar_anchors_tenant_id", "epcr_ar_anchors", ["tenant_id"])


def downgrade() -> None:
    """Drop clinical visual foundation tables."""

    op.drop_index("ix_epcr_ar_anchors_tenant_id", table_name="epcr_ar_anchors")
    op.drop_index("ix_epcr_ar_anchors_session_id", table_name="epcr_ar_anchors")
    op.drop_table("epcr_ar_anchors")

    op.drop_index("ix_epcr_ar_sessions_tenant_id", table_name="epcr_ar_sessions")
    op.drop_index("ix_epcr_ar_sessions_chart_id", table_name="epcr_ar_sessions")
    op.drop_table("epcr_ar_sessions")

    op.drop_index("ix_epcr_visual_overlays_tenant_id", table_name="epcr_visual_overlays")
    op.drop_index("ix_epcr_visual_overlays_finding_id", table_name="epcr_visual_overlays")
    op.drop_index("ix_epcr_visual_overlays_chart_id", table_name="epcr_visual_overlays")
    op.drop_table("epcr_visual_overlays")

    op.drop_index("ix_epcr_assessment_findings_tenant_id", table_name="epcr_assessment_findings")
    op.drop_index("ix_epcr_assessment_findings_chart_id", table_name="epcr_assessment_findings")
    op.drop_table("epcr_assessment_findings")
