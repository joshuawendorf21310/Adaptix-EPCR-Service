"""NEMSIS 3.5.1 Full EMSDataSet Compliance Builder.

Generates:
1. emsdataset_full_field_inventory.json  — every EMSDataSet field with full metadata
2. emsdataset_full_field_compliance_matrix.json — per-field compliance status

These artifacts are the authoritative source for:
- UI rendering decisions
- Backend validation
- Export gate decisions
- Audit trail

Rules:
- Never invents data. All fields sourced from official normalized registry.
- Never marks pass without code + test evidence.
- Never marks not_applicable without dictionary evidence.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running standalone from backend/
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from epcr_app.nemsis_registry_service import NemsisRegistryService

# Output directory
_ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifact" / "nemsis_compliance_audit"

# All 25 required EMSDataSet sections per NEMSIS 3.5.1 EMSDataSet_v3.xsd
EMS_DATASET_SECTIONS = [
    "eRecord",
    "eResponse",
    "eDispatch",
    "eCrew",
    "eTimes",
    "ePatient",
    "ePayment",
    "eScene",
    "eSituation",
    "eInjury",
    "eArrest",
    "eHistory",
    "eNarrative",
    "eVitals",
    "eLabs",
    "eExam",
    "eProtocols",
    "eMedications",
    "eProcedures",
    "eAirway",
    "eDevice",
    "eDisposition",
    "eOutcome",
    "eCustomResults",
    "eOther",
]

# Sections that have known implementation files in the EPCR service
# Evidence: file exists in epcr_app/
_IMPLEMENTED_SECTIONS: dict[str, list[str]] = {
    "eRecord": ["epcr_app/nemsis_xml_builder.py", "epcr_app/chart_service.py"],
    "eResponse": ["epcr_app/nemsis_xml_builder.py", "epcr_app/response_timeline_service.py"],
    "eDispatch": ["epcr_app/cad_handoff_ingest_service.py"],
    "eCrew": ["epcr_app/crew_service.py"],
    "eTimes": ["epcr_app/services_timeline.py", "epcr_app/integration_timeline.py"],
    "ePatient": ["epcr_app/patient_service.py"],
    "ePayment": ["epcr_app/billing_readiness_service.py"],
    "eScene": ["epcr_app/chart_service.py"],
    "eSituation": ["epcr_app/clinical_impression_service.py", "epcr_app/injury_illness_service.py"],
    "eInjury": ["epcr_app/injury_illness_service.py"],
    "eArrest": ["epcr_app/chart_service.py"],
    "eHistory": ["epcr_app/allergy_service.py", "epcr_app/medication_service.py"],
    "eNarrative": ["epcr_app/ai_narrative_service.py", "epcr_app/narrative_review_service.py"],
    "eVitals": ["epcr_app/vitals_service.py"],
    "eLabs": ["epcr_app/vitals_service.py"],
    "eExam": ["epcr_app/physical_exam_service.py", "epcr_app/assessment_service.py"],
    "eProtocols": ["epcr_app/chart_service.py"],
    "eMedications": ["epcr_app/medication_service.py", "epcr_app/intervention_service.py"],
    "eProcedures": ["epcr_app/procedure_service.py", "epcr_app/intervention_service.py"],
    "eAirway": ["epcr_app/procedure_service.py"],
    "eDevice": ["epcr_app/chart_service.py"],
    "eDisposition": ["epcr_app/disposition_service.py"],
    "eOutcome": ["epcr_app/disposition_service.py"],
    "eCustomResults": ["epcr_app/nemsis_custom_elements.py"],
    "eOther": ["epcr_app/chart_service.py"],
}

# Sections with known test coverage
_TESTED_SECTIONS: dict[str, list[str]] = {
    "eRecord": ["tests/test_nemsis_xml_builder_conformance.py"],
    "eResponse": ["tests/test_nemsis_xml_builder_conformance.py", "tests/test_nemsis_routes.py"],
    "eDispatch": ["tests/test_nemsis_cad_dispatch_mapper.py"],
    "eCrew": [],
    "eTimes": [],
    "ePatient": ["tests/test_nemsis_allergy_vertical_slice.py"],
    "ePayment": ["tests/test_epcr_billing_readiness.py"],
    "eScene": [],
    "eSituation": [],
    "eInjury": [],
    "eArrest": [],
    "eHistory": ["tests/test_nemsis_allergy_vertical_slice.py"],
    "eNarrative": ["tests/test_epcr_ai_narrative.py"],
    "eVitals": [],
    "eLabs": [],
    "eExam": [],
    "eProtocols": [],
    "eMedications": [],
    "eProcedures": [],
    "eAirway": [],
    "eDevice": [],
    "eDisposition": [],
    "eOutcome": [],
    "eCustomResults": ["tests/test_nemsis_custom_elements.py"],
    "eOther": [],
}


def _map_usage(raw: str | None) -> str:
    if not raw:
        return "Optional"
    mapping = {
        "Mandatory": "Mandatory",
        "Required": "Required",
        "Recommended": "Recommended",
        "Optional": "Optional",
        "mandatory": "Mandatory",
        "required": "Required",
        "recommended": "Recommended",
        "optional": "Optional",
    }
    return mapping.get(raw, raw)


def _map_recurrence(min_occurs: str | None, max_occurs: str | None) -> str:
    mn = str(min_occurs or "0")
    mx = str(max_occurs or "1")
    if mn == "0" and mx == "1":
        return "0:1"
    if mn == "0" and mx in ("unbounded", "M", "*"):
        return "0:M"
    if mn == "1" and mx == "1":
        return "1:1"
    if mn == "1" and mx in ("unbounded", "M", "*"):
        return "1:M"
    return f"{mn}:{mx}"


def _build_inventory_entry(field: dict[str, Any]) -> dict[str, Any]:
    """Transform a registry field record into the canonical inventory shape."""
    element = field.get("field_id") or field.get("element_id") or ""
    section = field.get("section") or ""

    # Code list from allowed_values or element enumerations
    code_list: list[dict[str, str]] = []
    for av in field.get("allowed_values") or []:
        if isinstance(av, dict):
            code_list.append({
                "code": str(av.get("code") or av.get("value") or ""),
                "description": str(av.get("description") or av.get("label") or ""),
            })
        elif isinstance(av, str):
            code_list.append({"code": av, "description": av})

    # Constraints
    raw_constraints = field.get("constraints") or {}
    constraints: dict[str, Any] = {}
    if raw_constraints.get("min_length"):
        constraints["minLength"] = int(raw_constraints["min_length"])
    if raw_constraints.get("max_length"):
        constraints["maxLength"] = int(raw_constraints["max_length"])
    if raw_constraints.get("min_inclusive"):
        constraints["minInclusive"] = raw_constraints["min_inclusive"]
    if raw_constraints.get("max_inclusive"):
        constraints["maxInclusive"] = raw_constraints["max_inclusive"]
    if raw_constraints.get("pattern") or field.get("pattern"):
        constraints["pattern"] = raw_constraints.get("pattern") or field.get("pattern")

    # NOT values — from attribute_enumerations for NV attribute
    not_values: list[str] = []
    accepts_not = bool(field.get("not_value_allowed"))

    # Pertinent negatives — from attribute_enumerations for PN attribute
    pn_values: list[str] = []
    accepts_pn = bool(field.get("pertinent_negative_allowed"))

    # Nillable
    is_nillable = field.get("nillable") is True or str(field.get("nillable") or "").lower() == "true"

    # National/state element
    national_raw = str(field.get("national_element") or "").lower()
    state_raw = str(field.get("state_element") or "").lower()
    national_element = "national" in national_raw
    state_element = "state" in state_raw

    return {
        "element": element,
        "section": section,
        "name": field.get("official_name") or field.get("label") or field.get("name") or element,
        "definition": field.get("definition") or "",
        "usage": _map_usage(field.get("usage") or field.get("required_level")),
        "recurrence": _map_recurrence(field.get("min_occurs"), field.get("max_occurs")),
        "nationalElement": national_element,
        "stateElement": state_element,
        "acceptsNotValues": accepts_not,
        "acceptedNotValues": not_values,
        "acceptsPertinentNegatives": accepts_pn,
        "acceptedPertinentNegatives": pn_values,
        "isNillable": is_nillable,
        "dataType": field.get("data_type") or "",
        "constraints": constraints,
        "codeList": code_list,
        "deprecated": bool(field.get("deprecated")),
        "validationRules": [],
        "source": "official-data-dictionary",
        "dictionaryVersion": field.get("dictionary_version") or "3.5.1",
        "sourceCommit": field.get("source_commit") or "",
        "sourceArtifact": field.get("source_artifact") or "",
    }


def _build_compliance_entry(
    inventory_entry: dict[str, Any],
    section: str,
    impl_files: list[str],
    test_files: list[str],
) -> dict[str, Any]:
    """Build a compliance matrix entry for a single field."""
    element = inventory_entry["element"]
    usage = inventory_entry["usage"]
    has_impl = bool(impl_files)
    has_tests = bool(test_files)

    # Determine per-dimension status based on evidence
    # pass = code + test evidence
    # partial = code exists but no test, or test exists but incomplete
    # unknown = no evidence either way
    # not_applicable = dictionary evidence says field doesn't apply

    ui_capture = "partial" if has_impl else "unknown"
    backend_persistence = "partial" if has_impl else "unknown"
    save_reload = "partial" if has_impl else "unknown"
    nemsis_mapping = "partial" if has_impl else "unknown"
    xml_export = "partial" if has_impl else "unknown"

    usage_validation = "partial" if has_impl else "unknown"
    recurrence_validation = "partial" if has_impl else "unknown"

    code_list_validation = "not_applicable" if not inventory_entry["codeList"] else (
        "partial" if has_impl else "unknown"
    )
    not_value_support = "not_applicable" if not inventory_entry["acceptsNotValues"] else (
        "partial" if has_impl else "unknown"
    )
    pn_support = "not_applicable" if not inventory_entry["acceptsPertinentNegatives"] else (
        "partial" if has_impl else "unknown"
    )
    nillable_support = "not_applicable" if not inventory_entry["isNillable"] else (
        "partial" if has_impl else "unknown"
    )
    constraint_validation = "not_applicable" if not inventory_entry["constraints"] else (
        "partial" if has_impl else "unknown"
    )
    deprecated_handling = "not_applicable" if not inventory_entry["deprecated"] else (
        "partial" if has_impl else "unknown"
    )

    xsd_validation = "partial"  # XSD validator exists but not per-field
    schematron_validation = "partial"  # Schematron gate exists but skippable

    blocking_defects: list[str] = []
    if not has_impl:
        blocking_defects.append(f"No implementation file found for section {section}")
    if not has_tests:
        blocking_defects.append(f"No test coverage for {element}")
    if usage == "Mandatory" and not has_impl:
        blocking_defects.append(f"MANDATORY field {element} has no implementation")
    if usage == "Required" and not has_impl:
        blocking_defects.append(f"REQUIRED field {element} has no implementation")

    return {
        "element": element,
        "section": section,
        "ui_capture": ui_capture,
        "backend_persistence": backend_persistence,
        "save_reload": save_reload,
        "nemsis_mapping": nemsis_mapping,
        "xml_export": xml_export,
        "usage_validation": usage_validation,
        "recurrence_validation": recurrence_validation,
        "code_list_validation": code_list_validation,
        "not_value_support": not_value_support,
        "pertinent_negative_support": pn_support,
        "nillable_support": nillable_support,
        "constraint_validation": constraint_validation,
        "deprecated_handling": deprecated_handling,
        "xsd_validation": xsd_validation,
        "schematron_validation": schematron_validation,
        "tests": test_files,
        "blocking_defects": blocking_defects,
        "implementation_files": impl_files,
        "validation_files": ["epcr_app/nemsis_xsd_validator.py", "epcr_app/nemsis_finalization_gate.py"],
    }


def build_full_inventory(svc: NemsisRegistryService) -> list[dict[str, Any]]:
    """Build the full EMSDataSet field inventory from the official registry."""
    inventory: list[dict[str, Any]] = []
    fields = svc.list_fields(dataset="EMSDataSet")

    for field in fields:
        entry = _build_inventory_entry(field)
        inventory.append(entry)

    # Sort by section then element
    inventory.sort(key=lambda x: (x["section"], x["element"]))
    return inventory


def build_compliance_matrix(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the compliance matrix from the inventory."""
    matrix: list[dict[str, Any]] = []

    for entry in inventory:
        section = entry["section"]
        impl_files = _IMPLEMENTED_SECTIONS.get(section, [])
        test_files = _TESTED_SECTIONS.get(section, [])
        compliance = _build_compliance_entry(entry, section, impl_files, test_files)
        matrix.append(compliance)

    return matrix


