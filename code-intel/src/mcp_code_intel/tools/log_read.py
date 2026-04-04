"""Tool implementation for log_read — read and filter an agent's log."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.log_md import (
    LOGS_DIR,
    parse_log,
    validate_agent_name,
)

_MAX_LIMIT = 50


def log_read(
    agent: str,
    category: str = "",
    tag: str = "",
    title_query: str = "",
    limit: int = 50,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Read and filter an agent's log entries.

    Returns entries newest-first with AND-combined filters.
    Returns {"error": "...", "message": "..."} on failure.
    """
    # Validate
    agent_err = validate_agent_name(agent)
    if agent_err:
        return {"error": "invalid_agent", "message": agent_err}

    effective_limit = min(limit, _MAX_LIMIT) if limit > 0 else _MAX_LIMIT

    log_file = workspace_root / LOGS_DIR / f"{agent}.log.md"
    if not log_file.exists():
        return {
            "error": "log_not_found",
            "message": f"No log file found for agent '{agent}'",
        }

    try:
        markdown = log_file.read_text(encoding="utf-8")
        log = parse_log(markdown)
    except (ValueError, OSError) as exc:
        return {"error": "parse_error", "message": str(exc)}

    # Reverse for newest-first
    entries = list(reversed(log.entries))

    # Apply AND-combined filters
    if category:
        entries = [e for e in entries if e.category == category]
    if tag:
        tag_lower = tag.lower()
        entries = [e for e in entries if tag_lower in [t.lower() for t in e.tags]]
    if title_query:
        query_lower = title_query.lower()
        entries = [e for e in entries if query_lower in e.title.lower()]

    total = len(entries)
    entries = entries[:effective_limit]

    return {
        "agent": log.agent,
        "entries": [
            {
                "id": e.id,
                "title": e.title,
                "date": e.date,
                "category": e.category,
                "tags": e.tags,
                "body": e.body,
            }
            for e in entries
        ],
        "total": total,
    }
