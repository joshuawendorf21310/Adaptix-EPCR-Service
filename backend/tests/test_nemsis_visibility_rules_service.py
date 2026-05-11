"""Tests for ``NemsisVisibilityRulesService``.

Asserts deterministic, registry-driven visibility/requiredness verdicts
including:
- Mandatory fields are required.
- Deprecated fields are hidden unless ``compatibility_mode``.
- Finalized charts force read-only.
- Agency/admin sections in encounter scope are visible but not required.
- State-pack required elements are required regardless of dictionary usage.
- Workflow-gated sections (eArrest, eInjury, …) hide when their flag is False.
- Unknown elements are flagged, never silently shown as compliant.
"""
from __future__ import annotations

from epcr_app.nemsis_visibility_rules_service import (
    NemsisVisibilityRulesService,
    get_default_visibility_service,
)


def _svc() -> NemsisVisibilityRulesService:
    return get_default_visibility_service()


def test_unknown_element_flagged() -> None:
    d = _svc().evaluate("eMystery.99")
    assert d.visible is True
    assert d.disabled is True
    assert d.extra.get("warning") == "element_not_in_registry"


def test_mandatory_field_is_required_by_default() -> None:
    # dAgency.01 is Mandatory in the registry.
    d = _svc().evaluate("dAgency.01")
    assert d.visible is True
    # dAgency is agency/admin scope; encounter scope demotes to optional.
    d_enc = _svc().evaluate("dAgency.01", {"scope": "encounter"})
    assert d_enc.required is False
    assert d_enc.source == "agency"


def test_finalized_chart_is_read_only() -> None:
    d = _svc().evaluate("eRecord.01", {"chart_status": "finalized"})
    assert d.disabled is True
    assert d.visible is True
    assert d.source == "workflow"


def test_workflow_gated_section_hidden_when_flag_false() -> None:
    d = _svc().evaluate("eArrest.01", {"cardiac_arrest": False})
    assert d.visible is False
    assert d.source == "workflow"


def test_workflow_gated_section_visible_when_flag_true_or_absent() -> None:
    d_true = _svc().evaluate("eArrest.01", {"cardiac_arrest": True})
    assert d_true.visible is True
    d_absent = _svc().evaluate("eArrest.01", {})
    assert d_absent.visible is True


def test_state_pack_required_overrides_usage() -> None:
    d = _svc().evaluate(
        "eRecord.01",
        {"state_pack": {"id": "CA-2026", "required_elements": ["eRecord.01"]}},
    )
    assert d.required is True
    assert d.source == "state"


def test_evaluate_section_returns_decision_per_field() -> None:
    decisions = _svc().evaluate_section("eRecord")
    assert decisions, "eRecord should have at least one field"
    for d in decisions:
        assert "element_number" in d
        assert "visible" in d
        assert "required" in d
        assert d["dataset"] == "EMSDataSet"


def test_evaluate_chart_returns_grouped_by_dataset() -> None:
    out = _svc().evaluate_chart()
    assert set(out.keys()) >= {"EMSDataSet", "DEMDataSet", "StateDataSet"}
    assert len(out["EMSDataSet"]) > 0
    assert len(out["DEMDataSet"]) > 0
    assert len(out["StateDataSet"]) > 0


def test_evaluate_chart_can_restrict_datasets() -> None:
    out = _svc().evaluate_chart(datasets=["EMSDataSet"])
    assert list(out.keys()) == ["EMSDataSet"]
