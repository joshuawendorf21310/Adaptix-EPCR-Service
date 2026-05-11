"""Regression tests for structured CPAE/VAS/ARCOS clinical visual foundations."""
import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.models import Base
from epcr_app.services import ChartService
from tests.agency_helpers import seed_active_agency


@pytest_asyncio.fixture
async def test_db():
    """Create an isolated in-memory database for clinical visual tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as s:
        await seed_active_agency(s, tenant_id="tenant-clinical")
        await s.commit()

    yield async_session

    await engine.dispose()


async def _create_chart(session: AsyncSession):
    """Create a baseline chart for testing findings and overlays."""
    return await ChartService.create_chart(
        session=session,
        tenant_id="tenant-clinical",
        call_number="CALL-CLINICAL-001",
        incident_type="medical",
        created_by_user_id="clinician-001",
    )


@pytest.mark.asyncio
async def test_record_assessment_finding_success(test_db):
    """Structured findings should persist and keep characteristic evidence."""
    async with test_db() as session:
        chart = await _create_chart(session)

        finding = await ChartService.record_assessment_finding(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            finding_data={
                "anatomy": "thorax",
                "system": "respiratory",
                "finding_type": "wheezing",
                "severity": "moderate",
                "detection_method": "direct_visual_observation",
                "characteristics": ["diffuse", "expiratory"],
                "source_artifact_ids": ["image-1", "audio-2"],
            },
        )

        assert finding.chart_id == chart.id
        assert finding.system == "respiratory"
        assert json.loads(finding.characteristics_json) == ["diffuse", "expiratory"]
        assert json.loads(finding.source_artifact_ids_json) == ["image-1", "audio-2"]


@pytest.mark.asyncio
async def test_record_visual_overlay_requires_linked_finding(test_db):
    """Governed overlays must reference a real structured finding."""
    async with test_db() as session:
        chart = await _create_chart(session)

        with pytest.raises(ValueError, match="Finding .* not found"):
            await ChartService.record_visual_overlay(
                session=session,
                tenant_id="tenant-clinical",
                chart_id=chart.id,
                provider_id="clinician-001",
                overlay_data={
                    "finding_id": "missing-finding",
                    "patient_model": "adult",
                    "anatomical_view": "anterior",
                    "overlay_type": "heatmap",
                    "anchor_region": "thorax",
                    "geometry_reference": '{"x": 0.5, "y": 0.5}',
                    "severity": "moderate",
                },
            )


@pytest.mark.asyncio
async def test_start_ar_session_and_anchor_success(test_db):
    """ARCOS sessions should persist and support anatomical anchor capture."""
    async with test_db() as session:
        chart = await _create_chart(session)

        ar_session = await ChartService.start_ar_session(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            started_by_user_id="clinician-001",
            patient_model="adult",
            mode="guided_exam",
        )
        anchor = await ChartService.record_ar_anchor(
            session=session,
            tenant_id="tenant-clinical",
            session_id=ar_session.id,
            anchored_by_user_id="clinician-001",
            anatomy="head",
            anatomical_view="anterior",
            confidence=0.97,
        )

        assert ar_session.chart_id == chart.id
        assert ar_session.status.value == "active"
        assert anchor.session_id == ar_session.id
        assert anchor.confidence == pytest.approx(0.97)


@pytest.mark.asyncio
async def test_update_finding_overlay_and_complete_session(test_db):
    """Clinical visual records should support correction and session completion."""
    async with test_db() as session:
        chart = await _create_chart(session)

        finding = await ChartService.record_assessment_finding(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            finding_data={
                "anatomy": "head",
                "system": "neurological",
                "finding_type": "anisocoria",
                "severity": "moderate",
                "detection_method": "direct_visual_observation",
            },
        )
        updated_finding = await ChartService.update_assessment_finding(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            finding_id=finding.id,
            provider_id="clinician-001",
            update_data={
                "severity": "severe",
                "review_state": "edited_and_accepted",
                "characteristics": ["right pupil enlarged"],
            },
        )

        overlay = await ChartService.record_visual_overlay(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            overlay_data={
                "finding_id": finding.id,
                "patient_model": "adult",
                "anatomical_view": "anterior",
                "overlay_type": "heatmap",
                "anchor_region": "head",
                "geometry_reference": '{"x": 0.2, "y": 0.4}',
                "severity": "moderate",
            },
        )
        updated_overlay = await ChartService.update_visual_overlay(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            overlay_id=overlay.id,
            provider_id="clinician-001",
            update_data={
                "review_state": "accepted",
                "geometry_reference": '{"x": 0.25, "y": 0.45}',
            },
        )

        ar_session = await ChartService.start_ar_session(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            started_by_user_id="clinician-001",
            patient_model="adult",
            mode="guided_exam",
        )
        completed_session = await ChartService.complete_ar_session(
            session=session,
            tenant_id="tenant-clinical",
            session_id=ar_session.id,
            completed_by_user_id="clinician-001",
        )

        assert updated_finding.severity == "severe"
        assert updated_finding.review_state.value == "edited_and_accepted"
        assert json.loads(updated_finding.characteristics_json) == ["right pupil enlarged"]
        assert updated_overlay.review_state.value == "accepted"
        assert updated_overlay.geometry_reference == '{"x": 0.25, "y": 0.45}'
        assert completed_session.status.value == "completed"
        assert completed_session.ended_at is not None


@pytest.mark.asyncio
async def test_client_reference_ids_are_used_for_mobile_created_entities(test_db):
    """Service-layer create flows should honor deterministic mobile IDs when provided."""
    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id="tenant-clinical",
            call_number="CALL-CLINICAL-DET-001",
            incident_type="medical",
            created_by_user_id="clinician-001",
            client_reference_id="11111111-1111-1111-1111-111111111111",
        )
        assert chart.id == "11111111-1111-1111-1111-111111111111"

        finding = await ChartService.record_assessment_finding(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            finding_data={
                "client_reference_id": "22222222-2222-2222-2222-222222222222",
                "anatomy": "thorax",
                "system": "respiratory",
                "finding_type": "wheezing",
                "severity": "moderate",
                "detection_method": "direct_visual_observation",
            },
        )
        assert finding.id == "22222222-2222-2222-2222-222222222222"

        overlay = await ChartService.record_visual_overlay(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            overlay_data={
                "client_reference_id": "33333333-3333-3333-3333-333333333333",
                "finding_id": finding.id,
                "patient_model": "adult",
                "anatomical_view": "anterior",
                "overlay_type": "heatmap",
                "anchor_region": "thorax",
                "geometry_reference": '{"x": 0.5, "y": 0.5}',
                "severity": "moderate",
            },
        )
        assert overlay.id == "33333333-3333-3333-3333-333333333333"

        ar_session = await ChartService.start_ar_session(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            started_by_user_id="clinician-001",
            patient_model="adult",
            mode="guided_exam",
            client_reference_id="44444444-4444-4444-4444-444444444444",
        )
        assert ar_session.id == "44444444-4444-4444-4444-444444444444"


@pytest.mark.asyncio
async def test_chart_workflow_authority_surfaces_persist_and_derive_outputs(test_db):
    """Address, interventions, notes, protocol guidance, and derived outputs should persist as EPCR truth."""
    async with test_db() as session:
        chart = await _create_chart(session)

        await ChartService.record_assessment_finding(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            finding_data={
                "anatomy": "thorax",
                "system": "respiratory",
                "finding_type": "respiratory_distress",
                "severity": "critical",
                "detection_method": "direct_visual_observation",
            },
        )

        address = await ChartService.upsert_chart_address(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            address_data={
                "raw_text": "123 Main Street, Springfield, IL 62704",
                "street_line_one": "123 Main Street",
                "city": "Springfield",
                "state": "IL",
                "postal_code": "62704",
                "latitude": 39.7817,
                "longitude": -89.6501,
                "intelligence_source": "manual_entry",
            },
        )
        intervention = await ChartService.record_intervention(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            intervention_data={
                "client_reference_id": "55555555-5555-5555-5555-555555555555",
                "category": "airway",
                "name": "Bag-valve-mask ventilation",
                "indication": "Critical respiratory distress",
                "intent": "Support oxygenation and ventilation",
                "expected_response": "Improved chest rise and SpO2",
                "protocol_family": "acls",
                "snomed_code": "40617009",
            },
        )
        updated_intervention = await ChartService.update_intervention(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            intervention_id=intervention.id,
            provider_id="clinician-001",
            update_data={
                "actual_response": "SpO2 improved from 82 to 94 percent",
                "export_state": "mapped_ready",
            },
        )
        note = await ChartService.record_clinical_note(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            provider_id="clinician-001",
            note_data={
                "client_reference_id": "66666666-6666-6666-6666-666666666666",
                "raw_text": "Patient found upright, tripod position, speaking one-word sentences, cyanosis improving after assisted ventilation.",
                "source": "manual_entry",
                "provenance": {"mode": "touch"},
            },
        )
        reviewed_note = await ChartService.update_clinical_note(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            note_id=note.id,
            provider_id="clinician-001",
            update_data={"review_state": "accepted"},
        )
        recommendations = await ChartService.generate_protocol_recommendations(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            generated_by_user_id="clinician-001",
            patient_model="adult",
        )
        derived_output = await ChartService.generate_derived_output(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
            generated_by_user_id="clinician-001",
            output_type="narrative",
        )
        dashboard = await ChartService.get_dashboard_summary(
            session=session,
            tenant_id="tenant-clinical",
            chart_id=chart.id,
        )

        assert address.validation_state.value == "validated"
        assert updated_intervention.id == "55555555-5555-5555-5555-555555555555"
        assert updated_intervention.export_state.value == "mapped_ready"
        assert reviewed_note.id == "66666666-6666-6666-6666-666666666666"
        assert reviewed_note.review_state.value == "accepted"
        assert recommendations[0].protocol_family.value in {"acls", "general"}
        assert "CareGraph narrative" in derived_output.content_text
        assert dashboard["intervention_count"] == 1
        assert dashboard["accepted_note_count"] == 1
        assert dashboard["derived_output_count"] == 1
