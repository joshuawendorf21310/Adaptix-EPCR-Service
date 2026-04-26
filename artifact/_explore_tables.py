"""Explore inspectorLine tables for reference XML content."""
import sys
import io
from pathlib import Path
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

html = Path(
    r"c:\Users\fusio\Downloads\Comparison Report _ NEMSIS 3 Compliance Testing3-4.html"
).read_text(encoding="utf-8", errors="replace")
soup = BeautifulSoup(html, "html.parser")

tables = soup.find_all("table")
for i, t in enumerate(tables):
    cls = t.get("class")
    print(f"--- TABLE [{i}] class={cls} ---")
    # just show first 2000 chars of raw text
    print(t.get_text("|", strip=False)[:2000])
    print()
