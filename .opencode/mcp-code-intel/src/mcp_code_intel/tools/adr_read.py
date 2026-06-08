"""Tool implementation for adr_read — read and parse an existing ADR."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.adr_md import (
    ADR_PREFIX,
    DECISIONS_DIR,
    parse_adr,
)


def _resolve_adr_path(name: str, workspace_root: Path) -> Path | None:
    """Resolve an ADR name to its file path.

    Accepts:
    - Full filename: "ADR-003-use-edges.md"
    - With prefix: "ADR-003-use-edges"
    - Number only: "003" or "3"
    - Slug: "ADR-003"
    """
    decisions_dir = workspace_root / DECISIONS_DIR
    if not decisions_dir.exists():
        return None

    # Strip .md
    if name.endswith(".md"):
        name = name[:-3]

    # If purely numeric, glob for that number
    stripped = name.removeprefix(ADR_PREFIX)
    if stripped.isdigit():
        num = int(stripped)
        pattern = f"ADR-{num:03d}-*.md"
        matches = list(decisions_dir.glob(pattern))
        if len(matches) == 1:
            return matches[0]
        # Also try exact match
        exact = decisions_dir / f"ADR-{num:03d}.md"
        if exact.exists():
            return exact
        return None

    # Try exact filename
    if not name.startswith(ADR_PREFIX):
        name = f"{ADR_PREFIX}{name}"
    candidate = decisions_dir / f"{name}.md"
    if candidate.exists():
        return candidate

    return None


def adr_read(
    name: str,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Read and parse an Architecture Decision Record.

    Accepts number, slug, filename, or ADR-prefixed name.
    Returns structured ADR data on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    if not name.strip():
        return {"error": "invalid_name", "message": "Name cannot be empty"}

    # Reject path traversal
    if "/" in name or "\\" in name or ".." in name:
        return {"error": "invalid_name", "message": "Name must not contain path separators"}

    adr_path = _resolve_adr_path(name, workspace_root)
    if adr_path is None:
        return {
            "error": "adr_not_found",
            "message": f"ADR not found: {name}",
            "searched": DECISIONS_DIR,
        }

    try:
        markdown = adr_path.read_text(encoding="utf-8")
        adr = parse_adr(markdown)
    except (ValueError, OSError) as exc:
        return {"error": "parse_error", "message": str(exc)}

    rel_path = str(adr_path.relative_to(workspace_root)).replace("\\", "/")
    return {
        "number": adr.number,
        "title": adr.title,
        "status": adr.status,
        "date": adr.date,
        "tags": adr.tags,
        "source_log": adr.source_log,
        "sections": adr.sections,
        "path": rel_path,
    }
