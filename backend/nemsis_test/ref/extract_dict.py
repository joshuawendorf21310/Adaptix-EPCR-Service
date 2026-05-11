"""Extract NEMSIS Data Dictionary PDF to text for offline reading."""
from pathlib import Path
import sys

import pypdf

src = Path("nemsis_test/ref/NEMSISDataDictionary_3.5.1.pdf")
out = Path("nemsis_test/ref/NEMSISDataDictionary_3.5.1.txt")

reader = pypdf.PdfReader(str(src))
n = len(reader.pages)
print(f"pages: {n}", file=sys.stderr)

with out.open("w", encoding="utf-8") as fh:
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            text = f"[extract_error page {i}: {exc}]"
        fh.write(f"\n===== PAGE {i + 1} / {n} =====\n")
        fh.write(text)
        fh.write("\n")

print(f"wrote {out} ({out.stat().st_size:,} bytes)")
