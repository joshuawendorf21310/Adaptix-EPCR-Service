"""Generate NEMSIS compliance audit artifacts.

Produces:
  artifact/nemsis_compliance_audit/emsdataset_full_field_inventory.json
  artifact/nemsis_compliance_audit/emsdataset_full_field_compliance_matrix.json

Reads from the normalized registry (fields.json, element_enumerations.json,
code_sets.json, sections.json, required_elements.json) which were produced by
the official NEMSIS 3.5.1 importer from the pinned source commit.

Run from backend/:
    python scripts/generate_nemsis_compliance_audit.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
NORMALIZED_DIR = BACKEND_DIR / "epcr_app" / "nemsis_resources" / "official" / "normalized"
OUTPUT_DIR = BACKEND_DIR.parent / "artifact" / "nemsis_compliance_audit"

# EMSDataSet sections per NEMSIS 3.5.1 EMSDataSet_v3.xsd canonical order
EMS_SECTIONS = [
    "eRecord", "eResponse", "eDispatch", "eCrew", "eTimes",
    "ePatient", "ePayment", "eScene", "eSituation", "eInjury",
    "eArrest", "eHistory", "eNarrative", "eVitals", "eLabs",
    "eExam", "eProtocols", "eMedications", "eProcedures", "eAirway",
    "eDevice", "eDisposition", "eOutcome", "eCustomResults", "eOther",
]


def load_json(name: str) -> list | dict:
    path = NORMALIZED_DIR / name
    if not path.exists():
        print(f"MISSING: {path}", file=sys.stderr)
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def build_inventory() -> list[dict]:
    """Build full EMSDataSet field inventory from normalized registry."""
    fields: list[dict] = load_json("fields.json")
    element_enums: list[dict] = load_json("element_enumerations.json")
    code_sets: list[dict] = load_json("code_sets.json")

    # Index code lists by field_id
    code_list_index: dict[str, list[dict]] = {}
    for row in element_enums:
        fid = row.get("field_id", "")
        code_list_index.setdefault(fid, []).append({
            "code": row.get("code", ""),
            "description": row.get("display") or row.get("code", ""),
        })

    # Index defined-list codes by field_id
    defined_list_index: dict[str, list[dict]] = {}
    for row in code_sets:
        if row.get("code_system") == "NEMSIS_DEFINED_LIST":
            fid = row.get("field_element_id", "")
            defined_list_index.setdefault(fid, []).append({
                "code": row.get("code", ""),
                "description": row.get("label") or row.get("code", ""),
            })

    inventory: list[dict] = []
    for f in fields:
        if f.get("dataset") != "EMSDataSet":
            continue

        fid = f["field_id"]
        usage = f.get("usage") or f.get("required_level") or "Optional"
        recurrence = f.get("recurrence") or "0:1"
        nv_raw = (f.get("not_value_allowed") or "").strip().lower()
        pn_raw = (f.get("pertinent_negative_allowed") or "").strip().lower()
        nillable_raw = (f.get("nillable") or "").strip().lower()

        accepts_nv = nv_raw in ("yes", "true", "1", "y")
        accepts_pn = pn_raw in ("yes", "true", "1", "y")
        is_nillable = nillable_raw in ("yes", "true", "1", "y")

        # Merge element enumerations + defined lists for code list
        code_list = code_list_index.get(fid, []) + defined_list_index.get(fid, [])

        constraints: dict = {}
        raw_c = f.get("constraints") or {}
        if raw_c.get("min_length"):
            constraints["minLength"] = int(raw_c["min_length"])
        if raw_c.get("max_length"):
            constraints["maxLength"] = int(raw_c["max_length"])
        if raw_c.get("min_inclusive"):
            constraints["minInclusive"] = raw_c["min_inclusive"]
        if raw_c.get("max_inclusive"):
            constraints["maxInclusive"] = raw_c["max_inclusive"]
        if raw_c.get("pattern"):
            constraints["pattern"] = raw_c["pattern"]

        inventory.append({
            "element": fid,
            "section": f.get("section", ""),
            "name": f.get("label") or f.get("official_name") or fid,
            "definition": f.get("definition") or "",
            "usage": usage,
            "recurrence": recurrence,
            "nationalElement": (f.get("national_element") or "").lower() in ("national", "yes", "true"),
            "stateElement": (f.get("state_element") or "").lower() in ("state", "yes", "true"),
            "acceptsNotValues": accepts_nv,
            "acceptedNotValues": [
                "7701001", "7701003"
            ] if accepts_nv else [],
            "acceptsPertinentNegatives": accepts_pn,
            "acceptedPertinentNegatives": [
                "8801001", "8801003", "8801005", "8801007", "8801009",
                "8801011", "8801013", "8801015", "8801017", "8801019",
                "8801021", "8801023",
            ] if accepts_pn else [],
            "isNillable": is_nillable,
            "dataType": f.get("data_type") or "",
            "constraints": constraints,
            "codeList": code_list,
            "deprecated": bool(f.get("deprecated", False)),
            "validationRules": [],
            "source": "official-data-dictionary",
        })

    # Sort by section canonical order then element number
    section_order = {s: i for i, s in enumerate(EMS_SECTIONS)}
    inventory.sort(key=lambda x: (
        section_order.get(x["section"], 999),
        x["element"],
    ))
    return inventory


def build_compliance_matrix(inventory: list[dict]) -> list[dict]:
    """Build compliance matrix with honest unknown status for all fields."""
    matrix: list[dict] = []
    for item in inventory:
        fid = item["element"]
        section = item["section"]
        usage = item["usage"]
        has_code_list = bool(item["codeList"])
        accepts_nv = item["acceptsNotValues"]
        accepts_pn = item["acceptsPertinentNegatives"]
        is_nillable = item["isNillable"]
        has_constraints = bool(item["constraints"])
        deprecated = item["deprecated"]

        # Determine what's applicable
        code_list_status = "unknown" if has_code_list else "not_applicable"
        nv_status = "unknown" if accepts_nv else "not_applicable"
        pn_status = "unknown" if accepts_pn else "not_applicable"
        nillable_status = "unknown" if is_nillable else "not_applicable"
        constraint_status = "unknown" if has_constraints else "not_applicable"
        deprecated_status = "pass" if not deprecated else "unknown"

        matrix.append({
            "element": fid,
            "section": section,
            "usage": usage,

            # UI capture — unknown without runtime evidence
            "ui_capture": "unknown",
            # Backend persistence — unknown without DB schema evidence
            "backend_persistence": "unknown",
            # Save/reload — unknown without integration test evidence
            "save_reload": "unknown",

            # NEMSIS mapping — unknown without mapping record evidence
            "nemsis_mapping": "unknown",
            # XML export — unknown without export test evidence
            "xml_export": "unknown",

            # Validation dimensions
            "usage_validation": "unknown",
            "recurrence_validation": "unknown",
            "code_list_validation": code_list_status,
            "not_value_support": nv_status,
            "pertinent_negative_support": pn_status,
            "nillable_support": nillable_status,
            "constraint_validation": constraint_status,
            "deprecated_handling": deprecated_status,

            # XSD/Schematron — unknown without live validation evidence
            "xsd_validation": "unknown",
            "schematron_validation": "unknown",

            "tests": [],
            "blocking_defects": [],
            "implementation_files": [],
            "validation_files": [],
        })
    return matrix


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading normalized registry...")
    inventory = build_inventory()
    print(f"  EMSDataSet fields: {len(inventory)}")

    # Verify all 25 EMS sections present
    sections_found = sorted({item["section"] for item in inventory})
    missing_sections = [s for s in EMS_SECTIONS if s not in sections_found]
    if missing_sections:
        print(f"  MISSING SECTIONS: {missing_sections}", file=sys.stderr)
    else:
        print(f"  All {len(EMS_SECTIONS)} EMSDataSet sections present: {sections_found}")

    # Write inventory
    inv_path = OUTPUT_DIR / "emsdataset_full_field_inventory.json"
    inv_path.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  Written: {inv_path}")

    # Build compliance matrix
    matrix = build_compliance_matrix(inventory)
    mat_path = OUTPUT_DIR / "emsdataset_full_field_compliance_matrix.json"
    mat_path.write_text(
        json.dumps(matrix, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  Written: {mat_path}")

    # Summary
    print("\n=== INVENTORY SUMMARY ===")
    section_counts: dict[str, int] = {}
    for item in inventory:
        section_counts[item["section"]] = section_counts.get(item["section"], 0) + 1
    for section in EMS_SECTIONS:
        count = section_counts.get(section, 0)
        print(f"  {section}: {count} fields")
    print(f"\nTotal EMSDataSet fields: {len(inventory)}")
    print(f"Total compliance matrix rows: {len(matrix)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
