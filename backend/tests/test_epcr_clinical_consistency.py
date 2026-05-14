from epcr_app.clinical_validation_service import ClinicalValidationService


def test_clinical_validation_service_exists():
    svc = ClinicalValidationService()
    assert svc is not None


def test_detects_medication_allergy_conflict():
    svc = ClinicalValidationService()
    result = svc.validate(chart_id='test-chart-1', tenant_id='test-tenant', actor_id='test-actor', chart_data={'medications': ['penicillin'], 'allergies': ['penicillin'], 'clinical_impression': 'respiratory distress'})
    assert any('penicillin' in c.description.lower() for c in result.contradictions)
    assert result.human_review_required is True


def test_detects_missing_required_fields():
    svc = ClinicalValidationService()
    result = svc.validate(chart_id='test-chart-2', tenant_id='test-tenant', actor_id='test-actor', chart_data={})
    assert len(result.missing_fields) > 0


def test_never_auto_locks_chart():
    svc = ClinicalValidationService()
    result = svc.validate(chart_id='test-chart-3', tenant_id='test-tenant', actor_id='test-actor', chart_data={'chief_complaint': 'test'})
    assert result.ai_may_not_auto_lock is True


def test_never_overwrites_facts():
    svc = ClinicalValidationService()
    result = svc.validate(chart_id='test-chart-4', tenant_id='test-tenant', actor_id='test-actor', chart_data={'chief_complaint': 'test'})
    assert result.ai_may_not_overwrite_facts is True


def test_clean_chart_no_contradictions():
    svc = ClinicalValidationService()
    result = svc.validate(chart_id='test-chart-5', tenant_id='test-tenant', actor_id='test-actor', chart_data={'patient_name': 'Test Patient', 'incident_date': '2026-05-03', 'dispatch_time': '10:00', 'arrival_time': '10:10', 'chief_complaint': 'chest pain', 'clinical_impression': 'ACS', 'disposition': 'transported', 'medications': ['aspirin'], 'allergies': ['penicillin']})
    assert len(result.contradictions) == 0
