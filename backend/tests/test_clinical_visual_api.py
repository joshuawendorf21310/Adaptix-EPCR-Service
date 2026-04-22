"""API tests for the structured CPAE/VAS/ARCOS workflow routes."""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from epcr_app.api import router
from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.models import Base


TENANT_ID = str(uuid4())
USER_ID = str(uuid4())
HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "X-User-ID": USER_ID,
    "Authorization": "Bearer test-token",
}


@pytest_asyncio.fixture
async def session_factory():
    """Create a shared in-memory database for API route tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield session_maker

    await engine.dispose()


@pytest.fixture
def client(session_factory):
    """Build a lightweight FastAPI app with dependency overrides for auth and DB."""
    app = FastAPI()
    app.include_router(router)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    async def override_get_current_user() -> CurrentUser:
        return CurrentUser(user_id=uuid4(), tenant_id=uuid4(), email="tester@example.com", roles=["clinician"])

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _create_chart(client: TestClient) -> str:
    """Create a chart and return its identifier."""
    response = client.post(
        "/api/v1/epcr/charts",
        headers=HEADERS,
        json={
            "call_number": f"CALL-{uuid4()}",
            "incident_type": "medical",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_structured_finding_create_list_update_flow(client: TestClient):
    """Structured findings should support create, read, and correction flows."""
    chart_id = _create_chart(client)

    create_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/assessment-findings",
        headers=HEADERS,
        json={
            "anatomy": "thorax",
            "system": "respiratory",
            "finding_type": "wheezing",
            "severity": "moderate",
            "detection_method": "direct_visual_observation",
            "characteristics": ["expiratory"],
            "source_artifact_ids": ["img-1"],
        },
    )
    assert create_response.status_code == 201
    finding_id = create_response.json()["id"]

    list_response = client.get(
        f"/api/v1/epcr/charts/{chart_id}/assessment-findings",
        headers=HEADERS,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    update_response = client.patch(
        f"/api/v1/epcr/charts/{chart_id}/assessment-findings/{finding_id}",
        headers=HEADERS,
        json={
            "severity": "severe",
            "review_state": "edited_and_accepted",
            "characteristics": ["expiratory", "diffuse"],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["severity"] == "severe"
    assert update_response.json()["review_state"] == "edited_and_accepted"


def test_overlay_and_ar_session_lifecycle_flow(client: TestClient):
    """Overlays and ARCOS sessions should support read/update/complete lifecycle steps."""
    chart_id = _create_chart(client)

    finding_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/assessment-findings",
        headers=HEADERS,
        json={
            "anatomy": "head",
            "system": "neurological",
            "finding_type": "anisocoria",
            "severity": "critical",
            "detection_method": "direct_visual_observation",
        },
    )
    assert finding_response.status_code == 201
    finding_id = finding_response.json()["id"]

    overlay_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/visual-overlays",
        headers=HEADERS,
        json={
            "finding_id": finding_id,
            "patient_model": "adult",
            "anatomical_view": "anterior",
            "overlay_type": "heatmap",
            "anchor_region": "head",
            "geometry_reference": '{"x":0.4,"y":0.2}',
            "severity": "critical",
        },
    )
    assert overlay_response.status_code == 201
    overlay_id = overlay_response.json()["id"]

    overlay_list_response = client.get(
        f"/api/v1/epcr/charts/{chart_id}/visual-overlays",
        headers=HEADERS,
    )
    assert overlay_list_response.status_code == 200
    assert overlay_list_response.json()["count"] == 1

    overlay_update_response = client.patch(
        f"/api/v1/epcr/charts/{chart_id}/visual-overlays/{overlay_id}",
        headers=HEADERS,
        json={
            "review_state": "accepted",
            "geometry_reference": '{"x":0.45,"y":0.25}',
        },
    )
    assert overlay_update_response.status_code == 200
    assert overlay_update_response.json()["id"] == overlay_id

    session_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/ar-sessions",
        headers=HEADERS,
        json={
            "patient_model": "adult",
            "mode": "guided_exam",
        },
    )
    assert session_response.status_code == 201
    session_id = session_response.json()["id"]

    anchor_response = client.post(
        f"/api/v1/epcr/ar-sessions/{session_id}/anchors",
        headers=HEADERS,
        json={
            "anatomy": "head",
            "anatomical_view": "anterior",
            "confidence": 0.98,
        },
    )
    assert anchor_response.status_code == 201

    anchor_list_response = client.get(
        f"/api/v1/epcr/ar-sessions/{session_id}/anchors",
        headers=HEADERS,
    )
    assert anchor_list_response.status_code == 200
    assert anchor_list_response.json()["count"] == 1

    complete_response = client.post(
        f"/api/v1/epcr/ar-sessions/{session_id}/complete",
        headers=HEADERS,
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"

    sessions_list_response = client.get(
        f"/api/v1/epcr/charts/{chart_id}/ar-sessions",
        headers=HEADERS,
    )
    assert sessions_list_response.status_code == 200
    assert sessions_list_response.json()["count"] == 1
    assert sessions_list_response.json()["items"][0]["status"] == "completed"


def test_client_reference_ids_are_preserved_for_mobile_offline_sync(client: TestClient):
    """Offline-created mobile records should preserve client-generated identifiers through the API."""
    chart_id = str(uuid4())
    chart_response = client.post(
        "/api/v1/epcr/charts",
        headers=HEADERS,
        json={
            "call_number": f"CALL-{uuid4()}",
            "incident_type": "medical",
            "client_reference_id": chart_id,
        },
    )
    assert chart_response.status_code == 201
    assert chart_response.json()["id"] == chart_id

    finding_id = str(uuid4())
    finding_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/assessment-findings",
        headers=HEADERS,
        json={
            "client_reference_id": finding_id,
            "anatomy": "thorax",
            "system": "respiratory",
            "finding_type": "wheezing",
            "severity": "moderate",
            "detection_method": "direct_visual_observation",
        },
    )
    assert finding_response.status_code == 201
    assert finding_response.json()["id"] == finding_id

    overlay_id = str(uuid4())
    overlay_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/visual-overlays",
        headers=HEADERS,
        json={
            "client_reference_id": overlay_id,
            "finding_id": finding_id,
            "patient_model": "adult",
            "anatomical_view": "anterior",
            "overlay_type": "heatmap",
            "anchor_region": "thorax",
            "geometry_reference": '{"x":0.5,"y":0.5}',
            "severity": "moderate",
        },
    )
    assert overlay_response.status_code == 201
    assert overlay_response.json()["id"] == overlay_id

    session_id = str(uuid4())
    session_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/ar-sessions",
        headers=HEADERS,
        json={
            "client_reference_id": session_id,
            "patient_model": "adult",
            "mode": "guided_exam",
        },
    )
    assert session_response.status_code == 201
    assert session_response.json()["id"] == session_id

    anchor_id = str(uuid4())
    anchor_response = client.post(
        f"/api/v1/epcr/ar-sessions/{session_id}/anchors",
        headers=HEADERS,
        json={
            "client_reference_id": anchor_id,
            "anatomy": "thorax",
            "anatomical_view": "anterior",
            "confidence": 0.91,
        },
    )
    assert anchor_response.status_code == 201
    assert anchor_response.json()["id"] == anchor_id


def test_chart_workflow_authority_api_flow(client: TestClient):
    """Address intelligence, interventions, notes, protocol guidance, derived outputs, and dashboard should work end to end."""
    chart_id = _create_chart(client)

    finding_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/assessment-findings",
        headers=HEADERS,
        json={
            "anatomy": "thorax",
            "system": "respiratory",
            "finding_type": "respiratory_distress",
            "severity": "critical",
            "detection_method": "direct_visual_observation",
        },
    )
    assert finding_response.status_code == 201

    address_response = client.put(
        f"/api/v1/epcr/charts/{chart_id}/address-intelligence",
        headers=HEADERS,
        json={
            "raw_text": "123 Main Street, Springfield, IL 62704",
            "street_line_one": "123 Main Street",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62704",
            "latitude": 39.78,
            "longitude": -89.65,
            "intelligence_source": "manual_entry",
        },
    )
    assert address_response.status_code == 200
    assert address_response.json()["validation_state"] == "validated"

    intervention_id = str(uuid4())
    intervention_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/interventions",
        headers=HEADERS,
        json={
            "client_reference_id": intervention_id,
            "category": "airway",
            "name": "Bag-valve-mask ventilation",
            "indication": "Critical respiratory distress",
            "intent": "Support oxygenation and ventilation",
            "expected_response": "Improved chest rise and SpO2",
            "protocol_family": "acls",
            "snomed_code": "40617009",
        },
    )
    assert intervention_response.status_code == 201
    assert intervention_response.json()["id"] == intervention_id

    update_intervention_response = client.patch(
        f"/api/v1/epcr/charts/{chart_id}/interventions/{intervention_id}",
        headers=HEADERS,
        json={
            "actual_response": "Improved chest rise and better color",
            "export_state": "mapped_ready",
        },
    )
    assert update_intervention_response.status_code == 200
    assert update_intervention_response.json()["export_state"] == "mapped_ready"

    note_id = str(uuid4())
    note_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/clinical-notes",
        headers=HEADERS,
        json={
            "client_reference_id": note_id,
            "raw_text": "Patient found in tripod position with severe work of breathing, improved after assisted ventilation.",
            "source": "manual_entry",
            "provenance": {"mode": "touch"},
        },
    )
    assert note_response.status_code == 201
    assert note_response.json()["id"] == note_id

    note_update_response = client.patch(
        f"/api/v1/epcr/charts/{chart_id}/clinical-notes/{note_id}",
        headers=HEADERS,
        json={"review_state": "accepted"},
    )
    assert note_update_response.status_code == 200
    assert note_update_response.json()["review_state"] == "accepted"

    protocol_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/protocol-recommendations/generate",
        headers=HEADERS,
        json={"patient_model": "adult"},
    )
    assert protocol_response.status_code == 200
    assert protocol_response.json()["count"] >= 1
    recommendation_id = protocol_response.json()["items"][0]["id"]

    protocol_update_response = client.patch(
        f"/api/v1/epcr/charts/{chart_id}/protocol-recommendations/{recommendation_id}",
        headers=HEADERS,
        json={"state": "accepted"},
    )
    assert protocol_update_response.status_code == 200
    assert protocol_update_response.json()["state"] == "accepted"

    derived_output_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/derived-outputs",
        headers=HEADERS,
        json={"output_type": "narrative"},
    )
    assert derived_output_response.status_code == 201
    assert "CareGraph narrative" in derived_output_response.json()["content_text"]

    dashboard_response = client.get(
        f"/api/v1/epcr/charts/{chart_id}/dashboard",
        headers=HEADERS,
    )
    assert dashboard_response.status_code == 200
    payload = dashboard_response.json()
    assert payload["intervention_count"] == 1
    assert payload["accepted_note_count"] == 1
    assert payload["derived_output_count"] == 1


def test_patient_vitals_impression_and_medication_authority_flow(client: TestClient):
    """Patient profile, vitals, impressions, and medications should round-trip through API authority."""
    chart_id = _create_chart(client)

    patient_response = client.put(
        f"/api/v1/epcr/charts/{chart_id}/patient-profile",
        headers=HEADERS,
        json={
            "first_name": "Jordan",
            "last_name": "Carter",
            "date_of_birth": "1987-06-18",
            "age_years": 38,
            "sex": "female",
            "phone_number": "5550102",
            "weight_kg": 72.4,
            "allergies": ["penicillin", "latex"],
        },
    )
    assert patient_response.status_code == 200
    assert patient_response.json()["allergies"] == ["penicillin", "latex"]

    vital_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/vitals",
        headers=HEADERS,
        json={
            "bp_sys": 146,
            "bp_dia": 88,
            "hr": 112,
            "rr": 24,
            "temp_f": 99.1,
            "spo2": 93,
            "glucose": 124,
            "recorded_at": "2026-04-21T14:35:00+00:00",
        },
    )
    assert vital_response.status_code == 201
    vital_id = vital_response.json()["id"]

    update_vital_response = client.patch(
        f"/api/v1/epcr/charts/{chart_id}/vitals/{vital_id}",
        headers=HEADERS,
        json={"spo2": 96},
    )
    assert update_vital_response.status_code == 200
    assert update_vital_response.json()["spo2"] == 96

    impression_response = client.put(
        f"/api/v1/epcr/charts/{chart_id}/clinical-impression",
        headers=HEADERS,
        json={
            "chief_complaint": "Shortness of breath",
            "field_diagnosis": "Acute asthma exacerbation",
            "primary_impression": "Respiratory distress",
            "secondary_impression": "Hypoxemia",
            "impression_notes": "Improved after nebulized therapy and coached ventilation.",
            "snomed_code": "271825005",
            "icd10_code": "J45.901",
            "acuity": "high",
        },
    )
    assert impression_response.status_code == 200
    assert impression_response.json()["primary_impression"] == "Respiratory distress"

    medication_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/medications",
        headers=HEADERS,
        json={
            "medication_name": "Albuterol",
            "rxnorm_code": "435",
            "dose_value": "2.5",
            "dose_unit": "mg",
            "route": "nebulized",
            "indication": "Bronchospasm",
            "administered_at": "2026-04-21T14:38:00+00:00",
        },
    )
    assert medication_response.status_code == 201
    medication_id = medication_response.json()["id"]

    medication_update_response = client.patch(
        f"/api/v1/epcr/charts/{chart_id}/medications/{medication_id}",
        headers=HEADERS,
        json={"response": "Breath sounds improved", "export_state": "mapped_ready"},
    )
    assert medication_update_response.status_code == 200
    assert medication_update_response.json()["export_state"] == "mapped_ready"

    patient_get_response = client.get(f"/api/v1/epcr/charts/{chart_id}/patient-profile", headers=HEADERS)
    assert patient_get_response.status_code == 200
    assert patient_get_response.json()["first_name"] == "Jordan"

    vitals_list_response = client.get(f"/api/v1/epcr/charts/{chart_id}/vitals", headers=HEADERS)
    assert vitals_list_response.status_code == 200
    assert vitals_list_response.json()["count"] == 1

    impression_get_response = client.get(f"/api/v1/epcr/charts/{chart_id}/clinical-impression", headers=HEADERS)
    assert impression_get_response.status_code == 200
    assert impression_get_response.json()["acuity"] == "high"

    medications_list_response = client.get(f"/api/v1/epcr/charts/{chart_id}/medications", headers=HEADERS)
    assert medications_list_response.status_code == 200
    assert medications_list_response.json()["count"] == 1

    derived_output_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/derived-outputs",
        headers=HEADERS,
        json={"output_type": "clinical_summary"},
    )
    assert derived_output_response.status_code == 201
    assert "Jordan Carter" in derived_output_response.json()["content_text"]
    assert "Albuterol" in derived_output_response.json()["content_text"]

    dashboard_response = client.get(f"/api/v1/epcr/charts/{chart_id}/dashboard", headers=HEADERS)
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["patient_profile_present"] is True
    assert dashboard["vitals_count"] == 1
    assert dashboard["medication_count"] == 1
    assert dashboard["impression_documented"] is True


def test_signature_artifact_authority_flow_updates_dashboard_and_derived_outputs(client: TestClient):
    """Signature artifacts should affect dashboard readiness and appear in derived outputs."""
    chart_id = _create_chart(client)

    blocked_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/signatures",
        headers=HEADERS,
        json={
            "client_reference_id": str(uuid4()),
            "signature_class": "patient_refusal",
            "signature_method": "electronic",
            "patient_capable_to_sign": True,
        },
    )
    assert blocked_response.status_code == 201
    blocked_payload = blocked_response.json()
    assert blocked_payload["compliance_decision"] == "blocked_missing_requirements"
    assert "signature_artifact_data_url" in blocked_payload["missing_requirements"]

    dashboard_response = client.get(f"/api/v1/epcr/charts/{chart_id}/dashboard", headers=HEADERS)
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["chart_completion_blocked_by_signature"] is True
    assert dashboard_response.json()["signature_count"] == 1

    update_response = client.patch(
        f"/api/v1/epcr/charts/{chart_id}/signatures/{blocked_payload['id']}",
        headers=HEADERS,
        json={
            "signature_artifact_data_url": "data:image/png;base64,ZmFrZXNpZw==",
            "signer_identity": "Jordan Carter",
            "signer_relationship": "self",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["compliance_decision"] == "captured_compliant"

    ingest_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/signatures/ingest",
        headers=HEADERS,
        json={
            "signature_capture_id": str(uuid4()),
            "source_domain": "crewlink",
            "signature_class": "transfer_of_care",
            "signature_method": "electronic",
            "workflow_policy": "electronic_allowed",
            "policy_pack_version": "crewlink.signature.v1",
            "payer_class": "ems_transport",
            "receiving_facility": "Memorial ED",
            "receiving_clinician_name": "Nurse Lane",
            "receiving_role_title": "RN",
            "transfer_of_care_time": "2026-04-21T15:12:00+00:00",
            "signature_artifact_data_url": "data:image/png;base64,dHJhbnNmZXI=",
            "decision": "captured_compliant",
            "decision_why": "Receiving clinician accepted transfer electronically.",
            "billing_readiness_effect": "ready",
            "chart_completion_effect": "complete",
        },
    )
    assert ingest_response.status_code == 201
    assert ingest_response.json()["signature_class"] == "transfer_of_care"

    signatures_response = client.get(f"/api/v1/epcr/charts/{chart_id}/signatures", headers=HEADERS)
    assert signatures_response.status_code == 200
    assert signatures_response.json()["count"] == 2

    derived_output_response = client.post(
        f"/api/v1/epcr/charts/{chart_id}/derived-outputs",
        headers=HEADERS,
        json={"output_type": "handoff"},
    )
    assert derived_output_response.status_code == 201
    assert "signatures" in derived_output_response.json()["content_text"]

    final_dashboard = client.get(f"/api/v1/epcr/charts/{chart_id}/dashboard", headers=HEADERS)
    assert final_dashboard.status_code == 200
    assert final_dashboard.json()["chart_completion_blocked_by_signature"] is False
    assert final_dashboard.json()["signature_count"] == 2
