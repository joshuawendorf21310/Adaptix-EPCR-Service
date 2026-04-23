"""Tests for NEMSIS validation persistence and patient state timeline.

Verifies real database persistence, validation blocking logic, and
immutable timeline recording.
"""
import pytest
from datetime import datetime, UTC
from sqlalchemy import create_engine, Column, String
from sqlalchemy.orm import Session, sessionmaker

# Use direct model imports
import sys
sys.path.insert(0, ".")

from epcr_app.models_nemsis_validation import (
    Base as ValidationBase,
    NEMSISValidationResult,
    NEMSISValidationError,
    NEMSISExportJob,
    ValidationStatus,
)
from epcr_app.models_timeline import Base as TimelineBase, PatientStateTimeline
from epcr_app.repositories_nemsis_validation import NEMSISValidationRepository
from epcr_app.repositories_timeline import PatientStateTimelineRepository
from epcr_app.services_nemsis_validation import NEMSISValidationService
from epcr_app.services_timeline import PatientStateTimelineService


# Create mock epcr_charts table in both bases
class MockChart(ValidationBase):
    __tablename__ = 'epcr_charts'
    id = Column(String(36), primary_key=True)


class MockChartTimeline(TimelineBase):
    __tablename__ = 'epcr_charts'
    id = Column(String(36), primary_key=True)


@pytest.fixture
def db_session():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    
    # Create all tables from both bases
    ValidationBase.metadata.create_all(engine, checkfirst=True)
    TimelineBase.metadata.create_all(engine, checkfirst=True)
    
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    # Create a mock chart for foreign key constraints
    session.execute(
        MockChart.__table__.insert().values(id="test-incident-456")
    )
    session.commit()
    
    yield session
    session.close()


def test_nemsis_validation_persistence(db_session: Session):
    """Test NEMSIS validation result persistence."""
    repo = NEMSISValidationRepository(db_session)

    tenant_id = "test-tenant-123"
    incident_id = "test-incident-456"
    user_id = "test-user-789"

    errors = [
        {
            "element_id": "eResponse.01",
            "error_code": "MISSING_REQUIRED",
            "message": "Agency Number is required",
            "field_path": "agency_number",
        }
    ]

    warnings = [
        {
            "element_id": "eVitals.26",
            "error_code": "OPTIONAL_MISSING",
            "message": "Patient Weight is recommended",
            "field_path": "patient_weight",
        }
    ]

    summary = {"total_errors": 1, "total_warnings": 1}

    # Save validation result
    result = repo.save_validation_result(
        tenant_id=tenant_id,
        incident_id=incident_id,
        validation_status=ValidationStatus.FAIL.value,
        errors=errors,
        warnings=warnings,
        summary=summary,
        created_by_user_id=user_id,
    )

    assert result.id is not None
    assert result.tenant_id == tenant_id
    assert result.incident_id == incident_id
    assert result.validation_status == ValidationStatus.FAIL.value
    assert result.error_count == 1
    assert result.warning_count == 1

    # Verify errors were saved
    saved_errors = repo.get_validation_errors(tenant_id=tenant_id, result_id=result.id)
    assert len(saved_errors) == 2  # 1 error + 1 warning
    
    # Find error and warning
    error_found = any(e.severity == "error" for e in saved_errors)
    warning_found = any(e.severity == "warning" for e in saved_errors)
    assert error_found, "Error record not found"
    assert warning_found, "Warning record not found"


def test_nemsis_validation_history(db_session: Session):
    """Test validation history retrieval."""
    repo = NEMSISValidationRepository(db_session)

    tenant_id = "test-tenant-123"
    incident_id = "test-incident-456"
    user_id = "test-user-789"

    # Create multiple validation runs
    for i in range(3):
        repo.save_validation_result(
            tenant_id=tenant_id,
            incident_id=incident_id,
            validation_status=ValidationStatus.PASS.value if i == 2 else ValidationStatus.FAIL.value,
            errors=[],
            warnings=[],
            summary={},
            created_by_user_id=user_id,
        )

    # Get history
    history = repo.list_validation_history(tenant_id=tenant_id, incident_id=incident_id)

    assert len(history) == 3
    # Should be ordered by newest first
    assert history[0].validation_status == ValidationStatus.PASS.value
    assert history[1].validation_status == ValidationStatus.FAIL.value


def test_nemsis_export_blocking(db_session: Session):
    """Test export blocking logic based on validation."""
    service = NEMSISValidationService(db_session)

    tenant_id = "test-tenant-123"
    incident_id = "test-incident-456"
    user_id = "test-user-789"

    # Run validation with errors
    incident_data = {
        "agency_name": "",  # Missing required field
        "patient_age": 45,
    }

    result = service.run_validation(
        tenant_id=tenant_id,
        incident_id=incident_id,
        incident_data=incident_data,
        user_id=user_id,
    )

    assert result.validation_status == ValidationStatus.FAIL.value
    assert result.error_count > 0

    # Check export blocking
    is_blocked, reason = service.block_export_if_invalid(
        tenant_id=tenant_id, incident_id=incident_id
    )

    assert is_blocked is True
    assert "error" in reason.lower()


