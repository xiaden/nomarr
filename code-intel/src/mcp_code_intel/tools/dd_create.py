"""Tool implementation for dd_create — create a new Design Document."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.dd_md import (
    DESIGNS_PENDING_DIR,
    DesignDocument,
    generate_dd,
    make_dd_filename,
    today_iso,
    validate_slug,
    validate_status,
)

# Standard DD sections in order
_DEFAULT_SECTIONS = (
    "Scope",
    "Problem Statement",
    "Architecture",
    "Design Goals",
    "Constraints",
    "Open Questions",
)


def dd_create(
    title: str,
    slug: str,
    status: str,
    author: str,
    scope: str,
    problem_statement: str,
    architecture: str,
    design_goals: str = "",
    constraints: str = "",
    open_questions: str = "",
    related_documents: list[dict[str, str]] | None = None,
    extra_sections: list[dict[str, str]] | None = None,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Create a new Design Document markdown file.

    Returns {"path": "...", "title": "..."} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    # Validate inputs
    slug_err = validate_slug(slug)
    if slug_err:
        return {"error": "invalid_slug", "message": slug_err}

    status_err = validate_status(status)
    if status_err:
        return {"error": "invalid_status", "message": status_err}

    if not title.strip():
        return {"error": "invalid_title", "message": "Title cannot be empty"}

    # Check target doesn't already exist
    filename = make_dd_filename(slug)
    target_dir = workspace_root / DESIGNS_PENDING_DIR
    target_path = target_dir / filename
    if target_path.exists():
        return {
            "error": "already_exists",
            "message": f"Design document already exists: {DESIGNS_PENDING_DIR}/{filename}",
        }

    # Build sections dict preserving order
    sections: dict[str, str] = {}
    section_values = {
        "Scope": scope,
        "Problem Statement": problem_statement,
        "Architecture": architecture,
        "Design Goals": design_goals,
        "Constraints": constraints,
        "Open Questions": open_questions,
    }
    for name in _DEFAULT_SECTIONS:
        val = section_values.get(name, "")
        if val.strip():
            sections[name] = val

    # Add extra sections
    if extra_sections:
        for es in extra_sections:
            heading = es.get("heading", "")
            content = es.get("content", "")
            if heading.strip() and content.strip():
                sections[heading] = content

    # Build document
    doc = DesignDocument(
        title=title.strip(),
        status=status,
        author=author.strip(),
        created=today_iso(),
        related_documents=related_documents or [],
        sections=sections,
    )

    # Generate and write
    markdown = generate_dd(doc)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_text(markdown, encoding="utf-8")

    rel_path = f"{DESIGNS_PENDING_DIR}/{filename}"
    return {"path": rel_path, "title": doc.title}
