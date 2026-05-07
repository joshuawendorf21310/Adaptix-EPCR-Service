from __future__ import annotations

import os
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


NEMSIS_NS = "http://www.nemsis.org"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
NAMESPACES = {"n": NEMSIS_NS}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = _REPO_ROOT.parent
# Baked-in templates COPYed by the Dockerfile via `COPY nemsis /app/nemsis`.
# This is the production-canonical template root and does not depend on any
# environment variable, source-tree layout, or sibling repository being mounted.
_BAKED_CTA_DIR = Path(__file__).resolve().parent.parent / "nemsis" / "templates" / "cta"
_EPCR_CTA_DIR = _REPO_ROOT / "nemsis_test" / "assets" / "cta" / "cta_uploaded_package" / "v3.5.1 C&S for vendors"
_CORE_CTA_DIR = _WORKSPACE_ROOT / "Adaptix-Core-Service" / "cta_upload"
_ENV_CTA_DIR = os.environ.get("NEMSIS_CTA_TEMPLATE_ROOT", "").strip()
_DEM_REFERENCE_NAME = "2025-DEM-1_v351.xml"
_DEFAULT_STATE_TEMPLATE = _BAKED_CTA_DIR / "2025-STATE-1_v351.xml"
_STATE_TEMPLATE_PATH = os.environ.get("NEMSIS_STATE_TEMPLATE_PATH", "").strip()

_SCENARIO_CODE_ALIASES = {
    "2025_EMS_1": "2025-EMS-1-Allergy_v351",
    "2025_EMS_2": "2025-EMS-2-HeatStroke_v351",
    "2025_EMS_3": "2025-EMS-3-PediatricAsthma_v351",
    "2025_EMS_4": "2025-EMS-4-ArmTrauma_v351",
    "2025_EMS_5": "2025-EMS-5-MentalHealthCrisis_v351",
}

_TEMPLATE_REGISTRY = {
    "2025-EMS-1-Allergy_v351": {
        "filename": "2025-EMS-1-Allergy_v351.xml",
        "tac_response_number": "351-241102-005-1",
        "scenario_type": "allergy",
        "required_overrides": {},
        "allowed_custom_elements": [],
    },
    "2025-EMS-2-HeatStroke_v351": {
        "filename": "2025-EMS-2-HeatStroke_v351.xml",
        "tac_response_number": "351-241134-005-1",
        "scenario_type": "heat",
        "required_overrides": {},
        "allowed_custom_elements": [],
    },
    "2025-EMS-3-PediatricAsthma_v351": {
        "filename": "2025-EMS-3-PediatricAsthma_v351.xml",
        "tac_response_number": "351-241140-004-1",
        "scenario_type": "respiratory",
        "required_overrides": {},
        "allowed_custom_elements": [],
    },
    "2025-EMS-4-ArmTrauma_v351": {
        "filename": "2025-EMS-4-ArmTrauma_v351.xml",
        "tac_response_number": "351-241198-002-1",
        "scenario_type": "trauma",
        "required_overrides": {},
        "allowed_custom_elements": [],
    },
    "2025-EMS-5-MentalHealthCrisis_v351": {
        "filename": "2025-EMS-5-MentalHealthCrisis_v351.xml",
        "tac_response_number": "351-241219-002-1",
        "scenario_type": "behavioral",
        "required_overrides": {},
        "allowed_custom_elements": ["eVitals.901"],
    },
}

_TAC_RESPONSE_TO_TEST_CASE = {
    value["tac_response_number"]: key for key, value in _TEMPLATE_REGISTRY.items()
}

_DEM_FIELD_MAP = {
    "eDisposition.03": "dFacility.07",
    "eDisposition.04": "dFacility.08",
    "eDisposition.05": "dFacility.09",
    "eDisposition.06": "dFacility.11",
    "eDisposition.07": "dFacility.10",
    "eDisposition.08": "dFacility.12",
    "eDisposition.09": "dFacility.13",
    "eDisposition.10": "dFacility.14",
}

_CUSTOM_INSERTION_RULES = {
    "eVitals.901": {
        "parent": "eVitals.VitalGroup",
        "before": ("eVitals.32", "eVitals.33"),
    },
}

_OFFICIAL_CTA_AGENCY_NAME = "Okaloosa County Emergency Medical Services"


def ns(tag: str) -> str:
    return f"{{{NEMSIS_NS}}}{tag}"


@dataclass(frozen=True)
class TemplateDefinition:
    template_path: str
    tac_response_number: str
    scenario_type: str
    required_overrides: dict[str, str]
    allowed_custom_elements: list[str]


def resolve_test_case_id_for_response_number(response_number: str | None) -> str | None:
    if response_number is None:
        return None
    return _TAC_RESPONSE_TO_TEST_CASE.get(response_number.strip())


