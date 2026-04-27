"""Windows-only Adaptix agent hook governance runtime.

The runtime is deterministic: it reads stdin, parses JSON when present, emits
compact JSON only on stdout, never writes stderr intentionally, contains all
runtime failures, and exits 0 for every hook path so the hook contract is
preserved even when malformed input is supplied.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

HOOK_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PreCompact",
    "TaskComplete",
}

WINDOWS_ENVIRONMENT_POLICY = """
ADAPTIX WINDOWS EXECUTION ENVIRONMENT LOCK:

This workspace is Windows-only for hook governance.
Use Windows paths, PowerShell-compatible behavior, and the configured Python runtime command only.
Do not introduce non-Windows commands, macOS commands, Bash assumptions, POSIX-only paths, or non-Windows absolute paths.
Do not use shell behavior that depends on non-Windows shells, POSIX utilities, heredocs, or POSIX path expansion.
Every hook command must remain: python .github\\scripts\\agent_governance_runtime.py
Every configured hook timeout must remain 15.
""".strip()

POLYREPO_SCOPE_POLICY = """
ADAPTIX POLYREPO SCOPE:

Adaptix is a public-safety platform polyrepo. Scope must be determined by the assigned user request and affected repositories.
Affected repositories may include Core, Web, Contracts, Infra, Billing, ePCR, Fire, Field, Workforce, CAD, Communications, Telephony, Transport, Air, Air Pilot, Labor, Crew, Graph, Inventory, Medications, and Narcotics.
Every affected repository must be inspected, modified where needed, wired to the others through real APIs/contracts/events, and validated before completion.
Shared foundations belong in Adaptix Core and shared contracts belong in Adaptix Contracts. Do not duplicate identity, auth, RBAC, tenant, entitlement, audit, or shared contract foundations inside domain services.
""".strip()

FULLSTACK_LOCK_POLICY = """
ADAPTIX GRAVITY-LEVEL FULLSTACK EXECUTION CONTRACT:

Every assigned task must be executed as a full vertical slice:

UI -> API client -> route -> service -> persistence -> response -> UI state

Frontend and backend must both be completed when the task has a user-facing or operational workflow.
Backend-only completion is invalid.
Frontend-only completion is invalid.
Partial wiring is invalid.
Mock-only production paths are invalid.
Placeholder production paths are invalid.
Fake success paths are invalid.
Disconnected UI is invalid.
Unknown service status is invalid.
Internal blockers are not blockers. Failed tests, builds, lint, type checks, imports, migrations, routes, services, contracts, UI wiring, API wiring, and validation are required repository work to fix.
Continue automatically after failures, fix repository-resolvable issues, rerun validation, and do not complete until production readiness is achieved.
Only proven external blockers may remain.
""".strip()

PRODUCTION_READY_POLICY = """
PRODUCTION-READY COMPLETION STANDARD:

Production-ready means the relevant Adaptix user can use the completed system today without developer intervention, mock data, fake flows, placeholder logic, disabled production controls, disconnected screens, missing endpoints, missing persistence, missing authentication, missing authorization, missing tenant isolation, broken navigation, unhandled errors, incomplete validation, missing audit behavior, manual database edits, manual code edits, or manual environment repair.

Do not mark complete if any internal issue remains:

- failing tests
- failing builds
- failing lint
- failing type checks
- broken imports
- broken migrations
- missing routes
- missing services
- missing persistence
- missing schemas
- missing API clients
- missing shared types
- missing frontend screens
- missing backend routes
- missing frontend/backend contract alignment
- missing authentication enforcement
- missing authorization enforcement
- missing tenant isolation
- missing validation
- missing structured error handling
- missing loading states
- missing empty states
- missing success states
- missing failure states
- missing audit behavior
- stale generated clients
- mock-only production paths
- placeholder production paths
- fake success responses
- disabled production controls
- disconnected UI
- unresolved repository-resolvable blocker

If any item above exists, continue automatically, fix it, rerun validation, and do not mark complete.
""".strip()

VALIDATION_POLICY = """
VALIDATION AND RERUN REQUIREMENT:

Validation is mandatory. Run applicable tests, builds, lint, type checks, import checks, migration checks, route/API checks, UI wiring checks, and contract checks for every affected repository.
If validation fails, diagnose root cause, fix repository-resolvable failures, and rerun validation until clean or until the only remaining blocker is proven external.
Do not treat a skipped validation as success. State skipped validations truthfully and continue if the skip is repository-resolvable.
""".strip()

EXTERNAL_BLOCKER_POLICY = """
ONLY PROVEN EXTERNAL BLOCKERS ALLOWED:

