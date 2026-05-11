"""Backfill NEMSIS v3.5.1 defined-list codes from local XSD bundle into the
canonical normalized fields.json registry.

Reads:  epcr_app/nemsis_resources/official/raw/{xsd_ems,xsd_dem,xsd_state}/*.xsd
Writes: epcr_app/nemsis_resources/official/normalized/fields.json (in place)

Algorithm:
  1. Index every named xs:simpleType / xs:complexType across all XSDs.
  2. Index every top-level xs:element with name like "X.NN" -> declared type
     or inline simpleType/complexType node.
  3. For each registry record with empty allowed_values, resolve the element's
     type chain (complexType.simpleContent.extension/restriction.@base ->
     simpleType.restriction.@base / union memberTypes) until enumerations are
     reached. Collect (value, documentation) pairs in document order.
  4. Opportunistically fill data_type / constraints (min_length, max_length,
     pattern, min_inclusive, max_inclusive) only when missing.
  5. Save fields.json with indent=2, ensure_ascii=False, original ordering.

Existing populated allowed_values are preserved verbatim (the registry already
uses {code, display}; new entries match that shape to keep the file
internally consistent).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree

XS_NS = "http://www.w3.org/2001/XMLSchema"
NSMAP = {"xs": XS_NS}

BACKEND_DIR = Path(__file__).resolve().parent.parent
RAW_ROOT = BACKEND_DIR / "epcr_app" / "nemsis_resources" / "official" / "raw"
XSD_DIRS = [RAW_ROOT / "xsd_ems", RAW_ROOT / "xsd_dem", RAW_ROOT / "xsd_state"]
REGISTRY_PATH = (
    BACKEND_DIR
    / "epcr_app"
    / "nemsis_resources"
    / "official"
    / "normalized"
    / "fields.json"
)

XS_TO_DATA_TYPE = {
    "string": "string",
    "token": "string",
    "normalizedString": "string",
    "date": "date",
    "dateTime": "datetime",
    "time": "time",
    "integer": "integer",
    "int": "integer",
    "long": "integer",
    "short": "integer",
    "nonNegativeInteger": "integer",
    "positiveInteger": "integer",
    "decimal": "decimal",
    "double": "decimal",
    "float": "decimal",
    "boolean": "boolean",
    "base64Binary": "base64Binary",
    "anyURI": "string",
}


def local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def strip_ns(qname: Optional[str]) -> Optional[str]:
    if qname is None:
        return None
    return qname.split(":", 1)[1] if ":" in qname else qname


def is_xs_primitive(qname: str) -> bool:
    return qname.startswith("xs:") or qname in XS_TO_DATA_TYPE


def load_xsds() -> List[Tuple[Path, etree._Element]]:
    docs: List[Tuple[Path, etree._Element]] = []
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    for d in XSD_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.xsd")):
            tree = etree.parse(str(p), parser)
            docs.append((p, tree.getroot()))
    return docs


def build_indexes(docs):
    """Return (type_index, element_index).

    type_index: name -> Element (xs:simpleType or xs:complexType)
    element_index: element_name (e.g. eVitals.06) -> Element (xs:element)
    """
    type_index: Dict[str, etree._Element] = {}
    element_index: Dict[str, etree._Element] = {}
    for path, root in docs:
        for st in root.iter(f"{{{XS_NS}}}simpleType"):
            name = st.get("name")
            if name and name not in type_index:
                type_index[name] = st
        for ct in root.iter(f"{{{XS_NS}}}complexType"):
            name = ct.get("name")
            if name and name not in type_index:
                type_index[name] = ct
        # Top-level xs:element with name="*.NN"
        for el in root.iter(f"{{{XS_NS}}}element"):
            name = el.get("name") or ""
            if "." in name and name not in element_index:
                element_index[name] = el
    return type_index, element_index


def resolve_simple_type(
    node: etree._Element,
    type_index: Dict[str, etree._Element],
    visited: Optional[set] = None,
) -> Tuple[List[dict], Dict[str, str], Optional[str]]:
    """Resolve a simpleType element to (enumerations, facets, base_xs_type).

    Walks restriction/@base and union/@memberTypes chains across the index.
    Returns enumerations as list of {"code", "display"}.
    """
    if visited is None:
        visited = set()

    enums: List[dict] = []
    facets: Dict[str, str] = {}
    base_xs_type: Optional[str] = None

    if node is None:
        return enums, facets, base_xs_type

    restriction = node.find(f"{{{XS_NS}}}restriction")
    union = node.find(f"{{{XS_NS}}}union")
    list_node = node.find(f"{{{XS_NS}}}list")

    if restriction is not None:
        base = restriction.get("base")
        if base:
            base_local = strip_ns(base)
            if base.startswith("xs:") and base_local in XS_TO_DATA_TYPE:
                base_xs_type = base_local
            elif base_local and base_local in type_index and base_local not in visited:
                visited.add(base_local)
                sub_enums, sub_facets, sub_base = resolve_type_node(
                    type_index[base_local], type_index, visited
                )
                enums.extend(sub_enums)
                for k, v in sub_facets.items():
                    facets.setdefault(k, v)
                if base_xs_type is None:
                    base_xs_type = sub_base

        # Direct enumerations on this restriction
        for enum_el in restriction.findall(f"{{{XS_NS}}}enumeration"):
            value = enum_el.get("value")
            if value is None:
                continue
            doc_el = enum_el.find(
                f"{{{XS_NS}}}annotation/{{{XS_NS}}}documentation"
            )
            doc_text = ""
            if doc_el is not None:
                doc_text = " ".join((doc_el.text or "").split()).strip()
            enums.append({"code": value, "display": doc_text})

        # Facets
        for facet_local, key in (
            ("minLength", "min_length"),
            ("maxLength", "max_length"),
            ("pattern", "pattern"),
            ("minInclusive", "min_inclusive"),
            ("maxInclusive", "max_inclusive"),
            ("minExclusive", "min_exclusive"),
            ("maxExclusive", "max_exclusive"),
            ("totalDigits", "total_digits"),
            ("fractionDigits", "fraction_digits"),
        ):
            f = restriction.find(f"{{{XS_NS}}}{facet_local}")
            if f is not None and f.get("value") is not None:
                facets.setdefault(key, f.get("value"))

    elif union is not None:
        members = union.get("memberTypes") or ""
        for m in members.split():
            ml = strip_ns(m)
            if ml and ml in type_index and ml not in visited:
                visited.add(ml)
                sub_enums, sub_facets, sub_base = resolve_type_node(
                    type_index[ml], type_index, visited
                )
                enums.extend(sub_enums)
                for k, v in sub_facets.items():
                    facets.setdefault(k, v)
                if base_xs_type is None:
                    base_xs_type = sub_base
        # Inline simpleTypes inside union
        for inline in union.findall(f"{{{XS_NS}}}simpleType"):
            sub_enums, sub_facets, sub_base = resolve_simple_type(
                inline, type_index, visited
            )
            enums.extend(sub_enums)
            for k, v in sub_facets.items():
                facets.setdefault(k, v)
            if base_xs_type is None:
                base_xs_type = sub_base

    elif list_node is not None:
        item_type = list_node.get("itemType")
        if item_type:
            il = strip_ns(item_type)
            if il and il in type_index and il not in visited:
                visited.add(il)
                sub_enums, sub_facets, sub_base = resolve_type_node(
                    type_index[il], type_index, visited
                )
                enums.extend(sub_enums)
                for k, v in sub_facets.items():
                    facets.setdefault(k, v)
                if base_xs_type is None:
                    base_xs_type = sub_base

    return enums, facets, base_xs_type


def resolve_complex_type(
    node: etree._Element,
    type_index: Dict[str, etree._Element],
    visited: Optional[set] = None,
) -> Tuple[List[dict], Dict[str, str], Optional[str]]:
    if visited is None:
        visited = set()
    enums: List[dict] = []
    facets: Dict[str, str] = {}
    base_xs_type: Optional[str] = None

    sc = node.find(f"{{{XS_NS}}}simpleContent")
    if sc is not None:
        for child_tag in ("extension", "restriction"):
            ext = sc.find(f"{{{XS_NS}}}{child_tag}")
            if ext is None:
                continue
            base = ext.get("base")
            if base:
                bl = strip_ns(base)
                if base.startswith("xs:") and bl in XS_TO_DATA_TYPE:
                    base_xs_type = bl
                elif bl and bl in type_index and bl not in visited:
                    visited.add(bl)
                    sub_enums, sub_facets, sub_base = resolve_type_node(
                        type_index[bl], type_index, visited
                    )
                    enums.extend(sub_enums)
                    for k, v in sub_facets.items():
                        facets.setdefault(k, v)
                    if base_xs_type is None:
                        base_xs_type = sub_base
            # restriction may carry enums/facets of its own
            if child_tag == "restriction":
                for enum_el in ext.findall(f"{{{XS_NS}}}enumeration"):
                    value = enum_el.get("value")
                    if value is None:
                        continue
                    doc_el = enum_el.find(
                        f"{{{XS_NS}}}annotation/{{{XS_NS}}}documentation"
                    )
                    doc_text = ""
                    if doc_el is not None:
                        doc_text = " ".join((doc_el.text or "").split()).strip()
                    enums.append({"code": value, "display": doc_text})
                for facet_local, key in (
                    ("minLength", "min_length"),
                    ("maxLength", "max_length"),
                    ("pattern", "pattern"),
                    ("minInclusive", "min_inclusive"),
                    ("maxInclusive", "max_inclusive"),
                ):
                    f = ext.find(f"{{{XS_NS}}}{facet_local}")
                    if f is not None and f.get("value") is not None:
                        facets.setdefault(key, f.get("value"))
            break
    return enums, facets, base_xs_type


def resolve_type_node(node, type_index, visited):
    tag = local_name(node.tag)
    if tag == "simpleType":
        return resolve_simple_type(node, type_index, visited)
    if tag == "complexType":
        return resolve_complex_type(node, type_index, visited)
    return [], {}, None


def resolve_element(
    el: etree._Element, type_index: Dict[str, etree._Element]
):
    """Resolve an element's allowed values + facets + base xs type."""
    visited: set = set()
    type_attr = el.get("type")
    if type_attr:
        tl = strip_ns(type_attr)
        if type_attr.startswith("xs:") and tl in XS_TO_DATA_TYPE:
            return [], {}, tl
        if tl and tl in type_index:
            visited.add(tl)
            return resolve_type_node(type_index[tl], type_index, visited)
        return [], {}, None
    # Inline type
    inline_st = el.find(f"{{{XS_NS}}}simpleType")
    if inline_st is not None:
        return resolve_simple_type(inline_st, type_index, visited)
    inline_ct = el.find(f"{{{XS_NS}}}complexType")
    if inline_ct is not None:
        return resolve_complex_type(inline_ct, type_index, visited)
    return [], {}, None


