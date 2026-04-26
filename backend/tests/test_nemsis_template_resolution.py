from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from epcr_app.nemsis_template_resolver import (
    NAMESPACES,
    build_nemsis_xml_from_template,
    merge_custom_elements,
    resolve_nemsis_template,
    _template_roots,
)


def _cta_xml_available() -> bool:
    """Return True when at least one CTA XML template file exists on disk."""
    for root in _template_roots():
        if root.exists() and any(root.glob("2025-EMS-*.xml")):
            return True
    return False


_skip_no_cta = pytest.mark.skipif(
    not _cta_xml_available(),
    reason="NEMSIS CTA vendor XML templates not present on disk",
)


def _root(xml_bytes: bytes) -> ET.Element:
    return ET.fromstring(xml_bytes)


def _children_tags(parent: ET.Element) -> list[str]:
    return [child.tag.split("}")[-1] for child in list(parent)]


@_skip_no_cta
def test_resolve_nemsis_template_returns_exact_tac_keys():
    trauma = resolve_nemsis_template("2025-EMS-4-ArmTrauma_v351")
    mental = resolve_nemsis_template("2025-EMS-5-MentalHealthCrisis_v351")

    assert trauma.tac_response_number == "351-241198-002-1"
    assert trauma.scenario_type == "trauma"
    assert mental.tac_response_number == "351-241219-002-1"
    assert mental.scenario_type == "behavioral"
    assert mental.allowed_custom_elements == ["eVitals.901"]


@_skip_no_cta
def test_template_builder_enforces_runtime_metadata_and_dem_enrichment():
    xml_bytes, _ = build_nemsis_xml_from_template(
        "2025-EMS-1-Allergy_v351",
        chart={
            "patient_care_report_number": "PCR-LOCKED-001",
            "software_creator": "Acme Creator",
            "software_name": "Acme ePCR",
            "software_version": "9.9.9",
        },
    )
    root = _root(xml_bytes)

    assert root.findtext(".//n:eRecord.01", namespaces=NAMESPACES) == "PCR-LOCKED-001"
    assert root.findtext(".//n:eRecord.02", namespaces=NAMESPACES) == "Acme Creator"
    assert root.findtext(".//n:eRecord.03", namespaces=NAMESPACES) == "Acme ePCR"
    assert root.findtext(".//n:eRecord.04", namespaces=NAMESPACES) == "9.9.9"
    assert root.findtext(".//n:eResponse.04", namespaces=NAMESPACES) == "351-241102-005-1"
    assert root.findtext(".//n:eResponse.02", namespaces=NAMESPACES) == (
        "Okaloosa County Emergency Medical Services"
    )
    assert root.findtext(".//n:eDisposition.03", namespaces=NAMESPACES) == "1000 Marwalt Drive"


@_skip_no_cta
def test_template_builder_preserves_repeated_groups_for_trauma_case():
    xml_bytes, _ = build_nemsis_xml_from_template("2025-EMS-4-ArmTrauma_v351")
    root = _root(xml_bytes)

    crew_groups = root.findall(".//n:eCrew.CrewGroup", NAMESPACES)
    insurance_groups = root.findall(".//n:ePayment.InsuranceGroup", NAMESPACES)

    assert len(crew_groups) >= 2
    assert len(insurance_groups) == 1
    assert root.findtext(".//n:eDispatch.03", namespaces=NAMESPACES) == "30E"
    assert root.findtext(".//n:eResponse.04", namespaces=NAMESPACES) == "351-241198-002-1"


@_skip_no_cta
def test_merge_custom_elements_inserts_allowed_state_extension_before_terminal_vitals_fields():
    xml_bytes, template = build_nemsis_xml_from_template("2025-EMS-5-MentalHealthCrisis_v351")
    root = _root(xml_bytes)

    merge_custom_elements(
        root,
        {
            "eVitals.901": [
                {"group_index": 0, "value": "3 - +3 Very agitated"},
                {"group_index": 1, "value": "2 - +2 Agitated"},
            ]
        },
        allowed_custom_elements=template.allowed_custom_elements,
    )

    vital_groups = root.findall(".//n:eVitals.VitalGroup", NAMESPACES)
    assert vital_groups[0].find("n:eVitals.901", NAMESPACES) is not None
    assert vital_groups[1].find("n:eVitals.901", NAMESPACES) is not None

    first_group_children = _children_tags(vital_groups[0])
    assert "eVitals.901" in first_group_children
    if "eVitals.33" in first_group_children:
        assert first_group_children.index("eVitals.901") < first_group_children.index("eVitals.33")


@_skip_no_cta
def test_merge_custom_elements_rejects_disallowed_extension():
    xml_bytes, _ = build_nemsis_xml_from_template("2025-EMS-1-Allergy_v351")
    root = _root(xml_bytes)

    with pytest.raises(ValueError, match="not allowed"):
        merge_custom_elements(
            root,
            {"eVitals.901": [{"group_index": 0, "value": "1 - +1 Restless"}]},
            allowed_custom_elements=[],
        )
