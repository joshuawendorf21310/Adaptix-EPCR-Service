"""Extract the $diffs JS variable from the NEMSIS CTA comparison HTML."""
import sys
import io
import re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

html = Path(
    r"c:\Users\fusio\Downloads\Comparison Report _ NEMSIS 3 Compliance Testing3-4.html"
).read_text(encoding="utf-8", errors="replace")

m = re.search(r"var\s+\$diffs\s*=\s*(\[[\s\S]+?\]);", html)
if m is None:
    print("NO MATCH")
    sys.exit(1)

raw = m.group(1)
out_path = Path("artifact/_diffs_js.txt")
out_path.write_text(raw, encoding="utf-8")
print(f"Extracted {len(raw)} chars of diffs JS to {out_path}")
print(raw[:3500])
