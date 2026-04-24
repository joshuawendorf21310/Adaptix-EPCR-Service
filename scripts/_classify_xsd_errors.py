"""Classify all local XSD errors by (element_id, current_value) to expose every missing element-specific mapping.

Writes a compact, grouped summary to .xsd_errors_classified.json for fix planning.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from lxml import etree

_REPO_ROOT = Path(__file__).resolve().parents[1]
_XSD_ROOT = _REPO_ROOT / "nemsis_test" / "assets" / "xsd" / "extracted" / "NEMSIS_XSDs"
_DEM_XSD = _XSD_ROOT / "DEMDataSet_v3.xsd"
_EMS_XSD = _XSD_ROOT / "EMSDataSet_v3.xsd"
_GENERATED = _REPO_ROOT / "artifact" / "generated" / "2025"
_OUT = _GENERATED / ".xsd_errors_classified.json"

_ENUM_RE = re.compile(
    r"Element '\{http://www\.nemsis\.org\}(?P<element>[A-Za-z0-9.]+)'"
    r"(?:, attribute '(?P<attr>[A-Za-z0-9]+)')?:"
    r" \[facet '(?P<facet>[a-zA-Z]+)'\] The value '(?P<value>[^']*)' (?P<rest>.*)"
)
_ATOMIC_RE = re.compile(
    r"Element '\{http://www\.nemsis\.org\}(?P<element>[A-Za-z0-9.]+)': '(?P<value>[^']*)' is not a valid value of the atomic type"
)
_EMPTY_RE = re.compile(
    r"Element '\{http://www\.nemsis\.org\}(?P<element>[A-Za-z0-9.]+)'"
    r"(?:, attribute '(?P<attr>[A-Za-z0-9]+)')?:"
    r" \[facet '(?P<facet>[a-zA-Z]+)'\] The value has a length"
)


def _pick_xsd(xml_path: Path) -> Path:
    head = xml_path.read_bytes()[:2048].decode("utf-8", errors="replace")
    if "<DEMDataSet" in head or "DEMDataSet_v3.xsd" in head:
        return _DEM_XSD
    return _EMS_XSD


def _enum_allowed(msg: str) -> list[str]:
    m = re.search(r"\{([^}]*)\}", msg)
    if m is None:
        return []
    body = m.group(1)
    vals = re.findall(r"'([^']*)'", body)
    return vals


def main() -> int:
    grouped: dict[str, dict] = defaultdict(lambda: {"cases": set(), "attr": None, "facet": None, "values": set(), "allowed": set()})
    for xml_path in sorted(_GENERATED.glob("2025-*.xml")):
        xsd = etree.XMLSchema(etree.parse(str(_pick_xsd(xml_path))))
        doc = etree.parse(str(xml_path))
        xsd.validate(doc)
        for err in xsd.error_log:
            msg = err.message
            m = _ENUM_RE.match(msg)
            if m is not None:
                element = m.group("element")
                attr = m.group("attr")
                facet = m.group("facet")
                value = m.group("value")
                rest = m.group("rest")
                key = f"{element}" + (f"@{attr}" if attr else "")
                grouped[key]["cases"].add(xml_path.name)
                grouped[key]["attr"] = attr
                grouped[key]["facet"] = facet
                grouped[key]["values"].add(value)
                allowed = _enum_allowed(rest)
                if allowed:
                    grouped[key]["allowed"].update(allowed)
                continue
            m = _ATOMIC_RE.match(msg)
            if m is not None:
                element = m.group("element")
                value = m.group("value")
                key = element
                grouped[key]["cases"].add(xml_path.name)
                grouped[key]["values"].add(value)
                grouped[key]["facet"] = "atomic"
                continue
            m = _EMPTY_RE.match(msg)
            if m is not None:
                element = m.group("element")
                attr = m.group("attr")
                facet = m.group("facet")
                key = f"{element}" + (f"@{attr}" if attr else "")
                grouped[key]["cases"].add(xml_path.name)
                grouped[key]["attr"] = attr
                grouped[key]["facet"] = facet
                grouped[key]["values"].add("<EMPTY>")
    serial = {}
    for k, v in sorted(grouped.items()):
        serial[k] = {
            "cases": sorted(v["cases"]),
            "attr": v["attr"],
            "facet": v["facet"],
            "seen_values": sorted(v["values"]),
            "allowed_head": sorted(v["allowed"])[:40],
            "allowed_count": len(v["allowed"]),
        }
    _OUT.write_text(json.dumps(serial, indent=2), encoding="utf-8")
    print(f"Classified {len(serial)} unique element+attr violations.")
    print(f"Written to {_OUT}")
    return 0


if __name__ == "__main__":
    main()
