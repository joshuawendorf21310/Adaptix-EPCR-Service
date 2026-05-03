"""Tests for Adaptix ePCR Narrative Intelligence AI service."""
import pytest
from epcr_app.ai_narrative_service import EPCRNarrativeIntelligenceService


def test_assess_returns_result():
    svc = EPCRNarrativeIntelligenceService()
    result = svc.assess("rec-001", "tenant-001", "actor-001", {})
    assert result.assessment_id is not None
    assert result.record_id == "rec-001"
    assert result.tenant_id == "tenant-001"


def test_ai_never_signs():
    svc = EPCRNarrativeIntelligenceService()
    result = svc.assess("rec-001", "tenant-001", "actor-001", {})
    assert result.ai_signed is False
    assert result.ai_marked_complete is False
    assert result.ai_dispatched_resources is False


def test_audit_fields_present():
    svc = EPCRNarrativeIntelligenceService()
    result = svc.assess("rec-001", "tenant-001", "actor-001", {})
    assert result.audit_event_id is not None
    assert result.correlation_id is not None
    assert result.created_at is not None


def test_credential_gated_when_no_ai_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    svc = EPCRNarrativeIntelligenceService()
    assert svc._ai_available is False
    # Should still return a result (rule-based)
    result = svc.assess("rec-001", "tenant-001", "actor-001", {})
    assert result is not None
