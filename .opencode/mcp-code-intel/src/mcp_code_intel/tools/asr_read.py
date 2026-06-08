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

    Accepts number-only variants such as "1", "0001", "ASR-0001", and
    "ASR-0001.md".
    """
    requirements_dir = workspace_root / REQUIREMENTS_DIR
    if not requirements_dir.exists():
        return None

    if name.endswith(".md"):
        name = name[:-3]

    stripped = name.removeprefix(ASR_PREFIX)
    if stripped.isdigit():
        candidate = requirements_dir / f"ASR-{int(stripped):04d}.md"
        if candidate.exists():
            return candidate

    return None


def asr_read(
    name: str,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Read and parse an Architecturally Significant Requirement.

    Accepts canonical number-based names such as "1", "0001", "ASR-0001",
    or "ASR-0001.md".
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

    rel_path = str(asr_path.relative_to(workspace_root)).replace("\\", "/")
    try:
        content = asr_path.read_text(encoding="utf-8")
        asr = parse_asr(content)
    except ValueError as e:
        return {"error": "parse_error", "message": str(e), "path": rel_path}

    return {
        "number": asr.number,
        "priority": asr.priority,
        "status": asr.status,
        "created": asr.created,
        "updated": asr.updated,
        "requirement": asr.requirement,
        "notes": asr.notes,
        "path": rel_path,
    }
