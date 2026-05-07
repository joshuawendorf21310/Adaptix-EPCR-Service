"""Full 2025 CTA TAC case-matrix regression.

Pins behavior for the entire required NEMSIS 3.5.1 CTA test-case set
(`2025_DEM_1`, `2025_EMS_1`..`2025_EMS_5`):

  * All six scenarios are registered.
  * All six baked CTA XML files exist on disk and are readable via the
    resolver template-root chain.
  * Each scenario submits the baked CTA XML directly:
      - `2025_DEM_1` root is `<DEMDataSet>`.
      - `2025_EMS_1`..`2025_EMS_5` root is `<EMSDataSet>`.
  * Stamping replaces only safe runtime identifiers (UUID attributes,
    `eRecord.01-04`, DEM `DemographicReport@timeStamp`). Every other
    byte (clinical key fields TAC checks) is preserved verbatim.
  * Generated XML is parseable.
  * 2025 EMS scenarios bypass `_build_template_resolved_xml` and
    `build_nemsis_xml_from_template`. (Required for `-16` fix.)
  * Missing baked CTA XML returns HTTP 422 with structured detail,
    never an uncaught 500.
  * Repeated generation produces fresh UUIDs/identifiers.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest
from fastapi import HTTPException

from epcr_app import api_nemsis_scenarios as scenarios_module


NEMSIS_NS = "http://www.nemsis.org"

ALL_2025_CTA_CASES = (
    ("2025_DEM_1", "DEM", "DEMDataSet"),
    ("2025_EMS_1", "EMS", "EMSDataSet"),
    ("2025_EMS_2", "EMS", "EMSDataSet"),
    ("2025_EMS_3", "EMS", "EMSDataSet"),
    ("2025_EMS_4", "EMS", "EMSDataSet"),
    ("2025_EMS_5", "EMS", "EMSDataSet"),
)
EMS_CASES = tuple(c for c in ALL_2025_CTA_CASES if c[1] == "EMS")


def _scenario(scenario_code: str) -> dict[str, Any]:
    s = scenarios_module._find_scenario(scenario_code)
    if s is None:
        pytest.skip(f"scenario {scenario_code} not registered")
    return s


# 1. All six CTA cases are registered.
@pytest.mark.parametrize("scenario_code,_cat,_root", ALL_2025_CTA_CASES)
def test_scenario_registered(scenario_code: str, _cat: str, _root: str) -> None:
    s = scenarios_module._find_scenario(scenario_code)
    assert s is not None, f"{scenario_code} must be registered"
    assert s["scenario_code"] == scenario_code
    assert s["category"] == _cat


# 2. All six baked XML files exist.
@pytest.mark.parametrize("scenario_code,_cat,_root", ALL_2025_CTA_CASES)
def test_baked_cta_xml_exists(
    scenario_code: str, _cat: str, _root: str
) -> None:
    s = _scenario(scenario_code)
    raw = scenarios_module._load_baked_cta_xml(s)
    assert raw is not None, (
        f"{scenario_code}: baked CTA XML must be readable from the "
        "resolver template-root chain"
    )
    assert raw.lstrip().startswith("<?xml"), (
        f"{scenario_code}: baked CTA XML must begin with an XML declaration"
    )


# 3-8. DEM root is DEMDataSet; EMS roots are EMSDataSet.
@pytest.mark.parametrize("scenario_code,_cat,expected_root", ALL_2025_CTA_CASES)
def test_generated_root_matches_baked(
    scenario_code: str, _cat: str, expected_root: str
) -> None:
    s = _scenario(scenario_code)
    xml_bytes = scenarios_module._generate_pretesting_xml_or_500(
        scenario_code, s
    )
    root = ET.fromstring(xml_bytes)
    assert root.tag == f"{{{NEMSIS_NS}}}{expected_root}", (
        f"{scenario_code}: root must be <{expected_root}>; got {root.tag!r}"
    )


# 9. Repeated generation yields fresh UUIDs/identifiers.
@pytest.mark.parametrize("scenario_code,_cat,_root", ALL_2025_CTA_CASES)
def test_repeated_generation_is_fresh(
    scenario_code: str, _cat: str, _root: str
) -> None:
    s = _scenario(scenario_code)
    a = scenarios_module._generate_pretesting_xml_or_500(scenario_code, s)
    b = scenarios_module._generate_pretesting_xml_or_500(scenario_code, s)
    assert a != b, (
        f"{scenario_code}: stamping must yield distinct UUIDs / "
        "identifiers per submission"
    )


# 10-11. EMS bypasses the resolver entirely.
@pytest.mark.parametrize("scenario_code,_cat,_root", EMS_CASES)
def test_ems_bypasses_template_registry(
    scenario_code: str, _cat: str, _root: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _scenario(scenario_code)

    def _fail(*_a: Any, **_k: Any) -> Any:
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
        scenario_code, s
    )
    root = ET.fromstring(xml_bytes)
    assert root.tag == f"{{{NEMSIS_NS}}}EMSDataSet"


# 12. DEM bypasses EMS resolver too.
def test_dem_bypasses_template_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _scenario("2025_DEM_1")

    def _fail(*_a: Any, **_k: Any) -> Any:
        raise AssertionError(
            "2025_DEM_1 must not invoke the EMS template registry"
        )

    monkeypatch.setattr(
        scenarios_module, "build_nemsis_xml_from_template", _fail
    )
    monkeypatch.setattr(
        scenarios_module, "_build_template_resolved_xml", _fail
    )
    xml_bytes = scenarios_module._generate_pretesting_xml_or_500(
        "2025_DEM_1", s
    )
    root = ET.fromstring(xml_bytes)
    assert root.tag == f"{{{NEMSIS_NS}}}DEMDataSet"


# 13. Missing baked CTA XML returns HTTP 422.
@pytest.mark.parametrize("scenario_code,_cat,_root", ALL_2025_CTA_CASES)
def test_missing_baked_xml_returns_422(
    scenario_code: str, _cat: str, _root: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _scenario(scenario_code)
    monkeypatch.setattr(
        scenarios_module, "_load_baked_cta_xml", lambda _x: None
    )
    with pytest.raises(HTTPException) as excinfo:
        scenarios_module._generate_pretesting_xml_or_500(scenario_code, s)
    assert excinfo.value.status_code == 422
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "unsupported_tac_test_case"
    assert detail["scenario_id"] == scenario_code


# 14. Generated XML is parseable (covered by tests 3-8 via ET.fromstring).
# 15-16. Generated XML preserves baked root, namespace, and all
# scenario-defining non-stamp fields verbatim.
@pytest.mark.parametrize("scenario_code,_cat,_root", ALL_2025_CTA_CASES)
def test_only_stamping_allow_list_is_mutated(
    scenario_code: str, _cat: str, _root: str
) -> None:
    """Compare baked CTA XML to generated XML after normalizing only
    the explicit stamping allow-list. Any divergence outside that list
    indicates an unsafe mutation that TAC will reject."""
    s = _scenario(scenario_code)
    baked = scenarios_module._load_baked_cta_xml(s)
    assert baked is not None
    generated = scenarios_module._generate_pretesting_xml_or_500(
        scenario_code, s
    ).decode("utf-8")

    def _normalize(text: str) -> str:
        text = re.sub(r'UUID="[^"]*"', 'UUID="X"', text)
        for tag in ("eRecord.01", "eRecord.02", "eRecord.03", "eRecord.04"):
            text = re.sub(
                rf"<{tag}>[^<]*</{tag}>", f"<{tag}>X</{tag}>", text
            )
        text = re.sub(
            r'DemographicReport\s+timeStamp="[^"]*"',
            'DemographicReport timeStamp="X"',
            text,
        )
        return text

    assert _normalize(baked) == _normalize(generated), (
        f"{scenario_code}: generated XML diverges from baked CTA XML "
        "outside the stamping allow-list"
    )


# 17. TAC key fields exactly match the operator-spec uploaded test
# cases. eResponse.04 / dAgency.02 are the discriminators TAC uses to
# pick which test case the submission is for; if these are wrong, TAC
# returns soap_response_code=-16 ("Incorrect test case provided").
EMS_KEY_RESPONSE_04 = {
    "2025_EMS_1": "351-241102-005-1",
    "2025_EMS_2": "351-241134-005-1",
    "2025_EMS_3": "351-241140-004-1",
    "2025_EMS_4": "351-241198-002-1",
    "2025_EMS_5": "351-241219-002-1",
}
DEM_KEY_AGENCY_02 = "351-T0495"


@pytest.mark.parametrize(
    "scenario_code,expected", sorted(EMS_KEY_RESPONSE_04.items())
)
def test_ems_eresponse_04_matches_uploaded_test_case(
    scenario_code: str, expected: str
) -> None:
    s = _scenario(scenario_code)
    xml_text = scenarios_module._generate_pretesting_xml_or_500(
        scenario_code, s
    ).decode("utf-8")
    m = re.search(r"<eResponse\.04>([^<]*)</eResponse\.04>", xml_text)
    assert m is not None, (
        f"{scenario_code}: <eResponse.04> must be present in generated XML"
    )
    assert m.group(1) == expected, (
        f"{scenario_code}: eResponse.04 must equal {expected!r} "
        f"(uploaded TAC test case key); got {m.group(1)!r}. TAC will "
        "return soap_response_code=-16 if this drifts."
    )


def test_dem_dagency_02_matches_uploaded_test_case() -> None:
    s = _scenario("2025_DEM_1")
    xml_text = scenarios_module._generate_pretesting_xml_or_500(
        "2025_DEM_1", s
    ).decode("utf-8")
    m = re.search(r"<dAgency\.02>([^<]*)</dAgency\.02>", xml_text)
    assert m is not None, "<dAgency.02> must be present in generated DEM XML"
    assert m.group(1) == DEM_KEY_AGENCY_02, (
        f"2025_DEM_1: dAgency.02 must equal {DEM_KEY_AGENCY_02!r} "
        f"(uploaded TAC test case key); got {m.group(1)!r}"
    )
