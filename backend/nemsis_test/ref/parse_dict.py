"""Parse the NEMSIS 3.5.1 Data Dictionary PDF text into a structured JSON registry.

Source: nemsis_test/ref/NEMSISDataDictionary_3.5.1.txt (extracted from the official PDF)
Output: nemsis_test/ref/NEMSISDataDictionary_3.5.1.json

Each element record contains:
  element_number, name, dataset, definition, national_element, state_element,
  pertinent_negatives, not_values, is_nillable, version2_element, usage,
  recurrence, performance_measures, code_list (list of {code, description}),
  data_element_comment, version3_changes, deprecated, validation_rules
  (list of {rule_id, level, message}), constraints (data_type, min_length,
  max_length, min_inclusive, max_inclusive, pattern), source_pages.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SRC = Path("nemsis_test/ref/NEMSISDataDictionary_3.5.1.txt")
OUT = Path("nemsis_test/ref/NEMSISDataDictionary_3.5.1.json")

# ----------------------------------------------------------------------------
# Step 1: split the document into pages.

PAGE_HEADER_RE = re.compile(r"^===== PAGE (\d+) / (\d+) =====$")


def split_pages(text: str) -> list[tuple[int, str]]:
    pages: list[tuple[int, str]] = []
    current_no = 0
    current_lines: list[str] = []
    for line in text.splitlines():
        m = PAGE_HEADER_RE.match(line)
        if m:
            if current_no:
                pages.append((current_no, "\n".join(current_lines)))
            current_no = int(m.group(1))
            current_lines = []
        else:
            current_lines.append(line)
    if current_no:
        pages.append((current_no, "\n".join(current_lines)))
    return pages


# ----------------------------------------------------------------------------
# Step 2: detect element page boundaries.

ELEMENT_HEADING_RE = re.compile(
    r"^([deus][A-Za-z]+)\.(\d{2})(?:\s*\(DEPRECATED\))?$"
)
ELEMENT_TITLE_RE = re.compile(
    r"^-?\s*([deus][A-Za-z]+)\.(\d{2})\s*-?\s*(.+?)\s*$"
)


def detect_element_pages(pages: list[tuple[int, str]]) -> list[tuple[str, list[int]]]:
    """Return [(element_id, [page_numbers]), ...] in document order."""
    starts: list[tuple[str, str, int]] = []  # (element_id, name, page_no)
    for page_no, body in pages:
        lines = [l for l in body.splitlines() if l.strip()]
        # An element page starts with the bare element number on its own line,
        # followed by "<id> - <name>", followed by "Definition".
        for i in range(len(lines) - 2):
            mh = ELEMENT_HEADING_RE.match(lines[i].strip())
            if not mh:
                continue
            # Find the title line within the next 1-3 lines (deprecated entries
            # interpose a 'Deprecated' marker line between heading and title).
            mt = None
            title_offset = 0
            for k in range(1, 4):
                if i + k >= len(lines):
                    break
                cand = lines[i + k].strip()
                if cand == "Deprecated":
                    continue
                m_try = ELEMENT_TITLE_RE.match(cand)
                if m_try and m_try.group(1) == mh.group(1) and m_try.group(2) == mh.group(2):
                    mt = m_try
                    title_offset = k
                    break
            if not mt:
                continue
            # 'Definition' must appear within 5 lines after the title line.
            if not any(
                lines[j].strip() == "Definition"
                for j in range(i + title_offset + 1, min(i + title_offset + 6, len(lines)))
            ):
                continue
            element_id = f"{mh.group(1)}.{mh.group(2)}"
            name = mt.group(3).replace("(DEPRECATED)", "").strip()
            starts.append((element_id, name, page_no))
            break

    # Group pages until the next element starts.
    result: list[tuple[str, str, list[int]]] = []
    page_total = pages[-1][0] if pages else 0
    for idx, (eid, name, start) in enumerate(starts):
        end = starts[idx + 1][2] - 1 if idx + 1 < len(starts) else page_total
        result.append((eid, name, list(range(start, end + 1))))
    return result


# ----------------------------------------------------------------------------
# Step 3: parse the body of an element across its pages.

ATTR_LABELS = (
    "National Element",
    "State Element",
    "Version 2 Element",
    "Pertinent Negatives (PN)",
    "NOT Values",
    "Is Nillable",
    "Usage",
    "Recurrence",
)

PERFORMANCE_MEASURES = (
    "Airway",
    "Cardiac Arrest",
    "Pediatric",
    "Response",
    "STEMI",
    "Stroke",
    "Trauma",
)

SECTION_HEADERS = {
    "Definition",
    "Constraints",
    "Code List",
    "Data Element Comment",
    "Version 3 Changes Implemented",
    "Element Deprecated",
    "Associated Performance Measure Initiatives",
    "Associated Validation Rules",
    "Attributes",
}

PUBLISHED_RE = re.compile(r"^Published:\s*\d+/\d+/\d+")
NEMSIS_FOOTER_RE = re.compile(r"^NEMSIS Version 3\.5\.1")


def clean_lines(pages: list[tuple[int, str]], page_nos: list[int]) -> list[str]:
    lines: list[str] = []
    for page_no, body in pages:
        if page_no not in page_nos:
            continue
        for raw in body.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if PUBLISHED_RE.match(stripped):
                continue
            if NEMSIS_FOOTER_RE.match(stripped):
                continue
            if stripped.startswith("Legend Dataset Level:"):
                continue
            if stripped.startswith("Usage: M = Mandatory"):
                continue
            if stripped.startswith("Attributes: N = Not Values"):
                continue
            if stripped.startswith("I = Custom Element ID"):
                continue
            if stripped in {"State", "National", "State National"}:
                # Banner placed at top of pages – not informative for parsing.
                continue
            lines.append(stripped)
    return lines


def parse_attribute_pairs(line: str) -> list[tuple[str, str]]:
    """Split a line like 'National Element Yes Pertinent Negatives (PN) No' into pairs."""
    pairs: list[tuple[str, str]] = []
    remainder = line
    while remainder:
        # Find the earliest known label in the remainder.
        candidates = [(remainder.find(label), label) for label in ATTR_LABELS]
        candidates = [(idx, lbl) for idx, lbl in candidates if idx >= 0]
        if not candidates:
            break
        candidates.sort()
        idx, label = candidates[0]
        if idx > 0:
            # Leading text is a value for the previous label; ignore here.
            pass
        # Find next label after this label position.
        start_value = idx + len(label)
        next_candidates = [
            (remainder.find(lbl, start_value), lbl) for lbl in ATTR_LABELS if lbl != label
        ]
        next_candidates = [(j, lbl) for j, lbl in next_candidates if j >= 0]
        next_idx = min(j for j, _ in next_candidates) if next_candidates else len(remainder)
        value = remainder[start_value:next_idx].strip()
        pairs.append((label, value))
        remainder = remainder[next_idx:].strip()
    return pairs


def parse_constraints(lines: list[str]) -> dict:
    """Lines under 'Constraints' until the next section."""
    constraints: dict = {}
    keys = {
        "Data Type": "data_type",
        "minLength": "min_length",
        "maxLength": "max_length",
        "minInclusive": "min_inclusive",
        "maxInclusive": "max_inclusive",
        "Pattern": "pattern",
        "minValue": "min_inclusive",
        "maxValue": "max_inclusive",
    }
    i = 0
    while i < len(lines):
        line = lines[i]
        if line in keys:
            key = keys[line]
            value = lines[i + 1] if i + 1 < len(lines) else ""
            constraints[key] = value
            i += 2
        else:
            i += 1
    return constraints


def parse_code_list(lines: list[str]) -> list[dict]:
    """Lines under 'Code List' until next section. Format alternates code / description,
    sometimes embedded on the same line."""
    if not lines:
        return []
    # Drop a leading 'Code Description' header if present.
    start = 0
    if lines[0].lower().startswith("code") and "description" in lines[0].lower():
        start = 1
    body = lines[start:]
    items: list[dict] = []
    code_re = re.compile(r"^(\d{7})\s*(.*)$")
    pending_code: str | None = None
    for ln in body:
        m = code_re.match(ln)
        if m:
            if pending_code is not None:
                # No description was found before next code; record empty.
                items.append({"code": pending_code, "description": ""})
            code = m.group(1)
            rest = m.group(2).strip()
            if rest:
                items.append({"code": code, "description": rest})
                pending_code = None
            else:
                pending_code = code
        else:
            if pending_code is not None:
                items.append({"code": pending_code, "description": ln})
                pending_code = None
            else:
                # Continuation of previous description.
                if items:
                    items[-1]["description"] = (
                        items[-1]["description"] + " " + ln
                    ).strip()
    if pending_code is not None:
        items.append({"code": pending_code, "description": ""})
    return items


def parse_validation_rules(lines: list[str]) -> list[dict]:
    rules: list[dict] = []
    if not lines:
        return rules
    start = 0
    if lines[0].lower().startswith("rule id"):
        start = 1
    rule_re = re.compile(r"^(nemSch_[a-z]\d+)\s+(Error|Warning|Info)\s*(.*)$")
    current: dict | None = None
    for ln in lines[start:]:
        m = rule_re.match(ln)
        if m:
            if current:
                rules.append(current)
            current = {
                "rule_id": m.group(1),
                "level": m.group(2),
                "message": m.group(3).strip(),
            }
        else:
            if current:
                current["message"] = (current["message"] + " " + ln).strip()
    if current:
        rules.append(current)
    return rules


def parse_performance_measures(lines: list[str]) -> list[str]:
    text = " ".join(lines)
    # The PDF lays out the seven categories on a single line; only those that
    # apply are visually highlighted, but pypdf flattens them into the same
    # text. We treat presence of all seven as "all applicable" only if the
    # section was rendered (caller invokes us only when it exists).
    found = [m for m in PERFORMANCE_MEASURES if m in text]
    return found


def detect_section_boundaries(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return (section_name, start_idx_inclusive, end_idx_exclusive)."""
    bounds: list[tuple[str, int]] = []
    for i, line in enumerate(lines):
        if line in SECTION_HEADERS:
            bounds.append((line, i))
    sections: list[tuple[str, int, int]] = []
    for j, (name, start) in enumerate(bounds):
        end = bounds[j + 1][1] if j + 1 < len(bounds) else len(lines)
        sections.append((name, start + 1, end))
    return sections


