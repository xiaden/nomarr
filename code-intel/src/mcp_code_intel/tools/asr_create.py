"""Tool implementation for asr_create — create a new Architecturally Significant Requirement."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.asr_md import (
    ASR,
    REQUIREMENTS_DIR,
    _unescape_literal_newlines,
    generate_asr,
    make_asr_filename,
    next_asr_number,
    today_iso,
    validate_priority,
    validate_status,
)


def asr_create(
    priority: int,
    requirement: str,
    notes: str = "",
    status: str = "Active",
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Create a new Architecturally Significant Requirement markdown file.

    Args:
        priority: Integer priority (lower = higher priority).
        requirement: The requirement statement text.
        notes: Optional context or rationale notes.
        status: One of 'Active', 'Archived', or 'Superseded by ASR-NNNN'.
        workspace_root: Absolute path to the workspace root.

    Returns:
        On success: {"path": str, "number": int, "markdown": str}
        On failure: {"error": str, "message": str}
    """
    err = validate_priority(priority)
    if err:
        return {"error": "invalid_priority", "message": err}

    requirement = requirement.strip()
    if not requirement:
        return {
            "error": "invalid_requirement",
            "message": "Requirement cannot be empty",
        }

    err = validate_status(status)
    if err:
        return {"error": "invalid_status", "message": err}

    requirement = _unescape_literal_newlines(requirement)
    notes = _unescape_literal_newlines(notes)

    requirements_dir = workspace_root / REQUIREMENTS_DIR
    requirements_dir.mkdir(parents=True, exist_ok=True)

    number = next_asr_number(requirements_dir)
    filename = make_asr_filename(number)
    target_path = requirements_dir / filename
    if target_path.exists():
        return {
            "error": "already_exists",
            "message": f"ASR file already exists: {REQUIREMENTS_DIR}/{filename}",
        }

    today = today_iso()
    asr = ASR(
        number=number,
        priority=priority,
        status=status,
        created=today,
        updated=today,
        requirement=requirement.strip(),
        notes=notes.strip(),
    )
    markdown = generate_asr(asr)
    target_path.write_text(markdown, encoding="utf-8")

    rel_path = str(target_path.relative_to(workspace_root)).replace("\\", "/")
    return {"path": rel_path, "number": number, "markdown": markdown}
