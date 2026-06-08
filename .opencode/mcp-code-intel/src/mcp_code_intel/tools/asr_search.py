"""Tool implementation for asr_search — search ASRs by status, priority, or query."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.asr_md import (
    REQUIREMENTS_DIR,
    parse_asr,
    parse_asr_metadata,
)

_MAX_LIMIT = 50  # Hard cap on results returned to MCP callers.


def asr_search(
    query: str = "",
    status: str = "",
    priority_min: int | None = None,
    priority_max: int | None = None,
    limit: int = 50,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Search ASRs by status, numeric priority range, and/or text query.

    Returns {"results": [...], "total": N} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    effective_limit = min(limit, _MAX_LIMIT) if limit > 0 else _MAX_LIMIT

    if priority_min is not None and priority_min < 0:
        return {
            "error": "invalid_params",
            "message": "priority_min cannot be negative",
        }
    if priority_max is not None and priority_max < 0:
        return {
            "error": "invalid_params",
            "message": "priority_max cannot be negative",
        }
    if priority_min is not None and priority_max is not None and priority_min > priority_max:
        return {
            "error": "invalid_params",
            "message": (
                f"priority_min ({priority_min}) cannot exceed priority_max ({priority_max})"
            ),
        }

    requirements_dir = workspace_root / REQUIREMENTS_DIR
    if not requirements_dir.exists():
        return {"results": [], "total": 0}

    asr_files = sorted(requirements_dir.glob("ASR-*.md"))
    if not asr_files:
        return {"results": [], "total": 0}

    needs_body_search = bool(query.strip())
    query_lower = query.strip().lower()

    results: list[dict[str, Any]] = []

    for asr_file in asr_files:
        try:
            content = asr_file.read_text(encoding="utf-8")

            if needs_body_search:
                asr = parse_asr(content)
                meta: dict[str, Any] = {
                    "number": asr.number,
                    "priority": asr.priority,
                    "status": asr.status,
                    "created": asr.created,
                    "updated": asr.updated,
                    "requirement": asr.requirement,
                    "notes": asr.notes,
                }
            else:
                meta = parse_asr_metadata(content)

            if status and meta["status"] != status:
                continue

            if priority_min is not None and meta["priority"] < priority_min:
                continue

            if priority_max is not None and meta["priority"] > priority_max:
                continue

            if needs_body_search and query_lower:
                searchable = (asr.requirement + " " + asr.notes).lower()
                if query_lower not in searchable:
                    continue

            rel_path = str(asr_file.relative_to(workspace_root)).replace("\\", "/")
            results.append(
                {
                    "number": meta["number"],
                    "priority": meta["priority"],
                    "status": meta["status"],
                    "created": meta["created"],
                    "updated": meta["updated"],
                    "path": rel_path,
                }
            )
        except (ValueError, OSError):
            continue

    results.sort(key=lambda r: r["priority"])
    total = len(results)

    return {
        "results": results[:effective_limit],
        "total": total,
    }
