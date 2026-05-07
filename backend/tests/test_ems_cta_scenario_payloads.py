"""Regression tests for the 2025 EMS CTA scenario submission path.

The 2025 EMS CTA scenarios (`2025_EMS_1` .. `2025_EMS_5`) must submit
the baked CTA `EMSDataSet` XML verbatim. They must NOT flow through the
EMS template registry (`build_nemsis_xml_from_template` /
`_build_template_resolved_xml`) because that registry mutates clinical
key fields and TAC rejects the result with `soap_response_code=-16`
("Incorrect test case provided. Key data elements must match a test
case.").

These tests pin the behavior:

  * Each EMS scenario produces XML whose root is `<EMSDataSet>`.
  * Each EMS scenario loads the baked CTA file from the resolver
    template-root chain (the same chain DEM uses).
  * Stamping replaces only safe runtime identifiers (UUIDs,
    eRecord.01-04). Scenario-defining clinical key fields (chief
    complaint, dispatch type, patient age/sex, conditions, medications,
    allergies, procedures, etc.) are preserved exactly as in the baked
    CTA file.
  * The EMS template registry is never invoked for 2025 EMS CTA
    scenarios. (Critical regression guard for the `-16` fix.)
  * Stamping yields fresh UUIDs / identifiers per call.
  * DEM still resolves through `<DEMDataSet>`.
  * Missing baked CTA XML returns HTTP 422, not 500.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest
from fastapi import HTTPException

from epcr_app import api_nemsis_scenarios as scenarios_module


NEMSIS_NS = "http://www.nemsis.org"

EMS_SCENARIO_CODES = (
    "2025_EMS_1",
    "2025_EMS_2",
    "2025_EMS_3",
    "2025_EMS_4",
    "2025_EMS_5",
)


def _find_scenario_or_skip(scenario_code: str) -> dict[str, Any]:
    scenario = scenarios_module._find_scenario(scenario_code)
    if scenario is None:
        pytest.skip(f"scenario {scenario_code} not registered in this build")
    return scenario


@pytest.mark.parametrize("scenario_code", EMS_SCENARIO_CODES)
def test_ems_scenario_root_is_ems_dataset(scenario_code: str) -> None:
    scenario = _find_scenario_or_skip(scenario_code)
    assert scenario["category"] == "EMS"

    xml_bytes = scenarios_module._generate_pretesting_xml_or_500(
        scenario_code, scenario
    )
    assert xml_bytes, f"{scenario_code} must produce non-empty XML"

    root = ET.fromstring(xml_bytes)
    assert root.tag == f"{{{NEMSIS_NS}}}EMSDataSet", (
        f"{scenario_code}: submitted XML must preserve <EMSDataSet> "
        f"root; got {root.tag!r}"
    )


@pytest.mark.parametrize("scenario_code", EMS_SCENARIO_CODES)
def test_ems_scenario_does_not_invoke_template_registry(
    scenario_code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The EMS template registry mutates CTA key fields, which TAC
    rejects with -16. 2025 EMS CTA scenarios must bypass it entirely."""
    scenario = _find_scenario_or_skip(scenario_code)

    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            f"{scenario_code} must not invoke the EMS template registry"
        )

    monkeypatch.setattr(
        scenarios_module, "build_nemsis_xml_from_template", _fail
    )
    monkeypatch.setattr(
        scenarios_module, "_build_template_resolved_xml", _fail
    )

    xml_bytes = scenarios_module._generate_pretesting_xml_or_500(
        scenario_code, scenario
    )
    root = ET.fromstring(xml_bytes)
    assert root.tag == f"{{{NEMSIS_NS}}}EMSDataSet"


@pytest.mark.parametrize("scenario_code", EMS_SCENARIO_CODES)
def test_ems_scenario_preserves_baked_cta_key_fields(scenario_code: str) -> None:
    """Stamping must not mutate any scenario-defining clinical key
    field. Compare baked CTA XML to generated XML element-by-element
    after stripping the explicitly-stamped runtime identifiers."""
    scenario = _find_scenario_or_skip(scenario_code)

    baked = scenarios_module._load_baked_cta_xml(scenario)
    assert baked is not None, f"{scenario_code}: baked CTA XML must exist"

    generated = scenarios_module._generate_pretesting_xml_or_500(
        scenario_code, scenario
    ).decode("utf-8")

    # Normalize the only fields the stamping pass is allowed to touch.
    def _normalize(text: str) -> str:
        # UUID attributes
        text = re.sub(r'UUID="[^"]*"', 'UUID="X"', text)
        # eRecord.01-04 (record number + software identity)
        for tag in ("eRecord.01", "eRecord.02", "eRecord.03", "eRecord.04"):
            text = re.sub(
                rf"<{tag}>[^<]*</{tag}>", f"<{tag}>X</{tag}>", text
            )
        # DEMDataSet only: DemographicReport timestamp
        text = re.sub(
            r'DemographicReport\s+timeStamp="[^"]*"',
            'DemographicReport timeStamp="X"',
            text,
        )
        return text

    assert _normalize(baked) == _normalize(generated), (
        f"{scenario_code}: generated EMS XML diverges from baked CTA "
        "XML in fields outside the stamping allow-list. TAC will "
        "reject with -16."
    )


@pytest.mark.parametrize("scenario_code", EMS_SCENARIO_CODES)
def test_ems_scenario_stamps_fresh_uuids(scenario_code: str) -> None:
    scenario = _find_scenario_or_skip(scenario_code)
    a = scenarios_module._generate_pretesting_xml_or_500(scenario_code, scenario)
    b = scenarios_module._generate_pretesting_xml_or_500(scenario_code, scenario)
    assert a != b, (
        f"{scenario_code}: stamping must yield distinct UUIDs / "
        "identifiers per submission"
    )


def test_dem_still_uses_dem_dataset_path() -> None:
    """Regression guard: the EMS fix must not break DEM."""
    scenario = _find_scenario_or_skip("2025_DEM_1")
    xml_bytes = scenarios_module._generate_pretesting_xml_or_500(
        "2025_DEM_1", scenario
    )
    root = ET.fromstring(xml_bytes)
    assert root.tag == f"{{{NEMSIS_NS}}}DEMDataSet"


def test_missing_baked_cta_xml_returns_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