def parse_definition(lines: list[str], end_idx: int) -> str:
    """Definition is the lines from start (under 'Definition') until the
    attribute-table line that contains 'National Element'."""
    body = []
    for ln in lines[:end_idx]:
        if "National Element" in ln:
            break
        body.append(ln)
    return " ".join(body).strip()


DATASET_PREFIX = {
    "e": "EMSDataSet",
    "d": "DEMDataSet",
    "s": "StateDataSet",
    "se": "StateDataSet",
    "sd": "StateDataSet",
    "u": "EMSDataSet",  # custom result correlation (UPatientCareReport)
}


def dataset_for(element_id: str) -> str:
    # Examine prefix letters before the first uppercase letter.
    m = re.match(r"^([a-z]+)[A-Z]", element_id)
    prefix = m.group(1) if m else element_id[0]
    return DATASET_PREFIX.get(prefix, "EMSDataSet")


def section_group(element_id: str) -> str:
    """Return the section/group identifier (e.g. 'eAirway' for 'eAirway.02')."""
    return element_id.split(".")[0]


def parse_element_body(lines: list[str], element_id: str, name: str) -> dict:
    record: dict = {
        "element_number": element_id,
        "name": name,
        "dataset": dataset_for(element_id),
        "section": section_group(element_id),
    }

    # Locate the "Definition" header.
    try:
        def_idx = lines.index("Definition")
    except ValueError:
        return record

    sections = detect_section_boundaries(lines)
    section_names = {s[0] for s in sections}

    # Definition runs from def_idx + 1 until the attribute-table line.
    def_end = len(lines)
    for sec_name, start, _ in sections:
        if sec_name != "Definition":
            def_end = min(def_end, start - 1)
    record["definition"] = parse_definition(lines[def_idx + 1:], def_end - def_idx - 1)

    # Parse the attribute-table line: there will typically be two lines that
    # together cover the eight attribute pairs.
    attr_indices = [
        i for i, ln in enumerate(lines) if "National Element" in ln
    ]
    attrs: dict[str, str] = {}
    if attr_indices:
        a = attr_indices[0]
        for line in lines[a:a + 4]:  # Up to 4 attribute lines (PDF wrap)
            for label, value in parse_attribute_pairs(line):
                attrs[label] = value
            if len(attrs) >= 8:
                break

    yes = lambda v: (v or "").strip().lower() in {"yes"}
    record["national_element"] = yes(attrs.get("National Element", ""))
    record["state_element"] = yes(attrs.get("State Element", ""))
    record["pertinent_negatives"] = yes(attrs.get("Pertinent Negatives (PN)", ""))
    record["not_values"] = yes(attrs.get("NOT Values", ""))
    record["is_nillable"] = yes(attrs.get("Is Nillable", ""))
    record["version2_element"] = (attrs.get("Version 2 Element") or "").strip()
    record["usage"] = (attrs.get("Usage") or "").strip()
    record["recurrence"] = (attrs.get("Recurrence") or "").strip()

    # Per-section content extraction.
    for sec_name, start, end in sections:
        chunk = lines[start:end]
        if sec_name == "Associated Performance Measure Initiatives":
            record["performance_measures"] = parse_performance_measures(chunk)
        elif sec_name == "Constraints":
            record["constraints"] = parse_constraints(chunk)
        elif sec_name == "Code List":
            record["code_list"] = parse_code_list(chunk)
        elif sec_name == "Data Element Comment":
            record["data_element_comment"] = " ".join(chunk).strip()
        elif sec_name == "Version 3 Changes Implemented":
            record["version3_changes"] = " ".join(chunk).strip()
        elif sec_name == "Element Deprecated":
            record["deprecated"] = True
        elif sec_name == "Associated Validation Rules":
            record["validation_rules"] = parse_validation_rules(chunk)

    record.setdefault("performance_measures", [])
    record.setdefault("constraints", {})
    record.setdefault("code_list", [])
    record.setdefault("validation_rules", [])
    deprecated_marker = "Deprecated" in lines[: lines.index("Definition")] if "Definition" in lines else False
    record["deprecated"] = (
        deprecated_marker
        or "(DEPRECATED)" in name.upper()
        or any("(DEPRECATED)" in (cl.get("description") or "").upper() for cl in record["code_list"])
    )

    return record


