from __future__ import annotations

"""Compare a generated NEMSIS XML artifact against the official Allergy baseline."""

import argparse
import json
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET


XMLNS_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _group_sequence(root: ET.Element) -> list[str]:
    patient_care_report = next((child for child in root.iter() if _local_name(child.tag) == "PatientCareReport"), None)
    if patient_care_report is None:
        return []
    return [_local_name(child.tag) for child in list(patient_care_report)]


def _repeated_group_counts(root: ET.Element) -> dict[str, int]:
    counts = Counter(_local_name(element.tag) for element in root.iter())
    return {tag: count for tag, count in sorted(counts.items()) if count > 1}


def _nv_pn_markers(root: ET.Element) -> list[dict[str, str]]:
    markers: list[dict[str, str]] = []
    for element in root.iter():
        nv = element.attrib.get("NV")
        pn = element.attrib.get("PN")
        xsi_nil = element.attrib.get(f"{{{XMLNS_XSI}}}nil")
        if nv or pn or xsi_nil:
            markers.append(
                {
                    "tag": _local_name(element.tag),
                    "nv": nv or "",
                    "pn": pn or "",
                    "xsi_nil": xsi_nil or "",
                }
            )
    return markers


def compare_official(official_path: Path, generated_path: Path) -> dict[str, object]:
    official_root = _parse_xml(official_path)
    generated_root = _parse_xml(generated_path)

    official_sequence = _group_sequence(official_root)
    generated_sequence = _group_sequence(generated_root)
    official_repeat_counts = _repeated_group_counts(official_root)
    generated_repeat_counts = _repeated_group_counts(generated_root)
    official_markers = _nv_pn_markers(official_root)
    generated_markers = _nv_pn_markers(generated_root)
    generated_text = generated_path.read_text(encoding="utf-8")

    result = {
        "root_match": _local_name(official_root.tag) == _local_name(generated_root.tag),
        "patient_care_report_sequence_match": official_sequence == generated_sequence,
        "tac_key_match": official_root.findtext(".//{http://www.nemsis.org}eResponse.04", default="").strip()
        == generated_root.findtext(".//{http://www.nemsis.org}eResponse.04", default="").strip(),
        "repeated_group_counts_match": official_repeat_counts == generated_repeat_counts,
        "nv_pn_markers_match": official_markers == generated_markers,
        "no_placeholders": "[Your" not in generated_text,
        "official_sequence": official_sequence,
        "generated_sequence": generated_sequence,
        "official_repeated_group_counts": official_repeat_counts,
        "generated_repeated_group_counts": generated_repeat_counts,
        "official_nv_pn_markers": official_markers,
        "generated_nv_pn_markers": generated_markers,
    }
    result["is_match"] = all(
        bool(result[key])
        for key in (
            "root_match",
            "patient_care_report_sequence_match",
            "tac_key_match",
            "repeated_group_counts_match",
            "nv_pn_markers_match",
            "no_placeholders",
        )
    )
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare generated Allergy XML against the official baseline.")
    parser.add_argument("--official", required=True, help="Path to the official Allergy XML.")
    parser.add_argument("--generated", required=True, help="Path to the generated Allergy XML.")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[3] / "artifact" / "fidelity" / "official-diff.json"),
        help="Path to write the JSON comparison result.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = compare_official(Path(args.official), Path(args.generated))
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("FIDELITY PASS" if result["is_match"] else "FIDELITY FAIL")
    return 0 if result["is_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())