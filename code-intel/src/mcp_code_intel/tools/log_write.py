"""Tool implementation for log_write — append an entry to an agent's log."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..helpers.log_md import (
    LOGS_DIR,
    LogEntry,
    append_entry,
    generate_log_header,
    next_entry_id,
    parse_log,
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
    """Append an entry to an agent's log file.

    Creates the log file with header on first call.
    Returns {"path": "...", "entry_id": "...", "title": "..."} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    # Validate inputs
    agent_err = validate_agent_name(agent)
    if agent_err:
        return {"error": "invalid_agent", "message": agent_err}

    cat_err = validate_category(category)
    if cat_err:
        return {"error": "invalid_category", "message": cat_err}

    if not title.strip():
        return {"error": "invalid_title", "message": "Title cannot be empty"}

    # Resolve log file
    logs_dir = workspace_root / LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"{agent}.log.md"

    # Create file with header if needed
    if not log_file.exists():
        log_file.write_text(generate_log_header(agent), encoding="utf-8")

    # Parse current log for next ID
    try:
        markdown = log_file.read_text(encoding="utf-8")
        log = parse_log(markdown)
    except (ValueError, OSError) as exc:
        return {"error": "parse_error", "message": str(exc)}

    entry_id = next_entry_id(log)
    entry = LogEntry(
        id=entry_id,
        title=title.strip(),
        date=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        category=category,
        tags=[t.strip() for t in (tags or []) if t.strip()],
        body=body,
    )

    append_entry(log_file, entry)

    rel_path = f"{LOGS_DIR}/{agent}.log.md"
    return {"path": rel_path, "entry_id": entry_id, "title": entry.title}