# ----------------------------------------------------------------------------
# Driver.

def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    pages = split_pages(text)
    print(f"pages parsed: {len(pages)}", file=sys.stderr)

    element_blocks = detect_element_pages(pages)
    print(f"element blocks detected: {len(element_blocks)}", file=sys.stderr)

    page_index = {n: body for n, body in pages}

    records: list[dict] = []
    seen_ids: set[str] = set()
    for element_id, name, page_nos in element_blocks:
        block = clean_lines(pages, page_nos)
        rec = parse_element_body(block, element_id, name)
        rec["source_pages"] = page_nos
        if element_id in seen_ids:
            # The dictionary renders dAgency.01/.02/.04 twice (once under
            # StateDataSet pages 8-10 and again under DEMDataSet). Keep the
            # first occurrence; later ones are the same authoritative entry.
            continue
        seen_ids.add(element_id)
        records.append(rec)

    # Aggregate counts.
    by_dataset: dict[str, int] = {}
    for r in records:
        by_dataset[r["dataset"]] = by_dataset.get(r["dataset"], 0) + 1
    print(f"elements by dataset: {by_dataset}", file=sys.stderr)

    OUT.write_text(
        json.dumps(
            {
                "version": "3.5.1.251001CP2",
                "published": "2025-10-01",
                "source": "https://nemsis.org/media/nemsis_v3/release-3.5.1/DataDictionary/PDFHTML/EMSDEMSTATE/NEMSISDataDictionary.pdf",
                "totals": {
                    "elements": len(records),
                    "by_dataset": by_dataset,
                },
                "elements": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes; {len(records)} elements)")


if __name__ == "__main__":
    main()
