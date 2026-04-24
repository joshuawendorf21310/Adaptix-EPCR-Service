"""Inspect HTML labels used for each coded element_id in the CTA 2025 test cases.

For each of the 6 HTML files, extract the exact display text used for the
specific protected coded element IDs so the element-specific mapping table
uses verbatim labels.
"""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup


ASSETS = Path(
    "nemsis_test/assets/cta/cta_uploaded_package/v3.5.1 C&S for vendors"
).resolve()

HTML_FILES = [
    "2025-DEM-1_v351.html",
    "2025-EMS-1-Allergy_v351.html",
    "2025-EMS-2-HeatStroke_v351.html",
    "2025-EMS-3-PediatricAsthma_v351.html",
    "2025-EMS-4-ArmTrauma_v351.html",
    "2025-EMS-5-MentalHealthCrisis_v351.html",
]

TARGET_IDS = {
    "dAgency.09", "dAgency.10", "dAgency.11", "dAgency.12",
    "dAgency.13", "dAgency.14",
    "dContact.01", "dContact.06", "dContact.14",
    "dConfiguration.01", "dConfiguration.10",
    "dVehicle.04",
    "dPersonnel.15", "dPersonnel.16",
    "dFacility.01", "dFacility.04", "dFacility.08", "dFacility.09",
    "dFacility.11", "dFacility.15",
    "eAgency.02", "eResponse.23",
    "eScene.09", "eScene.18", "eScene.19", "eScene.21",
    "ePatient.13", "ePatient.14", "ePatient.15",
    "eDisposition.04", "eDisposition.12", "eDisposition.19",
    "eSituation.04", "eSituation.09", "eSituation.11", "eSituation.12",
    "eSituation.13",
    "eVitals.12", "eVitals.14",
}


def element_id_from_row(tr) -> str | None:
    # Columns: element/group cell, value cell, description
    cells = tr.find_all("td", recursive=False)
    if not cells:
        return None
    first = cells[0]
    classes = first.get("class") or []
    if "element" not in classes:
        return None
    text = first.get_text(strip=True)
    return text


def extract_for_file(html_path: Path) -> dict[str, list[str]]:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    result: dict[str, list[str]] = {}
    for tr in soup.find_all("tr"):
        eid = element_id_from_row(tr)
        if not eid or eid not in TARGET_IDS:
            continue
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        val = cells[1].get_text(" ", strip=True)
        result.setdefault(eid, []).append(val)
    # Also handle rowspan-continuation rows (single-td rows that follow a rowspanned element row).
    return result


def main() -> None:
    out: dict[str, dict[str, list[str]]] = {}
    for fname in HTML_FILES:
        path = ASSETS / fname
        if not path.is_file():
            print(f"MISSING: {path}")
            continue
        out[fname] = extract_for_file(path)
    Path("artifact/generated/2025/.html_labels.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    # Print a grouped summary: for each element_id, show unique labels across all files.
    grouped: dict[str, set[str]] = {}
    for case, mapping in out.items():
        for eid, vals in mapping.items():
            grouped.setdefault(eid, set()).update(vals)
    for eid in sorted(grouped):
        print(f"--- {eid} ---")
        for v in sorted(grouped[eid]):
            print(f"  {v!r}")


if __name__ == "__main__":
    main()
