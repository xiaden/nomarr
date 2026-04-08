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
    validate_quality_attribute,
    validate_status,
)

_DEFAULT_SECTIONS = ("Stimulus", "Response Measure", "Background")


def asr_create(
    title: str,
    quality_attribute: str,
    priority: str,
    stimulus: str,
    response_measure: str,
    background: str = "",
    constraints: str = "",
    linked_adrs: list[str] | None = None,
    source: str = "",
    status: str = "Active",
    extra_sections: list[dict[str, str]] | None = None,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Create a new ASR markdown file.

    Returns {"path": "...", "number": N, "title": "...", "markdown": "..."} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    if linked_adrs is None:
        linked_adrs = []

    if not title.strip():
        return {"error": "invalid_title", "message": "Title cannot be empty"}

    qa_err = validate_quality_attribute(quality_attribute)
    if qa_err:
        return {"error": "invalid_quality_attribute", "message": qa_err}

    priority_err = validate_priority(priority)
    if priority_err:
        return {"error": "invalid_priority", "message": priority_err}

    status_err = validate_status(status)
    if status_err:
        return {"error": "invalid_status", "message": status_err}

    if not stimulus.strip():
        return {"error": "invalid_section", "message": "Stimulus section cannot be empty"}

    if not response_measure.strip():
        return {
            "error": "invalid_section",
            "message": "Response Measure section cannot be empty",
        }

    # Unescape literal newlines from MCP transport
    stimulus = _unescape_literal_newlines(stimulus)
    response_measure = _unescape_literal_newlines(response_measure)
    background = _unescape_literal_newlines(background)
    constraints = _unescape_literal_newlines(constraints)

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
        "Stimulus": stimulus,
        "Response Measure": response_measure,
    }
    if background.strip():
        sections["Background"] = background
    if constraints.strip():
        sections["Constraints"] = constraints

    if extra_sections:
        for es in extra_sections:
            heading = es.get("heading", "")
            content = es.get("content", "")
            if heading.strip() and content.strip():
                sections[heading] = content

    # Determine output path
    requirements_dir = workspace_root / REQUIREMENTS_DIR
    requirements_dir.mkdir(parents=True, exist_ok=True)

    number = next_asr_number(requirements_dir)
    filename = make_asr_filename(number, title.strip())
    target_path = requirements_dir / filename

    if target_path.exists():
        return {
            "error": "already_exists",
            "message": f"ASR file already exists: {REQUIREMENTS_DIR}/{filename}",
        }

    asr = ASR(
        number=number,
        title=title.strip(),
        status=status,
        date=today_iso(),
        quality_attribute=quality_attribute.strip(),
        priority=priority,
        source=source.strip(),
        linked_adrs=linked_adrs,
        sections=sections,
    )

    markdown = generate_asr(asr)
    try:
        target_path.write_text(markdown, encoding="utf-8")
    except OSError as e:
        return {"error": "write_error", "message": str(e)}

    rel_path = str(target_path.relative_to(workspace_root)).replace("\\", "/")
    return {
        "number": number,
        "title": asr.title,
        "path": rel_path,
        "markdown": markdown,
    }
