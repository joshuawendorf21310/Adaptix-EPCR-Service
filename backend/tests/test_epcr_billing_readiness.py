from epcr_app.billing_readiness_service import BillingReadinessService


def test_billing_readiness_service_exists():
    svc = BillingReadinessService()
    assert svc is not None


def test_incomplete_chart_not_ready():
    svc = BillingReadinessService()
    result = svc.assess(chart_id='test-chart-1', tenant_id='test-tenant', chart_data={})
    assert result.ready_for_billing is False
    assert len(result.missing_billing_fields) > 0


def test_complete_chart_ready():
    svc = BillingReadinessService()
    result = svc.assess(chart_id='test-chart-2', tenant_id='test-tenant', chart_data={'patient_name': 'Test Patient', 'date_of_birth': '1980-01-01', 'incident_date': '2026-05-03', 'chief_complaint': 'chest pain', 'clinical_impression': 'ACS', 'disposition': 'transported', 'origin': '123 Main St', 'destination': 'City Hospital', 'level_of_care': 'ALS', 'payer': 'Medicare', 'member_id': '1234567890A', 'medical_necessity_reason': 'ALS transport cardiac emergency'})
    assert result.ready_for_billing is True
    assert result.human_review_required is True


def test_always_requires_human_review():
    svc = BillingReadinessService()
    result = svc.assess(chart_id='test-chart-3', tenant_id='test-tenant', chart_data={'patient_name': 'Test'})
    assert result.human_review_required is True
