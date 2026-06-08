"""Tool implementation for log_archive — move matching log entries to an archive file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.log_jsonl import (
    LOGS_DIR,
    LogEntry,
    append_entry,
    parse_time_filter,
    read_entries,
    ts_to_datetime,
    validate_agent_name,
    write_entries,
)

_ARCHIVE_SUBDIR = "archive"


def log_archive(
    agent: str,
    ids: list[str] | None = None,
    tag: str = "",
    category: str = "",
    title_query: str = "",
    before: str = "",
    after: str = "",
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Move matching log entries to an archive file.

    Selection logic:
    - If `ids` is provided: archive exactly those entry IDs (other filters ignored).
    - Otherwise: archive entries matching the AND of all non-empty filters
      (tag, category, title_query, before, after).

    Archived entries are appended to:
        artifacts/logs/archive/{agent}.log.jsonl

    The source log is rewritten with the remaining (non-archived) entries.
    IDs are not re-numbered — gaps are expected.

    Returns:
        {
            "archived": <count of moved entries>,
            "remaining": <count of kept entries>,
            "archive_path": "artifacts/logs/archive/{agent}.log.jsonl",
            "archived_ids": ["L1", "L5", ...],
        }

    Error keys: "invalid_agent", "log_not_found", "nothing_to_archive",
                "invalid_time_filter", "no_filter".
    """
    agent_err = validate_agent_name(agent)
    if agent_err:
        return {"error": "invalid_agent", "message": agent_err}

    # Require at least one filter so the tool never silently empties a log.
    if not ids and not tag and not category and not title_query and not before and not after:
        return {
            "error": "no_filter",
            "message": (
                "Provide at least one filter: ids, tag, category, title_query, before, or after."
            ),
        }

    log_file = workspace_root / LOGS_DIR / f"{agent}.log.jsonl"
    if not log_file.exists():
        return {
            "error": "log_not_found",
            "message": f"No log file found for agent '{agent}'",
        }

    all_entries = read_entries(log_file)

    if ids is not None:
        # ID-based selection — exact match, order-preserving
        id_set = {i.strip() for i in ids}
        to_archive = [e for e in all_entries if e.id in id_set]
        to_keep = [e for e in all_entries if e.id not in id_set]
    else:
        # Filter-based selection
        try:
            before_dt = parse_time_filter(before)
            after_dt = parse_time_filter(after)
        except ValueError as exc:
            return {"error": "invalid_time_filter", "message": str(exc)}

        tag_lower = tag.lower() if tag else ""
        title_lower = title_query.lower() if title_query else ""

        def _matches(e: LogEntry) -> bool:
            if tag_lower and tag_lower not in [t.lower() for t in e.tags]:
                return False
            if category and e.category != category:
                return False
            if title_lower and title_lower not in e.title.lower():
                return False
            entry_dt = ts_to_datetime(e.ts)
            if before_dt is not None and entry_dt >= before_dt:
                return False
            if after_dt is not None and entry_dt <= after_dt:
                return False
            return True

        to_archive = [e for e in all_entries if _matches(e)]
        to_keep = [e for e in all_entries if not _matches(e)]

    if not to_archive:
        return {
            "error": "nothing_to_archive",
            "message": "No entries matched the given filters.",
        }

    # Write remaining entries back to the source log.
    write_entries(log_file, to_keep)

    # Append archived entries to the archive file.
    archive_file = workspace_root / LOGS_DIR / _ARCHIVE_SUBDIR / f"{agent}.log.jsonl"
    for entry in to_archive:
        append_entry(archive_file, entry)

    archive_rel = f"{LOGS_DIR}/{_ARCHIVE_SUBDIR}/{agent}.log.jsonl"
    return {
        "archived": len(to_archive),
        "remaining": len(to_keep),
        "archive_path": archive_rel,
        "archived_ids": [e.id for e in to_archive],
    }
