"""Tool implementation for adr_create — create a new Architecture Decision Record."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.adr_md import (
    ADR,
    DECISIONS_DIR,
    generate_adr,
    make_adr_filename,
    next_adr_number,
    today_iso,
    validate_source_log,
    validate_status,
)

# Standard ADR sections in order
_STANDARD_SECTIONS = ("Context", "Decision", "Consequences")
_MAX_RETRIES = 3


def adr_create(
    title: str,
    status: str,
    tags: list[str],
    context: str,
    decision: str,
    consequences: str,
    references: str = "",
    source_log: str = "",
    extra_sections: list[dict[str, str]] | None = None,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Create a new Architecture Decision Record.

    Returns {"path": "...", "number": N, "title": "..."} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    # Validate inputs
    if not title.strip():
        return {"error": "invalid_title", "message": "Title cannot be empty"}

    status_err = validate_status(status)
    if status_err:
        return {"error": "invalid_status", "message": status_err}

    if not tags:
        return {"error": "invalid_tags", "message": "At least one tag is required"}

    if not context.strip():
        return {"error": "invalid_section", "message": "Context section cannot be empty"}
    if not decision.strip():
        return {"error": "invalid_section", "message": "Decision section cannot be empty"}
    if not consequences.strip():
        return {"error": "invalid_section", "message": "Consequences section cannot be empty"}

    if source_log:
        sl_err = validate_source_log(source_log)
        if sl_err:
            return {"error": "invalid_source_log", "message": sl_err}

    # Build sections dict preserving order
    sections: dict[str, str] = {
        "Context": context,
        "Decision": decision,
        "Consequences": consequences,
    }

    # Add extra sections
    if extra_sections:
        for es in extra_sections:
            heading = es.get("heading", "")
            content = es.get("content", "")
            if heading.strip() and content.strip():
                sections[heading] = content

    # References last
    if references.strip():
        sections["References"] = references

    # Write with retry on collision
    target_dir = workspace_root / DECISIONS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    for _attempt in range(_MAX_RETRIES):
        number = next_adr_number(workspace_root)
        filename = make_adr_filename(number, title)
        target_path = target_dir / filename

        adr = ADR(
            number=number,
            title=title.strip(),
            status=status,
            date=today_iso(),
            tags=[t.strip() for t in tags if t.strip()],
            source_log=source_log if source_log else None,
            sections=sections,
        )

        markdown = generate_adr(adr)

        try:
            # Atomic create — fails if file exists
            target_path.write_text(markdown, encoding="utf-8")
            rel_path = f"{DECISIONS_DIR}/{filename}"
            return {"path": rel_path, "number": number, "title": adr.title}
        except FileExistsError:
            continue

    return {
        "error": "collision",
        "message": f"Failed to create ADR after {_MAX_RETRIES} retries due to numbering collision",
    }
