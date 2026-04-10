"""Pure functions for parsing and generating Architecturally Significant Requirement (ASR) markdown.

This module handles markdown mechanics only — no file I/O beyond next_asr_number(),
no logging, no MCP logic.

ASR markdown format:
    # ASR-NNNN
    **Priority:** 0
    **Status:** Active
    **Created:** 2026-04-08
    **Updated:** 2026-04-08

    ## Requirement
    ...

    ## Notes
    ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# --- Constants ---

ASR_STATUSES_EXACT: frozenset[str] = frozenset({"Active", "Archived"})
SUPERSEDED_PATTERN: re.Pattern[str] = re.compile(r"^Superseded by ASR-\d{4}$")
REQUIREMENTS_DIR = "artifacts/requirements"
ASR_PREFIX = "ASR-"

# --- Regex patterns ---

TITLE_PATTERN: re.Pattern[str] = re.compile(r"^#\s+ASR-(\d+)\s*$")
META_PATTERN: re.Pattern[str] = re.compile(r"^\*\*(\w[\w\s]*):\*\*\s*(.*)$")
SECTION_PATTERN: re.Pattern[str] = re.compile(r"^##\s+(.+)$")


# --- Dataclass ---


@dataclass
class ASR:
    """Structured representation of an Architecturally Significant Requirement."""

    number: int
    priority: int
    status: str
    created: str
    updated: str
    requirement: str
    notes: str = ""


# --- Helpers ---


def today_iso() -> str:
    """Return today's date as ISO 8601 string."""
    return date.today().isoformat()


def _unescape_literal_newlines(text: str) -> str:
    """Replace literal two-character escape sequences with actual characters.

    Handles ``\\n`` → newline (``\\x0a``) and ``\\t`` → tab (``\\x09``).
    This is needed because MCP transport serializes real newlines as the
    literal two-character sequence ``\\n``.
    """
    return text.replace("\\n", "\n").replace("\\t", "\t")


# --- Validation ---


def validate_status(status: str) -> str | None:
    """Validate an ASR status. Returns error message or None if valid."""
    if status in ASR_STATUSES_EXACT or SUPERSEDED_PATTERN.match(status):
        return None
    return (
        f"Invalid status '{status}': must be one of {sorted(ASR_STATUSES_EXACT)} "
        "or match 'Superseded by ASR-NNNN'"
    )


def validate_priority(priority: int) -> str | None:
    """Validate an ASR priority. Returns error message or None if valid."""
    if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0:
        return f"Invalid priority '{priority}': must be a non-negative integer"
    return None


# --- Generation ---


def generate_asr(asr: ASR) -> str:
    """Generate ASR markdown from an ASR dataclass."""
    lines: list[str] = []

    lines.append(f"# ASR-{asr.number:04d}")
    lines.append("")

    # Metadata
    lines.append(f"**Priority:** {asr.priority}  ")
    lines.append(f"**Status:** {asr.status}  ")
    lines.append(f"**Created:** {asr.created}  ")
    lines.append(f"**Updated:** {asr.updated}  ")
    lines.append("")

    lines.append("## Requirement")
    lines.append("")
    lines.append(asr.requirement.strip())
    lines.append("")

    notes = asr.notes.strip()
    if notes:
        lines.append("## Notes")
        lines.append("")
        lines.append(notes)
        lines.append("")

    return "\n".join(lines)


def make_asr_filename(number: int) -> str:
    """Build the canonical filename for an ASR."""
    return f"ASR-{number:04d}.md"


def next_asr_number(requirements_dir: Path) -> int:
    """Find the next available ASR number by scanning existing files."""
    if not requirements_dir.exists():
        return 1
    existing = list(requirements_dir.glob("ASR-*.md"))
    if not existing:
        return 1
    numbers: list[int] = []
    for f in existing:
        m = re.match(r"^ASR-(\d+)\.md$", f.name)
        if m:
            numbers.append(int(m.group(1)))
    return max(numbers, default=0) + 1


# --- Parsing ---


def parse_asr(markdown: str) -> ASR:
    """Parse ASR markdown into an ASR dataclass.

    Uses regex line-by-line parsing. Raises ValueError on malformed input.
    """
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    number = 0
    priority_raw = ""
    status = ""
    created = ""
    updated = ""
    requirement_lines: list[str] = []
    notes_lines: list[str] = []
    state = "header"

    for line in lines:
        stripped = line.strip()

        if state == "header":
            m = TITLE_PATTERN.match(line)
            if m:
                number = int(m.group(1))
                continue
            m = META_PATTERN.match(line)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip().rstrip()
                if val.endswith("  "):
                    val = val[:-2].rstrip()
                if key == "Priority":
                    priority_raw = val
                elif key == "Status":
                    status = val
                elif key == "Created":
                    created = val
                elif key == "Updated":
                    updated = val
                continue
            if stripped == "## Requirement":
                state = "requirement"
                continue
            if stripped == "## Notes":
                state = "notes"
                continue
        elif state == "requirement":
            if stripped == "## Notes":
                state = "notes"
                continue
            requirement_lines.append(line)
        elif state == "notes":
            notes_lines.append(line)

    requirement = "\n".join(requirement_lines).strip()
    notes = "\n".join(notes_lines).strip()

    if number == 0:
        raise ValueError("ASR number not found in markdown")
    if not requirement:
        raise ValueError("Requirement section not found or empty")

    try:
        priority = int(priority_raw)
    except ValueError as exc:
        raise ValueError("Priority must be an integer") from exc

    return ASR(
        number=number,
        priority=priority,
        status=status or "Active",
        created=created,
        updated=updated,
        requirement=requirement,
        notes=notes,
    )


def parse_asr_metadata(markdown: str) -> dict[str, Any]:
    """Parse only the metadata header of an ASR. Faster than full parse for search/filter."""
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    result: dict[str, Any] = {
        "number": 0,
        "priority": 0,
        "status": "",
        "created": "",
        "updated": "",
    }

    for line in lines:
        if SECTION_PATTERN.match(line):
            break
        m = TITLE_PATTERN.match(line)
        if m:
            result["number"] = int(m.group(1))
            continue
        m = META_PATTERN.match(line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip().rstrip()
            if val.endswith("  "):
                val = val[:-2].rstrip()
            if key == "Status":
                result["status"] = val
            elif key == "Priority":
                try:
                    result["priority"] = int(val)
                except ValueError as exc:
                    raise ValueError("Priority must be an integer") from exc
            elif key == "Created":
                result["created"] = val
            elif key == "Updated":
                result["updated"] = val

    if result["number"] == 0:
        raise ValueError("ASR number not found in markdown")

    return result