def test_nemsis_export_job_tracking(db_session: Session):
    """Test export job creation and status updates."""
    repo = NEMSISValidationRepository(db_session)

    tenant_id = "test-tenant-123"
    incident_id = "test-incident-456"
    user_id = "test-user-789"

    # Create export job
    job = repo.create_export_job(
        tenant_id=tenant_id,
        incident_id=incident_id,
        validation_result_id=None,
        created_by_user_id=user_id,
    )

    assert job.id is not None
    assert job.status == "pending"
    assert job.retry_count == 0

    # Update status
    updated_job = repo.update_export_job_status(
        tenant_id=tenant_id,
        job_id=job.id,
        status="exporting",
        s3_bucket="test-bucket",
        s3_key="exports/test.xml",
    )

    assert updated_job.status == "exporting"
    assert updated_job.s3_bucket == "test-bucket"
    assert updated_job.started_at is not None


def test_patient_state_timeline_append(db_session: Session):
    """Test patient state timeline append-only recording."""
    repo = PatientStateTimelineRepository(db_session)

    tenant_id = "test-tenant-123"
    incident_id = "test-incident-456"
    patient_id = "test-patient-789"
    user_id = "test-user-abc"

    # Append state transitions
    entry1 = repo.append_state_transition(
        tenant_id=tenant_id,
        incident_id=incident_id,
        patient_id=patient_id,
        state_name="patient_added",
        changed_by=user_id,
    )

    entry2 = repo.append_state_transition(
        tenant_id=tenant_id,
        incident_id=incident_id,
        patient_id=patient_id,
        state_name="vitals_recorded",
        prior_state="patient_added",
        changed_by=user_id,
        entity_type="vital",
        entity_id="vital-123",
    )

    assert entry1.id is not None
    assert entry2.id is not None
    assert entry1.state_name == "patient_added"
    assert entry2.state_name == "vitals_recorded"


def test_patient_state_timeline_retrieval(db_session: Session):
    """Test timeline retrieval with ordering."""
    service = PatientStateTimelineService(db_session)

    tenant_id = "test-tenant-123"
    incident_id = "test-incident-456"
    patient_id = "test-patient-789"
    user_id = "test-user-abc"

    # Record multiple state changes
    service.record_patient_added(
        tenant_id=tenant_id,
        incident_id=incident_id,
        patient_id=patient_id,
        user_id=user_id,
    )

    service.record_vitals_recorded(
        tenant_id=tenant_id,
        incident_id=incident_id,
        patient_id=patient_id,
        vital_id="vital-123",
        user_id=user_id,
    )

    service.record_intervention_performed(
        tenant_id=tenant_id,
        incident_id=incident_id,
        patient_id=patient_id,
        intervention_id="intervention-456",
        user_id=user_id,
    )

    # Get full timeline
    timeline = service.get_timeline(
        tenant_id=tenant_id, incident_id=incident_id, patient_id=patient_id
    )

    assert len(timeline) == 3
    assert timeline[0].state_name == "patient_added"
    assert timeline[1].state_name == "vitals_recorded"
    assert timeline[2].state_name == "intervention_performed"


def test_patient_state_timeline_immutability(db_session: Session):
    """Test that timeline records are immutable (no version or deleted_at)."""
    repo = PatientStateTimelineRepository(db_session)

    tenant_id = "test-tenant-123"
    incident_id = "test-incident-456"
    user_id = "test-user-abc"

    entry = repo.append_state_transition(
        tenant_id=tenant_id,
        incident_id=incident_id,
        patient_id=None,
        state_name="incident_created",
        changed_by=user_id,
    )

    # Verify no version or deleted_at columns
    assert not hasattr(entry, "version")
    assert not hasattr(entry, "deleted_at")


def test_validation_service_real_logic(db_session: Session):
    """Test validation service with real NEMSIS rules."""
    service = NEMSISValidationService(db_session)

    tenant_id = "test-tenant-123"
    incident_id = "test-incident-456"
    user_id = "test-user-789"

    # Test with missing required fields
    incident_data = {
        "agency_name": "",
        "dispatch_notified_time": "",
        "scene_gps_latitude": None,
    }

    result = service.run_validation(
        tenant_id=tenant_id,
        incident_id=incident_id,
        incident_data=incident_data,
        user_id=user_id,
    )

    assert result.validation_status == ValidationStatus.FAIL.value
    assert result.error_count >= 3  # At least 3 missing required fields

    # Test with valid data
    valid_data = {
        "agency_name": "Test Agency",
        "agency_number": "12345",
        "dispatch_notified_time": "2026-04-23T10:00:00Z",
        "unit_enroute_time": "2026-04-23T10:05:00Z",
        "arrival_at_scene_time": "2026-04-23T10:15:00Z",
        "scene_gps_latitude": "40.7128",
        "scene_gps_longitude": "-74.0060",
        "dispatch_reason": "Medical emergency",
        "patient_age": 45,
        "patient_gender": "male",
    }

    result2 = service.run_validation(
        tenant_id=tenant_id,
        incident_id=incident_id,
        incident_data=valid_data,
        user_id=user_id,
    )

    assert result2.validation_status in [ValidationStatus.PASS.value, ValidationStatus.WARNING.value]
    assert result2.error_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
