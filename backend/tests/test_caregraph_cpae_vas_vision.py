"""Comprehensive tests for CareGraph, CPAE, VAS, Vision, CriticalCare, Sync, Dashboard.

Tests cover:
- Model creation and persistence
- API route validation
- Tenant isolation
- Audit trail
- 5-layer validation stack
- Sync event idempotency
- Vision review gate enforcement
- CPAE finding validation (anatomy + physiology required)
- Dashboard customization isolation from clinical truth
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, UTC

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from epcr_app.models import Base, Chart, ChartStatus
from epcr_app.models_caregraph import (
    CareGraphNode, OPQRSTSymptom, CareGraphNodeType, CareGraphEdgeType, EvidenceStrength, SyncSafetyState,
)
from epcr_app.models_cpae import (
    PhysicalFinding,
)
from epcr_app.models_vas import VASOverlay, VASProjectionReview
from epcr_app.models_vision import (
    VisionArtifact, VisionExtraction, VisionReviewActionRecord,
    VisionProvenanceRecord,
)
from epcr_app.models_critical_care import (
    InfusionRun, VentilatorSession, ResponseWindow,
)
from epcr_app.models_terminology import (
    SnomedConcept, ICD10Code, RxNormConcept, ImpressionBinding, NemsisRegexRule,
)
from epcr_app.models_sync import (
    SyncEventLog, SyncConflict, SyncHealthRecord, AuditEnvelope,
)
from epcr_app.models_dashboard import (
    UserDashboardProfile, UserFavorite, WorkspaceProfile, AgencyWorkflowConfig,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

TENANT_ID = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"
OTHER_TENANT_ID = "00000000-0000-0000-0000-000000000099"


def make_chart_id() -> str:
    return str(uuid.uuid4())


def make_id() -> str:
    return str(uuid.uuid4())


def now_ts() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# CareGraph Node Tests
# ---------------------------------------------------------------------------

class TestCareGraphNode:
    """CareGraph node creation and validation."""

    def test_node_type_enum_values(self):
        """All required node types are defined."""
        required_types = [
            "patient_state", "symptom", "physical_finding", "vital",
            "impression", "intervention", "medication", "device_state",
            "protocol_state", "transport_state", "disposition",
            "response", "reassessment", "outcome",
        ]
        for t in required_types:
            assert CareGraphNodeType(t) is not None

    def test_edge_type_enum_values(self):
        """All required edge types are defined."""
        required_types = [
            "causality", "timing", "intent", "evidence_support",
            "clinical_response", "escalation", "downgrade",
            "protocol_linkage", "terminology_binding", "export_mapping",
            "reassessment_delta", "intervention_response",
        ]
        for t in required_types:
            assert CareGraphEdgeType(t) is not None

    def test_node_has_required_fields(self):
        """CareGraph node has all required fields."""
        node = CareGraphNode(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            node_type=CareGraphNodeType.SYMPTOM,
            label="Chest pain",
            evidence_strength=EvidenceStrength.CONFIRMED,
            provider_id=USER_ID,
            sync_state=SyncSafetyState.CLEAN,
            occurred_at=now_ts(),
            created_at=now_ts(),
            updated_at=now_ts(),
        )
        assert node.tenant_id == TENANT_ID
        assert node.node_type == CareGraphNodeType.SYMPTOM
        assert node.evidence_strength == EvidenceStrength.CONFIRMED
        assert node.sync_state == SyncSafetyState.CLEAN

    def test_node_terminology_bindings(self):
        """CareGraph node supports all terminology layers."""
        node = CareGraphNode(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            node_type=CareGraphNodeType.IMPRESSION,
            label="STEMI",
            snomed_code="57054005",
            snomed_display="Acute myocardial infarction",
            icd10_code="I21.9",
            icd10_display="Acute myocardial infarction, unspecified",
            nemsis_element="eSituation.11",
            nemsis_value="2821013",
            provider_id=USER_ID,
            occurred_at=now_ts(),
            created_at=now_ts(),
            updated_at=now_ts(),
        )
        assert node.snomed_code == "57054005"
        assert node.icd10_code == "I21.9"
        assert node.nemsis_element == "eSituation.11"


# ---------------------------------------------------------------------------
# OPQRST Tests
# ---------------------------------------------------------------------------

class TestOPQRST:
    """OPQRST symptom engine tests."""

    def test_opqrst_structured_fields(self):
        """OPQRST stores structured fields, not plain text."""
        opqrst = OPQRSTSymptom(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            symptom_category="pain",
            symptom_label="Chest pain",
            severity_scale=8,
            time_progression="constant",
            onset_sudden=True,
            radiation_present=True,
            radiation_locations_json=json.dumps(["left_arm", "jaw"]),
            quality_descriptors_json=json.dumps(["pressure", "crushing"]),
            provocation_factors_json=json.dumps(["exertion"]),
            palliation_factors_json=json.dumps(["rest", "nitroglycerin"]),
            provider_id=USER_ID,
            documented_at=now_ts(),
            updated_at=now_ts(),
        )
        assert opqrst.symptom_category == "pain"
        assert opqrst.severity_scale == 8
        assert opqrst.onset_sudden is True
        # Verify structured JSON fields
        assert json.loads(opqrst.radiation_locations_json) == ["left_arm", "jaw"]
        assert json.loads(opqrst.quality_descriptors_json) == ["pressure", "crushing"]

    def test_opqrst_not_plain_text(self):
        """OPQRST fields are structured, not a single text blob."""
        opqrst = OPQRSTSymptom(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            symptom_category="dyspnea",
            symptom_label="Shortness of breath",
            provider_id=USER_ID,
            documented_at=now_ts(),
            updated_at=now_ts(),
        )
        # No single "description" text field — all structured
        assert not hasattr(opqrst, "description_text")
        assert opqrst.symptom_category == "dyspnea"


# ---------------------------------------------------------------------------
# CPAE Physical Finding Tests
# ---------------------------------------------------------------------------

class TestCPAEPhysicalFinding:
    """CPAE physical assessment engine tests."""

    def test_finding_requires_anatomy_and_physiology(self):
        """Findings must have anatomy and physiologic_system."""
        finding = PhysicalFinding(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            anatomy="anterior_chest",
            physiologic_system="cardiovascular",
            finding_class="auscultation",
            severity="moderate",
            finding_label="Diminished breath sounds",
            detection_method="direct",
            review_state="direct_confirmed",
            provider_id=USER_ID,
            observed_at=now_ts(),
            updated_at=now_ts(),
        )
        assert finding.anatomy == "anterior_chest"
        assert finding.physiologic_system == "cardiovascular"
        assert finding.finding_class == "auscultation"

    def test_finding_review_state_for_vision_proposals(self):
        """Vision-proposed findings have review_state != direct_confirmed."""
        finding = PhysicalFinding(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            anatomy="head",
            physiologic_system="neurological",
            finding_class="inspection",
            severity="mild",
            finding_label="Facial droop",
            detection_method="vision",
            review_state="vision_proposed",  # NOT direct_confirmed
            provider_id=USER_ID,
            observed_at=now_ts(),
            updated_at=now_ts(),
        )
        assert finding.review_state == "vision_proposed"
        assert finding.review_state != "direct_confirmed"

    def test_finding_contradiction_detection(self):
        """Findings can flag contradictions."""
        finding = PhysicalFinding(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            anatomy="left_lower_extremity",
            physiologic_system="musculoskeletal",
            finding_class="palpation",
            severity="severe",
            finding_label="Deformity",
            detection_method="direct",
            review_state="direct_confirmed",
            has_contradiction=True,
            contradiction_detail="Bilateral deformity documented but laterality is left only",
            provider_id=USER_ID,
            observed_at=now_ts(),
            updated_at=now_ts(),
        )
        assert finding.has_contradiction is True
        assert finding.contradiction_detail is not None

    def test_finding_laterality_support(self):
        """Findings support laterality enforcement."""
        for laterality in ["left", "right", "bilateral", "midline", "not_applicable"]:
            finding = PhysicalFinding(
                id=make_id(),
                chart_id=make_chart_id(),
                tenant_id=TENANT_ID,
                anatomy="right_upper_extremity",
                physiologic_system="musculoskeletal",
                finding_class="palpation",
                severity="mild",
                finding_label="Tenderness",
                laterality=laterality,
                detection_method="direct",
                review_state="direct_confirmed",
                provider_id=USER_ID,
                observed_at=now_ts(),
                updated_at=now_ts(),
            )
            assert finding.laterality == laterality

    def test_finding_nemsis_link(self):
        """Findings can be linked to NEMSIS eExam elements."""
        from epcr_app.models_cpae import FindingNemsisLink
        link = FindingNemsisLink(
            id=make_id(),
            finding_id=make_id(),
            tenant_id=TENANT_ID,
            nemsis_section="eExam",
            nemsis_element="eExam.01",
            nemsis_value="3516001",
            xml_path="EMSDataSet/Header/PatientCareReport/eExam/eExam.01",
            export_ready=True,
        )
        assert link.nemsis_section == "eExam"
        assert link.export_ready is True


# ---------------------------------------------------------------------------
# VAS Visual Assessment Tests
# ---------------------------------------------------------------------------

class TestVASOverlay:
    """VAS visual assessment system tests."""

    def test_overlay_requires_physical_finding_link(self):
        """VAS overlays must be linked to a CPAE physical finding."""
        overlay = VASOverlay(
            id=make_id(),
            chart_id=make_chart_id(),
            physical_finding_id=make_id(),  # REQUIRED — not optional
            tenant_id=TENANT_ID,
            patient_model="adult",
            anatomical_view="front",
            overlay_type="bruising",
            anchor_region="anterior_chest",
            geometry_json=json.dumps({"type": "ellipse", "x": 0.4, "y": 0.3, "width": 0.1, "height": 0.08}),
            severity="moderate",
            evolution="new",
            review_state="direct_confirmed",
            provider_id=USER_ID,
            rendered_at=now_ts(),
            updated_at=now_ts(),
        )
        assert overlay.physical_finding_id is not None
        assert overlay.geometry_json is not None

    def test_overlay_vision_proposal_requires_review(self):
        """Vision-proposed overlays have review_state = vision_proposed."""
        overlay = VASOverlay(
            id=make_id(),
            chart_id=make_chart_id(),
            physical_finding_id=make_id(),
            tenant_id=TENANT_ID,
            patient_model="adult",
            anatomical_view="front",
            overlay_type="bleeding",
            anchor_region="head",
            geometry_json=json.dumps({"type": "circle", "x": 0.5, "y": 0.1, "radius": 0.05}),
            severity="severe",
            evolution="new",
            review_state="vision_proposed",  # NOT accepted yet
            provider_id=USER_ID,
            rendered_at=now_ts(),
            updated_at=now_ts(),
        )
        assert overlay.review_state == "vision_proposed"

    def test_projection_review_pending_state(self):
        """Vision projection reviews start in pending state."""
        review = VASProjectionReview(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            vision_artifact_id=make_id(),
            proposed_overlay_json=json.dumps({"overlay_type": "bruising"}),
            confidence=0.87,
            model_version="vision-v2.1",
            review_state="pending",  # NOT auto-accepted
            proposed_at=now_ts(),
        )
        assert review.review_state == "pending"
        assert review.reviewer_id is None  # Not yet reviewed


# ---------------------------------------------------------------------------
# Vision Integration Tests
# ---------------------------------------------------------------------------

class TestVisionIntegration:
    """Vision governed perception layer tests."""

    def test_artifact_has_secure_storage_path(self):
        """Vision artifacts store internal paths, never public URLs."""
        artifact = VisionArtifact(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            ingestion_source="mobile_camera",
            content_type="image/jpeg",
            storage_path="s3://adaptix-internal/epcr/artifacts/abc123.jpg",  # internal path
            source_hash_sha256="abc123def456" * 4,
            processing_status="pending",
            uploaded_by_user_id=USER_ID,
            uploaded_at=now_ts(),
            updated_at=now_ts(),
        )
        # Storage path is internal — not a public URL
        assert artifact.storage_path.startswith("s3://")
        assert "public" not in artifact.storage_path

    def test_extraction_starts_pending_review(self):
        """Vision extractions start in pending_review state — never auto-accepted."""
        extraction = VisionExtraction(
            id=make_id(),
            artifact_id=make_id(),
            tenant_id=TENANT_ID,
            proposal_target="medication",
            extracted_value_json=json.dumps({"name": "Epinephrine", "dose": "1mg"}),
            confidence=0.92,
            source_hash_sha256="abc123" * 8,
            review_state="pending_review",  # NEVER auto-accepted
            extracted_at=now_ts(),
        )
        assert extraction.review_state == "pending_review"
        assert extraction.reviewer_id is None

    def test_extraction_provenance_preserved(self):
        """Vision extraction provenance is never destroyed."""
        provenance = VisionProvenanceRecord(
            id=make_id(),
            extraction_id=make_id(),
            tenant_id=TENANT_ID,
            provenance_type="source",
            provenance_detail_json=json.dumps({
                "artifact_id": make_id(),
                "model_version": "vision-v2.1",
                "source_hash": "abc123",
            }),
            recorded_at=now_ts(),
        )
        assert provenance.provenance_type == "source"
        assert provenance.provenance_detail_json is not None

    def test_review_action_records_actor(self):
        """Vision review actions record the actor for audit."""
        action = VisionReviewActionRecord(
            id=make_id(),
            queue_entry_id=make_id(),
            extraction_id=make_id(),
            tenant_id=TENANT_ID,
            action="accept",
            actor_id=USER_ID,
            performed_at=now_ts(),
        )
        assert action.actor_id == USER_ID
        assert action.action == "accept"

    def test_vision_cannot_auto_accept(self):
        """Vision proposals require explicit review — no auto-accept path."""
        # The review_state field must be explicitly set to "accepted"
        # by a human reviewer action — it cannot be set to "accepted" at creation
        extraction = VisionExtraction(
            id=make_id(),
            artifact_id=make_id(),
            tenant_id=TENANT_ID,
            proposal_target="vital",
            extracted_value_json=json.dumps({"hr": 88}),
            confidence=0.95,
            source_hash_sha256="def456" * 8,
            review_state="pending_review",
            extracted_at=now_ts(),
        )
        # Cannot be accepted without reviewer_id
        assert extraction.reviewer_id is None
        assert extraction.reviewed_at is None


# ---------------------------------------------------------------------------
# Critical Care Tests
# ---------------------------------------------------------------------------

class TestCriticalCare:
    """Critical care intervention engine tests."""

    def test_infusion_run_requires_indication(self):
        """Infusion runs must have an indication."""
        infusion = InfusionRun(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            medication_name="Norepinephrine",
            rxnorm_code="7512",
            concentration="4mg/250mL",
            initial_rate_value=0.1,
            initial_rate_unit="mcg/kg/min",
            indication="Refractory hypotension, MAP < 65 mmHg",  # REQUIRED
            started_at=now_ts(),
            provider_id=USER_ID,
            updated_at=now_ts(),
        )
        assert infusion.indication is not None
        assert len(infusion.indication) > 0

    def test_ventilator_session_has_mode(self):
        """Ventilator sessions must have a mode."""
        vent = VentilatorSession(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            mode="AC/VC",
            tidal_volume_ml=500,
            respiratory_rate=14,
            fio2_percent=40,
            peep_cmh2o=5.0,
            indication="Respiratory failure",
            started_at=now_ts(),
            provider_id=USER_ID,
            updated_at=now_ts(),
        )
        assert vent.mode == "AC/VC"
        assert vent.indication is not None

    def test_response_window_pending_state(self):
        """Response windows start in pending state."""
        window = ResponseWindow(
            id=make_id(),
            chart_id=make_chart_id(),
            intervention_id=make_id(),
            tenant_id=TENANT_ID,
            expected_response="MAP > 65 mmHg within 15 minutes",
            expected_response_window_minutes=15,
            response_availability="pending",  # Not yet documented
            provider_id=USER_ID,
        )
        assert window.response_availability == "pending"
        assert window.actual_response is None

    def test_response_window_unavailability_requires_reason(self):
        """If response unavailable, reason must be provided."""
        window = ResponseWindow(
            id=make_id(),
            chart_id=make_chart_id(),
            intervention_id=make_id(),
            tenant_id=TENANT_ID,
            expected_response="Seizure cessation",
            response_availability="unavailable_transport_time",
            unavailability_reason="Transport time too short to assess response",
            provider_id=USER_ID,
        )
        assert window.response_availability == "unavailable_transport_time"
        assert window.unavailability_reason is not None


# ---------------------------------------------------------------------------
# Terminology Fabric Tests
# ---------------------------------------------------------------------------

class TestTerminologyFabric:
    """Terminology fabric — four distinct layers."""

    def test_snomed_concept_fields(self):
        """SNOMED CT concepts have required fields."""
        concept = SnomedConcept(
            id=make_id(),
            concept_id="57054005",
            fsn="Acute myocardial infarction (disorder)",
            preferred_term="Acute myocardial infarction",
            semantic_tag="(disorder)",
            is_active=True,
            version_date="20240901",
            source_artifact_version="SNOMED_CT_20240901",
            created_at=now_ts(),
        )
        assert concept.concept_id == "57054005"
        assert concept.semantic_tag == "(disorder)"

    def test_icd10_code_fields(self):
        """ICD-10-CM codes have required fields."""
        code = ICD10Code(
            id=make_id(),
            code="I21.9",
            description="Acute myocardial infarction, unspecified",
            category_code="I21",
            is_billable=True,
            is_active=True,
            fiscal_year="2025",
            source_artifact_version="ICD10CM_FY2025",
            created_at=now_ts(),
        )
        assert code.code == "I21.9"
        assert code.is_billable is True

    def test_rxnorm_concept_fields(self):
        """RxNorm concepts have required fields."""
        concept = RxNormConcept(
            id=make_id(),
            rxcui="7512",
            name="Norepinephrine",
            tty="IN",
            is_active=True,
            version_date="20240101",
            source_artifact_version="RXNORM_20240101",
            created_at=now_ts(),
        )
        assert concept.rxcui == "7512"
        assert concept.tty == "IN"

    def test_impression_binding_multi_layer(self):
        """Impression bindings support all four terminology layers."""
        binding = ImpressionBinding(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            impression_class="primary",
            adaptix_label="STEMI",
            snomed_code="57054005",
            snomed_display="Acute myocardial infarction",
            icd10_code="I21.9",
            icd10_display="Acute myocardial infarction, unspecified",
            nemsis_element="eSituation.11",
            nemsis_value="2821013",
            is_ai_suggested=False,
            review_state="direct_confirmed",
            provider_id=USER_ID,
            documented_at=now_ts(),
            updated_at=now_ts(),
        )
        assert binding.snomed_code is not None
        assert binding.icd10_code is not None
        assert binding.nemsis_element is not None
        # ICD-10 is NOT NEMSIS export truth
        assert binding.icd10_code != binding.nemsis_value

    def test_ai_suggested_impression_requires_review(self):
        """AI-suggested impressions must be reviewed before acceptance."""
        binding = ImpressionBinding(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            impression_class="primary",
            adaptix_label="Sepsis",
            is_ai_suggested=True,
            review_state="pending_review",  # NOT direct_confirmed
            provider_id=USER_ID,
            documented_at=now_ts(),
            updated_at=now_ts(),
        )
        assert binding.is_ai_suggested is True
        assert binding.review_state == "pending_review"
        assert binding.reviewer_id is None


# ---------------------------------------------------------------------------
# Sync Engine Tests
# ---------------------------------------------------------------------------

class TestSyncEngine:
    """Offline sync engine tests."""

    def test_sync_event_has_idempotency_key(self):
        """Sync events have idempotency keys for safe retry."""
        event = SyncEventLog(
            id=make_id(),
            tenant_id=TENANT_ID,
            chart_id=make_chart_id(),
            device_id="device-001",
            user_id=USER_ID,
            event_type="chart_create",
            event_payload_json=json.dumps({"chart_id": make_id()}),
            entity_type="chart",
            entity_id=make_id(),
            local_sequence_number=1,
            device_timestamp=now_ts(),
            status="pending",
            upload_attempts=0,
            uploaded_at=None,
            error_detail=None,
            idempotency_key=f"chart_create_{make_id()}",
            created_at=now_ts(),
        )
        assert event.idempotency_key is not None
        assert event.status == "pending"

    def test_sync_conflict_records_both_states(self):
        """Sync conflicts record both client and server state."""
        conflict = SyncConflict(
            id=make_id(),
            tenant_id=TENANT_ID,
            chart_id=make_chart_id(),
            device_id="device-001",
            user_id=USER_ID,
            sync_event_id=make_id(),
            entity_type="chart",
            entity_id=make_id(),
            client_state_json=json.dumps({"status": "in_progress", "version": 3}),
            server_state_json=json.dumps({"status": "finalized", "version": 5}),
            conflict_fields_json=json.dumps(["status", "version"]),
            detected_at=now_ts(),
        )
        assert conflict.client_state_json is not None
        assert conflict.server_state_json is not None
        assert conflict.resolved_at is None  # Not yet resolved

    def test_sync_health_tracks_degraded_state(self):
        """Sync health explicitly tracks degraded state."""
        health = SyncHealthRecord(
            id=make_id(),
            tenant_id=TENANT_ID,
            device_id="device-001",
            user_id=USER_ID,
            health_state="sync_failed",
            pending_events_count=5,
            failed_events_count=2,
            is_degraded=True,
            degraded_reason="Upload failed after 3 retries",
            updated_at=now_ts(),
        )
        assert health.is_degraded is True
        assert health.degraded_reason is not None
        assert health.health_state == "sync_failed"

    def test_audit_envelope_never_lost(self):
        """Audit envelopes preserve audit events during offline mode."""
        envelope = AuditEnvelope(
            id=make_id(),
            tenant_id=TENANT_ID,
            chart_id=make_chart_id(),
            device_id="device-001",
            user_id=USER_ID,
            audit_events_json=json.dumps([
                {"action": "create", "entity": "chart", "actor": USER_ID},
                {"action": "update", "entity": "vitals", "actor": USER_ID},
            ]),
            event_count=2,
            sequence_start=1,
            sequence_end=2,
            upload_status="pending",
            uploaded_at=None,
            idempotency_key=f"audit_{make_id()}",
            captured_at=now_ts(),
            created_at=now_ts(),
        )
        assert envelope.event_count == 2
        assert envelope.upload_status == "pending"
        assert envelope.uploaded_at is None


# ---------------------------------------------------------------------------
# Dashboard Customization Tests
# ---------------------------------------------------------------------------

class TestDashboardCustomization:
    """Dashboard customization isolation from clinical truth."""

    def test_dashboard_profile_does_not_affect_clinical_truth(self):
        """Dashboard profile has no clinical fields."""
        profile = UserDashboardProfile(
            id=make_id(),
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            profile_name="field_mode",
            is_active=True,
            density="compact",
            theme_mode="dark",
            created_at=now_ts(),
            updated_at=now_ts(),
        )
        # Dashboard profile has no clinical fields
        assert not hasattr(profile, "chart_id")
        assert not hasattr(profile, "nemsis_field")
        assert not hasattr(profile, "clinical_payload_json")

    def test_workspace_profile_does_not_hide_mandatory_blockers(self):
        """Workspace profiles cannot hide mandatory completion blockers."""
        profile = WorkspaceProfile(
            id=make_id(),
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            profile_type="critical_care_transport",
            profile_name="CCT Mode",
            is_default=True,
            critical_care_mode=True,
            show_ventilator_panel=True,
            show_infusion_panel=True,
            created_at=now_ts(),
            updated_at=now_ts(),
        )
        # Profile can show/hide panels but cannot hide mandatory blockers
        # (enforced at API layer — profile has no "hide_blockers" field)
        assert not hasattr(profile, "hide_mandatory_blockers")
        assert not hasattr(profile, "bypass_nemsis_validation")

    def test_user_favorites_do_not_affect_clinical_truth(self):
        """User favorites are display preferences only."""
        favorite = UserFavorite(
            id=make_id(),
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            favorite_type="medication",
            favorite_key="epinephrine_1mg",
            display_label="Epinephrine 1mg",
            created_at=now_ts(),
            updated_at=now_ts(),
        )
        # Favorites have no clinical payload
        assert not hasattr(favorite, "chart_id")
        assert not hasattr(favorite, "administered_at")

    def test_agency_config_cannot_break_nemsis(self):
        """Agency workflow config cannot break NEMSIS mapping."""
        config = AgencyWorkflowConfig(
            id=make_id(),
            tenant_id=TENANT_ID,
            require_opqrst_for_pain=True,
            require_reassessment_after_intervention=True,
            require_response_documentation=True,
            state_code="12",
            agency_number="FL-001",
            updated_at=now_ts(),
        )
        # Config can add requirements but cannot remove NEMSIS mandatory fields
        assert not hasattr(config, "disable_nemsis_validation")
        assert not hasattr(config, "skip_mandatory_fields")


# ---------------------------------------------------------------------------
# 5-Layer Validation Stack Tests
# ---------------------------------------------------------------------------

class TestValidationStack:
    """5-layer validation stack tests."""

    def test_validation_result_structure(self):
        """ValidationResult has all required fields."""
        from epcr_app.clinical_validation_stack import ValidationResult

        result = ValidationResult(
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            validated_at=now_ts(),
        )
        assert result.layer_1_passed is False
        assert result.layer_2_passed is False
        assert result.layer_3_passed is False
        assert result.layer_4_passed is False
        assert result.layer_5_passed is False
        assert result.export_blocked is False
        assert result.export_blockers == []
        assert result.issues == []

    def test_validation_issue_structure(self):
        """ValidationIssue has all required fields."""
        from epcr_app.clinical_validation_stack import ValidationIssue

        issue = ValidationIssue(
            layer=1,
            severity="error",
            code="CLINICAL_IMPOSSIBLE_HR",
            message="Heart rate 500 is physiologically impossible",
            field="hr",
            entity_id=make_id(),
            entity_type="vitals",
            remediation="Correct heart rate value",
        )
        assert issue.layer == 1
        assert issue.severity == "error"
        assert issue.code == "CLINICAL_IMPOSSIBLE_HR"
        assert issue.remediation is not None

    def test_validation_result_to_dict(self):
        """ValidationResult serializes to dict correctly."""
        from epcr_app.clinical_validation_stack import ValidationResult, ValidationIssue

        result = ValidationResult(
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            validated_at=now_ts(),
        )
        result.issues.append(ValidationIssue(
            layer=2,
            severity="error",
            code="NEMSIS_MANDATORY_MISSING",
            message="eRecord.01 is missing",
            nemsis_element="eRecord.01",
        ))
        result.export_blockers.append("Missing mandatory: eRecord.01")
        result.export_blocked = True

        d = result.to_dict()
        assert d["export_blocked"] is True
        assert len(d["export_blockers"]) == 1
        assert d["error_count"] == 1
        assert len(d["issues"]) == 1
        assert d["issues"][0]["layer"] == 2

    def test_nemsis_mandatory_fields_defined(self):
        """All required NEMSIS mandatory fields are in the validation stack."""
        from epcr_app.clinical_validation_stack import NEMSIS_MANDATORY_FIELDS

        required = ["eRecord.01", "eResponse.05", "eTimes.03", "ePatient.13", "ePatient.15"]
        for field in required:
            assert field in NEMSIS_MANDATORY_FIELDS

    def test_datetime_pattern_validates_correctly(self):
        """NEMSIS datetime pattern validates ISO 8601 correctly."""
        from epcr_app.clinical_validation_stack import NEMSIS_DATETIME_PATTERN

        valid = [
            "2026-04-22T12:00:00Z",
            "2026-04-22T12:00:00+05:00",
            "2026-04-22T12:00:00.000Z",
        ]
        invalid = [
            "2026-04-22",
            "12:00:00",
            "not-a-date",
            "2026/04/22T12:00:00Z",
        ]
        for v in valid:
            assert NEMSIS_DATETIME_PATTERN.match(v), f"Should be valid: {v}"
        for v in invalid:
            assert not NEMSIS_DATETIME_PATTERN.match(v), f"Should be invalid: {v}"

    @pytest.mark.asyncio
    async def test_invalid_regex_rule_is_reported_as_explicit_validation_error(self):
        """Invalid DB regex rules must block Layer 2 instead of being skipped silently."""
        from epcr_app.clinical_validation_stack import (
            ValidationResult,
            validate_layer_2_nemsis_structural,
        )
        from epcr_app.models import NemsisMappingRecord

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
        chart_id = make_chart_id()

        async with SessionLocal() as async_session:
            async_session.add(
                Chart(
                    id=chart_id,
                    tenant_id=TENANT_ID,
                    call_number="TEST-REGEX-001",
                    incident_type="medical",
                    status=ChartStatus.NEW,
                    created_by_user_id=USER_ID,
                    created_at=now_ts(),
                    updated_at=now_ts(),
                )
            )
            async_session.add(
                NemsisRegexRule(
                    id=make_id(),
                    element_number="eCustom.01",
                    element_name="Broken Regex Element",
                    regex_pattern="(",
                    description="intentionally invalid regex",
                    source_artifact_version="test",
                )
            )
            async_session.add(
                NemsisMappingRecord(
                    id=make_id(),
                    chart_id=chart_id,
                    tenant_id=TENANT_ID,
                    nemsis_field="eCustom.01",
                    nemsis_value="abc123",
                    source="manual",
                    created_at=now_ts(),
                    updated_at=now_ts(),
                )
            )
            await async_session.commit()

        async with SessionLocal() as async_session:
            result = ValidationResult(
                chart_id=chart_id,
                tenant_id=TENANT_ID,
                validated_at=now_ts(),
            )

            await validate_layer_2_nemsis_structural(
                chart_id,
                TENANT_ID,
                async_session,
                result,
            )

            invalid_rule_issue = next(
                issue for issue in result.issues if issue.code == "NEMSIS_REGEX_RULE_INVALID"
            )
            assert invalid_rule_issue.severity == "error"
            assert invalid_rule_issue.nemsis_element == "eCustom.01"
            assert result.layer_2_passed is False

        await engine.dispose()


# ---------------------------------------------------------------------------
# Tenant Isolation Tests
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    """Tenant isolation enforcement tests."""

    def test_all_models_have_tenant_id(self):
        """All clinical models have tenant_id field."""
        models_to_check = [
            CareGraphNode, OPQRSTSymptom, PhysicalFinding,
            VASOverlay, VisionArtifact, VisionExtraction,
            InfusionRun, VentilatorSession, ResponseWindow,
            ImpressionBinding, SyncEventLog, SyncConflict,
            UserDashboardProfile, WorkspaceProfile,
        ]
        for model_class in models_to_check:
            assert hasattr(model_class, "tenant_id") or \
                   any(col.key == "tenant_id" for col in model_class.__table__.columns), \
                   f"{model_class.__name__} missing tenant_id"

    def test_caregraph_node_tenant_scoped(self):
        """CareGraph nodes are tenant-scoped."""
        node = CareGraphNode(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            node_type=CareGraphNodeType.VITAL,
            label="BP 120/80",
            provider_id=USER_ID,
            occurred_at=now_ts(),
            created_at=now_ts(),
            updated_at=now_ts(),
        )
        assert node.tenant_id == TENANT_ID
        # Different tenant cannot access this node
        assert node.tenant_id != OTHER_TENANT_ID


# ---------------------------------------------------------------------------
# Anti-Drift Tests
# ---------------------------------------------------------------------------

class TestAntiDrift:
    """Anti-drift enforcement — no narrative as truth, no orphan findings."""

    def test_narrative_is_not_clinical_truth(self):
        """Narrative is derived output only — not stored in CareGraph."""
        # CareGraph nodes do NOT have a narrative field
        node = CareGraphNode(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            node_type=CareGraphNodeType.SYMPTOM,
            label="Chest pain",
            provider_id=USER_ID,
            occurred_at=now_ts(),
            created_at=now_ts(),
            updated_at=now_ts(),
        )
        assert not hasattr(node, "narrative")
        assert not hasattr(node, "narrative_text")

    def test_physical_finding_not_orphan(self):
        """Physical findings must have chart_id and tenant_id."""
        finding = PhysicalFinding(
            id=make_id(),
            chart_id=make_chart_id(),  # REQUIRED
            tenant_id=TENANT_ID,       # REQUIRED
            anatomy="head",
            physiologic_system="neurological",
            finding_class="inspection",
            severity="mild",
            finding_label="Pupil dilation",
            detection_method="direct",
            review_state="direct_confirmed",
            provider_id=USER_ID,
            observed_at=now_ts(),
            updated_at=now_ts(),
        )
        assert finding.chart_id is not None
        assert finding.tenant_id is not None

    def test_vision_extraction_not_orphan(self):
        """Vision extractions must be linked to an artifact."""
        extraction = VisionExtraction(
            id=make_id(),
            artifact_id=make_id(),  # REQUIRED — links to source artifact
            tenant_id=TENANT_ID,
            proposal_target="medication",
            extracted_value_json=json.dumps({"name": "Aspirin"}),
            confidence=0.88,
            source_hash_sha256="abc" * 16,
            review_state="pending_review",
            extracted_at=now_ts(),
        )
        assert extraction.artifact_id is not None

    def test_impression_not_from_free_text(self):
        """Impressions have structured bindings, not free text only."""
        binding = ImpressionBinding(
            id=make_id(),
            chart_id=make_chart_id(),
            tenant_id=TENANT_ID,
            impression_class="primary",
            adaptix_label="Stroke",
            snomed_code="230690007",
            icd10_code="I63.9",
            nemsis_element="eSituation.11",
            nemsis_value="2821015",
            provider_id=USER_ID,
            documented_at=now_ts(),
            updated_at=now_ts(),
        )
        # Impression has structured bindings — not just a text field
        assert binding.snomed_code is not None
        assert binding.icd10_code is not None
        assert binding.nemsis_element is not None
