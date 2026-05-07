"""2025 DEM 1 exact-match regression.

Pins the operator-confirmed truth: the baked
`backend/nemsis/templates/cta/2025-DEM-1_v351.xml` is the TAC-passed
DEMDataSet payload. Adaptix-generated DEM submissions must canonicalize
equal to that file in strict mode, with the only allowed mutations
being:

  * Every `UUID="..."` attribute (re-stamped per submission)
  * `<eRecord.01>` ... `<eRecord.04>` software-identity tags
  * `DemographicReport@timeStamp`

Any other byte difference indicates a regression that TAC will reject.

Operator-required identifier preservation:
  * `dRecord.01` == "NEMSIS Technical Assistance Center"
  * `dRecord.02` == "Compliance Testing"
  * `dRecord.03` == "3.5.1.250403CP1_250317"
  * `dAgency.27` == "9923003" (Licensed Agency identifier)
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from epcr_app import api_nemsis_scenarios as scenarios_module
from epcr_app.nemsis_template_resolver import resolve_cta_template_path


NEMSIS_NS = "http://www.nemsis.org"
SCENARIO_CODE = "2025_DEM_1"
BAKED_FILENAME = "2025-DEM-1_v351.xml"

REQUIRED_DEM_IDENTIFIERS = {
    "dRecord.01": "NEMSIS Technical Assistance Center",
    "dRecord.02": "Compliance Testing",
    "dRecord.03": "3.5.1.250403CP1_250317",
}

# The TAC-passed DEM payload carries the agency identifier "9923003".
# In NEMSIS 3.5.1 it appears as `<dContact.16>` and `<dConfiguration.12>`.
# The operator spec refers to it as "dAgency.27" using 3.5.0 vocabulary.
REQUIRED_AGENCY_IDENTIFIER = "9923003"


def _scenario() -> dict[str, Any]:
    s = scenarios_module._find_scenario(SCENARIO_CODE)
    if s is None:
        pytest.skip(f"{SCENARIO_CODE} not registered")
    return s


def _baked_xml_text() -> str:
    path = resolve_cta_template_path(BAKED_FILENAME)
    return path.read_text(encoding="utf-8")


def _generated_xml_text() -> str:
    return scenarios_module._generate_pretesting_xml_or_500(
        SCENARIO_CODE, _scenario()
    ).decode("utf-8")


def _normalize_runtime_stamps(xml_text: str) -> str:
    """Collapse the explicit production-stamp allow-list to placeholders
    so byte-equality measures only the DEM clinical/identity content."""
    xml_text = re.sub(r'UUID="[^"]*"', 'UUID="X"', xml_text)
    for tag in ("eRecord.01", "eRecord.02", "eRecord.03", "eRecord.04"):
        xml_text = re.sub(
            rf"<{tag}>[^<]*</{tag}>",
            f"<{tag}>X</{tag}>",
            xml_text,
        )
    xml_text = re.sub(
        r'DemographicReport\s+timeStamp="[^"]*"',
        'DemographicReport timeStamp="X"',
        xml_text,
    )
    return xml_text


# 1. Baked source-of-truth fixture exists and is the TAC-passed payload.
def test_baked_dem_fixture_exists() -> None:
    path = resolve_cta_template_path(BAKED_FILENAME)
    assert path.exists(), (
        f"Baked TAC-passed DEM fixture must exist at {path}"
    )
    text = path.read_text(encoding="utf-8")
    assert text.lstrip().startswith("<?xml"), (
        "Baked DEM fixture must begin with an XML declaration"
    )
    root = ET.fromstring(text)
    assert root.tag == f"{{{NEMSIS_NS}}}DEMDataSet", (
        f"Baked DEM root must be <DEMDataSet>; got {root.tag!r}"
    )


# 2. Generated DEM root is DEMDataSet.
def test_generated_dem_root_is_demdataset() -> None:
    root = ET.fromstring(_generated_xml_text())
    assert root.tag == f"{{{NEMSIS_NS}}}DEMDataSet"


# 3. Generated DEM canonicalizes equal to baked TAC-passed XML.
def test_generated_dem_canonicalizes_equal_to_baked() -> None:
    baked = _baked_xml_text()
    generated = _generated_xml_text()
    assert _normalize_runtime_stamps(baked) == _normalize_runtime_stamps(
        generated
    ), (
        "Generated DEM XML must canonicalize equal to baked TAC-passed "
        "DEM XML outside the runtime stamping allow-list (UUIDs, "
        "eRecord.01-04, DemographicReport@timeStamp)."
    )


# 4. Production stamp mode: only stamp allow-list differs.
def test_production_stamp_only_allowed_differences() -> None:
    """Compare generated vs. baked at the byte level. Differing
    sections must each be one of: UUID attribute, eRecord.01-04, or
    DemographicReport@timeStamp. Anything else is forbidden."""
    baked = _baked_xml_text()
    generated = _generated_xml_text()

    # If they normalize equal (test 3) the only differences are the
    # explicit allow-list. Re-prove it by isolating diffs:
    if baked == generated:
        return  # pragma: no cover - allow-list was a no-op

    # Strip allow-list, then assert byte-equality.
    assert _normalize_runtime_stamps(baked) == _normalize_runtime_stamps(
        generated
    ), "Forbidden mutation outside production-stamp allow-list"


# 5. dRecord.01 preserved.
def test_drecord_01_preserved() -> None:
    generated = _generated_xml_text()
    m = re.search(r"<dRecord\.01>([^<]*)</dRecord\.01>", generated)
    assert m is not None, "<dRecord.01> must be present"
    assert m.group(1) == REQUIRED_DEM_IDENTIFIERS["dRecord.01"]


# 6. dRecord.02 preserved.
def test_drecord_02_preserved() -> None:
    generated = _generated_xml_text()
    m = re.search(r"<dRecord\.02>([^<]*)</dRecord\.02>", generated)
    assert m is not None, "<dRecord.02> must be present"
    assert m.group(1) == REQUIRED_DEM_IDENTIFIERS["dRecord.02"]


# 7. dRecord.03 preserved.
def test_drecord_03_preserved() -> None:
    generated = _generated_xml_text()
    m = re.search(r"<dRecord\.03>([^<]*)</dRecord\.03>", generated)
    assert m is not None, "<dRecord.03> must be present"
    assert m.group(1) == REQUIRED_DEM_IDENTIFIERS["dRecord.03"]


# 8. dAgency.27 == 9923003 preserved verbatim.
def test_dagency_27_preserved() -> None:
    """The TAC-passed DEM payload carries
    `<dAgency.27>9923003</dAgency.27>` (Licensed Agency).
    Both the baked source-of-truth and the generated submission must
    contain that exact element text, byte-for-byte."""
    baked = _baked_xml_text()
    generated = _generated_xml_text()

    expected = f"<dAgency.27>{REQUIRED_AGENCY_IDENTIFIER}</dAgency.27>"
    assert expected in baked, (
        f"Baked DEM fixture must contain {expected!r}"
    )
    assert expected in generated, (
        f"Generated DEM XML must contain {expected!r} verbatim"
    )

    # Occurrence count must match exactly between baked and generated
    # so no instance of the agency identifier may be inserted, dropped,
    # or mutated anywhere in the document.
    assert baked.count(REQUIRED_AGENCY_IDENTIFIER) == generated.count(
        REQUIRED_AGENCY_IDENTIFIER
    ), (
        f"Agency identifier {REQUIRED_AGENCY_IDENTIFIER!r} occurrence "
        "count must be preserved verbatim between baked and generated "
        "DEM XML"
    )


# Defense-in-depth: the resolver mutation pipeline must not be invoked.
def test_dem_does_not_invoke_template_resolver_or_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _scenario()

    def _fail(*_a: Any, **_k: Any) -> Any:
        raise AssertionError(
            "2025_DEM_1 must not invoke EMS template resolver/registry"
        )

    monkeypatch.setattr(
        scenarios_module, "build_nemsis_xml_from_template", _fail
    )
    monkeypatch.setattr(
        scenarios_module, "_build_template_resolved_xml", _fail
    )
    xml_bytes = scenarios_module._generate_pretesting_xml_or_500(
        SCENARIO_CODE, s
    )
    root = ET.fromstring(xml_bytes)
    assert root.tag == f"{{{NEMSIS_NS}}}DEMDataSet"


# Defense-in-depth: forbidden field families are byte-preserved.
@pytest.mark.parametrize(
    "tag_prefix",
    [
        "dAgency.",
        "dContact.",
        "dConfiguration.",
        "dLocation.",
        "dVehicle.",
        "dPersonnel.",
        "dDevice.",
        "dFacility.",
        "dCustomResults.",
    ],
)
def test_dem_forbidden_field_families_unchanged(tag_prefix: str) -> None:
    """Every <dX.NN>...</dX.NN> opening/closing tag and its text must
    appear in the generated XML exactly as it does in the baked XML."""
    baked = _baked_xml_text()
    generated = _generated_xml_text()
    pattern = re.compile(
        rf"<{re.escape(tag_prefix)}\d+(?:\s[^>]*)?>[^<]*</{re.escape(tag_prefix)}\d+>"
    )
    baked_hits = pattern.findall(baked)
    generated_hits = pattern.findall(generated)
    assert baked_hits == generated_hits, (
        f"Forbidden mutation detected in <{tag_prefix}*> family"
    )
