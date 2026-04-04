"""Pure functions for parsing and generating Architecture Decision Record (ADR) markdown files.

This module handles markdown mechanics only — no file I/O beyond next_adr_number(),
no logging, no MCP logic.

ADR markdown format:
    # ADR-NNN: {title}
    **Status:** Proposed
    **Date:** 2026-04-01
    **Tags:** persistence, arangodb
    **Source Log:** rnd-ddauthor#L42

    ## Context
    ...

    ## Decision
    ...

    ## Consequences
    ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# --- Constants ---

ADR_STATUSES: frozenset[str] = frozenset({"Proposed", "Accepted", "Deprecated", "Superseded"})
SOURCE_LOG_PATTERN: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]#L\d+$")
DECISIONS_DIR = "artifacts/decisions"
ADR_PREFIX = "ADR-"

# --- Regex patterns ---

TITLE_PATTERN: re.Pattern[str] = re.compile(r"^#\s+ADR-(\d+):\s+(.+)$")
DRAFT_TITLE_PATTERN: re.Pattern[str] = re.compile(r"^#\s+ADR-DRAFT:\s+(.+)$")
META_PATTERN: re.Pattern[str] = re.compile(r"^\*\*(\w[\w\s]*):\*\*\s*(.*)$")
SECTION_PATTERN: re.Pattern[str] = re.compile(r"^##\s+(.+)$")

# Standard section order
_STANDARD_SECTIONS = ("Context", "Decision", "Consequences")


# --- Dataclass ---


@dataclass
class ADR:
    """Structured representation of an Architecture Decision Record."""

    number: int
    title: str
    status: str
    date: str
    tags: list[str] = field(default_factory=list)
    source_log: str | None = None
    supersedes: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)


# --- Helpers ---


def _slugify(title: str) -> str:
    """Convert a title to a URL-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    # Collapse multiple hyphens
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
    """Validate an ADR status. Returns error message or None if valid."""
    if status not in ADR_STATUSES:
        return f"Invalid status '{status}': must be one of {sorted(ADR_STATUSES)}"
    return None


def validate_source_log(source_log: str) -> str | None:
    """Validate a source log reference. Returns error message or None if valid."""
    if not source_log:
        return None
    if not SOURCE_LOG_PATTERN.match(source_log):
        return (
            f"Invalid source_log '{source_log}': "
            "must match pattern '{agent-name}#L{{number}}' (e.g., 'rnd-ddauthor#L42')"
        )
    return None


# --- Generation ---


def generate_adr(adr: ADR) -> str:
    """Generate ADR markdown from an ADR dataclass."""
    lines: list[str] = []

    # Title
    if adr.number == 0:
        lines.append(f"# ADR-DRAFT: {adr.title}")
    else:
        lines.append(f"# ADR-{adr.number:03d}: {adr.title}")
    lines.append("")

    # Metadata
    lines.append(f"**Status:** {adr.status}  ")
    lines.append(f"**Date:** {adr.date}  ")
    lines.append(f"**Tags:** {', '.join(adr.tags)}  ")
    if adr.source_log:
        lines.append(f"**Source Log:** {adr.source_log}  ")
    if adr.supersedes:
        lines.append(f"**Supersedes:** {', '.join(adr.supersedes)}  ")
    lines.append("")

    # Sections: standard order first, then extras, References last
    written: set[str] = set()
    for heading in _STANDARD_SECTIONS:
        if heading in adr.sections:
            lines.append(f"## {heading}")
            lines.append("")
            content = adr.sections[heading].strip()
            if content:
                lines.append(content)
                lines.append("")
            written.add(heading)

    # Extra sections (not standard and not References)
    for heading, content in adr.sections.items():
        if heading in written or heading == "References":
            continue
        lines.append(f"## {heading}")
        lines.append("")
        if content.strip():
            lines.append(content.strip())
            lines.append("")
        written.add(heading)

    # References last
    if "References" in adr.sections:
        lines.append("## References")
        lines.append("")
        ref_content = adr.sections["References"].strip()
        if ref_content:
            lines.append(ref_content)
            lines.append("")

    return "\n".join(lines)