Only these may remain as blockers, and only if proven outside repository control:

- unavailable third-party credentials
- unavailable vendor account access
- unavailable production secrets
- missing human legal approval
- unavailable external service outside repository control

Even when an external blocker exists, all repository-resolvable frontend, backend, Android, shared-contract, database, migration, API, UI, test, build, lint, type-check, validation, and documentation work must still be completed.
""".strip()

FINAL_REPORT_POLICY = """
FINAL REPORT REQUIREMENT:

The completion response must include:

- repositories inspected
- repositories modified
- files created
- files modified
- hook/config/runtime paths when hook work is in scope
- backend completed
- frontend completed
- Android completed, if applicable
- fullstack wiring completed
- shared contracts completed
- database and migration work completed
- integrations completed
- tests run
- builds run
- lint and type checks run
- validation commands run
- failures found
- failures fixed
- proven external blockers only
- final production-ready status

If any requirement is not satisfied, continue automatically.
Do not ask whether to continue.
Do not mark complete.
Do not claim production-ready.
Continue until frontend and backend are both production-ready, fully wired, validated, and user-operational, or until only proven external blockers remain.
""".strip()

SESSION_START_POLICY = """
SESSIONSTART HOOK DIRECTIVE:

Inject the full Adaptix gravity-level fullstack execution contract at session start. Every session begins under Windows-only hook governance and full vertical-slice production-readiness expectations.
""".strip()

USER_PROMPT_POLICY = """
USERPROMPTSUBMIT HOOK DIRECTIVE:

Treat every prompt as fullstack production work unless the user explicitly asks for advice-only work or the request is external and impossible to perform in the repository. If a prompt assigns implementation, execute it as a complete vertical slice and validate it before completion.
""".strip()

PRE_TOOL_POLICY = """
PRETOOLUSE HOOK DIRECTIVE:

Every tool action must contribute to frontend completion, backend completion, wiring, validation, production readiness, truthful blocker handling, or precise context gathering required to complete those outcomes. Do not use tools for destructive, unrelated, POSIX-only, fake-success, or placeholder-producing actions.
""".strip()

POST_TOOL_POLICY = """
POSTTOOLUSE HOOK DIRECTIVE:

After every tool result, inspect outcomes conceptually. If failures, gaps, mocks, placeholders, broken wiring, failed tests, failed builds, failed type checks, failed lint, incomplete frontend work, incomplete backend work, contract drift, invalid JSON, or repository-resolvable blockers remain, continue automatically and fix them.
""".strip()

PRE_COMPACT_POLICY = """
PRECOMPACT HOOK DIRECTIVE:

Before compaction, preserve the full execution contract, Windows-only environment requirement, unresolved work, affected repositories, modified files, failures, gaps, frontend state, backend state, shared contract state, contract mismatches, validation gaps, and remaining repository-resolvable work. The next agent turn must continue from the next incomplete production-readiness step, not restart or mark complete prematurely.
""".strip()

TASK_COMPLETE_POLICY = """
TASKCOMPLETE HOOK DIRECTIVE:

