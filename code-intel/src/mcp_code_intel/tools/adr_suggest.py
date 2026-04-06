"""Tool implementation for adr_suggest — preview an ADR without writing to disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.adr_md import (
    ADR,
    DRAFTS_DIR,
    _slugify,
    _unescape_literal_newlines,
    generate_adr,
    today_iso,
    validate_source_log,
    validate_status,
)


def adr_suggest(
    title: str,
    status: str,
    tags: list[str],
    context: str,
    decision: str,
    consequences: str,
    references: str = "",
    source_log: str = "",
    extra_sections: list[dict[str, str]] | None = None,
    supersedes: list[str] | None = None,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Generate an ADR preview without writing to disk.

    Returns {"markdown": "...", "title": "...", "draft_id": "...", "word_count": N} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    if supersedes is None:
        supersedes = []

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

    # Unescape literal newlines from MCP transport
    context = _unescape_literal_newlines(context)
    decision = _unescape_literal_newlines(decision)
    consequences = _unescape_literal_newlines(consequences)
    references = _unescape_literal_newlines(references)

    if extra_sections:
        extra_sections = [
            {
                "heading": es.get("heading", ""),
                "content": _unescape_literal_newlines(es.get("content", "")),
            }
            for es in extra_sections
        ]

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

    adr = ADR(
        number=0,
        title=title.strip(),
        status=status,
        date=today_iso(),
        tags=[t.strip() for t in tags if t.strip()],
        source_log=source_log if source_log else None,
        supersedes=supersedes,
        sections=sections,
    )

    markdown = generate_adr(adr)

    # Compute word count across body sections (after unescape)
    word_count = len(" ".join([context, decision, consequences]).split())

    # Derive draft_id from title
    draft_id = _slugify(title.strip())

    # Write draft to local staging folder (gitignored, not committed to repo)
    drafts_dir = workspace_root / DRAFTS_DIR
    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_file = drafts_dir / f"DRAFT-{draft_id}.md"
    draft_file.write_text(markdown, encoding="utf-8")
    draft_path = f"{DRAFTS_DIR}/DRAFT-{draft_id}.md"

    return {
        "markdown": markdown,
        "title": adr.title,
        "draft_id": draft_id,
        "draft_path": draft_path,
        "word_count": word_count,
    }