# --- Parsing ---


def parse_adr(markdown: str) -> ADR:
    """Parse ADR markdown into an ADR dataclass.

    Raises ValueError on malformed input.
    """
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    number = 0
    title = ""
    status = ""
    adr_date = ""
    tags: list[str] = []
    source_log: str | None = None
    supersedes: list[str] = []
    sections: dict[str, str] = {}

    current_section: str | None = None
    section_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Title
        if not title:
            m = TITLE_PATTERN.match(stripped)
            if m:
                number = int(m.group(1))
                title = m.group(2).strip()
                continue
            m = DRAFT_TITLE_PATTERN.match(stripped)
            if m:
                number = 0
                title = m.group(1).strip()
                continue

        # Section heading
        m = SECTION_PATTERN.match(stripped)
        if m:
            # Save previous section
            if current_section is not None:
                sections[current_section] = "\n".join(section_lines).strip()
            current_section = m.group(1).strip()
            section_lines = []
            continue

        # Metadata (before first section)
        if current_section is None:
            m = META_PATTERN.match(stripped)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                if key == "Status":
                    status = value
                elif key == "Date":
                    adr_date = value
                elif key == "Tags":
                    tags = [t.strip() for t in value.split(",") if t.strip()]
                elif key == "Source Log":
                    source_log = value if value else None
                elif key == "Supersedes":
                    supersedes = [s.strip() for s in value.split(",") if s.strip()]
                continue

        # Content within a section
        if current_section is not None:
            section_lines.append(line)

    # Save last section
    if current_section is not None and section_lines:
        sections[current_section] = "\n".join(section_lines).strip()

    if not title:
        raise ValueError("Could not find ADR title (expected '# ADR-NNN: {title}')")

    return ADR(
        number=number,
        title=title,
        status=status,
        date=adr_date,
        tags=tags,
        source_log=source_log,
        supersedes=supersedes,
        sections=sections,
    )


def parse_adr_metadata(markdown: str) -> dict[str, Any]:
    """Parse only the ADR header metadata — stops at first ## heading.

    Returns dict with number, title, status, date, tags, source_log.
    For search performance: avoids parsing section bodies.
    """
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    number = 0
    title = ""
    status = ""
    adr_date = ""
    tags: list[str] = []
    source_log: str | None = None
    supersedes: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Stop at first section heading
        if SECTION_PATTERN.match(stripped):
            break

        # Title
        if not title:
            m = TITLE_PATTERN.match(stripped)
            if m:
                number = int(m.group(1))
                title = m.group(2).strip()
                continue
            m = DRAFT_TITLE_PATTERN.match(stripped)
            if m:
                number = 0
                title = m.group(1).strip()
                continue

        # Metadata
        m = META_PATTERN.match(stripped)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            if key == "Status":
                status = value
            elif key == "Date":
                adr_date = value
            elif key == "Tags":
                tags = [t.strip() for t in value.split(",") if t.strip()]
            elif key == "Source Log":
                source_log = value if value else None
            elif key == "Supersedes":
                supersedes = [s.strip() for s in value.split(",") if s.strip()]

    return {
        "number": number,
        "title": title,
        "status": status,
        "date": adr_date,
        "tags": tags,
        "source_log": source_log,
        "supersedes": supersedes,
    }


def next_adr_number(workspace_root: Path) -> int:
    """Find the next ADR number by scanning existing files."""
    decisions_dir = workspace_root / DECISIONS_DIR
    if not decisions_dir.exists():
        return 1

    max_num = 0
    for f in decisions_dir.glob("ADR-*.md"):
        m = re.match(r"ADR-(\d+)", f.stem)
        if m:
            num = int(m.group(1))
            if num > max_num:
                max_num = num

    return max_num + 1


def make_adr_filename(number: int, title: str) -> str:
    """Generate the filename for an ADR."""
    slug = _slugify(title)
    return f"{ADR_PREFIX}{number:03d}-{slug}.md"


def today_iso() -> str:
    """Return today's date in ISO format."""
    return date.today().isoformat()
