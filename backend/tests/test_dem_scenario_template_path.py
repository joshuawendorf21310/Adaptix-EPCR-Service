"""Regression tests for the DEM CTA scenario template path.

The 2025 DEM CTA scenario (`2025_DEM_1` / template id `2025-DEM-1_v351`)
is **not** modeled by the EMS template registry inside
`nemsis_template_resolver.py`. Submitting it through the EMS registry
path raises `ValueError("Unsupported TAC test case id: ...")` which
previously surfaced as an HTTP 500.

These tests pin the corrected behavior:

  * DEM scenarios load the baked CTA `DEMDataSet` XML directly and DO
    NOT call into `build_nemsis_xml_from_template` (the EMS pipeline).
  * The XML payload submitted for a DEM scenario has `<DEMDataSet>` as
    its root element.
  * 2025 EMS CTA scenarios likewise load the baked CTA `EMSDataSet`
    XML directly and DO NOT call the EMS template registry, so the
    scenario-defining clinical key fields TAC checks survive verbatim
    (this is what eliminates `soap_response_code=-16`).
  * An unsupported / missing CTA template surfaces as HTTP 422 with a
    structured `code: unsupported_tac_test_case` body, never an
    uncaught 500.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import pytest
from fastapi import HTTPException

from epcr_app import api_nemsis_scenarios as scenarios_module


NEMSIS_NS = "http://www.nemsis.org"


def _find_scenario_or_skip(scenario_code: str) -> dict[str, Any]:
    scenario = scenarios_module._find_scenario(scenario_code)
    if scenario is None:
        pytest.skip(f"scenario {scenario_code} not registered in this build")
    return scenario


def test_dem_scenario_resolves_through_dem_dataset_path() -> None:
    """`2025_DEM_1` must load the baked CTA DEMDataSet XML directly."""
    scenario = _find_scenario_or_skip("2025_DEM_1")
    assert scenario["category"] == "DEM"

    xml_bytes = scenarios_module._generate_pretesting_xml_or_500(
        "2025_DEM_1", scenario
    )
    assert xml_bytes, "DEM scenario must produce non-empty XML payload"

    root = ET.fromstring(xml_bytes)
    assert root.tag == f"{{{NEMSIS_NS}}}DEMDataSet", (
        "DEM scenario submission must preserve <DEMDataSet> as the root "
        f"element; got {root.tag!r}"
    )


def test_dem_scenario_does_not_use_ems_template_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEM scenarios must skip the EMS `build_nemsis_xml_from_template`
    pipeline entirely."""
    scenario = _find_scenario_or_skip("2025_DEM_1")

    calls: list[str] = []

    def _fail(*_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover
        calls.append("called")
        raise AssertionError(
            "DEM scenario must not invoke the EMS template registry"
        )

    monkeypatch.setattr(
        scenarios_module, "build_nemsis_xml_from_template", _fail
    )
    # The internal helper that wraps it must also stay untouched for DEM.
    monkeypatch.setattr(
        scenarios_module, "_build_template_resolved_xml", _fail
    )

    scenarios_module._generate_pretesting_xml_or_500("2025_DEM_1", scenario)
    assert calls == [], "EMS template registry must not be called for DEM"


def test_unsupported_tac_test_case_returns_422_when_baked_xml_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the baked CTA XML cannot be loaded for a 2025 CTA scenario,
    `_generate_pretesting_xml_or_500` must surface a structured HTTP
    422, never an uncaught 500."""
    scenario = _find_scenario_or_skip("2025_EMS_1")

    monkeypatch.setattr(
        scenarios_module, "_load_baked_cta_xml", lambda _s: None
    )

    with pytest.raises(HTTPException) as excinfo:
        scenarios_module._generate_pretesting_xml_or_500(
            "2025_EMS_1", scenario
        )

    assert excinfo.value.status_code == 422
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "unsupported_tac_test_case"
    assert detail["scenario_id"] == "2025_EMS_1"
    assert detail["template_id"] == "2025-EMS-1-Allergy_v351"


def test_dem_scenario_xml_is_stamped_with_fresh_uuids() -> None:
    """DEM stamping (the 2026 pre-testing pattern) must replace UUID
    attributes so submissions are not duplicates."""
    scenario = _find_scenario_or_skip("2025_DEM_1")

    a = scenarios_module._generate_pretesting_xml_or_500("2025_DEM_1", scenario)
    b = scenarios_module._generate_pretesting_xml_or_500("2025_DEM_1", scenario)

    # Two stamping passes must not produce byte-identical payloads
    # because the UUID stamps and eRecord.01 timestamps must differ.
    assert a != b, "DEM stamping must yield distinct UUIDs/identifiers per call"
