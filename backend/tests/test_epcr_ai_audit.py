from epcr_app.narrative_review_service import NarrativeReviewService, NarrativeReviewAction


def test_narrative_review_service_exists():
    svc = NarrativeReviewService()
    assert svc is not None


def test_record_accepted_action():
    svc = NarrativeReviewService()
    record = svc.record_action(chart_id='test-chart-1', generation_id='gen-1', tenant_id='test-tenant', actor_id='test-actor', action=NarrativeReviewAction.ACCEPTED, original_text='Draft narrative text', final_text='Draft narrative text')
    assert record.action == NarrativeReviewAction.ACCEPTED
    assert record.chart_auto_locked is False


def test_record_edited_action():
    svc = NarrativeReviewService()
    record = svc.record_action(chart_id='test-chart-2', generation_id='gen-2', tenant_id='test-tenant', actor_id='test-actor', action=NarrativeReviewAction.EDITED, original_text='Original draft', final_text='Edited by clinician', edit_summary='Corrected medication dosage')
    assert record.action == NarrativeReviewAction.EDITED
    assert record.edit_summary == 'Corrected medication dosage'


def test_no_phi_logged():
    svc = NarrativeReviewService()
    record = svc.record_action(chart_id='test-chart-3', generation_id='gen-3', tenant_id='test-tenant', actor_id='test-actor', action=NarrativeReviewAction.REJECTED)
    assert record.phi_logged is False
    assert record.prompt_logged is False
    assert record.completion_logged is False


def test_chart_never_auto_locked():
    svc = NarrativeReviewService()
    for action in NarrativeReviewAction:
        record = svc.record_action(chart_id='test-chart-4', generation_id='gen-4', tenant_id='test-tenant', actor_id='test-actor', action=action)
        assert record.chart_auto_locked is False, f"Chart was auto-locked for action {action}"
