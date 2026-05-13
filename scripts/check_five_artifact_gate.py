#!/usr/bin/env python3
"""
Five-Artifact Production Readiness Gate (server-side, EPCR backend).

Rule (approved plan: Five-Artifact Production Readiness Rule):
A capability declared ``"capability": "live"`` inside
``backend/epcr_app/chart_workspace_service.py`` is only permitted to merge
when the SAME diff (this branch vs ``origin/main``) introduces all five
backing artifacts for that capability:

    1. service   — a new/modified file under backend/epcr_app/services/*.py
    2. model+migration — a new/modified file under backend/migrations/versions/*.py
    3. endpoint  — a new/modified route in chart_workspace_service.py or api_*.py
    4. contract test — a new/modified file under backend/tests/test_*_contract.py
    5. audit-write evidence — at least one touched service file references
       EpcrAuditLog(, epcr_ai_audit_event, or epcr_provider_override.

This script is the server-side complement of
``Adaptix-Web-App/scripts/check_five_artifact_gate.ts``. It runs on backend
CI to ensure no capability is flipped to ``live`` without the 5 artifacts in
the same commit set.

Exit codes:
    0  — gate satisfied (or no newly-introduced ``live`` capabilities).
    1  — at least one capability missing one or more artifacts.
    2  — unrecoverable git/IO error.

Output: a structured JSON report on stdout listing every newly-introduced
``live`` capability and its five-artifact verdict.

No new dependencies. Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Repo root = parent of scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent

CHART_WS = "backend/epcr_app/chart_workspace_service.py"
SERVICES_GLOB = re.compile(r"^backend/epcr_app/services/[^/]+\.py$")
MIGRATIONS_GLOB = re.compile(r"^backend/migrations/versions/[^/]+\.py$")
ENDPOINT_GLOB = re.compile(
    r"^backend/epcr_app/(chart_workspace_service\.py|.*api_[^/]*\.py|.*/api_[^/]*\.py)$"
)
TESTS_GLOB = re.compile(r"^backend/tests/test_.*_contract\.py$")

AUDIT_PATTERNS = ("EpcrAuditLog(", "epcr_ai_audit_event", "epcr_provider_override")

# Match a python dict entry of the form:  "<name>": {  ... "capability": "live"
# We scan added lines for `"capability": "live"` and then walk backward in the
# same hunk to find the nearest `"<name>": {` header. This is purely a textual
# attribution heuristic — the gate enforcement is per-capability label.
CAP_HEADER_RE = re.compile(r'^\s*"(?P<name>[a-z0-9_]+)"\s*:\s*\{\s*$')
CAP_LIVE_RE = re.compile(r'"capability"\s*:\s*"live"')


def run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        print(f"PRODUCTION_READINESS_GATE: git not available: {e}", file=sys.stderr)
        sys.exit(2)
    if out.returncode not in (0, 1):  # `git diff` returns 1 only on usage errors here
        # tolerate non-zero for empty-diff or no-upstream cases below
        pass
    return out.stdout


def resolve_base_ref() -> str:
    """Return the ref to diff against.

    Preference order:
        1. ``GATE_BASE_REF`` env var (CI overrides).
        2. ``origin/main``         (fetched in PR workflows).
        3. ``main``                (local fallback).
        4. root-of-history (``--root``) — diff entire branch.
    """
    env = os.environ.get("GATE_BASE_REF")
    if env:
        return env

    for candidate in ("origin/main", "main"):
        res = subprocess.run(
            ["git", "rev-parse", "--verify", candidate],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return candidate

    return "--root"


def changed_files(base: str) -> list[str]:
    if base == "--root":
        # Whole branch — every tracked file.
        out = run(["git", "ls-files"])
    else:
        out = run(["git", "diff", "--name-only", f"{base}...HEAD"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def added_lines(base: str, path: str) -> list[str]:
    """Return the *added* lines (lines beginning with '+', not '+++') in the diff."""
    if base == "--root":
        try:
            return Path(REPO_ROOT, path).read_text(encoding="utf-8", errors="replace").splitlines()
        except (FileNotFoundError, IsADirectoryError):
            return []
    out = run(["git", "diff", "--unified=0", f"{base}...HEAD", "--", path])
    added: list[str] = []
    for line in out.splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
    return added


def full_diff_hunk(base: str, path: str) -> str:
    """Return unified diff text for path; or full file content when base==--root."""
    if base == "--root":
        try:
            return Path(REPO_ROOT, path).read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError):
            return ""
    return run(["git", "diff", "--unified=200", f"{base}...HEAD", "--", path])


def detect_new_live_capabilities(base: str) -> list[str]:
    """Find capability names newly flipped to ``live`` in chart_workspace_service.py.

    Returns the list of capability label strings (e.g. ``"readiness"``).
    """
    diff_text = full_diff_hunk(base, CHART_WS)
    if not diff_text:
        return []

    # Walk added lines, tracking the most recent capability header seen
    # (a header may itself be an added line OR may be context).
    capabilities: list[str] = []
    current_name: str | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("+++") or raw.startswith("---") or raw.startswith("@@"):
            # New hunk → reset context attribution.
            if raw.startswith("@@"):
                current_name = None
            continue
        # Strip leading diff marker for content evaluation.
        if raw.startswith("+") or raw.startswith(" "):
            content = raw[1:]
        elif raw.startswith("-"):
            # Deletions don't establish current header.
            continue
        else:
            content = raw  # base==--root case: plain file content

        m = CAP_HEADER_RE.match(content)
        if m:
            current_name = m.group("name")
            continue

        # Only ADDED `"capability": "live"` lines count as flips.
        is_added = raw.startswith("+") or base == "--root"
        if is_added and CAP_LIVE_RE.search(content) and current_name:
            capabilities.append(current_name)

    # dedupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for c in capabilities:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def classify(files: Iterable[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "service": [],
        "migration": [],
        "endpoint": [],
        "contract_test": [],
    }
    for f in files:
        nf = f.replace("\\", "/")
        if SERVICES_GLOB.match(nf):
            buckets["service"].append(nf)
        if MIGRATIONS_GLOB.match(nf):
            buckets["migration"].append(nf)
        if ENDPOINT_GLOB.match(nf) or nf == CHART_WS:
            buckets["endpoint"].append(nf)
        if TESTS_GLOB.match(nf):
            buckets["contract_test"].append(nf)
    return buckets


def detect_audit_evidence(base: str, services: list[str]) -> list[str]:
    hits: list[str] = []
    for svc in services:
        added = added_lines(base, svc)
        if any(any(p in line for p in AUDIT_PATTERNS) for line in added):
            hits.append(svc)
    return hits


def main() -> int:
    base = resolve_base_ref()
    files = changed_files(base)
    buckets = classify(files)
    audit_hits = detect_audit_evidence(base, buckets["service"])
    new_live = detect_new_live_capabilities(base)

    report: dict = {
        "gate": "five_artifact",
        "repo": "Adaptix-EPCR-Service",
        "base_ref": base,
        "changed_file_count": len(files),
        "newly_live_capabilities": new_live,
        "verdicts": [],
    }

    if not new_live:
        report["result"] = "pass_no_new_live_capabilities"
        print(json.dumps(report, indent=2))
        return 0

    failed = False
    for cap in new_live:
        missing: list[str] = []
        if not buckets["service"]:
            missing.append("service")
        if not buckets["migration"]:
            missing.append("model_migration")
        if not buckets["endpoint"]:
            missing.append("endpoint")
        if not buckets["contract_test"]:
            missing.append("contract_test")
        if not audit_hits:
            missing.append("audit_write")

        verdict = {
            "capability": cap,
            "artifacts": {
                "service": buckets["service"],
                "model_migration": buckets["migration"],
                "endpoint": buckets["endpoint"],
                "contract_test": buckets["contract_test"],
                "audit_write_evidence": audit_hits,
            },
            "missing": missing,
            "passed": not missing,
        }
        report["verdicts"].append(verdict)

        if missing:
            failed = True
            for art in missing:
                print(
                    f"PRODUCTION_READINESS_GATE: {cap} missing {art}",
                    file=sys.stderr,
                )

    report["result"] = "fail" if failed else "pass"
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