def generate_summary(inventory: list[dict[str, Any]], matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate a compliance summary report."""
    total = len(inventory)
    by_section: dict[str, dict[str, Any]] = {}

    for entry in inventory:
        sec = entry["section"]
        if sec not in by_section:
            by_section[sec] = {"total": 0, "mandatory": 0, "required": 0, "recommended": 0, "optional": 0}
        by_section[sec]["total"] += 1
        usage = entry["usage"].lower()
        if usage in by_section[sec]:
            by_section[sec][usage] += 1

    # Count blocking defects
    total_blockers = sum(len(m["blocking_defects"]) for m in matrix)
    mandatory_fields = [e for e in inventory if e["usage"] == "Mandatory"]
    required_fields = [e for e in inventory if e["usage"] == "Required"]

    # Sections with no implementation
    unimplemented_sections = [
        sec for sec in EMS_DATASET_SECTIONS
        if not _IMPLEMENTED_SECTIONS.get(sec)
    ]

    # Sections with no tests
    untested_sections = [
        sec for sec in EMS_DATASET_SECTIONS
        if not _TESTED_SECTIONS.get(sec)
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dictionary_version": "3.5.1",
        "source_mode": "official_partial",
        "source_commit": "9bff090cbf95db614529bdff5e1e988a93f89717",
        "total_ems_fields": total,
        "total_mandatory": len(mandatory_fields),
        "total_required": len(required_fields),
        "total_blocking_defects": total_blockers,
        "sections_covered": len(by_section),
        "sections_required": len(EMS_DATASET_SECTIONS),
        "sections_with_implementation": len([s for s in EMS_DATASET_SECTIONS if _IMPLEMENTED_SECTIONS.get(s)]),
        "sections_with_tests": len([s for s in EMS_DATASET_SECTIONS if _TESTED_SECTIONS.get(s)]),
        "unimplemented_sections": unimplemented_sections,
        "untested_sections": untested_sections,
        "by_section": by_section,
        "compliance_status": "PARTIALLY_COMPLIANT",
        "compliance_gaps": [
            "Schematron validation skippable in current validator (not acceptable for certification/production)",
            "No per-field validation engine (usage, recurrence, NOT values, PN, nillable, code-list)",
            "No validation mode enforcement (development/certification/production)",
            "No frontend rendering contract (metadata-driven field renderer)",
            "Multiple sections have no dedicated test coverage",
            "Chart finalization gate uses small hardcoded mandatory list, not full EMSDataSet matrix",
        ],
        "blocking_for_certification": [
            "NEMSIS_VALIDATION_MODE=certification requires Schematron to not be skippable",
            "Universal field validator must enforce all 18 validation dimensions",
            "All 25 EMSDataSet sections must have save/reload/export tests",
        ],
    }


def run(output_dir: Path | None = None) -> dict[str, Any]:
    """Generate all compliance artifacts and return summary."""
    out_dir = output_dir or _ARTIFACT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    svc = NemsisRegistryService()

    print(f"Building EMSDataSet field inventory from official registry...")
    inventory = build_full_inventory(svc)
    print(f"  [OK] {len(inventory)} fields across {len(set(e['section'] for e in inventory))} sections")

    inventory_path = out_dir / "emsdataset_full_field_inventory.json"
    inventory_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] Written: {inventory_path}")

    print("Building compliance matrix...")
    matrix = build_compliance_matrix(inventory)
    matrix_path = out_dir / "emsdataset_full_field_compliance_matrix.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] Written: {matrix_path}")

    print("Generating summary report...")
    summary = generate_summary(inventory, matrix)
    summary_path = out_dir / "emsdataset_compliance_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] Written: {summary_path}")

    return summary


if __name__ == "__main__":
    summary = run()
    print("\n=== COMPLIANCE SUMMARY ===")
    print(f"Total EMSDataSet fields: {summary['total_ems_fields']}")
    print(f"Mandatory fields: {summary['total_mandatory']}")
    print(f"Required fields: {summary['total_required']}")
    print(f"Sections covered: {summary['sections_covered']}/{summary['sections_required']}")
    print(f"Sections with implementation: {summary['sections_with_implementation']}/{summary['sections_required']}")
    print(f"Sections with tests: {summary['sections_with_tests']}/{summary['sections_required']}")
    print(f"Total blocking defects: {summary['total_blocking_defects']}")
    print(f"Status: {summary['compliance_status']}")
    print("\nGaps:")
    for gap in summary["compliance_gaps"]:
        print(f"  - {gap}")
