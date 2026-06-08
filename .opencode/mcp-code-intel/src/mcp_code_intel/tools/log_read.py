"""Tool implementation for log_read — read and filter an agent's JSONL log."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_code_intel.helpers.log_jsonl import (
    LOGS_DIR,
    parse_time_filter,
    read_entries,
    ts_to_datetime,
    validate_agent_name,
)

_MAX_LIMIT = 50


def log_read(
    agent: str,
    category: str = "",
    tag: str = "",
    title_query: str = "",
    since: str = "",
    until: str = "",
    limit: int = 50,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Read and filter an agent's log entries.

    Pass agent="*" to read across all agents (entries include an "agent" field).
    Returns entries newest-first with AND-combined filters.

    Time filters (since / until) accept:
    - Relative durations: "30m", "2h", "7d"
    - ISO 8601 timestamps: "2026-05-28T10:00:00Z"

    Returns {"error": "...", "message": "..."} on failure.
    """
    if agent == "*":
        return _log_read_all(
            category=category,
            tag=tag,
            title_query=title_query,
            since=since,
            until=until,
            limit=limit,
            workspace_root=workspace_root,
        )

    agent_err = validate_agent_name(agent)
    if agent_err:
        return {"error": "invalid_agent", "message": agent_err}

    try:
        since_dt = parse_time_filter(since)
        until_dt = parse_time_filter(until)
    except ValueError as exc:
        return {"error": "invalid_time_filter", "message": str(exc)}

    effective_limit = min(limit, _MAX_LIMIT) if limit > 0 else _MAX_LIMIT

    log_file = workspace_root / LOGS_DIR / f"{agent}.log.jsonl"
    if not log_file.exists():
        return {
            "error": "log_not_found",
            "message": f"No log file found for agent '{agent}'",
        }

    entries = list(reversed(read_entries(log_file)))  # newest-first

    if category:
        entries = [e for e in entries if e.category == category]
    if tag:
        tag_lower = tag.lower()
        entries = [e for e in entries if tag_lower in [t.lower() for t in e.tags]]
    if title_query:
        query_lower = title_query.lower()
        entries = [e for e in entries if query_lower in e.title.lower()]
    if since_dt is not None:
        entries = [e for e in entries if ts_to_datetime(e.ts) >= since_dt]
    if until_dt is not None:
        entries = [e for e in entries if ts_to_datetime(e.ts) <= until_dt]

    total = len(entries)
    entries = entries[:effective_limit]

    return {
        "agent": agent,
        "entries": [
            {
                "id": e.id,
                "title": e.title,
                "ts": e.ts,
                "category": e.category,
                "tags": e.tags,
                "body": e.body,
            }
            for e in entries
        ],
        "total": total,
    }


def _log_read_all(
    category: str,
    tag: str,
    title_query: str,
    since: str,
    until: str,
    limit: int,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Read and merge log entries from all agents, sorted newest-first."""
    try:
        since_dt = parse_time_filter(since)
        until_dt = parse_time_filter(until)
    except ValueError as exc:
        return {"error": "invalid_time_filter", "message": str(exc)}

    logs_dir = workspace_root / LOGS_DIR
    if not logs_dir.exists():
        return {"agent": "*", "entries": [], "total": 0}

    effective_limit = min(limit, _MAX_LIMIT) if limit > 0 else _MAX_LIMIT

    all_entries: list[tuple[str, Any]] = []
    for log_file in sorted(logs_dir.glob("*.log.jsonl")):
        agent_name = log_file.name.removesuffix(".log.jsonl")
        all_entries.extend((agent_name, entry) for entry in read_entries(log_file))

    # ISO timestamps sort correctly as strings (lexicographic == chronological)
    all_entries.sort(key=lambda x: x[1].ts, reverse=True)

    if category:
        all_entries = [(a, e) for a, e in all_entries if e.category == category]
    if tag:
        tag_lower = tag.lower()
        all_entries = [(a, e) for a, e in all_entries if tag_lower in [t.lower() for t in e.tags]]
    if title_query:
        query_lower = title_query.lower()
        all_entries = [(a, e) for a, e in all_entries if query_lower in e.title.lower()]
    if since_dt is not None:
        all_entries = [(a, e) for a, e in all_entries if ts_to_datetime(e.ts) >= since_dt]
    if until_dt is not None:
        all_entries = [(a, e) for a, e in all_entries if ts_to_datetime(e.ts) <= until_dt]

    total = len(all_entries)
    all_entries = all_entries[:effective_limit]

    return {
        "agent": "*",
        "entries": [
            {
                "agent": agent_name,
                "id": e.id,
                "title": e.title,
                "ts": e.ts,
                "category": e.category,
                "tags": e.tags,
                "body": e.body,
            }
            for agent_name, e in all_entries
        ],
        "total": total,
    }
