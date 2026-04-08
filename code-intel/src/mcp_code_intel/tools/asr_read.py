"""Tool implementation for asr_read — read and parse an existing ASR."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.asr_md import (
    ASR_PREFIX,
    REQUIREMENTS_DIR,
    parse_asr,
)


def _resolve_asr_path(name: str, workspace_root: Path) -> Path | None:
    """Resolve an ASR name to its file path.

    Accepts:
    - Full filename: "ASR-003-fast-search.md"
    - With prefix: "ASR-003-fast-search"
    - Number only: "003" or "3"
    - Slug: "ASR-003"
    """
    requirements_dir = workspace_root / REQUIREMENTS_DIR
    if not requirements_dir.exists():
        return None

    # Strip .md
    if name.endswith(".md"):
        name = name[:-3]

    # If purely numeric, glob for that number
    stripped = name.removeprefix(ASR_PREFIX)
    if stripped.isdigit():
        num = int(stripped)
        pattern = f"ASR-{num:03d}-*.md"
        matches = list(requirements_dir.glob(pattern))
        if len(matches) == 1:
            return matches[0]
        # Also try exact match without slug
        exact = requirements_dir / f"ASR-{num:03d}.md"
        if exact.exists():
            return exact
        return None

    # Try exact filename
    if not name.startswith(ASR_PREFIX):
        name = f"{ASR_PREFIX}{name}"
    candidate = requirements_dir / f"{name}.md"
    if candidate.exists():
        return candidate

    return None


def asr_read(
    name: str,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Read and parse an Architecturally Significant Requirement.

    Accepts number, slug, filename, or ASR-prefixed name.
    Returns structured ASR data on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    if not name.strip():
        return {"error": "invalid_name", "message": "Name cannot be empty"}

    # Reject path traversal
    if "/" in name or "\\" in name or ".." in name:
        return {"error": "invalid_name", "message": "Name must not contain path separators"}

    asr_path = _resolve_asr_path(name, workspace_root)
    if asr_path is None:
        return {
            "error": "asr_not_found",
            "message": f"ASR not found: {name}",
            "searched": REQUIREMENTS_DIR,
        }

    try:
        markdown = asr_path.read_text(encoding="utf-8")
        asr = parse_asr(markdown)
    except (ValueError, OSError) as exc:
        return {"error": "parse_error", "message": str(exc)}

    rel_path = str(asr_path.relative_to(workspace_root)).replace("\\", "/")
    return {
        "number": asr.number,
        "title": asr.title,
        "status": asr.status,
        "date": asr.date,
        "quality_attribute": asr.quality_attribute,
        "priority": asr.priority,
        "source": asr.source,
        "linked_adrs": asr.linked_adrs,
        "sections": asr.sections,
        "path": rel_path,
    }