def main() -> int:
    docs = load_xsds()
    type_index, element_index = build_indexes(docs)
    print(
        f"Indexed {len(type_index)} named types, {len(element_index)} elements "
        f"from {len(docs)} XSDs."
    )

    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        records = json.load(f)

    before_with_av = sum(1 for r in records if r.get("allowed_values"))

    gained_av = 0
    gained_dt = 0
    gained_ct = 0
    unresolved: List[str] = []

    for rec in records:
        eid = rec.get("element_id") or rec.get("field_id")
        if not eid:
            continue
        el = element_index.get(eid)
        if el is None:
            if not rec.get("allowed_values"):
                unresolved.append(eid)
            continue

        enums, facets, base_xs = resolve_element(el, type_index)

        # Allowed values: only fill if currently empty
        if not rec.get("allowed_values") and enums:
            # de-duplicate preserving order
            seen = set()
            deduped = []
            for e in enums:
                key = e["code"]
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(e)
            rec["allowed_values"] = deduped
            gained_av += 1

        # data_type: only fill if null/empty
        if not rec.get("data_type") and base_xs:
            rec["data_type"] = XS_TO_DATA_TYPE.get(base_xs, base_xs)
            gained_dt += 1

        # Constraints
        if facets:
            constraints = rec.get("constraints") or {}
            if not isinstance(constraints, dict):
                constraints = {}
            changed = False
            for key, val in facets.items():
                if key not in constraints or constraints.get(key) in (None, ""):
                    constraints[key] = val
                    changed = True
                # mirror to top-level fields where they exist
                if key in ("min_length", "max_length", "pattern"):
                    if rec.get(key) in (None, ""):
                        rec[key] = val
                        changed = True
            if changed:
                rec["constraints"] = constraints
                gained_ct += 1

        if not rec.get("allowed_values") and not enums:
            # Did not resolve to a code list; might legitimately be free text.
            # Only flag as unresolved if data_type also missing AND element id
            # is not in a "free text" common pattern. Keep simple: track id.
            if base_xs is None:
                unresolved.append(eid)

    after_with_av = sum(1 for r in records if r.get("allowed_values"))
    still_empty = [r["element_id"] for r in records if not r.get("allowed_values")]

    with REGISTRY_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("=" * 60)
    print(f"Records BEFORE with allowed_values: {before_with_av}")
    print(f"Records AFTER  with allowed_values: {after_with_av}")
    print(f"Net gained allowed_values:          {gained_av}")
    print(f"Records gained data_type:           {gained_dt}")
    print(f"Records gained constraints:         {gained_ct}")
    print(f"Records still empty allowed_values: {len(still_empty)}")
    print("Sample still-empty element_ids (up to 30):")
    for eid in still_empty[:30]:
        print(f"  - {eid}")
    if unresolved:
        print(f"Elements with no resolvable type ({len(unresolved)} sample up to 20):")
        for eid in unresolved[:20]:
            print(f"  - {eid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
