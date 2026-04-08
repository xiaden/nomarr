"""Pure functions for parsing and generating Architecturally Significant Requirement (ASR) markdown.

This module handles markdown mechanics only — no file I/O beyond next_asr_number(),
no logging, no MCP logic.

ASR markdown format:
    # ASR-NNN: {title}
    **Status:** Active
    **Date:** 2026-04-08
    **Quality Attribute:** performance
    **Priority:** High
    **Source:** {optional source reference}
    **Linked ADRs:** ADR-001, ADR-003

    ## Stimulus
    ...

    ## Response Measure
    ...

    ## Background
    ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# --- Constants ---

ASR_STATUSES: frozenset[str] = frozenset({"Active", "Satisfied", "Deferred", "Obsolete"})
ASR_PRIORITIES: frozenset[str] = frozenset({"Critical", "High", "Medium", "Low"})
REQUIREMENTS_DIR = "artifacts/requirements"
ASR_PREFIX = "ASR-"

# --- Regex patterns ---

TITLE_PATTERN: re.Pattern[str] = re.compile(r"^#\s+ASR-(\d+):\s+(.+)$")
META_PATTERN: re.Pattern[str] = re.compile(r"^\*\*(\w[\w\s]*):\*\*\s*(.*)$")
SECTION_PATTERN: re.Pattern[str] = re.compile(r"^##\s+(.+)$")

# Standard section order
_STANDARD_SECTIONS = ("Stimulus", "Response Measure", "Background")


# --- Dataclass ---


@dataclass
class ASR:
    """Structured representation of an Architecturally Significant Requirement."""

    number: int
    title: str
    status: str
    date: str
    quality_attribute: str
    priority: str
    source: str = ""
    linked_adrs: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)


# --- Helpers ---


def _slugify(title: str) -> str:
    """Convert a title to a URL-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug


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
    if status not in ASR_STATUSES:
        return f"Invalid status '{status}': must be one of {sorted(ASR_STATUSES)}"
    return None


def validate_priority(priority: str) -> str | None:
    """Validate an ASR priority. Returns error message or None if valid."""
    if priority not in ASR_PRIORITIES:
        return f"Invalid priority '{priority}': must be one of {sorted(ASR_PRIORITIES)}"
    return None


def validate_quality_attribute(qa: str) -> str | None:
    """Validate that quality_attribute is non-empty. Returns error message or None if valid."""
    if not qa.strip():
        return "Quality attribute cannot be empty"
    return None


# --- Generation ---


def generate_asr(asr: ASR) -> str:
    """Generate ASR markdown from an ASR dataclass."""
    lines: list[str] = []

    # Title
    lines.append(f"# ASR-{asr.number:03d}: {asr.title}")
    lines.append("")

    # Metadata
    lines.append(f"**Status:** {asr.status}  ")
    lines.append(f"**Date:** {asr.date}  ")
    lines.append(f"**Quality Attribute:** {asr.quality_attribute}  ")
    lines.append(f"**Priority:** {asr.priority}  ")
    if asr.source:
        lines.append(f"**Source:** {asr.source}  ")
    if asr.linked_adrs:
        lines.append(f"**Linked ADRs:** {', '.join(asr.linked_adrs)}  ")
    lines.append("")

    # Standard sections first, then extras
    written: set[str] = set()
    for heading in _STANDARD_SECTIONS:
        if heading in asr.sections:
            lines.append(f"## {heading}")
            lines.append("")
            content = asr.sections[heading].strip()
            if content:
                lines.append(content)
                lines.append("")
            written.add(heading)

    # Extra sections
    for heading, content in asr.sections.items():
        if heading not in written:
            lines.append(f"## {heading}")
            lines.append("")
            if content.strip():
                lines.append(content.strip())
                lines.append("")

    return "\n".join(lines)


def make_asr_filename(number: int, title: str) -> str:
    """Build the canonical filename for an ASR."""
    slug = _slugify(title)
    return f"ASR-{number:03d}-{slug}.md"


def next_asr_number(requirements_dir: Path) -> int:
    """Find the next available ASR number by scanning existing files."""
    if not requirements_dir.exists():
        return 1
    existing = list(requirements_dir.glob("ASR-*.md"))
    if not existing:
        return 1
    numbers: list[int] = []
    for f in existing:
        m = re.match(r"ASR-(\d+)-", f.name)
        if m:
            numbers.append(int(m.group(1)))
    return max(numbers, default=0) + 1


def today_iso() -> str:
    """Return today's date as ISO 8601 string."""
    return date.today().isoformat()


# --- Parsing ---


def parse_asr(markdown: str) -> ASR:
    """Parse ASR markdown into an ASR dataclass.

    Uses regex line-by-line parsing. Raises ValueError on malformed input.
    """
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    number = 0
    title = ""
    status = ""
    date_str = ""
    quality_attribute = ""
    priority = ""
    source = ""
    linked_adrs: list[str] = []
    sections: dict[str, str] = {}

    _IN_HEADER = "header"
    _IN_SECTION = "section"
    state = _IN_HEADER
    current_section = ""
    current_lines: list[str] = []

    for line in lines:
        if state == _IN_HEADER:
            m = TITLE_PATTERN.match(line)
            if m:
                number = int(m.group(1))
                title = m.group(2).strip()
                continue
            m = META_PATTERN.match(line)
            if m:
                key = m.group(1).strip()
                # Strip trailing double-space (markdown line break)
                val = m.group(2).strip().rstrip()
                if val.endswith("  "):
                    val = val[:-2].rstrip()
                if key == "Status":
                    status = val
                elif key == "Date":
                    date_str = val
                elif key == "Quality Attribute":
                    quality_attribute = val
                elif key == "Priority":
                    priority = val
                elif key == "Source":
                    source = val
                elif key == "Linked ADRs":
                    linked_adrs = [a.strip() for a in val.split(",") if a.strip()]
                continue
            m = SECTION_PATTERN.match(line)
            if m:
                state = _IN_SECTION
                current_section = m.group(1).strip()
                current_lines = []
                continue
        elif state == _IN_SECTION:
            m = SECTION_PATTERN.match(line)
            if m:
                sections[current_section] = "\n".join(current_lines).strip()
                current_section = m.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    if not title:
        raise ValueError("ASR title not found in markdown")

    return ASR(
        number=number,
        title=title,
        status=status or "Active",
        date=date_str,
        quality_attribute=quality_attribute,
        priority=priority,
        source=source,
        linked_adrs=linked_adrs,
        sections=sections,
    )


def parse_asr_metadata(markdown: str) -> dict[str, Any]:
    """Parse only the metadata header of an ASR. Faster than full parse for search/filter."""
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    result: dict[str, Any] = {
        "number": 0,
        "title": "",
        "status": "",
        "date": "",
        "quality_attribute": "",
        "priority": "",
    }

    for line in lines:
        if line.startswith("## "):
            break
        m = TITLE_PATTERN.match(line)
        if m:
            result["number"] = int(m.group(1))
            result["title"] = m.group(2).strip()
            continue
        m = META_PATTERN.match(line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip().rstrip()
            if val.endswith("  "):
                val = val[:-2].rstrip()
            if key == "Status":
                result["status"] = val
            elif key == "Date":
                result["date"] = val
            elif key == "Quality Attribute":
                result["quality_attribute"] = val
            elif key == "Priority":
                result["priority"] = val

    return result
