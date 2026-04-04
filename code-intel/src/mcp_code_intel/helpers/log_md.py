"""Pure functions for parsing and generating agent log markdown files.

This module handles markdown mechanics only — no MCP logic.
Log files are append-only per-agent files with entries separated by headings.

Log markdown format:
    # Agent Log: {agent-name}

    ---

    ## [L1] First entry title
    **Date:** 2026-04-01T14:30:00
    **Category:** research
    **Tags:** persistence, arangodb

    Body text here.

    ---

    ## [L2] Second entry title
    ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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

# --- Regex patterns ---

HEADER_PATTERN: re.Pattern[str] = re.compile(r"^#\s+Agent\s+Log:\s+(.+)$")
ENTRY_PATTERN: re.Pattern[str] = re.compile(r"^##\s+\[L(\d+)\]\s+(.+)$")
META_PATTERN: re.Pattern[str] = re.compile(r"^\*\*(\w[\w\s]*):\*\*\s*(.*)$")
SEPARATOR_PATTERN: re.Pattern[str] = re.compile(r"^---\s*$")


# --- Dataclasses ---


@dataclass
class LogEntry:
    """A single log entry."""

    id: str  # e.g. "L42"
    title: str
    date: str  # ISO 8601 UTC
    category: str
    tags: list[str] = field(default_factory=list)
    body: str = ""


@dataclass
class AgentLog:
    """A complete agent log file."""

    agent: str
    entries: list[LogEntry] = field(default_factory=list)


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


# --- Generation ---


def generate_log_header(agent: str) -> str:
    """Generate the initial log file content."""
    return f"# Agent Log: {agent}\n\n---\n"


def next_entry_id(log: AgentLog) -> str:
    """Find the next entry ID (L{N+1})."""
    if not log.entries:
        return "L1"
    max_num = 0
    for entry in log.entries:
        # Extract number from "L42"
        if entry.id.startswith("L"):
            try:
                num = int(entry.id[1:])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    return f"L{max_num + 1}"


# --- Parsing ---


def parse_log(markdown: str) -> AgentLog:
    """Parse agent log markdown into an AgentLog dataclass.

    Raises ValueError on malformed input.
    """
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    agent = ""
    entries: list[LogEntry] = []

    current_entry_id: str | None = None
    current_entry_title = ""
    current_entry_date = ""
    current_entry_category = ""
    current_entry_tags: list[str] = []
    body_lines: list[str] = []
    in_metadata = False

    def _flush_entry() -> None:
        nonlocal current_entry_id, current_entry_title
        nonlocal current_entry_date, current_entry_category, current_entry_tags
        nonlocal body_lines, in_metadata
        if current_entry_id is not None:
            entries.append(
                LogEntry(
                    id=current_entry_id,
                    title=current_entry_title,
                    date=current_entry_date,
                    category=current_entry_category,
                    tags=list(current_entry_tags),
                    body="\n".join(body_lines).strip(),
                )
            )
        current_entry_id = None
        current_entry_title = ""
        current_entry_date = ""
        current_entry_category = ""
        current_entry_tags = []
        body_lines = []
        in_metadata = False

    for line in lines:
        stripped = line.strip()

        # Agent header
        if not agent:
            m = HEADER_PATTERN.match(stripped)
            if m:
                agent = m.group(1).strip()
                continue

        # Entry heading
        m = ENTRY_PATTERN.match(stripped)
        if m:
            _flush_entry()
            current_entry_id = f"L{m.group(1)}"
            current_entry_title = m.group(2).strip()
            in_metadata = True
            continue

        # Separator — ends current entry if we're in one
        if SEPARATOR_PATTERN.match(stripped):
            if current_entry_id is not None:
                _flush_entry()
            continue

        # Metadata within an entry (right after heading)
        if current_entry_id is not None and in_metadata:
            m = META_PATTERN.match(stripped)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                if key == "Date":
                    current_entry_date = value
                elif key == "Category":
                    current_entry_category = value
                elif key == "Tags":
                    current_entry_tags = [t.strip() for t in value.split(",") if t.strip()]
                continue
            # Blank line after metadata transitions to body
            if not stripped:
                in_metadata = False
                continue

        # Body content
        if current_entry_id is not None and not in_metadata:
            body_lines.append(line)

    # Flush last entry
    _flush_entry()

    if not agent:
        raise ValueError("Could not find log header (expected '# Agent Log: {name}')")

    return AgentLog(agent=agent, entries=entries)


# --- Appending ---


def append_entry(file_path: Path, entry: LogEntry) -> None:
    """Append a log entry to an existing log file."""
    lines: list[str] = [
        "",
        f"## [{entry.id}] {entry.title}",
        f"**Date:** {entry.date}  ",
        f"**Category:** {entry.category}  ",
    ]

    if entry.tags:
        lines.append(f"**Tags:** {', '.join(entry.tags)}  ")

    lines.append("")

    if entry.body.strip():
        lines.append(entry.body.strip())
        lines.append("")

    lines.append("---")
    lines.append("")

    with file_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))
