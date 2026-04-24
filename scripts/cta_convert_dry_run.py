"""Convert all 6 CTA test cases locally (no SOAP submission).

Useful for debugging the HTML to XML pipeline before spending live CTA attempts.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from cta_submit_2025_full import (  # noqa: E402
    TEST_CASES,
    _build_conversion_input,
)
from epcr_app.nemsis.cta_html_to_xml import convert_html_to_nemsis_xml  # noqa: E402


def main() -> None:
    html_dir = (
        _REPO_ROOT
        / "nemsis_test"
        / "assets"
        / "cta"
        / "cta_uploaded_package"
        / "v3.5.1 C&S for vendors"
    )
    state_xml_path = html_dir / "2025-STATE-1_v351.xml"
    generated_dir = _REPO_ROOT / "artifact" / "generated" / "2025"
    generated_dir.mkdir(parents=True, exist_ok=True)

    results: list[tuple[str, str, str]] = []
    for tc in TEST_CASES:
        tc_id = tc["id"]
        html_path = html_dir / tc["html_filename"]
        out_path = generated_dir / f"{tc_id}.xml"
        print(f"\n=== {tc_id} ===")
        try:
            ci = _build_conversion_input(html_path, tc_id)
            print(
                f"inputs: {len(ci.uuids)} UUIDs, "
                f"{len(ci.timestamps)} timestamps, "
                f"{len(ci.placeholder_values)} placeholders"
            )
            root = convert_html_to_nemsis_xml(
                html_path=html_path,
                state_xml_path=state_xml_path,
                output_path=out_path,
                conversion_input=ci,
            )
            local = root.tag.split("}", 1)[-1]
            print(f"OK root={local} wrote {out_path}")
            results.append((tc_id, "OK", local))
        except Exception as exc:
            print(f"FAIL: {type(exc).__name__}: {exc}")
            results.append((tc_id, "FAIL", f"{type(exc).__name__}: {exc}"))

    print("\n" + "=" * 80)
    for tc_id, status, detail in results:
        print(f"{status:<5} {tc_id:<42} {detail}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