Block completion unless frontend and backend are both complete, wired, validated, and user-operational for the assigned scope. Completion is invalid if any internal blocker remains. Task completion may proceed only when repository-resolvable work is complete and any remaining blockers are proven external.
""".strip()

FULL_CONTRACT = "\n\n".join(
    [
        POLYREPO_SCOPE_POLICY,
        WINDOWS_ENVIRONMENT_POLICY,
        FULLSTACK_LOCK_POLICY,
        PRODUCTION_READY_POLICY,
        VALIDATION_POLICY,
        EXTERNAL_BLOCKER_POLICY,
        FINAL_REPORT_POLICY,
    ]
)

EVENT_DIRECTIVES = {
    "SessionStart": SESSION_START_POLICY,
    "UserPromptSubmit": USER_PROMPT_POLICY,
    "PreToolUse": PRE_TOOL_POLICY,
    "PostToolUse": POST_TOOL_POLICY,
    "PreCompact": PRE_COMPACT_POLICY,
    "TaskComplete": TASK_COMPLETE_POLICY,
}

INTERNAL_FAILURE_RE = re.compile(
    r"\b("
    r"failed|failing|failure|error|exception|traceback|not\s+implemented|todo|placeholder|mock-only|mock\s+data|"
    r"fake\s+success|disconnected|broken|missing|not\s+run|skipped|type-check\s+failed|lint\s+failed|"
    r"build\s+failed|tests?\s+failed|unresolved|internal\s+blocker|manual\s+(database|code|environment)"
    r")\b",
    flags=re.IGNORECASE,
)

EXTERNAL_BLOCKER_RE = re.compile(
    r"\b("
    r"third[- ]party credentials|vendor account access|production secrets|human legal approval|"
    r"external service outside repository control|unavailable credentials|missing credentials"
    r")\b",
    flags=re.IGNORECASE,
)

COMPLETION_PROOF_TERMS = [
    "repositories inspected",
    "repositories modified",
    "backend completed",
    "frontend completed",
    "fullstack wiring completed",
    "tests run",
    "builds run",
    "lint and type checks run",
    "failures found",
    "failures fixed",
    "final production-ready status",
]


def recursive_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for nested in value.values():
            strings.extend(recursive_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            strings.extend(recursive_strings(nested))
    return strings


def collect_relevant_text(payload: dict[str, Any]) -> str:
    return "\n".join(recursive_strings(payload))


def extract_event_name(payload: dict[str, Any]) -> str:
    for key in ("hookEventName", "eventName"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    nested = payload.get("hookSpecificInput")
    if isinstance(nested, dict):
        for key in ("hookEventName", "eventName"):
            value = nested.get(key)
            if isinstance(value, str):
                return value
    return "Unknown"


def read_stdin_payload() -> tuple[dict[str, Any], str]:
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return {}, ""
    try:
        parsed = json.loads(raw_input)
    except json.JSONDecodeError as exc:
        return {}, f"[AdaptixHookGovernance] Invalid JSON input: {exc.msg} at line {exc.lineno}, column {exc.colno}"
    if not isinstance(parsed, dict):
        return {}, "[AdaptixHookGovernance] Invalid JSON input: top-level value must be an object"
    return parsed, ""


def build_context(event_name: str) -> str:
    directive = EVENT_DIRECTIVES.get(
        event_name,
        "UNKNOWN HOOK DIRECTIVE:\nApply the full Adaptix gravity-level execution contract and continue repository-resolvable work until production readiness is proven.",
    )
    return f"{directive}\n\n{FULL_CONTRACT}"


def task_complete_block_reason(payload: dict[str, Any], event_name: str) -> str:
    if event_name != "TaskComplete":
        return ""

    text_blob = collect_relevant_text(payload)
    lowered = text_blob.lower()
    has_internal_failure = bool(INTERNAL_FAILURE_RE.search(text_blob))
    has_external_blocker = bool(EXTERNAL_BLOCKER_RE.search(text_blob))
    has_completion_proof = all(term in lowered for term in COMPLETION_PROOF_TERMS)

    if has_internal_failure and not has_external_blocker:
        return "[TaskComplete] Blocked: repository-resolvable failures, gaps, mocks, placeholders, broken wiring, skipped validation, or internal blockers remain. Continue, fix, and rerun validation."
    if not has_completion_proof:
        return "[TaskComplete] Blocked: completion report does not prove inspected/modified repositories, backend/frontend/fullstack completion, validations run, failures fixed, and final production-ready status. Continue until the full report is satisfied."
    return ""


def response_payload(payload: dict[str, Any], parse_error: str) -> dict[str, Any]:
    event_name = extract_event_name(payload)
    if event_name not in HOOK_EVENTS:
        event_name = "Unknown"

    error_message = parse_error
    cancel = False
    block_reason = task_complete_block_reason(payload, event_name)
    if block_reason:
        cancel = True
        error_message = block_reason

    return {
        "cancel": cancel,
        "contextModification": build_context(event_name),
        "errorMessage": error_message,
    }


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def main() -> int:
    try:
        payload, parse_error = read_stdin_payload()
        emit(response_payload(payload, parse_error))
    except Exception as exc:
        emit(
            {
                "cancel": False,
                "contextModification": build_context("Unknown"),
                "errorMessage": f"[AdaptixHookGovernance] Runtime error safely contained: {type(exc).__name__}: {exc}",
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
