#!/usr/bin/env python3
"""Shared-context capture hook for PreToolUse(runSubagent) events.

Reads hook JSON from stdin, writes hook response JSON to stdout.
For runSubagent calls: freezes pending envelope, reserves next_child items,
appends to authoritative journal under artifacts/scratch/shared-context/v1/.
Non-runSubagent events are passed through immediately.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Final

HOOKS_DIR = Path(__file__).resolve().parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

# ruff: noqa: E402
from shared_context import SessionStorage, capture_pretooluse_spawn, normalize_payload
from shared_context.storage import JSONValue

_RUNSUBAGENT_TOOL_NAMES: Final[frozenset[str]] = frozenset({"agent", "run_subagent", "runsubagent"})


def _allow() -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }


def _emit_allow() -> int:
    print(json.dumps(_allow(), ensure_ascii=False))
    return 0


def _read_stdin_json() -> dict[str, object]:
    """Read a hook payload from stdin, returning an empty dict on any issue."""

    raw = sys.stdin.read().strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _repo_root() -> Path:
    """Resolve repository root from this script location."""

    return Path(__file__).resolve().parents[2]


def _normalize_non_empty_string(value: object) -> str | None:
    """Return a trimmed non-empty string, or None when unusable."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_lineage(value: object) -> list[str]:
    """Return a deterministic lineage list with empty or duplicate entries removed."""

    if not isinstance(value, list):
        return []

    lineage: list[str] = []
    seen: set[str] = set()
    for raw_entry in value:
        entry = _normalize_non_empty_string(raw_entry)
        if entry is None or entry in seen:
            continue
        seen.add(entry)
        lineage.append(entry)
    return lineage


def _append_malformed_event(
    storage: SessionStorage | None,
    *,
    agent_id: str,
    correlation_id: str | None,
    reason: str,
    details: dict[str, JSONValue] | None = None,
) -> None:
    """Best-effort malformed-event journal append; never raises."""

    if storage is None:
        return

    try:
        payload: dict[str, JSONValue] = {"reason": reason}
        if details is not None:
            payload["details"] = details
        storage.append_journal_record(
            record_type="malformed_event_ignored",
            agent_id=agent_id,
            correlation_id=correlation_id,
            payload=payload,
        )
    except Exception:
        return


