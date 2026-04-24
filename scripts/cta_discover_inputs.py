"""Enumerate every ConversionInput key required by the 6 official CTA test cases.

Walks each HTML with :class:`HtmlParser` and produces a sorted, de-duplicated
report of every UUID occurrence key, timestamp occurrence key, and
``[Your <kind>]`` placeholder descriptor discovered across the corpus.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from epcr_app.nemsis.cta_html_to_xml import HtmlParser


HTML_FILES = [
    "2025-DEM-1_v351.html",
    "2025-EMS-1-Allergy_v351.html",
    "2025-EMS-2-HeatStroke_v351.html",
    "2025-EMS-3-PediatricAsthma_v351.html",
    "2025-EMS-4-ArmTrauma_v351.html",
    "2025-EMS-5-MentalHealthCrisis_v351.html",
]


def main() -> None:
    html_dir = (
        _REPO_ROOT
        / "nemsis_test"
        / "assets"
        / "cta"
        / "cta_uploaded_package"
        / "v3.5.1 C&S for vendors"
    )
    parser = HtmlParser()

    per_case: dict[str, dict[str, list[str]]] = {}
    all_uuid_keys: set[str] = set()
    all_timestamp_keys: set[str] = set()
    placeholder_descriptors: dict[str, set[str]] = defaultdict(set)

    for html_name in HTML_FILES:
        html_path = html_dir / html_name
        root_tag, cells = parser.parse(html_path)
        uuid_keys: list[str] = []
        ts_keys: list[str] = []
        placeholders: list[str] = []
        for cell in cells:
            if cell.needs_uuid_attr:
                uuid_keys.append(cell.occurrence_key)
                all_uuid_keys.add(cell.occurrence_key)
            if cell.needs_timestamp_attr:
                ts_keys.append(cell.occurrence_key)
                all_timestamp_keys.add(cell.occurrence_key)
            if cell.your_placeholder is not None:
                placeholders.append(cell.your_placeholder)
                placeholder_descriptors[cell.your_placeholder].add(html_name)
        per_case[html_name] = {
            "root_tag": root_tag,
            "cell_count": len(cells),
            "uuid_keys": sorted(set(uuid_keys)),
            "timestamp_keys": sorted(set(ts_keys)),
            "placeholders": sorted(set(placeholders)),
        }
        print(
            f"{html_name}: root={root_tag} cells={len(cells)} "
            f"uuids={len(set(uuid_keys))} timestamps={len(set(ts_keys))} "
            f"placeholders={len(set(placeholders))}"
        )

    summary = {
        "global_uuid_keys": sorted(all_uuid_keys),
        "global_timestamp_keys": sorted(all_timestamp_keys),
        "global_placeholder_descriptors": {
            k: sorted(v) for k, v in sorted(placeholder_descriptors.items())
        },
        "per_case": per_case,
    }

    out_dir = _REPO_ROOT / "artifact" / "cta" / "2025"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "discovery.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nDiscovery report: {out_path}")

    print("\nGLOBAL UUID KEYS:")
    for k in summary["global_uuid_keys"]:
        print(f"  {k}")
    print("\nGLOBAL TIMESTAMP KEYS:")
    for k in summary["global_timestamp_keys"]:
        print(f"  {k}")
    print("\nGLOBAL PLACEHOLDER DESCRIPTORS:")
    for k, sources in summary["global_placeholder_descriptors"].items():
        print(f"  {k!r} -> {', '.join(sources)}")


if __name__ == "__main__":
    main()
