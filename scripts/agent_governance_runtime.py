from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GOVERNANCE_VERSION = "2026.04.21"
ROOT_MARKER = "INHERITS_ROOT_GOVERNANCE: true"
ROOT_PATH_MARKER = "ROOT_GOVERNANCE_PATH: AGENTS.md"

EDITING_TOOLS = {
    "create_file",
    "apply_patch",
    "edit_notebook_file",
    "vscode_renameSymbol",
}
TERMINAL_TOOLS = {"run_in_terminal", "send_to_terminal", "create_and_run_task", "run_task"}
PATH_KEYS = {
    "filePath",
    "filePaths",
    "path",
    "paths",
    "dirPath",
    "includePattern",
    "query",
    "workspaceFolder",
}
TEXT_KEYS = {
    "content",
    "input",
    "command",
    "newCode",
    "lineContent",
    "query",
    "insert_text",
    "old_str",
    "new_str",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernanceError(RuntimeError):
    pass


class GovernanceRuntime:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self.repo_root = self._resolve_repo_root(self.cwd)
        self.manifest_path = self.repo_root / ".github" / "governance" / "governance.manifest.json"
        self.manifest = self._load_json(self.manifest_path)
        self.audit_path = self.repo_root / self.manifest["auditLogPath"]
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_repo_root(start: Path) -> Path:
        for candidate in [start, *start.parents]:
            if (candidate / ".github" / "governance" / "governance.manifest.json").exists():
                return candidate
            if (candidate / ".git").exists():
                repo_candidate = candidate / ".github" / "governance" / "governance.manifest.json"
                if repo_candidate.exists():
                    return candidate
        raise GovernanceError(f"Unable to locate governance manifest from cwd={start}")

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise GovernanceError(f"Missing governance manifest: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _candidate_paths(self, value: Any) -> list[Path]:
        results: list[Path] = []
        self._walk_paths(value, results)
        filtered: list[Path] = []
        for item in results:
            try:
                resolved = item if item.is_absolute() else (self.cwd / item).resolve()
            except OSError:
                continue
            if str(resolved).startswith(str(self.repo_root)):
                filtered.append(resolved)
        return filtered

    def _walk_paths(self, value: Any, results: list[Path], key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                self._walk_paths(child_value, results, child_key)
            return
        if isinstance(value, list):
            for item in value:
                self._walk_paths(item, results, key)
            return
        if isinstance(value, str) and key in PATH_KEYS:
            normalized = value.strip()
            if not normalized:
                return
            if normalized.startswith("http://") or normalized.startswith("https://"):
                return
            if key == "query" and not any(sep in normalized for sep in ("/", "\\", ".")):
                return
            results.append(Path(normalized))

    def _extract_text_blobs(self, value: Any, key: str | None = None) -> list[str]:
        blobs: list[str] = []
        self._walk_text(value, blobs, key)
        return blobs

    def _walk_text(self, value: Any, results: list[str], key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                self._walk_text(child_value, results, child_key)
            return
        if isinstance(value, list):
            for item in value:
                self._walk_text(item, results, key)
            return
        if isinstance(value, str) and (key in TEXT_KEYS or key is None):
            results.append(value)

    def _active_local_agent(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        candidate_paths = self._candidate_paths(payload.get("tool_input", {}))
        local_agents = self.manifest.get("localAgents", [])
        ranked: list[tuple[int, dict[str, Any]]] = []
        for agent in local_agents:
            agent_path = (self.repo_root / agent["path"]).resolve()
            agent_dir = agent_path.parent
            if candidate_paths:
                for candidate in candidate_paths:
                    try:
                        candidate.relative_to(agent_dir)
                        ranked.append((len(agent_dir.parts), agent))
                        break
                    except ValueError:
                        continue
            elif agent.get("default", False):
                ranked.append((len(agent_dir.parts), agent))
        if not ranked:
            for agent in local_agents:
                if agent.get("default", False):
                    return agent
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def _load_rules(self, payload: dict[str, Any]) -> tuple[str, str | None, dict[str, Any] | None]:
        root_agents_path = self.repo_root / self.manifest["rootAgentsPath"]
        if not root_agents_path.exists():
            raise GovernanceError(f"Missing root AGENTS.md at {root_agents_path}")
        root_content = root_agents_path.read_text(encoding="utf-8")
        local_agent = self._active_local_agent(payload)
        local_content: str | None = None
        if local_agent is not None:
            local_path = self.repo_root / local_agent["path"]
            if not local_path.exists():
                raise GovernanceError(f"Missing local AGENTS.md at {local_path}")
            local_content = local_path.read_text(encoding="utf-8")
            self._validate_inheritance(local_content, local_agent)
        return root_content, local_content, local_agent

    def _validate_inheritance(self, local_content: str, local_agent: dict[str, Any]) -> None:
        expected_version = local_agent["governanceVersion"]
        required_markers = [
            ROOT_MARKER,
            ROOT_PATH_MARKER,
            f"GOVERNANCE_VERSION: {expected_version}",
            f"SUBSYSTEM_KEY: {local_agent['subsystemKey']}",
        ]
        missing = [marker for marker in required_markers if marker not in local_content]
        if missing:
            raise GovernanceError(
                f"Local AGENTS.md inheritance markers missing for {local_agent['path']}: {', '.join(missing)}"
            )
        contradiction_markers = self.manifest.get("contradictionMarkers", [])
        for marker in contradiction_markers:
            if marker.lower() in local_content.lower():
                raise GovernanceError(
                    f"Contradictory marker '{marker}' found in local AGENTS.md {local_agent['path']}"
                )

    def _detect_violations(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        local_agent: dict[str, Any] | None,
    ) -> list[str]:
        violations: list[str] = []
        text = "\n".join(self._extract_text_blobs(tool_input))
        repo_role = self.manifest.get("repoRole", "service")

        if tool_name in TERMINAL_TOOLS:
            command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
            for pattern in self.manifest.get("blockedTerminalPatterns", []):
                if re.search(pattern, command, flags=re.IGNORECASE):
                    violations.append(f"Blocked terminal command pattern matched: {pattern}")

        if tool_name in EDITING_TOOLS:
            if repo_role not in {"platform-core", "billing", "infra", "web"}:
                for pattern in self.manifest.get("sharedFoundationPatterns", []):
                    if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
                        violations.append(
                            "Shared platform foundation duplication detected outside allowed repos"
                        )
                        break

            if repo_role not in {"platform-core", "billing", "infra", "web"}:
                for pattern in self.manifest.get("pricingLogicPatterns", []):
                    if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
                        violations.append(
                            "Commercial pricing logic detected in a domain repo that must remain entitlement-only"
                        )
                        break

            if local_agent is not None:
                for import_root in local_agent.get("forbiddenImportRoots", []):
                    import_patterns = [
                        rf"from\s+{re.escape(import_root)}\b",
                        rf"import\s+{re.escape(import_root)}\b",
                    ]
                    if any(re.search(pattern, text) for pattern in import_patterns):
                        violations.append(
                            f"Private cross-domain import detected for forbidden root '{import_root}'"
                        )
                        break

        return violations

    def audit(self, payload: dict[str, Any], decision: str, reason: str, local_agent: dict[str, Any] | None) -> None:
        record = {
            "timestamp": utc_now(),
            "governanceVersion": self.manifest["governanceVersion"],
            "repo": self.manifest["repoName"],
            "repoRole": self.manifest["repoRole"],
            "hookEventName": payload.get("hookEventName"),
            "sessionId": payload.get("sessionId"),
            "toolName": payload.get("tool_name"),
            "cwd": payload.get("cwd"),
            "decision": decision,
            "reason": reason,
            "activeLocalAgent": None if local_agent is None else local_agent["path"],
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def process(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        event = payload.get("hookEventName")
        root_content, local_content, local_agent = self._load_rules(payload)
        summary = [
            f"Loaded root AGENTS.md for {self.manifest['repoName']}",
            f"Governance version {self.manifest['governanceVersion']}",
        ]
        if local_agent is not None:
            summary.append(f"Loaded local AGENTS.md: {local_agent['path']}")
            summary.append(f"Subsystem: {local_agent['displayName']}")
        else:
            summary.append("No local subsystem AGENTS.md resolved for this event")
        summary_text = " | ".join(summary)

        if event == "SessionStart":
            self.audit(payload, "allow", "session started", local_agent)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": summary_text,
                }
            }, 0

        if event == "UserPromptSubmit":
            self.audit(payload, "allow", "prompt submitted", local_agent)
            return {"systemMessage": summary_text}, 0

        if event == "PreToolUse":
            tool_name = payload.get("tool_name", "")
            tool_input = payload.get("tool_input", {})
            violations = self._detect_violations(tool_name, tool_input, local_agent)
            if violations:
                reason = "; ".join(violations)
                self.audit(payload, "deny", reason, local_agent)
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                        "additionalContext": summary_text,
                    }
                }, 0
            self.audit(payload, "allow", "tool allowed", local_agent)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": summary_text,
                    "additionalContext": summary_text,
                }
            }, 0

        if event == "PostToolUse":
            self.audit(payload, "allow", "tool completed", local_agent)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": summary_text,
                }
            }, 0

        if event == "Stop":
            self.audit(payload, "allow", "session stopping", local_agent)
            return {}, 0

        self.audit(payload, "allow", f"unhandled event {event}", local_agent)
        return {}, 0


