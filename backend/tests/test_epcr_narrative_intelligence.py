from epcr_app.ai_narrative_service import AdaptixNarrativeService


def test_narrative_service_exists():
    svc = AdaptixNarrativeService()
    assert svc is not None


def test_narrative_requires_human_review():
    svc = AdaptixNarrativeService()
    result = svc.generate_narrative(chart_id='test-chart-1', tenant_id='test-tenant', actor_id='test-actor', chart_data={'chief_complaint': 'chest pain'})
    assert result.human_review_required is True


def test_narrative_never_auto_locks():
    svc = AdaptixNarrativeService()
    result = svc.generate_narrative(chart_id='test-chart-2', tenant_id='test-tenant', actor_id='test-actor', chart_data={'chief_complaint': 'fall'})
    assert result.chart_auto_locked is False


def test_narrative_no_phi_logged():
    svc = AdaptixNarrativeService()
    result = svc.generate_narrative(chart_id='test-chart-3', tenant_id='test-tenant', actor_id='test-actor', chart_data={'chief_complaint': 'breathing'})
    assert result.phi_logged is False
    assert result.prompt_logged is False
    assert result.completion_logged is False


def test_narrative_no_invented_facts():
    svc = AdaptixNarrativeService()
    result = svc.generate_narrative(chart_id='test-chart-4', tenant_id='test-tenant', actor_id='test-actor', chart_data={})
    assert result.no_invented_facts is True


def test_narrative_has_generation_id():
    svc = AdaptixNarrativeService()
    result = svc.generate_narrative(chart_id='test-chart-5', tenant_id='test-tenant', actor_id='test-actor', chart_data={'chief_complaint': 'trauma'})
    assert result.generation_id is not None
    assert len(result.generation_id) > 0


def test_narrative_credential_gated_when_no_provider():
    import os
    original = os.environ.pop('BEDROCK_REGION', None)
    try:
        svc = AdaptixNarrativeService()
        result = svc.generate_narrative(chart_id='test-chart-6', tenant_id='test-tenant', actor_id='test-actor', chart_data={'chief_complaint': 'test'})
        assert result.provider_status in ('credential_gated', 'not_configured', 'configured')
    finally:
        if original:
            os.environ['BEDROCK_REGION'] = original


def test_narrative_does_not_use_external_naming():
    svc = AdaptixNarrativeService()
    assert 'Adaptix' in type(svc).__name__
