"""Pure functions for JSONL agent log files.

Each line is a self-contained JSON object — append is a single json.dumps + newline,
no full-file parse or rewrite required.

Log file format:  artifacts/logs/{agent}.log.jsonl
Each line:
    {"id": "L1", "ts": "2026-05-28T11:45:47Z", "category": "discovery",
     "title": "...", "tags": ["a", "b"], "body": "..."}

Timestamps are stored with an explicit "Z" suffix (UTC).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

# --- Constants ---

CATEGORIES: frozenset[str] = frozenset(
    {
        "research",
        "decision",
        "blocker",
        "discovery",
        "dead-end",
        "implementation",
        "observation",
    }
)
AGENT_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
LOGS_DIR = "artifacts/logs"

# Relative duration: "30m", "2h", "7d"
_DURATION_PATTERN: re.Pattern[str] = re.compile(r"^(\d+)(m|h|d)$")


# --- Dataclasses ---


@dataclass
class LogEntry:
    """A single log entry."""

    id: str  # e.g. "L42"
    ts: str  # ISO 8601 UTC with Z suffix, e.g. "2026-05-28T11:45:47Z"
    category: str
    title: str
    tags: list[str] = field(default_factory=list)
    body: str = ""


# --- Validation ---


def validate_category(category: str) -> str | None:
    """Validate a log category. Returns error message or None if valid."""
    if category not in CATEGORIES:
        return f"Invalid category '{category}': must be one of {sorted(CATEGORIES)}"
    return None


def validate_agent_name(agent: str) -> str | None:
    """Validate an agent name. Returns error message or None if valid."""
    if not agent:
        return "Agent name cannot be empty"
    if not AGENT_NAME_PATTERN.match(agent):
        return (
            f"Invalid agent name '{agent}': must be lowercase alphanumeric with hyphens, "
            "at least 2 chars, no leading/trailing hyphens"
        )
    return None


# --- Time filter parsing ---


def parse_time_filter(value: str) -> datetime | None:
    """Parse a time filter string to a UTC-aware datetime.

    Accepts:
    - Relative: "30m", "2h", "7d"
    - ISO 8601: "2026-05-28T10:00:00Z" or "2026-05-28T10:00:00"
    - Empty string → None (no filter)

    Raises ValueError on unrecognised format.
    """
    if not value:
        return None
    m = _DURATION_PATTERN.match(value)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        deltas = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }
        return datetime.now(UTC) - deltas[unit]  # noqa: TID251
    # ISO timestamp (with or without Z)
    try:
        return datetime.fromisoformat(value.rstrip("Z")).replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(
            f"Unrecognised time filter '{value}': use relative (e.g. '30m', '2h', '7d') "
            "or ISO 8601 timestamp"
        ) from exc


def ts_to_datetime(ts: str) -> datetime:
    """Parse a stored 'Z'-suffixed timestamp string to a UTC-aware datetime.

    Returns datetime.min (UTC) for empty or unparseable timestamps so that
    corrupt or legacy entries sort as very old rather than crashing callers.
    """
    clean = ts.rstrip("Z")
    if not clean:
        return datetime.min.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(clean).replace(tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


# --- ID management ---


def next_entry_id(log_file: Path) -> str:
    """Scan the JSONL file for the highest L-number and return the next one."""
    if not log_file.exists():
        return "L1"
    max_num = 0
    try:
        with log_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry_id = json.loads(line).get("id", "")
                    if entry_id.startswith("L"):
                        num = int(entry_id[1:])
                        if num > max_num:
                            max_num = num
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass
    return f"L{max_num + 1}"


# --- I/O ---


def append_entry(log_file: Path, entry: LogEntry) -> None:
    """Append a single log entry as a JSONL line."""
    record = {
        "id": entry.id,
        "ts": entry.ts,
        "category": entry.category,
        "title": entry.title,
        "tags": entry.tags,
        "body": entry.body,
    }
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_entries(log_file: Path) -> list[LogEntry]:
    """Read all entries from a JSONL log file, oldest-first.

    Skips malformed lines rather than raising, so a single corrupt line
    cannot make an entire log unreadable.
    """
    entries: list[LogEntry] = []
    try:
        with log_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    entries.append(
                        LogEntry(
                            id=obj.get("id", ""),
                            ts=obj.get("ts", ""),
                            category=obj.get("category", ""),
                            title=obj.get("title", ""),
                            tags=obj.get("tags", []),
                            body=obj.get("body", ""),
                        )
                    )
                except (json.JSONDecodeError, KeyError):
                    continue
    except OSError:
        pass
    return entries


def write_entries(log_file: Path, entries: list[LogEntry]) -> None:
    """Overwrite a JSONL log file with the given entries (oldest-first order)."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as f:
        for entry in entries:
            record = {
                "id": entry.id,
                "ts": entry.ts,
                "category": entry.category,
                "title": entry.title,
                "tags": entry.tags,
                "body": entry.body,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
