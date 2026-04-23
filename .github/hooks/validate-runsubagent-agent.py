#!/usr/bin/env python3
"""Validate runSubagent calls target a real named custom agent.

This script is designed for a VS Code Copilot `PreToolUse` hook.
It reads hook input JSON from stdin and returns a hook response JSON on stdout.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_RUNSUBAGENT_TOOL_NAMES: set[str] = {
    "runsubagent",
    "run_subagent",
    "agent",
}


def _read_stdin_json() -> dict:
    """Read hook payload from stdin."""
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
        if name:
            names.add(name)
    return names


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _allow() -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }


def _is_runsubagent_tool(tool_name: str) -> bool:
    normalized = tool_name.strip().lower()
    if normalized in _RUNSUBAGENT_TOOL_NAMES:
        return True
    return normalized.endswith(".runsubagent")


def main() -> int:
    payload = _read_stdin_json()

    tool_name = str(payload.get("tool_name", "")).strip()
    if not _is_runsubagent_tool(tool_name):
        print(json.dumps(_allow()))
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        print(json.dumps(_deny("runSubagent requires tool_input to be an object.")))
        return 0

    # The VS Code tool API uses `agentName`.
    # We also tolerate `agent_name` for compatibility.
    raw_agent_name = tool_input.get("agentName", tool_input.get("agent_name", ""))
    agent_name = str(raw_agent_name).strip() if raw_agent_name is not None else ""

    if not agent_name:
        print(
            json.dumps(
                _deny(
                    "runSubagent must include a non-empty 'agentName' and it must match an agent in .github/agents.",
                ),
            ),
        )
        return 0

    names = _discover_agent_names(_repo_root())
    if not names:
        print(
            json.dumps(
                _deny(
                    "No agents were discovered under .github/agents; cannot validate runSubagent target.",
                ),
            ),
        )
        return 0

    if agent_name not in names:
        allowed = ", ".join(sorted(names))
        print(
            json.dumps(
                _deny(
                    f"Unknown runSubagent agentName '{agent_name}'. Allowed agent names: {allowed}",
                ),
            ),
        )
        return 0

    print(json.dumps(_allow()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
