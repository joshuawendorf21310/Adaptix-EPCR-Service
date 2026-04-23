"""Regression tests for NEMSIS pack role detection and completeness rules.

Covers deterministic role classification and required-role enforcement
for official NEMSIS source bundles. These rules operate at the shared
pack-management layer and must remain stable across domains.
"""

from epcr_app.nemsis_pack_manager import (
    _detect_role,
    _required_roles_for_pack_type,
)


def test_detect_role_classifies_official_nemsis_bundle_files() -> None:
    """Official NEMSIS filenames must map to stable machine-readable roles."""
    assert _detect_role("Combined_ElementDetails_Full.txt") == "element_details"
    assert _detect_role("Combined_ElementEnumerations.txt") == "element_enumerations"
    assert _detect_role("Combined_ElementAttributes.txt") == "attribute_enumerations"
    assert _detect_role("EMSDataSet_v3_xsd.html") == "ems_dataset_api"
    assert _detect_role("NEMSIS_XSDs.zip") == "xsd_bundle"
    assert _detect_role("NEMSISDataDictionary.pdf") == "data_dictionary"


def test_detect_role_is_case_insensitive_and_extension_tolerant() -> None:
    """Role detection must not depend on filename casing or extension variants."""
    assert _detect_role("combined_elementdetails_full.TXT") == "element_details"
    assert _detect_role("nemsis_xsds.ZIP") == "xsd_bundle"
    assert _detect_role("NEMSISDATADICTIONARY.PDF") == "data_dictionary"


def test_detect_role_returns_none_for_unrecognized_files() -> None:
    """Unknown filenames must not be misclassified."""
    assert _detect_role("random_file.txt") is None
    assert _detect_role("unknown_bundle.zip") is None


def test_required_roles_for_official_source_bundle_are_complete() -> None:
    """Official source bundles must require the full authoritative role set."""
    assert _required_roles_for_pack_type("official_source_bundle") == {
        "data_dictionary",
        "xsd_bundle",
        "ems_dataset_api",
        "element_details",
        "element_enumerations",
        "attribute_enumerations",
    }


def test_required_roles_for_pack_type_is_case_normalized() -> None:
    """Pack type resolution must be case-insensitive."""
    assert _required_roles_for_pack_type("OFFICIAL_SOURCE_BUNDLE") == {
        "data_dictionary",
        "xsd_bundle",
        "ems_dataset_api",
        "element_details",
        "element_enumerations",
        "attribute_enumerations",
    }


def test_unknown_pack_type_has_no_required_roles() -> None:
    """Unknown pack types must not fabricate completeness requirements."""
    assert _required_roles_for_pack_type("mystery") == set()


def test_required_roles_are_immutable() -> None:
    """Returned role sets must not be mutable across calls."""
    roles = _required_roles_for_pack_type("official_source_bundle")
    roles.add("tampered")

    # Re-fetch to ensure original definition is not mutated
    assert _required_roles_for_pack_type("official_source_bundle") == {
        "data_dictionary",
        "xsd_bundle",
        "ems_dataset_api",
        "element_details",
        "element_enumerations",
        "attribute_enumerations",
    }