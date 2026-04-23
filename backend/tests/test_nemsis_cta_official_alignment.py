"""Regression tests for official 2025 CTA EMS/DEM alignment."""

from pathlib import Path
import xml.etree.ElementTree as ET

from epcr_app import api_nemsis_scenarios
from epcr_app.nemsis_template_resolver import resolve_nemsis_template


NEMSIS_NS = {"n": "http://www.nemsis.org"}
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
CTA_UPLOAD_DIR = WORKSPACE_ROOT / "Adaptix-Core-Service" / "cta_upload"
OFFICIAL_AGENCY_NAME = "Okaloosa County Emergency Medical Services"


def _parse_xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _dem_facility_map() -> tuple[str, dict[str, dict[str, str]]]:
    dem_root = _parse_xml(CTA_UPLOAD_DIR / "2025-DEM-1_v351.xml")
    agency_name = dem_root.findtext(".//n:dAgency.03", default="", namespaces=NEMSIS_NS).strip()
    if not agency_name:
        agency_name = OFFICIAL_AGENCY_NAME
    facilities: dict[str, dict[str, str]] = {}
    for facility in dem_root.findall(".//n:dFacility.FacilityGroup", NEMSIS_NS):
        code = facility.findtext("n:dFacility.03", default="", namespaces=NEMSIS_NS).strip()
        if not code:
            continue
        facilities[code] = {
            "eDisposition.03": facility.findtext("n:dFacility.07", default="", namespaces=NEMSIS_NS),
            "eDisposition.04": facility.findtext("n:dFacility.08", default="", namespaces=NEMSIS_NS),
            "eDisposition.05": facility.findtext("n:dFacility.09", default="", namespaces=NEMSIS_NS),
            "eDisposition.06": facility.findtext("n:dFacility.11", default="", namespaces=NEMSIS_NS),
            "eDisposition.07": facility.findtext("n:dFacility.10", default="", namespaces=NEMSIS_NS),
            "eDisposition.08": facility.findtext("n:dFacility.12", default="", namespaces=NEMSIS_NS),
            "eDisposition.09": facility.findtext("n:dFacility.13", default="", namespaces=NEMSIS_NS),
            "eDisposition.10": facility.findtext("n:dFacility.14", default="", namespaces=NEMSIS_NS),
        }
    return agency_name, facilities


def test_official_2025_dem_contains_agency_identifier_for_ems_derivation():
    dem_root = _parse_xml(CTA_UPLOAD_DIR / "2025-DEM-1_v351.xml")
    assert dem_root.findtext(".//n:dAgency.02", default="", namespaces=NEMSIS_NS) == "351-T0495"


def test_official_2025_agency_name_contract_matches_export_metadata():
    agency_name, _ = _dem_facility_map()
    assert agency_name == OFFICIAL_AGENCY_NAME


def test_official_2025_ems_reference_files_use_dem_derived_values():
    agency_name, facilities = _dem_facility_map()
    cases = {
        "2025-EMS-1-Allergy_v351.xml": "231002234363",
        "2025-EMS-2-HeatStroke_v351.xml": None,
        "2025-EMS-3-PediatricAsthma_v351.xml": "231000254433",
        "2025-EMS-4-ArmTrauma_v351.xml": None,
        "2025-EMS-5-MentalHealthCrisis_v351.xml": "17179601838554",
    }

    for filename, facility_code in cases.items():
        root = _parse_xml(CTA_UPLOAD_DIR / filename)
        assert root.findtext(".//n:eResponse.02", default="", namespaces=NEMSIS_NS) == agency_name
        if facility_code is None:
            continue
        expected = facilities[facility_code]
        for field, expected_value in expected.items():
            assert root.findtext(f".//n:{field}", default="", namespaces=NEMSIS_NS) == expected_value


def test_2025_cta_scenarios_use_official_agency_name_metadata():
    for scenario in api_nemsis_scenarios._2025_CTA_SCENARIOS:
        assert scenario["agency_info"]["agency_name"] == OFFICIAL_AGENCY_NAME


def test_submission_organization_prefers_configured_cta_account(monkeypatch):
    scenario = api_nemsis_scenarios._find_scenario("2025_EMS_1")
    assert scenario is not None

    monkeypatch.setattr(api_nemsis_scenarios, "_TAC_ORGANIZATION", "FusionEMSQuantum")
    assert api_nemsis_scenarios._resolve_submission_organization(scenario) == "FusionEMSQuantum"

    monkeypatch.setattr(api_nemsis_scenarios, "_TAC_ORGANIZATION", "")
    assert api_nemsis_scenarios._resolve_submission_organization(scenario) == OFFICIAL_AGENCY_NAME


def test_template_resolution_contract_matches_official_2025_case_keys():
    trauma = resolve_nemsis_template("2025-EMS-4-ArmTrauma_v351")
    mental = resolve_nemsis_template("2025-EMS-5-MentalHealthCrisis_v351")

    assert trauma.tac_response_number == "351-241198-002-1"
    assert trauma.scenario_type == "trauma"
    assert mental.tac_response_number == "351-241219-002-1"
    assert mental.allowed_custom_elements == ["eVitals.901"]
