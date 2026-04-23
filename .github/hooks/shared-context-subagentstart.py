#!/usr/bin/env python3
"""Shared-context activation hook for SubagentStart events.

Reads hook JSON from stdin, writes hook response JSON to stdout.
For SubagentStart calls: correlates the child agent with any pending envelope,
activates inherited context, and appends authoritative journal records under
artifacts/scratch/shared-context/v1/.
Non-SubagentStart events are passed through immediately.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

# ruff: noqa: E402
from shared_context import SessionStorage, correlate_subagent_start, normalize_payload
from shared_context.storage import JSONValue


def _allow() -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
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


def _event_matches(payload: dict[str, object], expected_name: str) -> bool:
    """Return whether the normalized hook event name matches case-insensitively."""

    hook_event_name = _normalize_non_empty_string(payload.get("hook_event_name"))
    if hook_event_name is None:
        return False
    return hook_event_name.casefold() == expected_name.casefold()


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


def main() -> int:
    """Activate shared-context envelopes for SubagentStart events."""

    raw_payload = _read_stdin_json()
    if not raw_payload:
        return _emit_allow()

    try:
        payload = normalize_payload(raw_payload)
    except Exception:
        return _emit_allow()

    if not _event_matches(payload, "SubagentStart"):
        return _emit_allow()

    session_id = _normalize_non_empty_string(payload.get("session_id"))
    agent_id = _normalize_non_empty_string(payload.get("agent_id"))
    storage = SessionStorage(session_id=session_id, repo_root=_repo_root()) if session_id is not None else None

    if session_id is None or agent_id is None:
        fallback_agent_id = agent_id or (f"root:{session_id}" if session_id is not None else "root:unknown")
        _append_malformed_event(
            storage,
            agent_id=fallback_agent_id,
            correlation_id=agent_id,
            reason="missing_required_subagentstart_fields",
            details={
                "missing_fields": [
                    field_name
                    for field_name, field_value in (("session_id", session_id), ("agent_id", agent_id))
                    if field_value is None
                ]
            },
        )
        return _emit_allow()

    try:
        correlate_subagent_start(
            storage=SessionStorage(session_id=session_id, repo_root=_repo_root()),
            subagent_session_id=session_id,
            subagent_agent_id=agent_id,
        )
    except Exception:
        _append_malformed_event(
            storage,
            agent_id=agent_id,
            correlation_id=agent_id,
            reason="subagentstart_correlation_failed",
        )

    return _emit_allow()


if __name__ == "__main__":
    raise SystemExit(main())
