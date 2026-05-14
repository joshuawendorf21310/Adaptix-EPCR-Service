"""Quality-audit the parsed NEMSIS 3.5.1 registry and reconcile with our local registry."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PDF_JSON = Path("nemsis_test/ref/NEMSISDataDictionary_3.5.1.json")
LOCAL = Path("epcr_app/nemsis_resources/official/normalized/fields.json")

pdf = json.loads(PDF_JSON.read_text(encoding="utf-8"))
elements = pdf["elements"]

print("=== Aggregate counts ===")
print(f"total elements: {len(elements)}")
by_ds = Counter(e["dataset"] for e in elements)
print(f"by dataset:    {dict(by_ds)}")
by_usage = Counter(e["usage"] for e in elements)
print(f"by usage:      {dict(by_usage)}")
# Official dictionary cover-page totals: Mandatory 57, Required 144,
# Recommended 115, Optional 336 (= 652).
official_usage = {"Mandatory": 57, "Required": 144, "Recommended": 115, "Optional": 336}
for k, expected in official_usage.items():
    got = by_usage.get(k, 0)
    flag = "OK" if got == expected else f"DRIFT (expected {expected})"
    print(f"  {k:11} {got:4d}  {flag}")

print()
print("=== Field coverage ===")
missing_def = [e["element_number"] for e in elements if not e.get("definition")]
missing_usage = [e["element_number"] for e in elements if not e.get("usage")]
missing_recur = [e["element_number"] for e in elements if not e.get("recurrence")]
print(f"missing definition: {len(missing_def)}  {missing_def[:5]}")
print(f"missing usage:      {len(missing_usage)} {missing_usage[:5]}")
print(f"missing recurrence: {len(missing_recur)} {missing_recur[:5]}")

print()
print("=== Constraint coverage ===")
with_constraints = sum(1 for e in elements if e.get("constraints"))
with_pattern = sum(1 for e in elements if (e.get("constraints") or {}).get("pattern"))
with_codelist = sum(1 for e in elements if e.get("code_list"))
with_pn = sum(1 for e in elements if e.get("pertinent_negatives"))
with_nv = sum(1 for e in elements if e.get("not_values"))
with_nil = sum(1 for e in elements if e.get("is_nillable"))
deprecated = [e["element_number"] for e in elements if e.get("deprecated")]
print(f"with constraints:    {with_constraints}")
print(f"with pattern:        {with_pattern}")
print(f"with code list:      {with_codelist}")
print(f"with PN attribute:   {with_pn}")
print(f"with NV attribute:   {with_nv}")
print(f"with isNillable=Yes: {with_nil}")
print(f"deprecated elements: {len(deprecated)} {deprecated}")

print()
print("=== Data type distribution ===")
dt = Counter((e.get("constraints") or {}).get("data_type", "(none)") for e in elements)
for k, v in dt.most_common():
    print(f"  {k:20} {v:4d}")

print()
print("=== Validation rule coverage ===")
rule_count = sum(len(e.get("validation_rules", [])) for e in elements)
rule_levels: Counter[str] = Counter()
for e in elements:
    for r in e.get("validation_rules", []):
        rule_levels[r["level"]] += 1
print(f"total inline rules: {rule_count}")
print(f"by level:           {dict(rule_levels)}")

print()
print("=== Performance measure coverage ===")
pm = Counter()
for e in elements:
    for m in e.get("performance_measures", []):
        pm[m] += 1
for k, v in pm.most_common():
    print(f"  {k:14} {v:4d}")

print()
print("=== Reconciliation with local registry ===")
if LOCAL.exists():
    local = json.loads(LOCAL.read_text(encoding="utf-8"))
    local_elements = local if isinstance(local, list) else local.get("elements") or local.get("fields") or []
    if isinstance(local_elements, dict):
        local_elements = list(local_elements.values())
    local_by_id = {
        (x.get("element_id") or x.get("field_id") or x.get("element_number")): x
        for x in local_elements
    }
    local_by_id.pop(None, None)
    pdf_by_id = {e["element_number"]: e for e in elements}
    only_pdf = sorted(set(pdf_by_id) - set(local_by_id))
    only_local = sorted(set(local_by_id) - set(pdf_by_id))
    common = sorted(set(pdf_by_id) & set(local_by_id))
    print(f"local registry size: {len(local_elements)}")
    print(f"common:         {len(common)}")
    print(f"only in PDF:    {len(only_pdf)}  e.g. {only_pdf[:15]}")
    print(f"only in local:  {len(only_local)} e.g. {only_local[:15]}")

    # Drift detection: for elements present in both, compare key facets.
    drift_usage: list[tuple[str, str, str]] = []
    drift_definition: list[str] = []
    drift_recurrence: list[tuple[str, str, str]] = []
    drift_nv: list[tuple[str, bool, object]] = []
    drift_pn: list[tuple[str, bool, object]] = []
    drift_nil: list[tuple[str, bool, object]] = []
    drift_national: list[tuple[str, bool, object]] = []
    drift_state: list[tuple[str, bool, object]] = []
    missing_codelist_local: list[tuple[str, int]] = []
    missing_constraints_local: list[str] = []
    for eid in common:
        pdf_rec = pdf_by_id[eid]
        loc = local_by_id[eid]
        if (loc.get("usage") or "").strip() != pdf_rec["usage"]:
            drift_usage.append((eid, loc.get("usage"), pdf_rec["usage"]))
        if not (loc.get("definition") or "").strip() and pdf_rec["definition"]:
            drift_definition.append(eid)
        # Recurrence normalised compare (PDF "0 : 1" vs local "0:1")
        pdf_recur = pdf_rec["recurrence"].replace(" ", "")
        loc_recur = (loc.get("recurrence") or "").replace(" ", "")
        if loc_recur and pdf_recur and loc_recur != pdf_recur:
            drift_recurrence.append((eid, loc_recur, pdf_recur))
        # NV / PN / nillable mismatches.
        loc_nv = loc.get("not_value_allowed")
        if loc_nv is None or bool(loc_nv) != pdf_rec["not_values"]:
            drift_nv.append((eid, pdf_rec["not_values"], loc_nv))
        loc_pn = loc.get("pertinent_negative_allowed")
        if loc_pn is None or bool(loc_pn) != pdf_rec["pertinent_negatives"]:
            drift_pn.append((eid, pdf_rec["pertinent_negatives"], loc_pn))
        loc_nil = loc.get("nillable")
        if loc_nil is None or bool(loc_nil) != pdf_rec["is_nillable"]:
            drift_nil.append((eid, pdf_rec["is_nillable"], loc_nil))
        # National / state mismatches.
        loc_nat = (loc.get("national_element") or "").lower() == "national"
        if loc_nat != pdf_rec["national_element"]:
            drift_national.append((eid, pdf_rec["national_element"], loc.get("national_element")))
        loc_st = (loc.get("state_element") or "").lower() == "state"
        if loc_st != pdf_rec["state_element"]:
            drift_state.append((eid, pdf_rec["state_element"], loc.get("state_element")))
        # Code list richness.
        if pdf_rec["code_list"] and not loc.get("defined_list_ref"):
            missing_codelist_local.append((eid, len(pdf_rec["code_list"])))
        if pdf_rec.get("constraints") and not loc.get("min_length") and not loc.get("max_length") and not loc.get("pattern"):
            missing_constraints_local.append(eid)

    print()
    print("=== Drift summary (PDF is law) ===")
    print(f"usage drift:                {len(drift_usage):4d}  e.g. {drift_usage[:5]}")
    print(f"definition missing locally: {len(drift_definition):4d}  e.g. {drift_definition[:5]}")
    print(f"recurrence drift:           {len(drift_recurrence):4d}  e.g. {drift_recurrence[:5]}")
    print(f"NV-allowed drift:           {len(drift_nv):4d}  e.g. {drift_nv[:5]}")
    print(f"PN-allowed drift:           {len(drift_pn):4d}  e.g. {drift_pn[:5]}")
    print(f"nillable drift:             {len(drift_nil):4d}  e.g. {drift_nil[:5]}")
    print(f"national-flag drift:        {len(drift_national):4d}  e.g. {drift_national[:5]}")
    print(f"state-flag drift:           {len(drift_state):4d}  e.g. {drift_state[:5]}")
    print(f"local missing code-list:    {len(missing_codelist_local):4d}  e.g. {missing_codelist_local[:5]}")
    print(f"local missing constraints:  {len(missing_constraints_local):4d}  e.g. {missing_constraints_local[:5]}")
else:
    print(f"local registry not found at {LOCAL}")
