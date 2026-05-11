"""Add CareGraph, CPAE, VAS, Vision, Critical Care, Terminology, Sync, Dashboard tables.

Revision ID: 015
Revises: 014_recreate_nemsis_export_lifecycle
Create Date: 2026-05-03

This migration adds all tables for:
- CareGraph clinical truth graph (nodes, edges, OPQRST, reassessment deltas, audit events)
- CPAE physical assessment engine (regions, systems, findings, characteristics, reassessments,
  evidence links, intervention links, response links, NEMSIS links, audit events)
- VAS visual assessment system (models, regions, overlays v2, overlay versions, finding links,
  reassessment snapshots, intervention response links, projection reviews, audit events)
- Vision integration layer (artifacts, versions, ingestion jobs, extraction runs, extractions,
  classifications, bounding regions, annotations, review queue, review actions, provenance,
  model versions, chart links, quality flags, duplicate clusters)
- Critical care engine (devices, infusion runs, ventilator sessions, blood products,
  response windows, intents, indications, contraindications, protocol links,
  terminology bindings, NEMSIS links)
- Terminology fabric (SNOMED, ICD-10, RxNorm, NEMSIS value sets, regex rules,
  impression bindings, differential impressions, version metadata)
- Offline sync engine (event log, conflicts, upload queue, sync health, audit envelopes)
- Dashboard/customization (dashboard profiles, card preferences, favorites, theme settings,
  recent actions, workspace profiles, agency workflow configs)
"""
from alembic import op
import sqlalchemy as sa