def resolve_nemsis_template(test_case_id: str) -> TemplateDefinition:
    canonical_id = _SCENARIO_CODE_ALIASES.get(test_case_id, test_case_id)
    record = _TEMPLATE_REGISTRY.get(canonical_id)
    if record is None:
        raise ValueError(f"Unsupported TAC test case id: {test_case_id}")

    template_path = _resolve_template_path(record["filename"])
    return TemplateDefinition(
        template_path=str(template_path),
        tac_response_number=str(record["tac_response_number"]),
        scenario_type=str(record["scenario_type"]),
        required_overrides=dict(record["required_overrides"]),
        allowed_custom_elements=list(record["allowed_custom_elements"]),
    )


def load_template(template_path: str) -> ET.Element:
    root = ET.parse(template_path).getroot()
    ET.register_namespace("", NEMSIS_NS)
    ET.register_namespace("xsi", XSI_NS)
    return root


def apply_required_overrides(base_xml: ET.Element, required_overrides: dict[str, str]) -> ET.Element:
    for field_name, value in required_overrides.items():
        _set_first_value(base_xml, field_name, value)
    return base_xml


def inject_runtime_data(base_xml: ET.Element, chart: dict[str, Any] | None) -> ET.Element:
    chart = chart or {}
    _refresh_uuid_attributes(base_xml)

    patient_care_report_number = str(
        chart.get("patient_care_report_number")
        or f"PCR-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    )
    software_creator = str(chart.get("software_creator") or os.environ.get("NEMSIS_SOFTWARE_CREATOR", "Adaptix Platform"))
    software_name = str(chart.get("software_name") or os.environ.get("NEMSIS_SOFTWARE_NAME", "Adaptix ePCR"))
    software_version = str(chart.get("software_version") or os.environ.get("NEMSIS_SOFTWARE_VERSION", "1.0.0"))

    _set_first_value(base_xml, "eRecord.01", patient_care_report_number)
    _set_first_value(base_xml, "eRecord.02", software_creator)
    _set_first_value(base_xml, "eRecord.03", software_name)
    _set_first_value(base_xml, "eRecord.04", software_version)

    for field_name, value in (chart.get("field_overrides") or {}).items():
        _set_first_value(base_xml, str(field_name), str(value))

    return base_xml


def merge_custom_elements(
    base_xml: ET.Element,
    custom_data: dict[str, list[dict[str, Any]]] | None,
    *,
    allowed_custom_elements: list[str],
) -> ET.Element:
    if not custom_data:
        return base_xml

    allowed = set(allowed_custom_elements)
    requested = set(custom_data.keys())
    disallowed = requested - allowed
    if disallowed:
        raise ValueError(
            "Custom elements are not allowed for this template: " + ", ".join(sorted(disallowed))
        )

    for element_name, entries in custom_data.items():
        insertion_rule = _CUSTOM_INSERTION_RULES.get(element_name)
        if insertion_rule is None:
            raise ValueError(f"No insertion rule defined for custom element {element_name}")

        parent_groups = base_xml.findall(f".//n:{insertion_rule['parent']}", NAMESPACES)
        for index, entry in enumerate(entries):
            group_index = int(entry.get("group_index", index))
            value = str(entry["value"])
            if group_index >= len(parent_groups):
                raise ValueError(
                    f"Custom element {element_name} targets missing group index {group_index}"
                )
            _insert_custom_child(
                parent_groups[group_index],
                element_name,
                value,
                before_tags=tuple(insertion_rule["before"]),
            )

    return base_xml


def enforce_tac_key(base_xml: ET.Element, tac_response_number: str) -> ET.Element:
    _set_first_value(base_xml, "eResponse.04", tac_response_number)
    return base_xml


def validate_state_dataset(base_xml: ET.Element, template_definition: TemplateDefinition) -> list[str]:
    declared_custom_elements = _load_state_custom_elements(_resolved_state_template_path())
    if not declared_custom_elements:
        return []

    errors: list[str] = []
    for element_name in template_definition.allowed_custom_elements:
        for _ in base_xml.findall(f".//n:{element_name}", NAMESPACES):
            if element_name not in declared_custom_elements:
                errors.append(f"State dataset does not declare custom element {element_name}.")
    return errors


def build_nemsis_xml_from_template(
    test_case_id: str,
    chart: dict[str, Any] | None = None,
) -> tuple[bytes, TemplateDefinition]:
    template_definition = resolve_nemsis_template(test_case_id)
    base_xml = load_template(template_definition.template_path)
    apply_required_overrides(base_xml, template_definition.required_overrides)
    apply_dem_dataset_enrichment(base_xml, _resolve_dem_reference_path())
    inject_runtime_data(base_xml, chart)
    merge_custom_elements(
        base_xml,
        (chart or {}).get("custom_elements"),
        allowed_custom_elements=template_definition.allowed_custom_elements,
    )
    enforce_tac_key(base_xml, template_definition.tac_response_number)

    state_errors = validate_state_dataset(base_xml, template_definition)
    if state_errors:
        raise ValueError("State dataset validation failed: " + "; ".join(state_errors))

    try:
        ET.indent(base_xml, space="  ")
    except AttributeError:
        pass

    return ET.tostring(base_xml, encoding="utf-8", xml_declaration=True), template_definition


def apply_dem_dataset_enrichment(base_xml: ET.Element, dem_xml_path: str | Path) -> ET.Element:
    dem_path = Path(dem_xml_path)
    if not dem_path.exists():
        _set_first_value(base_xml, "eResponse.01", "351-T0495")
        if not _find_text(base_xml, "eResponse.02"):
            _set_first_value(base_xml, "eResponse.02", _OFFICIAL_CTA_AGENCY_NAME)
        return base_xml

    dem_root = ET.parse(dem_path).getroot()
    agency_name = _find_text(dem_root, "dAgency.03") or _OFFICIAL_CTA_AGENCY_NAME
    agency_number = _find_text(dem_root, "dAgency.02") or "351-T0495"
    if agency_name:
        _set_first_value(base_xml, "eResponse.02", agency_name)
    if agency_number:
        _set_first_value(base_xml, "eResponse.01", agency_number)

    destination_code = _find_text(base_xml, "eDisposition.02")
    if not destination_code:
        return base_xml

    for facility in dem_root.findall(".//n:dFacility.FacilityGroup", NAMESPACES):
        if _find_text(facility, "dFacility.03") != destination_code:
            continue
        for ems_field, dem_field in _DEM_FIELD_MAP.items():
            dem_value = _find_text(facility, dem_field)
            if dem_value:
                _set_first_value(base_xml, ems_field, dem_value)
        break

    return base_xml


def _resolve_template_path(filename: str) -> Path:
    for root in _template_roots():
        candidate = root / filename
        if candidate.exists():
            return candidate
    raise ValueError(f"Template file not found for {filename}")


def resolve_cta_template_path(filename: str) -> Path:
    """Public wrapper used by the scenario submit handler so the DEM
    pre-testing path can locate baked CTA files via the same resolution
    chain (env override -> baked image -> repo source) without going
    through the EMS template-registry/enrichment pipeline."""
    return _resolve_template_path(filename)


def _resolve_dem_reference_path() -> Path:
    for root in _template_roots():
        candidate = root / _DEM_REFERENCE_NAME
        if candidate.exists():
            return candidate
    return _CORE_CTA_DIR / _DEM_REFERENCE_NAME


def _resolved_state_template_path() -> str:
    if _STATE_TEMPLATE_PATH:
        return _STATE_TEMPLATE_PATH
    return str(_DEFAULT_STATE_TEMPLATE)


def _template_roots() -> list[Path]:
    roots: list[Path] = []
    if _ENV_CTA_DIR:
        roots.append(Path(_ENV_CTA_DIR))
    roots.append(_BAKED_CTA_DIR)
    roots.append(_EPCR_CTA_DIR)
    roots.append(_CORE_CTA_DIR)
    seen: set[Path] = set()
    ordered: list[Path] = []
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        ordered.append(root)
    return ordered


def _refresh_uuid_attributes(root: ET.Element) -> None:
    for element in root.iter():
        if "UUID" in element.attrib:
            element.set("UUID", str(uuid.uuid4()))


def _set_first_value(root: ET.Element, field_name: str, value: str) -> None:
    target = root.find(f".//n:{field_name}", NAMESPACES)
    if target is not None:
        target.text = value
        # Bug fix: xsi:nil lives in the XSI namespace, not the NEMSIS namespace.
        # The previous `ns("nil")` produced `{http://www.nemsis.org}nil`, which
        # never matched the actual `{http://www.w3.org/2001/XMLSchema-instance}nil`
        # attribute, leaving the element marked as nilled while also carrying
        # text — an XSD violation. Pop both forms defensively.
        target.attrib.pop(f"{{{XSI_NS}}}nil", None)
        target.attrib.pop(ns("nil"), None)
        target.attrib.pop("NV", None)
        target.attrib.pop("PN", None)


def _find_text(root: ET.Element, field_name: str) -> str:
    target = root.find(f".//n:{field_name}", NAMESPACES)
    return (target.text or "").strip() if target is not None and target.text else ""


def _insert_custom_child(
    parent: ET.Element,
    field_name: str,
    value: str,
    *,
    before_tags: tuple[str, ...],
) -> None:
    existing = parent.find(f"n:{field_name}", NAMESPACES)
    if existing is not None:
        existing.text = value
        return

    new_child = ET.Element(ns(field_name))
    new_child.text = value

    insertion_index = len(parent)
    before_tag_names = {ns(tag_name) for tag_name in before_tags}
    for idx, child in enumerate(list(parent)):
        if child.tag in before_tag_names:
            insertion_index = idx
            break
    parent.insert(insertion_index, new_child)


def _load_state_custom_elements(state_template_path: str) -> set[str]:
    if not state_template_path:
        return set()

    state_path = Path(state_template_path)
    if not state_path.exists():
        return set()

    state_root = ET.parse(state_path).getroot()
    custom_elements = set()
    for custom_group in state_root.findall(".//*[@CustomElementID]"):
        custom_element_id = custom_group.attrib.get("CustomElementID", "").strip()
        if custom_element_id:
            custom_elements.add(custom_element_id)
    return custom_elements