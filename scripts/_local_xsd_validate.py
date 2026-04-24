"""Validate every generated CTA 2025 XML against its NEMSIS v3.5.1 XSD.

Writes a single consolidated report at:
    artifact/generated/2025/LOCAL_XSD_VALIDATION_REPORT.txt

Exit code 0 when all files pass; non-zero otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

_REPO_ROOT = Path(__file__).resolve().parents[1]
_XSD_ROOT = _REPO_ROOT / "nemsis_test" / "assets" / "xsd" / "extracted" / "NEMSIS_XSDs"
_DEM_XSD = _XSD_ROOT / "DEMDataSet_v3.xsd"
_EMS_XSD = _XSD_ROOT / "EMSDataSet_v3.xsd"
_GENERATED = _REPO_ROOT / "artifact" / "generated" / "2025"
_REPORT = _GENERATED / "LOCAL_XSD_VALIDATION_REPORT.txt"


def _pick_xsd(xml_path: Path) -> Path:
    head = xml_path.read_bytes()[:2048].decode("utf-8", errors="replace")
    if "<DEMDataSet" in head or "DEMDataSet_v3.xsd" in head:
        return _DEM_XSD
    if "<EMSDataSet" in head or "EMSDataSet_v3.xsd" in head:
        return _EMS_XSD
    raise RuntimeError(f"cannot determine dataset type for {xml_path.name}")


def _validate_one(xml_path: Path) -> tuple[bool, list[str]]:
    xsd_path = _pick_xsd(xml_path)
    xmlschema = etree.XMLSchema(etree.parse(str(xsd_path)))
    try:
        doc = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as exc:
        return False, [f"XML syntax error: {exc}"]
    ok = xmlschema.validate(doc)
    errors = [
        f"line {err.line}: {err.message}" for err in xmlschema.error_log
    ]
    return ok, errors


def main() -> int:
    files = sorted(_GENERATED.glob("2025-*.xml"))
    lines: list[str] = []
    total_errors = 0
    overall_ok = True
    for xml_path in files:
        try:
            ok, errors = _validate_one(xml_path)
        except Exception as exc:
            ok = False
            errors = [f"validation error: {type(exc).__name__}: {exc}"]
        status = "PASS" if ok else "FAIL"
        lines.append(f"=== {xml_path.name}: {status} ({len(errors)} errors) ===")
        if not ok:
            overall_ok = False
            total_errors += len(errors)
            for e in errors[:200]:
                lines.append(f"  {e}")
            if len(errors) > 200:
                lines.append(f"  ... ({len(errors) - 200} more)")
        lines.append("")
    header = [
        f"NEMSIS v3.5.1 local XSD validation — {('ALL PASS' if overall_ok else 'FAIL')}",
        f"files: {len(files)}, total errors: {total_errors}",
        "",
    ]
    _REPORT.write_text("\n".join(header + lines), encoding="utf-8")
    print("\n".join(header + lines[: min(len(lines), 200)]))
    print(f"\nReport written to: {_REPORT}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
