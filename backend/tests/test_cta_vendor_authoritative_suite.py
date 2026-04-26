"""Authoritative CTA suite built from vendor HTML package and official reference XML.

This suite replaces older ad-hoc CTA tests. It uses the vendor HTML files as the
source of truth for TAC keys and the official CTA XML reference files as the
source of truth for generated output content.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest

from epcr_app.nemsis_template_resolver import NAMESPACES, build_nemsis_xml_from_template


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
VENDOR_HTML_DIR = (
    WORKSPACE_ROOT
    / "Adaptix-EPCR-Service"
    / "nemsis_test"
    / "assets"
    / "cta"
    / "cta_uploaded_package"
    / "v3.5.1 C&S for vendors"
)
OFFICIAL_XML_DIR = WORKSPACE_ROOT / "Adaptix-Core-Service" / "cta_upload"
OFFICIAL_AGENCY_NAME = "Okaloosa County Emergency Medical Services"

_cta_available = OFFICIAL_XML_DIR.exists() and any(OFFICIAL_XML_DIR.glob("2025-EMS-*.xml"))

SCENARIOS = {
    "2025-EMS-1-Allergy_v351": {
        "html": VENDOR_HTML_DIR / "2025-EMS-1-Allergy_v351.html",
        "xml": OFFICIAL_XML_DIR / "2025-EMS-1-Allergy_v351.xml",
    },
    "2025-EMS-2-HeatStroke_v351": {
        "html": VENDOR_HTML_DIR / "2025-EMS-2-HeatStroke_v351.html",
        "xml": OFFICIAL_XML_DIR / "2025-EMS-2-HeatStroke_v351.xml",
    },
    "2025-EMS-3-PediatricAsthma_v351": {
        "html": VENDOR_HTML_DIR / "2025-EMS-3-PediatricAsthma_v351.html",
        "xml": OFFICIAL_XML_DIR / "2025-EMS-3-PediatricAsthma_v351.xml",
    },
    "2025-EMS-4-ArmTrauma_v351": {
        "html": VENDOR_HTML_DIR / "2025-EMS-4-ArmTrauma_v351.html",
        "xml": OFFICIAL_XML_DIR / "2025-EMS-4-ArmTrauma_v351.xml",
    },
    "2025-EMS-5-MentalHealthCrisis_v351": {
        "html": VENDOR_HTML_DIR / "2025-EMS-5-MentalHealthCrisis_v351.html",
        "xml": OFFICIAL_XML_DIR / "2025-EMS-5-MentalHealthCrisis_v351.xml",
    },
}
EXCLUDED_COMPARE_FIELDS = {
    "eRecord.01",
    "eRecord.02",
    "eRecord.03",
    "eRecord.04",
}


def _parse_xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _root_from_bytes(xml_bytes: bytes) -> ET.Element:
    return ET.fromstring(xml_bytes)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _collect_leaf_values(root: ET.Element) -> dict[str, list[str]]:
    values: dict[str, list[str]] = defaultdict(list)
    for element in root.iter():
        if list(element):
            continue
        name = _local_name(element.tag)
        if name in EXCLUDED_COMPARE_FIELDS:
            continue
        text = (element.text or "").strip()
        nil_flag = element.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
        nv_flag = element.attrib.get("NV")
        pn_flag = element.attrib.get("PN")
        if text:
            values[name].append(text)
        elif nil_flag == "true":
            marker = f"__NIL__:{nv_flag or pn_flag or ''}"
            values[name].append(marker)
    return dict(values)


def _extract_vendor_response_values(html_path: Path) -> tuple[str, str]:
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    incident_match = re.search(
        r"<span>eResponse\.03.*?</span>.*?<td>([^<]+)</td>",
        html,
        flags=re.DOTALL,
    )
    response_match = re.search(
        r"<span>eResponse\.04.*?</span>.*?<td>([^<]+)</td>",
        html,
        flags=re.DOTALL,
    )
    if not incident_match or not response_match:
        raise AssertionError(f"Could not extract eResponse.03/eResponse.04 from {html_path.name}")
    return incident_match.group(1).strip(), response_match.group(1).strip()


def _find_text(root: ET.Element, field_name: str) -> str:
    result = root.findtext(f".//n:{field_name}", default="", namespaces=NAMESPACES)
    return result.strip() if result else ""


@pytest.mark.skipif(not _cta_available, reason="NEMSIS CTA vendor XML templates not present")
@pytest.mark.parametrize("scenario_id,paths", SCENARIOS.items())
def test_vendor_html_tac_keys_match_generated_xml(scenario_id: str, paths: dict[str, Path]) -> None:
    """Use vendor HTML package as the authoritative source of TAC incident and response keys."""
    expected_incident, expected_response = _extract_vendor_response_values(paths["html"])
    xml_bytes, _ = build_nemsis_xml_from_template(scenario_id)
    generated_root = _root_from_bytes(xml_bytes)

    assert _find_text(generated_root, "eResponse.03") == expected_incident
    assert _find_text(generated_root, "eResponse.04") == expected_response


@pytest.mark.skipif(not _cta_available, reason="NEMSIS CTA vendor XML templates not present")
@pytest.mark.parametrize("scenario_id,paths", SCENARIOS.items())
def test_generated_xml_matches_official_reference_xml(scenario_id: str, paths: dict[str, Path]) -> None:
    """Compare generated XML against the official XML reference file for every stable leaf field."""
    xml_bytes, _ = build_nemsis_xml_from_template(scenario_id)
    generated_root = _root_from_bytes(xml_bytes)
    official_root = _parse_xml(paths["xml"])

    generated_values = _collect_leaf_values(generated_root)
    official_values = _collect_leaf_values(official_root)

    missing_fields: list[str] = []
    mismatched_fields: list[str] = []
    for field_name, expected_values in sorted(official_values.items()):
        actual_values = generated_values.get(field_name)
        if actual_values is None:
            missing_fields.append(field_name)
            continue
        if actual_values != expected_values:
            mismatched_fields.append(
                f"{field_name}: expected {expected_values!r}, got {actual_values!r}"
            )

    assert not missing_fields, f"{scenario_id}: missing fields {missing_fields}"
    assert not mismatched_fields, (
        f"{scenario_id}: mismatched fields:\n" + "\n".join(mismatched_fields[:20])
    )


@pytest.mark.skipif(not _cta_available, reason="NEMSIS CTA vendor XML templates not present")
@pytest.mark.parametrize("scenario_id,paths", SCENARIOS.items())
def test_generated_xml_preserves_agency_identity(scenario_id: str, paths: dict[str, Path]) -> None:
    """Ensure generated XML preserves the official CTA agency identity."""
    del paths
    xml_bytes, _ = build_nemsis_xml_from_template(scenario_id)
    generated_root = _root_from_bytes(xml_bytes)

    assert _find_text(generated_root, "eResponse.01") == "351-T0495"
    assert _find_text(generated_root, "eResponse.02") == OFFICIAL_AGENCY_NAME


@pytest.mark.skipif(not _cta_available, reason="NEMSIS CTA vendor XML templates not present")
def test_vendor_html_suite_covers_all_five_2025_cta_scenarios() -> None:
    """Protect against accidental loss of any official 2025 CTA scenario coverage."""
    assert set(SCENARIOS) == {
        "2025-EMS-1-Allergy_v351",
        "2025-EMS-2-HeatStroke_v351",
        "2025-EMS-3-PediatricAsthma_v351",
        "2025-EMS-4-ArmTrauma_v351",
        "2025-EMS-5-MentalHealthCrisis_v351",
    }
    for paths in SCENARIOS.values():
        assert paths["html"].exists(), f"Missing vendor HTML file: {paths['html']}"
        assert paths["xml"].exists(), f"Missing official XML file: {paths['xml']}"