def _extract_frontmatter_name(text: str) -> str | None:
    """Extract `name:` from markdown YAML frontmatter without external deps."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    try:
        end_idx = lines.index("---", 1)
    except ValueError:
        return None

    name_pattern = re.compile(r"^name\s*:\s*(.+?)\s*$", re.IGNORECASE)
    for line in lines[1:end_idx]:
        match = name_pattern.match(line.strip())
        if not match:
            continue
        value = match.group(1).strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1].strip()
        return value or None
    return None


def _discover_agent_names(root: Path) -> set[str]:
    """Collect custom agent display names from .agent.md frontmatter."""

    agents_dir = root / ".github" / "agents"
    if not agents_dir.exists():
        return set()

    names: set[str] = set()
    for agent_file in agents_dir.rglob("*.agent.md"):
        try:
            content = agent_file.read_text(encoding="utf-8")
        except OSError:
            continue
        name = _extract_frontmatter_name(content)
        if name is not None:
            names.add(name)
    return names


def _is_runsubagent_tool(tool_name: object) -> bool:
    """Return whether the provided tool name maps to a runSubagent call."""

    normalized = _normalize_non_empty_string(tool_name)
    if normalized is None:
        return False
    return normalized.lower().replace("-", "_") in _RUNSUBAGENT_TOOL_NAMES


def _event_matches(payload: dict[str, object], expected_name: str) -> bool:
    """Return whether the normalized hook event name matches case-insensitively."""

    hook_event_name = _normalize_non_empty_string(payload.get("hook_event_name"))
    if hook_event_name is None:
        return False
    return hook_event_name.casefold() == expected_name.casefold()


def _extract_tool_input_summary(tool_input: dict[str, object]) -> dict[str, object]:
    """Return the bounded tool-input summary persisted with the pending envelope."""

    agent_name = _normalize_non_empty_string(tool_input.get("agent_name"))
    if agent_name is None:
        agent_name = _normalize_non_empty_string(tool_input.get("agentName"))

    description = _normalize_non_empty_string(tool_input.get("description")) or ""
    return {
        "agent_name": agent_name or "",
        "description": description,
        "prompt_present": "prompt" in tool_input,
    }


def _has_valid_named_agent_target(tool_input: dict[str, object], repo_root: Path) -> bool:
    """Mirror the runSubagent validator policy so invalid calls never write state."""

    agent_name = _normalize_non_empty_string(tool_input.get("agent_name"))
    if agent_name is None:
        agent_name = _normalize_non_empty_string(tool_input.get("agentName"))
    if agent_name is None:
        return False

    return agent_name in _discover_agent_names(repo_root)


def main() -> int:
    """Capture shared-context spawn state for allowed runSubagent calls."""

    raw_payload = _read_stdin_json()
    if not raw_payload:
        return _emit_allow()

    try:
        payload = normalize_payload(raw_payload)
    except Exception:
        return _emit_allow()

    if not _event_matches(payload, "PreToolUse"):
        return _emit_allow()

    if not _is_runsubagent_tool(payload.get("tool_name")):
        return _emit_allow()

    session_id = _normalize_non_empty_string(payload.get("session_id"))
    tool_use_id = _normalize_non_empty_string(payload.get("tool_use_id"))
    repo_root = _repo_root()
    storage = SessionStorage(session_id=session_id, repo_root=repo_root) if session_id is not None else None

    if session_id is None or tool_use_id is None:
        fallback_agent_id = f"root:{session_id}" if session_id is not None else "root:unknown"
        _append_malformed_event(
            storage,
            agent_id=fallback_agent_id,
            correlation_id=tool_use_id,
            reason="missing_required_pretooluse_fields",
            details={
                "missing_fields": [
                    field_name
                    for field_name, field_value in (("session_id", session_id), ("tool_use_id", tool_use_id))
                    if field_value is None
                ]
            },
        )
        return _emit_allow()

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        _append_malformed_event(
            storage,
            agent_id=f"root:{session_id}",
            correlation_id=tool_use_id,
            reason="tool_input_missing_or_invalid",
        )
        return _emit_allow()

    if not _has_valid_named_agent_target(tool_input, repo_root):
        return _emit_allow()

    parent_agent_id = _normalize_non_empty_string(payload.get("agent_id")) or f"root:{session_id}"
    parent_lineage = []
    for field_name in ("parent_lineage", "agent_lineage", "lineage"):
        if field_name in payload:
            parent_lineage = _normalize_lineage(payload.get(field_name))
            break

    transcript_path = _normalize_non_empty_string(payload.get("transcript_path"))
    cwd = _normalize_non_empty_string(payload.get("cwd"))
    if transcript_path is None or cwd is None:
        _append_malformed_event(
            storage,
            agent_id=parent_agent_id,
            correlation_id=tool_use_id,
            reason="missing_pretooluse_runtime_paths",
            details={
                "missing_fields": [
                    field_name
                    for field_name, field_value in (("transcript_path", transcript_path), ("cwd", cwd))
                    if field_value is None
                ]
            },
        )
        return _emit_allow()

    tool_input_summary = _extract_tool_input_summary(tool_input)
    try:
        capture_pretooluse_spawn(
            storage=SessionStorage(session_id=session_id, repo_root=repo_root),
            session_id=session_id,
            tool_use_id=tool_use_id,
            parent_agent_id=parent_agent_id,
            parent_lineage=parent_lineage,
            tool_input_summary=tool_input_summary,
            transcript_path=transcript_path,
            cwd=cwd,
        )
    except Exception:
        _append_malformed_event(
            storage,
            agent_id=parent_agent_id,
            correlation_id=tool_use_id,
            reason="pretooluse_capture_failed",
        )

    return _emit_allow()


if __name__ == "__main__":
    raise SystemExit(main())
