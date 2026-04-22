"""Tests for NEMSIS pack role detection and official-source completeness rules."""
from epcr_app.nemsis_pack_manager import _detect_role, _required_roles_for_pack_type


def test_detect_role_classifies_official_nemsis_bundle_files() -> None:
    """Official NEMSIS filenames should map to explicit machine-readable roles."""
    assert _detect_role("Combined_ElementDetails_Full.txt") == "element_details"
    assert _detect_role("Combined_ElementEnumerations.txt") == "element_enumerations"
    assert _detect_role("Combined_ElementAttributes.txt") == "attribute_enumerations"
    assert _detect_role("EMSDataSet_v3_xsd.html") == "ems_dataset_api"
    assert _detect_role("NEMSIS_XSDs.zip") == "xsd_bundle"
    assert _detect_role("NEMSISDataDictionary.pdf") == "data_dictionary"


def test_required_roles_for_official_source_bundle_are_complete() -> None:
    """Official source bundles must require the full authoritative source pack."""
    assert _required_roles_for_pack_type("official_source_bundle") == {
        "data_dictionary",
        "xsd_bundle",
        "ems_dataset_api",
        "element_details",
        "element_enumerations",
        "attribute_enumerations",
    }


def test_unknown_pack_type_has_no_required_roles() -> None:
    """Unknown pack types should not fabricate completeness requirements."""
    assert _required_roles_for_pack_type("mystery") == set()
