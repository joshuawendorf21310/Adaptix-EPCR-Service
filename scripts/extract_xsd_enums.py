"""Extract canonical NEMSIS v3.5.1 simpleType enumerations and element-to-type
mappings from the XSD bundle into a JSON lookup file.

Output path: artifact/generated/2025/.xsd_enums.json

Structure::
    {
      "simple_types": {
        "<TypeName>": {"<code>": "<label>", ...}
      },
      "element_types": {
        "<ElementId>": "<TypeName>"
      },
      "element_inline_enums": {
        "<ElementId>": {"<code>": "<label>", ...}
      }
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET


XSD_DIR = Path(
    "nemsis_test/assets/xsd/extracted/NEMSIS_XSDs"
).resolve()
OUT = Path("artifact/generated/2025/.xsd_enums.json").resolve()

NS = {"xs": "http://www.w3.org/2001/XMLSchema"}


def _doc_text(anno_parent: ET.Element) -> str:
    anno = anno_parent.find("xs:annotation", NS)
    if anno is None:
        return ""
    doc = anno.find("xs:documentation", NS)
    if doc is None:
        return ""
    fragments: list[str] = []
    if doc.text:
        fragments.append(doc.text)
    for child in doc.iter():
        if child is doc:
            continue
        if child.text:
            fragments.append(child.text)
    raw = " ".join(fragments)
    return re.sub(r"\s+", " ", raw).strip()


def _collect_enum(st: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    restriction = st.find("xs:restriction", NS)
    if restriction is None:
        return out
    for enum in restriction.findall("xs:enumeration", NS):
        value = enum.get("value")
        if value is None:
            continue
        out[value] = _doc_text(enum)
    return out


def _walk_simple_types(root: ET.Element) -> dict[str, dict[str, str]]:
    named: dict[str, dict[str, str]] = {}
    for st in root.iter(f"{{{NS['xs']}}}simpleType"):
        name = st.get("name")
        if not name:
            continue
        enum = _collect_enum(st)
        if enum:
            named[name] = enum
    return named


def _walk_elements(root: ET.Element) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    element_types: dict[str, str] = {}
    element_inline: dict[str, dict[str, str]] = {}
    for el in root.iter(f"{{{NS['xs']}}}element"):
        name = el.get("name")
        if not name:
            continue
        typ = el.get("type")
        if typ:
            element_types[name] = typ
            continue
        st = el.find("xs:simpleType", NS)
        if st is not None:
            enum = _collect_enum(st)
            if enum:
                element_inline[name] = enum
            continue
        ctype = el.find("xs:complexType", NS)
        if ctype is None:
            continue
        sc = ctype.find("xs:simpleContent", NS)
        if sc is None:
            continue
        ext = sc.find("xs:extension", NS)
        if ext is not None and ext.get("base"):
            element_types[name] = ext.get("base")
            continue
        restriction = sc.find("xs:restriction", NS)
        if restriction is not None and restriction.get("base"):
            element_types[name] = restriction.get("base")
    return element_types, element_inline


def extract() -> dict[str, object]:
    simple_types: dict[str, dict[str, str]] = {}
    element_types: dict[str, str] = {}
    element_inline_enums: dict[str, dict[str, str]] = {}

    for xsd_path in sorted(XSD_DIR.glob("*.xsd")):
        tree = ET.parse(xsd_path)
        root = tree.getroot()
        simple_types.update(_walk_simple_types(root))
        etypes, einline = _walk_elements(root)
        element_types.update(etypes)
        element_inline_enums.update(einline)

    return {
        "simple_types": simple_types,
        "element_types": element_types,
        "element_inline_enums": element_inline_enums,
    }


def main() -> None:
    if not XSD_DIR.is_dir():
        raise SystemExit(f"XSD directory not found: {XSD_DIR}")
    data = extract()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    print(
        f"Wrote {OUT}: "
        f"{len(data['simple_types'])} named simpleTypes, "
        f"{len(data['element_types'])} element-to-type mappings, "
        f"{len(data['element_inline_enums'])} inline element enums"
    )


if __name__ == "__main__":
    main()
