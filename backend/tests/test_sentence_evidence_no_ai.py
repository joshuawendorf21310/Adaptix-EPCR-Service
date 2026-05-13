"""Regression guard: ``sentence_evidence_service.py`` must never depend
on an LLM client.

The AI-evidence-link pillar is a *deterministic* layer that wraps the
existing :mod:`ai_narrative_service` output. To keep the audit story
clean (no opaque model calls, no prompt logging risk, no surprise
network traffic) this module is forbidden from importing any LLM
client at the module level. We enforce that here by reading the source
file directly rather than trusting import-time side effects.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from epcr_app.services import sentence_evidence_service as _svc_mod


FORBIDDEN_TOP_LEVEL_MODULES = {
    "anthropic",
    "openai",
    "boto3",
    "botocore",
    "epcr_app._ai_bedrock",
    "epcr_app.ai_narrative_service",
    "epcr_app.ai_clinical_engine",
}

# Any of these names appearing as a top-level identifier signals a
# direct LLM client import even if the module path is renamed.
FORBIDDEN_NAME_FRAGMENTS = (
    "anthropic",
    "openai",
    "bedrock",
    "claude",
    "llm",
)


def _service_source() -> str:
    path = Path(_svc_mod.__file__)
    return path.read_text(encoding="utf-8")


def _module_level_imports(source: str) -> list[tuple[str, str]]:
    """Return list of (module_name, alias_or_name) tuples for module-level
    ``import`` / ``from ... import`` statements only.
    """
    tree = ast.parse(source)
    imports: list[tuple[str, str]] = []
    for node in tree.body:  # top-level only — nested imports are fine.
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, alias.asname or alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append((mod, alias.asname or alias.name))
    return imports


def test_no_module_level_llm_imports() -> None:
    source = _service_source()
    imports = _module_level_imports(source)
    assert imports, "expected at least one module-level import"
    offenders: list[str] = []
    for mod, name in imports:
        haystack = f"{mod}.{name}".lower()
        if mod in FORBIDDEN_TOP_LEVEL_MODULES:
            offenders.append(f"forbidden module import: {mod}")
            continue
        for fragment in FORBIDDEN_NAME_FRAGMENTS:
            if fragment in haystack:
                offenders.append(
                    f"forbidden token {fragment!r} in import {mod}.{name}"
                )
                break
    assert offenders == [], (
        "sentence_evidence_service.py must not import LLM clients at "
        f"module scope; offenders: {offenders}"
    )


def test_no_textual_llm_call_signatures() -> None:
    """Cheap belt-and-braces scan for obvious LLM call sites.

    Looks for substrings that would only appear if the service were
    actually invoking a model. Comments and docstrings are excluded
    by stripping them before scanning.
    """
    source = _service_source()
    tree = ast.parse(source)
    # Remove docstrings so the words "LLM" / "Claude" in module docs do
    # not trigger this guard.
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body[0].value.value = ""
    scrubbed = ast.unparse(tree).lower()

    forbidden_call_fragments = (
        "anthropic.client",
        "openai.client",
        "openai.chatcompletion",
        "messages.create",
        "chat.completions.create",
        "bedrock-runtime",
        "invoke_model",
    )
    hits = [f for f in forbidden_call_fragments if f in scrubbed]
    assert hits == [], (
        f"sentence_evidence_service.py contains LLM call signatures: {hits}"
    )