def _emit(output: dict[str, Any], exit_code: int) -> None:
    if output:
        sys.stdout.write(json.dumps(output))
    raise SystemExit(exit_code)


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GovernanceError(f"Invalid hook JSON payload: {exc}") from exc


def _self_test(repo_root: Path) -> int:
    runtime = GovernanceRuntime(repo_root)
    base_payload = {
        "timestamp": utc_now(),
        "cwd": str(repo_root),
        "sessionId": "self-test",
    }
    session_output, session_code = runtime.process({**base_payload, "hookEventName": "SessionStart", "source": "new"})
    if session_code != 0 or "hookSpecificOutput" not in session_output:
        raise GovernanceError("SessionStart self-test failed")

    default_local = None
    for item in runtime.manifest.get("localAgents", []):
        if item.get("default", False):
            default_local = item
            break

    safe_tool_input = {"filePath": default_local["path"] if default_local else "AGENTS.md", "content": "# safe edit"}
    safe_output, safe_code = runtime.process({
        **base_payload,
        "hookEventName": "PreToolUse",
        "tool_name": "create_file",
        "tool_input": safe_tool_input,
        "tool_use_id": "allow-case",
    })
    decision = safe_output.get("hookSpecificOutput", {}).get("permissionDecision")
    if safe_code != 0 or decision != "allow":
        raise GovernanceError("Allow-case PreToolUse self-test failed")

    deny_output, deny_code = runtime.process({
        **base_payload,
        "hookEventName": "PreToolUse",
        "tool_name": "run_in_terminal",
        "tool_input": {
            "command": "git push --force",
        },
        "tool_use_id": "deny-case",
    })
    deny_decision = deny_output.get("hookSpecificOutput", {}).get("permissionDecision")
    if deny_code != 0 or deny_decision != "deny":
        raise GovernanceError("Deny-case PreToolUse self-test failed")

    return 0


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--self-test":
        repo_root = Path(args[1]).resolve() if len(args) > 1 else Path.cwd().resolve()
        try:
            code = _self_test(repo_root)
        except GovernanceError as exc:
            sys.stderr.write(str(exc))
            raise SystemExit(2)
        raise SystemExit(code)

    try:
        payload = _read_payload()
        runtime = GovernanceRuntime(Path(payload.get("cwd") or Path.cwd()))
        output, exit_code = runtime.process(payload)
        _emit(output, exit_code)
    except GovernanceError as exc:
        sys.stderr.write(str(exc))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
