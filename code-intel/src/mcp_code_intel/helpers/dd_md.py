"""Pure functions for parsing and generating Design Document (DD) markdown files.

This module handles markdown mechanics only — no file I/O, logging, or MCP logic.
All functions operate on strings and return structured data or modified strings.

DD markdown format:
    # {Title} — Design Document
    **Status:** Draft
    **Author:** RnD-DDAuthor
    **Created:** 2026-04-01
    **Revised:** 2026-04-02

    **Related Documents:**
    - [{title}]({path}) — {description}

    ---

    ## {Section Heading}

    {content}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

# --- Constants ---

DD_STATUSES: frozenset[str] = frozenset({"Draft", "Approved", "Completed", "Superseded"})
SLUG_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
DD_PREFIX = "DD-"
DESIGNS_PENDING_DIR = "artifacts/designs/pending"
DESIGNS_COMPLETED_DIR = "artifacts/designs/completed"

# --- Regex patterns ---

TITLE_PATTERN: re.Pattern[str] = re.compile(r"^#\s+(.+?)\s*(?:—|--)\s*Design\s+Document\s*$")
META_PATTERN: re.Pattern[str] = re.compile(r"^\*\*(\w[\w\s]*):\*\*\s*(.*)$")
RELATED_DOC_PATTERN: re.Pattern[str] = re.compile(
    r"^-\s+\[([^\]]+)\]\(([^)]+)\)\s*(?:—|--)\s*(.+)$"
)
SECTION_PATTERN: re.Pattern[str] = re.compile(r"^##\s+(.+)$")
SEPARATOR_PATTERN: re.Pattern[str] = re.compile(r"^---\s*$")


# --- Dataclass ---


@dataclass
class DesignDocument:
    """Structured representation of a Design Document."""

    title: str
    status: str
    author: str
    created: str
    revised: str = ""
    related_documents: list[dict[str, str]] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)


# --- Validation ---


def validate_slug(slug: str) -> str | None:
    """Validate a DD slug. Returns error message or None if valid."""
    if not slug:
        return "Slug cannot be empty"
    if not SLUG_PATTERN.match(slug):
        return (
            f"Invalid slug '{slug}': must be lowercase alphanumeric with hyphens, "
            "at least 2 chars, no leading/trailing hyphens"
        )
    return None


def validate_status(status: str) -> str | None:
    """Validate a DD status. Returns error message or None if valid."""
    if status not in DD_STATUSES:
        return f"Invalid status '{status}': must be one of {sorted(DD_STATUSES)}"
    return None


# --- Generation ---


def generate_dd(doc: DesignDocument) -> str:
    """Generate DD markdown from a DesignDocument dataclass.

    Returns the full markdown string.
    """
    lines: list[str] = []

    # Title
    lines.append(f"# {doc.title} — Design Document")
    lines.append("")

    # Metadata
    lines.append(f"**Status:** {doc.status}  ")
    lines.append(f"**Author:** {doc.author}  ")
    lines.append(f"**Created:** {doc.created}  ")
    if doc.revised:
        lines.append(f"**Revised:** {doc.revised}  ")
    lines.append("")

    # Related documents
    if doc.related_documents:
        lines.append("**Related Documents:**")
        for rd in doc.related_documents:
            title = rd.get("title", "")
            path = rd.get("path", "")
            description = rd.get("description", "")
            lines.append(f"- [{title}]({path}) — {description}")
        lines.append("")

    # Separator between metadata and sections
    lines.append("---")
    lines.append("")

    # Sections
    for heading, content in doc.sections.items():
        lines.append(f"## {heading}")
        lines.append("")
        if content.strip():
            lines.append(content.strip())
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# --- Parsing ---


def parse_dd(markdown: str) -> DesignDocument:
    """Parse DD markdown into a DesignDocument dataclass.

    Uses regex line-by-line parsing. Raises ValueError on malformed input.
    """
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    title = ""
    status = ""
    author = ""
    created = ""
    revised = ""
    related_documents: list[dict[str, str]] = []
    sections: dict[str, str] = {}

    current_section: str | None = None
    section_lines: list[str] = []
    in_related_docs = False
    past_first_separator = False

    for line in lines:
        stripped = line.strip()

        # Title
        if not title:
            m = TITLE_PATTERN.match(stripped)
            if m:
                title = m.group(1).strip()
                continue

        # Before first separator: metadata region
        if not past_first_separator:
            if SEPARATOR_PATTERN.match(stripped):
                past_first_separator = True
                in_related_docs = False
                continue

            # Metadata fields
            m = META_PATTERN.match(stripped)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                if key == "Status":
                    status = value
                elif key == "Author":
                    author = value
                elif key == "Created":
                    created = value
                elif key == "Revised":
                    revised = value
                elif key == "Related Documents":
                    in_related_docs = True
                in_related_docs = in_related_docs and key in (
                    "Related Documents",
                    "",
                )
                continue

            # Related document entries
            if in_related_docs:
                m = RELATED_DOC_PATTERN.match(stripped)
                if m:
                    related_documents.append(
                        {
                            "title": m.group(1),
                            "path": m.group(2),
                            "description": m.group(3).strip(),
                        }
                    )
                    continue

            continue

        # After first separator: sections
        m = SECTION_PATTERN.match(stripped)
        if m:
            # Save previous section
            if current_section is not None:
                sections[current_section] = "\n".join(section_lines).strip()
            current_section = m.group(1).strip()
            section_lines = []
            continue

        if SEPARATOR_PATTERN.match(stripped):
            # Section separators — save current section and reset
            if current_section is not None:
                sections[current_section] = "\n".join(section_lines).strip()
                current_section = None
                section_lines = []
            continue

        # Content within a section
        if current_section is not None:
            section_lines.append(line)

    # Save last section
    if current_section is not None and section_lines:
        sections[current_section] = "\n".join(section_lines).strip()

    if not title:
        raise ValueError("Could not find DD title (expected '# {title} — Design Document')")

    return DesignDocument(
        title=title,
        status=status,
        author=author,
        created=created,
        revised=revised,
        related_documents=related_documents,
        sections=sections,
    )


def make_dd_filename(slug: str) -> str:
    """Generate the filename for a DD from its slug."""
    return f"{DD_PREFIX}{slug}.md"


def today_iso() -> str:
    """Return today's date in ISO format."""
    return date.today().isoformat()
