"""Extract the TAC-passed DEMDataSet payload from a SOAP request artifact
and write it to the baked CTA template path so production submissions
canonicalize equal to the operator's verified payload."""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "artifact" / "cta" / "2025" / "2025-DEM-1_v351-request.xml"
DST = ROOT / "backend" / "nemsis" / "templates" / "cta" / "2025-DEM-1_v351.xml"

src_text = SRC.read_text(encoding="utf-8")
m = re.search(
    r"<ws:payloadOfXmlElement>(.*?)</ws:payloadOfXmlElement>",
    src_text,
    re.DOTALL,
)
if not m:
    sys.exit("payloadOfXmlElement not found in artifact")
payload = m.group(1).strip()
if not payload.startswith("<DEMDataSet"):
    sys.exit(f"unexpected payload start: {payload[:200]!r}")

xml_decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
out = xml_decl + payload + "\n"

# Sanity: parseable.
root = ET.fromstring(out)
ns = "{http://www.nemsis.org}"
assert root.tag == ns + "DEMDataSet", f"unexpected root: {root.tag}"

# Required identifier preservation.
required = {
    "dRecord.01": "NEMSIS Technical Assistance Center",
    "dRecord.02": "Compliance Testing",
    "dRecord.03": "3.5.1.250403CP1_250317",
}
for tag, val in required.items():
    assert f"<{tag}>{val}</{tag}>" in out, f"missing {tag}={val}"
assert "<dAgency.27>9923003</dAgency.27>" in out, "missing dAgency.27=9923003"

DST.write_text(out, encoding="utf-8", newline="")
print(f"wrote {DST} ({len(out)} bytes)")
print("dAgency.27=9923003: OK")
print("dRecord.01/02/03: OK")
