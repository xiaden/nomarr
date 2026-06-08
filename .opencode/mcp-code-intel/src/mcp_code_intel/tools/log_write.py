"""Tool implementation for log_write — append an entry to an agent's JSONL log."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..helpers.log_jsonl import (
    LOGS_DIR,
    LogEntry,
    append_entry,
    next_entry_id,
    validate_agent_name,
    validate_category,
)


def log_write(
    agent: str,
    title: str,
    category: str,
    body: str = "",
    tags: list[str] | None = None,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Append an entry to an agent's JSONL log file.

    Creates the log file on first call (no header needed — pure JSONL).
    Returns {"path": "...", "entry_id": "...", "title": "..."} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    agent_err = validate_agent_name(agent)
    if agent_err:
        return {"error": "invalid_agent", "message": agent_err}

    cat_err = validate_category(category)
    if cat_err:
        return {"error": "invalid_category", "message": cat_err}

    if not title.strip():
        return {"error": "invalid_title", "message": "Title cannot be empty"}

    log_file = workspace_root / LOGS_DIR / f"{agent}.log.jsonl"

    entry_id = next_entry_id(log_file)
    entry = LogEntry(
        id=entry_id,
        ts=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        category=category,
        title=title.strip(),
        tags=[t.strip() for t in (tags or []) if t.strip()],
        body=body,
    )

    append_entry(log_file, entry)

    rel_path = f"{LOGS_DIR}/{agent}.log.jsonl"
    return {"path": rel_path, "entry_id": entry_id, "title": entry.title}