revision = "015"
down_revision = "014_recreate_nemsis_export_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # CAREGRAPH
    # =========================================================================

    op.create_table(
        "epcr_caregraph_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("evidence_strength", sa.String(32), nullable=False, server_default="confirmed"),
        sa.Column("evidence_source_ids_json", sa.Text, nullable=True),
        sa.Column("provenance_json", sa.Text, nullable=True),
        sa.Column("snomed_code", sa.String(32), nullable=True),
        sa.Column("snomed_display", sa.String(255), nullable=True),
        sa.Column("icd10_code", sa.String(32), nullable=True),
        sa.Column("icd10_display", sa.String(255), nullable=True),
        sa.Column("rxnorm_code", sa.String(32), nullable=True),
        sa.Column("rxnorm_display", sa.String(255), nullable=True),
        sa.Column("nemsis_element", sa.String(64), nullable=True),
        sa.Column("nemsis_value", sa.String(255), nullable=True),
        sa.Column("clinical_payload_json", sa.Text, nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("provider_role", sa.String(64), nullable=True),
        sa.Column("sync_state", sa.String(32), nullable=False, server_default="clean"),
        sa.Column("local_sequence_number", sa.Integer, nullable=True),
        sa.Column("device_id", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    op.create_index("ix_epcr_caregraph_nodes_chart_id", "epcr_caregraph_nodes", ["chart_id"])
    op.create_index("ix_epcr_caregraph_nodes_tenant_id", "epcr_caregraph_nodes", ["tenant_id"])
    op.create_index("ix_epcr_caregraph_nodes_node_type", "epcr_caregraph_nodes", ["node_type"])

    op.create_table(
        "epcr_caregraph_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("source_node_id", sa.String(36), sa.ForeignKey("epcr_caregraph_nodes.id"), nullable=False),
        sa.Column("target_node_id", sa.String(36), sa.ForeignKey("epcr_caregraph_nodes.id"), nullable=False),
        sa.Column("edge_type", sa.String(64), nullable=False),
        sa.Column("weight", sa.Float, nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    op.create_index("ix_epcr_caregraph_edges_chart_id", "epcr_caregraph_edges", ["chart_id"])
    op.create_index("ix_epcr_caregraph_edges_source_node_id", "epcr_caregraph_edges", ["source_node_id"])
    op.create_index("ix_epcr_caregraph_edges_target_node_id", "epcr_caregraph_edges", ["target_node_id"])

    op.create_table(
        "epcr_opqrst_symptoms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("caregraph_node_id", sa.String(36), nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("symptom_category", sa.String(64), nullable=False),
        sa.Column("symptom_label", sa.String(255), nullable=False),
        sa.Column("onset_description", sa.String(500), nullable=True),
        sa.Column("onset_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onset_sudden", sa.Boolean, nullable=True),
        sa.Column("provocation_factors_json", sa.Text, nullable=True),
        sa.Column("palliation_factors_json", sa.Text, nullable=True),
        sa.Column("quality_descriptors_json", sa.Text, nullable=True),
        sa.Column("radiation_present", sa.Boolean, nullable=True),
        sa.Column("radiation_locations_json", sa.Text, nullable=True),
        sa.Column("region_primary", sa.String(64), nullable=True),
        sa.Column("region_secondary_json", sa.Text, nullable=True),
        sa.Column("severity_scale", sa.Integer, nullable=True),
        sa.Column("severity_functional_impact", sa.String(255), nullable=True),
        sa.Column("time_duration_minutes", sa.Integer, nullable=True),
        sa.Column("time_progression", sa.String(64), nullable=True),
        sa.Column("time_prior_episodes", sa.Boolean, nullable=True),
        sa.Column("time_last_episode_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("associated_symptoms_json", sa.Text, nullable=True),
        sa.Column("baseline_comparison", sa.String(255), nullable=True),
        sa.Column("recurrence_pattern", sa.String(255), nullable=True),
        sa.Column("witness_context", sa.String(500), nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("documented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    op.create_index("ix_epcr_opqrst_symptoms_chart_id", "epcr_opqrst_symptoms", ["chart_id"])

    op.create_table(
        "epcr_reassessment_deltas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("prior_node_id", sa.String(36), sa.ForeignKey("epcr_caregraph_nodes.id"), nullable=False),
        sa.Column("reassessment_node_id", sa.String(36), sa.ForeignKey("epcr_caregraph_nodes.id"), nullable=False),
        sa.Column("delta_type", sa.String(64), nullable=False),
        sa.Column("delta_description", sa.Text, nullable=False),
        sa.Column("delta_payload_json", sa.Text, nullable=True),
        sa.Column("intervention_trigger_id", sa.String(36), nullable=True),
        sa.Column("reassessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_caregraph_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("actor_role", sa.String(64), nullable=True),
        sa.Column("device_id", sa.String(64), nullable=True),
        sa.Column("before_state_json", sa.Text, nullable=True),
        sa.Column("after_state_json", sa.Text, nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sync_sequence", sa.Integer, nullable=True),
        if_not_exists=True)
    op.create_index("ix_epcr_caregraph_audit_events_chart_id", "epcr_caregraph_audit_events", ["chart_id"])
    op.create_index("ix_epcr_caregraph_audit_events_entity_id", "epcr_caregraph_audit_events", ["entity_id"])

    # =========================================================================
    # CPAE
    # =========================================================================

    op.create_table(
        "epcr_assessment_regions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("region_code", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("parent_region_code", sa.String(64), nullable=True),
        sa.Column("supports_laterality", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("nemsis_body_site_code", sa.String(32), nullable=True),
        sa.Column("snomed_code", sa.String(32), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_physiologic_systems",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_code", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("nemsis_section_hint", sa.String(64), nullable=True),
        sa.Column("snomed_code", sa.String(32), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_physical_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("caregraph_node_id", sa.String(36), nullable=True),
        sa.Column("anatomy", sa.String(64), nullable=False),
        sa.Column("physiologic_system", sa.String(64), nullable=False),
        sa.Column("finding_class", sa.String(64), nullable=False),
        sa.Column("laterality", sa.String(32), nullable=True),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("finding_label", sa.String(255), nullable=False),
        sa.Column("finding_description", sa.Text, nullable=True),
        sa.Column("characteristics_json", sa.Text, nullable=True),
        sa.Column("detection_method", sa.String(64), nullable=False),
        sa.Column("review_state", sa.String(64), nullable=False, server_default="direct_confirmed"),
        sa.Column("snomed_code", sa.String(32), nullable=True),
        sa.Column("snomed_display", sa.String(255), nullable=True),
        sa.Column("nemsis_exam_element", sa.String(64), nullable=True),
        sa.Column("nemsis_exam_value", sa.String(255), nullable=True),
        sa.Column("has_contradiction", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("contradiction_detail", sa.Text, nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("source_artifact_ids_json", sa.Text, nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    op.create_index("ix_epcr_physical_findings_chart_id", "epcr_physical_findings", ["chart_id"])
    op.create_index("ix_epcr_physical_findings_anatomy", "epcr_physical_findings", ["anatomy"])
    op.create_index("ix_epcr_physical_findings_physiologic_system", "epcr_physical_findings", ["physiologic_system"])

    op.create_table(
        "epcr_finding_characteristics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("epcr_physical_findings.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("characteristic_key", sa.String(64), nullable=False),
        sa.Column("characteristic_value", sa.String(255), nullable=False),
        sa.Column("characteristic_unit", sa.String(32), nullable=True),
        sa.Column("snomed_code", sa.String(32), nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_finding_reassessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("epcr_physical_findings.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("caregraph_reassessment_node_id", sa.String(36), nullable=True),
        sa.Column("evolution", sa.String(32), nullable=False),
        sa.Column("severity_at_reassessment", sa.String(32), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("characteristics_json", sa.Text, nullable=True),
        sa.Column("intervention_trigger_id", sa.String(36), nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("reassessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_finding_evidence_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("epcr_physical_findings.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.Column("evidence_description", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_finding_intervention_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("epcr_physical_findings.id"), nullable=False),
        sa.Column("intervention_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("link_rationale", sa.Text, nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_finding_response_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("epcr_physical_findings.id"), nullable=False),
        sa.Column("response_node_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("response_description", sa.Text, nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_finding_nemsis_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("epcr_physical_findings.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("nemsis_section", sa.String(32), nullable=False),
        sa.Column("nemsis_element", sa.String(64), nullable=False),
        sa.Column("nemsis_value", sa.String(255), nullable=False),
        sa.Column("xml_path", sa.String(255), nullable=True),
        sa.Column("export_ready", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("export_blocker_reason", sa.Text, nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_finding_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("epcr_physical_findings.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("before_state_json", sa.Text, nullable=True),
        sa.Column("after_state_json", sa.Text, nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    # =========================================================================
    # VAS
    # =========================================================================

    op.create_table(
        "epcr_visual_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_type", sa.String(32), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("available_views_json", sa.Text, nullable=False),
        sa.Column("supported_overlays_json", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_visual_regions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_type", sa.String(32), nullable=False),
        sa.Column("anatomical_view", sa.String(32), nullable=False),
        sa.Column("region_code", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("cpae_anatomy_code", sa.String(64), nullable=True),
        sa.Column("default_geometry_json", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_visual_overlays_v2",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("physical_finding_id", sa.String(36), nullable=False),
        sa.Column("caregraph_node_id", sa.String(36), nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("patient_model", sa.String(32), nullable=False),
        sa.Column("anatomical_view", sa.String(32), nullable=False),
        sa.Column("overlay_type", sa.String(64), nullable=False),
        sa.Column("anchor_region", sa.String(64), nullable=False),
        sa.Column("geometry_json", sa.Text, nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("evolution", sa.String(32), nullable=False, server_default="new"),
        sa.Column("review_state", sa.String(64), nullable=False, server_default="direct_confirmed"),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("evidence_artifact_ids_json", sa.Text, nullable=True),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    op.create_index("ix_epcr_visual_overlays_v2_chart_id", "epcr_visual_overlays_v2", ["chart_id"])

    op.create_table(
        "epcr_visual_overlay_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("overlay_id", sa.String(36), sa.ForeignKey("epcr_visual_overlays_v2.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("geometry_json", sa.Text, nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("evolution", sa.String(32), nullable=False),
        sa.Column("snapshot_reason", sa.String(64), nullable=False),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "epcr_visual_finding_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("overlay_id", sa.String(36), nullable=False),
        sa.Column("finding_id", sa.String(36), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("link_type", sa.String(64), nullable=False, server_default="primary"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "epcr_visual_reassessment_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("overlay_id", sa.String(36), sa.ForeignKey("epcr_visual_overlays_v2.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("snapshot_type", sa.String(64), nullable=False),
        sa.Column("full_state_json", sa.Text, nullable=False),
        sa.Column("delta_from_prior_json", sa.Text, nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_visual_intervention_response_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("overlay_id", sa.String(36), sa.ForeignKey("epcr_visual_overlays_v2.id"), nullable=False),
        sa.Column("intervention_id", sa.String(36), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("response_description", sa.Text, nullable=False),
        sa.Column("visual_change_json", sa.Text, nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "epcr_visual_projection_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("vision_artifact_id", sa.String(36), nullable=False),
        sa.Column("proposed_overlay_json", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("review_state", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("reviewer_id", sa.String(255), nullable=True),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("accepted_overlay_id", sa.String(36), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_visual_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("overlay_id", sa.String(36), sa.ForeignKey("epcr_visual_overlays_v2.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("before_state_json", sa.Text, nullable=True),
        sa.Column("after_state_json", sa.Text, nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    # =========================================================================
    # VISION
    # =========================================================================

    op.create_table(
        "vision_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("ingestion_source", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("storage_bucket", sa.String(128), nullable=True),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column("source_hash_sha256", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.Column("uploaded_by_user_id", sa.String(255), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    op.create_index("ix_vision_artifacts_chart_id", "vision_artifacts", ["chart_id"])
    op.create_index("ix_vision_artifacts_source_hash", "vision_artifacts", ["source_hash_sha256"])

    op.create_table(
        "vision_artifact_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("vision_artifacts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("source_hash_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("created_by_user_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "vision_ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("vision_artifacts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("pipeline_version", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "vision_extraction_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("vision_ingestion_jobs.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("extraction_type", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("raw_output_json", sa.Text, nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "vision_extractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("vision_artifacts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("proposal_target", sa.String(64), nullable=False),
        sa.Column("extracted_value_json", sa.Text, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("source_hash_sha256", sa.String(64), nullable=False),
        sa.Column("review_state", sa.String(64), nullable=False, server_default="pending_review"),
        sa.Column("reviewer_id", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("edited_value_json", sa.Text, nullable=True),
        sa.Column("accepted_chart_field", sa.String(128), nullable=True),
        sa.Column("accepted_chart_record_id", sa.String(36), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "vision_classifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("vision_artifacts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("review_state", sa.String(64), nullable=False, server_default="pending_review"),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "vision_bounding_regions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("extraction_id", sa.String(36), sa.ForeignKey("vision_extractions.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("x", sa.Float, nullable=False),
        sa.Column("y", sa.Float, nullable=False),
        sa.Column("width", sa.Float, nullable=False),
        sa.Column("height", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        if_not_exists=True)

    op.create_table(
        "vision_annotations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("extraction_id", sa.String(36), sa.ForeignKey("vision_extractions.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("annotation_type", sa.String(64), nullable=False),
        sa.Column("annotation_value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        if_not_exists=True)

    op.create_table(
        "vision_review_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("extraction_id", sa.String(36), sa.ForeignKey("vision_extractions.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="5"),
        sa.Column("assigned_to_user_id", sa.String(255), nullable=True),
        sa.Column("queue_state", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("escalation_reason", sa.Text, nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "vision_review_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("queue_entry_id", sa.String(36), sa.ForeignKey("vision_review_queue.id"), nullable=False),
        sa.Column("extraction_id", sa.String(36), sa.ForeignKey("vision_extractions.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("edited_value_json", sa.Text, nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "vision_provenance_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("extraction_id", sa.String(36), sa.ForeignKey("vision_extractions.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("provenance_type", sa.String(64), nullable=False),
        sa.Column("provenance_detail_json", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "vision_model_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("capabilities_json", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "vision_chart_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("vision_artifacts.id"), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("link_reason", sa.String(128), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "vision_quality_flags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("vision_artifacts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("flag_type", sa.String(64), nullable=False),
        sa.Column("flag_detail", sa.Text, nullable=True),
        sa.Column("severity", sa.String(32), nullable=False, server_default="warning"),
        sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.String(255), nullable=True),
        if_not_exists=True)

    op.create_table(
        "vision_duplicate_clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("artifact_ids_json", sa.Text, nullable=False),
        sa.Column("similarity_score", sa.Float, nullable=False),
        sa.Column("resolution_state", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("resolved_by_user_id", sa.String(255), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    # =========================================================================
    # CRITICAL CARE
    # =========================================================================

    op.create_table(
        "epcr_critical_care_devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("caregraph_node_id", sa.String(36), nullable=True),
        sa.Column("device_type", sa.String(64), nullable=False),
        sa.Column("device_name", sa.String(128), nullable=False),
        sa.Column("device_model", sa.String(128), nullable=True),
        sa.Column("device_serial", sa.String(64), nullable=True),
        sa.Column("initial_settings_json", sa.Text, nullable=True),
        sa.Column("current_settings_json", sa.Text, nullable=True),
        sa.Column("settings_change_log_json", sa.Text, nullable=True),
        sa.Column("received_from_facility", sa.String(255), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_to_facility", sa.String(255), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("continuity_notes", sa.Text, nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("documented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_infusion_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("caregraph_node_id", sa.String(36), nullable=True),
        sa.Column("medication_name", sa.String(128), nullable=False),
        sa.Column("rxnorm_code", sa.String(32), nullable=True),
        sa.Column("concentration", sa.String(64), nullable=True),
        sa.Column("concentration_unit", sa.String(32), nullable=True),
        sa.Column("initial_rate_value", sa.Float, nullable=False),
        sa.Column("initial_rate_unit", sa.String(32), nullable=False),
        sa.Column("initial_dose_value", sa.Float, nullable=True),
        sa.Column("initial_dose_unit", sa.String(32), nullable=True),
        sa.Column("titration_log_json", sa.Text, nullable=True),
        sa.Column("indication", sa.Text, nullable=False),
        sa.Column("protocol_family", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(255), nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_ventilator_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("device_id", sa.String(36), nullable=True),
        sa.Column("caregraph_node_id", sa.String(36), nullable=True),
        sa.Column("mode", sa.String(64), nullable=False),
        sa.Column("tidal_volume_ml", sa.Integer, nullable=True),
        sa.Column("respiratory_rate", sa.Integer, nullable=True),
        sa.Column("fio2_percent", sa.Integer, nullable=True),
        sa.Column("peep_cmh2o", sa.Float, nullable=True),
        sa.Column("inspiratory_pressure_cmh2o", sa.Float, nullable=True),
        sa.Column("inspiratory_time_seconds", sa.Float, nullable=True),
        sa.Column("flow_rate_lpm", sa.Float, nullable=True),
        sa.Column("pressure_support_cmh2o", sa.Float, nullable=True),
        sa.Column("peak_pressure_cmh2o", sa.Float, nullable=True),
        sa.Column("plateau_pressure_cmh2o", sa.Float, nullable=True),
        sa.Column("minute_ventilation_lpm", sa.Float, nullable=True),
        sa.Column("etco2_mmhg", sa.Float, nullable=True),
        sa.Column("settings_change_log_json", sa.Text, nullable=True),
        sa.Column("airway_type", sa.String(64), nullable=True),
        sa.Column("ett_size_mm", sa.Float, nullable=True),
        sa.Column("ett_depth_cm", sa.Float, nullable=True),
        sa.Column("cuff_pressure_cmh2o", sa.Float, nullable=True),
        sa.Column("indication", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_blood_product_administrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("caregraph_node_id", sa.String(36), nullable=True),
        sa.Column("product_type", sa.String(64), nullable=False),
        sa.Column("unit_number", sa.String(64), nullable=True),
        sa.Column("blood_type", sa.String(16), nullable=True),
        sa.Column("volume_ml", sa.Integer, nullable=True),
        sa.Column("rate_ml_per_hr", sa.Float, nullable=True),
        sa.Column("indication", sa.Text, nullable=False),
        sa.Column("pre_transfusion_hgb", sa.Float, nullable=True),
        sa.Column("pre_transfusion_hct", sa.Float, nullable=True),
        sa.Column("reaction_observed", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("reaction_description", sa.Text, nullable=True),
        sa.Column("reaction_intervention", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    op.create_table(
        "epcr_response_windows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
        sa.Column("intervention_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("caregraph_node_id", sa.String(36), nullable=True),
        sa.Column("expected_response", sa.Text, nullable=False),
        sa.Column("expected_response_window_minutes", sa.Integer, nullable=True),
        sa.Column("actual_response", sa.Text, nullable=True),
        sa.Column("response_availability", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("unavailability_reason", sa.Text, nullable=True),
        sa.Column("response_adequate", sa.Boolean, nullable=True),
        sa.Column("escalation_triggered", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("escalation_detail", sa.Text, nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)

    for tbl, cols in [
        ("epcr_intervention_intents", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intervention_id", sa.String(36), nullable=False),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("intent_category", sa.String(64), nullable=False),
            sa.Column("intent_description", sa.Text, nullable=False),
            sa.Column("clinical_goal", sa.Text, nullable=True),
            sa.Column("target_parameter", sa.String(128), nullable=True),
            sa.Column("target_value", sa.String(64), nullable=True),
            sa.Column("provider_id", sa.String(255), nullable=False),
            sa.Column("documented_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("epcr_intervention_indications", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intervention_id", sa.String(36), nullable=False),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("indication_label", sa.String(255), nullable=False),
            sa.Column("snomed_code", sa.String(32), nullable=True),
            sa.Column("icd10_code", sa.String(32), nullable=True),
            sa.Column("evidence_node_ids_json", sa.Text, nullable=True),
            sa.Column("provider_id", sa.String(255), nullable=False),
            sa.Column("documented_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("epcr_intervention_contraindications", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intervention_id", sa.String(36), nullable=False),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("contraindication_label", sa.String(255), nullable=False),
            sa.Column("contraindication_present", sa.Boolean, nullable=False),
            sa.Column("override_reason", sa.Text, nullable=True),
            sa.Column("override_authorized_by", sa.String(255), nullable=True),
            sa.Column("provider_id", sa.String(255), nullable=False),
            sa.Column("documented_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("epcr_intervention_protocol_links", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intervention_id", sa.String(36), nullable=False),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("protocol_family", sa.String(64), nullable=False),
            sa.Column("protocol_name", sa.String(255), nullable=False),
            sa.Column("protocol_version", sa.String(64), nullable=True),
            sa.Column("protocol_step", sa.String(128), nullable=True),
            sa.Column("deviation_present", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("deviation_reason", sa.Text, nullable=True),
            sa.Column("provider_id", sa.String(255), nullable=False),
            sa.Column("documented_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("epcr_intervention_terminology_bindings", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intervention_id", sa.String(36), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("terminology_system", sa.String(32), nullable=False),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("display", sa.String(255), nullable=True),
            sa.Column("binding_confidence", sa.String(32), nullable=False, server_default="confirmed"),
            sa.Column("source", sa.String(64), nullable=True),
        ]),
        ("epcr_intervention_nemsis_links", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intervention_id", sa.String(36), nullable=False),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("nemsis_section", sa.String(32), nullable=False),
            sa.Column("nemsis_element", sa.String(64), nullable=False),
            sa.Column("nemsis_value", sa.String(255), nullable=False),
            sa.Column("xml_path", sa.String(255), nullable=True),
            sa.Column("export_ready", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("export_blocker_reason", sa.Text, nullable=True),
        ]),
    ]:
        op.create_table(tbl, *cols,
        if_not_exists=True)

    # =========================================================================
    # TERMINOLOGY
    # =========================================================================

    for tbl, cols in [
        ("ref_snomed_concepts", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("concept_id", sa.String(32), unique=True, nullable=False),
            sa.Column("fsn", sa.String(512), nullable=False),
            sa.Column("preferred_term", sa.String(512), nullable=False),
            sa.Column("semantic_tag", sa.String(128), nullable=True),
            sa.Column("hierarchy_code", sa.String(32), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("version_date", sa.String(32), nullable=False),
            sa.Column("source_artifact_version", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("ref_icd10_codes", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("code", sa.String(16), unique=True, nullable=False),
            sa.Column("description", sa.String(512), nullable=False),
            sa.Column("category_code", sa.String(8), nullable=True),
            sa.Column("category_description", sa.String(512), nullable=True),
            sa.Column("is_billable", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("fiscal_year", sa.String(16), nullable=False),
            sa.Column("source_artifact_version", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("ref_rxnorm_concepts", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("rxcui", sa.String(16), unique=True, nullable=False),
            sa.Column("name", sa.String(512), nullable=False),
            sa.Column("tty", sa.String(32), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("version_date", sa.String(32), nullable=False),
            sa.Column("source_artifact_version", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("ref_nemsis_value_sets", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("element_number", sa.String(32), nullable=False),
            sa.Column("element_name", sa.String(255), nullable=False),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("display", sa.String(512), nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("nemsis_version", sa.String(16), nullable=False, server_default="3.5.1"),
            sa.Column("source_artifact_version", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("ref_nemsis_regex_rules", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("element_number", sa.String(32), unique=True, nullable=False),
            sa.Column("element_name", sa.String(255), nullable=False),
            sa.Column("regex_pattern", sa.String(512), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("nemsis_version", sa.String(16), nullable=False, server_default="3.5.1"),
            sa.Column("source_artifact_version", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("ref_terminology_versions", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("terminology_system", sa.String(32), nullable=False),
            sa.Column("version_identifier", sa.String(64), nullable=False),
            sa.Column("release_date", sa.String(32), nullable=True),
            sa.Column("record_count", sa.Integer, nullable=True),
            sa.Column("is_current", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("loaded_by", sa.String(255), nullable=True),
            sa.Column("source_artifact_path", sa.String(512), nullable=True),
        ]),
        ("epcr_impression_bindings", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("caregraph_node_id", sa.String(36), nullable=True),
            sa.Column("impression_class", sa.String(64), nullable=False),
            sa.Column("adaptix_label", sa.String(255), nullable=False),
            sa.Column("snomed_code", sa.String(32), nullable=True),
            sa.Column("snomed_display", sa.String(512), nullable=True),
            sa.Column("snomed_confidence", sa.String(32), nullable=True),
            sa.Column("icd10_code", sa.String(16), nullable=True),
            sa.Column("icd10_display", sa.String(512), nullable=True),
            sa.Column("icd10_confidence", sa.String(32), nullable=True),
            sa.Column("nemsis_element", sa.String(64), nullable=True),
            sa.Column("nemsis_value", sa.String(64), nullable=True),
            sa.Column("nemsis_export_valid", sa.Boolean, nullable=True),
            sa.Column("nemsis_export_blocker", sa.Text, nullable=True),
            sa.Column("evidence_node_ids_json", sa.Text, nullable=True),
            sa.Column("provenance_json", sa.Text, nullable=True),
            sa.Column("is_ai_suggested", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("review_state", sa.String(64), nullable=False, server_default="direct_confirmed"),
            sa.Column("reviewer_id", sa.String(255), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_id", sa.String(255), nullable=False),
            sa.Column("documented_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ]),
        ("epcr_differential_impressions", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("chart_id", sa.String(36), sa.ForeignKey("epcr_charts.id"), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("impression_binding_id", sa.String(36), nullable=True),
            sa.Column("adaptix_label", sa.String(255), nullable=False),
            sa.Column("snomed_code", sa.String(32), nullable=True),
            sa.Column("icd10_code", sa.String(16), nullable=True),
            sa.Column("differential_state", sa.String(64), nullable=False, server_default="active"),
            sa.Column("ruling_out_evidence_json", sa.Text, nullable=True),
            sa.Column("ruling_out_reason", sa.Text, nullable=True),
            sa.Column("provider_id", sa.String(255), nullable=False),
            sa.Column("documented_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ]),
    ]:
        op.create_table(tbl, *cols,
        if_not_exists=True)

    # =========================================================================
    # SYNC ENGINE
    # =========================================================================

    op.create_table(
        "epcr_sync_event_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("chart_id", sa.String(36), nullable=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_payload_json", sa.Text, nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("local_sequence_number", sa.Integer, nullable=False),
        sa.Column("device_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("upload_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_upload_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("idempotency_key", sa.String(64), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)
    op.create_index("ix_epcr_sync_event_log_device_id", "epcr_sync_event_log", ["device_id"])
    op.create_index("ix_epcr_sync_event_log_status", "epcr_sync_event_log", ["status"])

    op.create_table(
        "epcr_sync_conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("chart_id", sa.String(36), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("sync_event_id", sa.String(36), sa.ForeignKey("epcr_sync_event_log.id"), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("client_state_json", sa.Text, nullable=False),
        sa.Column("server_state_json", sa.Text, nullable=False),
        sa.Column("conflict_fields_json", sa.Text, nullable=False),
        sa.Column("resolution_strategy", sa.String(64), nullable=True),
        sa.Column("resolved_state_json", sa.Text, nullable=True),
        sa.Column("resolved_by_user_id", sa.String(255), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_upload_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("chart_id", sa.String(36), nullable=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("upload_type", sa.String(64), nullable=False),
        sa.Column("local_path", sa.String(512), nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("source_hash_sha256", sa.String(64), nullable=False),
        sa.Column("upload_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("bytes_uploaded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("upload_session_id", sa.String(255), nullable=True),
        sa.Column("upload_url", sa.String(512), nullable=True),
        sa.Column("upload_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("idempotency_key", sa.String(64), unique=True, nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_sync_health",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("device_id", sa.String(64), unique=True, nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("health_state", sa.String(32), nullable=False, server_default="healthy"),
        sa.Column("pending_events_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_events_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pending_uploads_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_uploads_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unresolved_conflicts_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_detail", sa.Text, nullable=True),
        sa.Column("is_degraded", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("degraded_reason", sa.String(255), nullable=True),
        sa.Column("degraded_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    op.create_table(
        "epcr_audit_envelopes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("chart_id", sa.String(36), nullable=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("audit_events_json", sa.Text, nullable=False),
        sa.Column("event_count", sa.Integer, nullable=False),
        sa.Column("sequence_start", sa.Integer, nullable=False),
        sa.Column("sequence_end", sa.Integer, nullable=False),
        sa.Column("upload_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(64), unique=True, nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

    # =========================================================================
    # DASHBOARD / CUSTOMIZATION
    # =========================================================================

    op.create_table(
        "epcr_user_dashboard_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("profile_name", sa.String(128), nullable=False, server_default="default"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("card_order_json", sa.Text, nullable=True),
        sa.Column("hidden_cards_json", sa.Text, nullable=True),
        sa.Column("density", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("theme_mode", sa.String(32), nullable=False, server_default="system"),
        sa.Column("accent_color", sa.String(16), nullable=True),
        sa.Column("custom_theme_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        if_not_exists=True)

    op.create_table(
        "epcr_dashboard_card_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("epcr_user_dashboard_profiles.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("card_type", sa.String(64), nullable=False),
        sa.Column("is_visible", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("config_json", sa.Text, nullable=True),
        if_not_exists=True)

    for tbl, cols in [
        ("epcr_user_favorites", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("favorite_type", sa.String(64), nullable=False),
            sa.Column("favorite_key", sa.String(255), nullable=False),
            sa.Column("display_label", sa.String(255), nullable=False),
            sa.Column("metadata_json", sa.Text, nullable=True),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("use_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("epcr_user_theme_settings", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(255), unique=True, nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("theme_mode", sa.String(32), nullable=False, server_default="system"),
            sa.Column("accent_color", sa.String(16), nullable=True),
            sa.Column("font_size_scale", sa.Float, nullable=False, server_default="1.0"),
            sa.Column("high_contrast_enabled", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("reduce_motion", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("glove_mode", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        ]),
        ("epcr_user_recent_actions", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("action_type", sa.String(64), nullable=False),
            sa.Column("action_key", sa.String(255), nullable=False),
            sa.Column("display_label", sa.String(255), nullable=False),
            sa.Column("context_json", sa.Text, nullable=True),
            sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        ]),
        ("epcr_workspace_profiles", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(255), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("profile_type", sa.String(64), nullable=False),
            sa.Column("profile_name", sa.String(128), nullable=False),
            sa.Column("is_default", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("visible_sections_json", sa.Text, nullable=True),
            sa.Column("expanded_panels_json", sa.Text, nullable=True),
            sa.Column("quick_access_items_json", sa.Text, nullable=True),
            sa.Column("critical_care_mode", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("show_ventilator_panel", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("show_infusion_panel", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("show_device_continuity_panel", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        ]),
        ("epcr_agency_workflow_configs", [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), unique=True, nullable=False),
            sa.Column("additional_required_fields_json", sa.Text, nullable=True),
            sa.Column("enabled_protocol_families_json", sa.Text, nullable=True),
            sa.Column("default_protocol_family", sa.String(64), nullable=True),
            sa.Column("require_opqrst_for_pain", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("require_reassessment_after_intervention", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("require_response_documentation", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("require_bilateral_assessment", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("state_code", sa.String(8), nullable=True),
            sa.Column("agency_number", sa.String(32), nullable=True),
            sa.Column("custom_nemsis_fields_json", sa.Text, nullable=True),
            sa.Column("updated_by", sa.String(255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        ]),
    ]:
        op.create_table(tbl, *cols,
        if_not_exists=True)


def downgrade() -> None:
    tables_to_drop = [
        # Dashboard
        "epcr_agency_workflow_configs",
        "epcr_workspace_profiles",
        "epcr_user_recent_actions",
        "epcr_user_theme_settings",
        "epcr_user_favorites",
        "epcr_dashboard_card_preferences",
        "epcr_user_dashboard_profiles",
        # Sync
        "epcr_audit_envelopes",
        "epcr_sync_health",
        "epcr_upload_queue",
        "epcr_sync_conflicts",
        "epcr_sync_event_log",
        # Terminology
        "epcr_differential_impressions",
        "epcr_impression_bindings",
        "ref_terminology_versions",
        "ref_nemsis_regex_rules",
        "ref_nemsis_value_sets",
        "ref_rxnorm_concepts",
        "ref_icd10_codes",
        "ref_snomed_concepts",
        # Critical care
        "epcr_intervention_nemsis_links",
        "epcr_intervention_terminology_bindings",
        "epcr_intervention_protocol_links",
        "epcr_intervention_contraindications",
        "epcr_intervention_indications",
        "epcr_intervention_intents",
        "epcr_response_windows",
        "epcr_blood_product_administrations",
        "epcr_ventilator_sessions",
        "epcr_infusion_runs",
        "epcr_critical_care_devices",
        # Vision
        "vision_duplicate_clusters",
        "vision_quality_flags",
        "vision_chart_links",
        "vision_model_versions",
        "vision_provenance_records",
        "vision_review_actions",
        "vision_review_queue",
        "vision_annotations",
        "vision_bounding_regions",
        "vision_classifications",
        "vision_extractions",
        "vision_extraction_runs",
        "vision_ingestion_jobs",
        "vision_artifact_versions",
        "vision_artifacts",
        # VAS
        "epcr_visual_audit_events",
        "epcr_visual_projection_reviews",
        "epcr_visual_intervention_response_links",
        "epcr_visual_reassessment_snapshots",
        "epcr_visual_finding_links",
        "epcr_visual_overlay_versions",
        "epcr_visual_overlays_v2",
        "epcr_visual_regions",
        "epcr_visual_models",
        # CPAE
        "epcr_finding_audit_events",
        "epcr_finding_nemsis_links",
        "epcr_finding_response_links",
        "epcr_finding_intervention_links",
        "epcr_finding_evidence_links",
        "epcr_finding_reassessments",
        "epcr_finding_characteristics",
        "epcr_physical_findings",
        "epcr_physiologic_systems",
        "epcr_assessment_regions",
        # CareGraph
        "epcr_caregraph_audit_events",
        "epcr_reassessment_deltas",
        "epcr_opqrst_symptoms",
        "epcr_caregraph_edges",
        "epcr_caregraph_nodes",
    ]
    for tbl in tables_to_drop:
        op.drop_table(tbl)
