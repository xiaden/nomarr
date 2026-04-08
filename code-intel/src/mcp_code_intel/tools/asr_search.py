"""Tool implementation for asr_search — search ASRs by quality attribute, status, or query."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.asr_md import (
    REQUIREMENTS_DIR,
    parse_asr,
    parse_asr_metadata,
)

_MAX_LIMIT = 50


def asr_search(
    query: str = "",
    quality_attribute: str = "",
    status: str = "",
    priority: str = "",
    limit: int = 50,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Search ASRs by quality attribute, status, priority, and/or text query.

    Returns {"results": [...], "total": N} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    effective_limit = min(limit, _MAX_LIMIT) if limit > 0 else _MAX_LIMIT

    requirements_dir = workspace_root / REQUIREMENTS_DIR
    if not requirements_dir.exists():
        return {"results": [], "total": 0}

    asr_files = sorted(requirements_dir.glob("ASR-*.md"))
    if not asr_files:
        return {"results": [], "total": 0}

    # Need full parse only when searching body text
    needs_body_search = bool(query.strip())
    query_lower = query.strip().lower()
    qa_lower = quality_attribute.strip().lower()
    priority_lower = priority.strip().lower()

    results: list[dict[str, Any]] = []

    for asr_file in asr_files:
        try:
            markdown = asr_file.read_text(encoding="utf-8")

            if needs_body_search:
                asr = parse_asr(markdown)
                meta: dict[str, Any] = {
                    "number": asr.number,
                    "title": asr.title,
                    "status": asr.status,
                    "date": asr.date,
                    "quality_attribute": asr.quality_attribute,
                    "priority": asr.priority,
                }
                body_text = " ".join(asr.sections.values()).lower()
            else:
                meta = parse_asr_metadata(markdown)
                body_text = ""

            # Filter by status (exact match)
            if status and meta.get("status", "") != status:
                continue

            # Filter by quality_attribute (case-insensitive)
            if qa_lower and meta.get("quality_attribute", "").lower() != qa_lower:
                continue

            # Filter by priority (case-insensitive)
            if priority_lower and meta.get("priority", "").lower() != priority_lower:
                continue

            # Filter by query (case-insensitive substring in title + quality_attribute + body)
            if query_lower:
                title_lower = meta.get("title", "").lower()
                qa_text = meta.get("quality_attribute", "").lower()
                searchable = f"{title_lower} {qa_text} {body_text}"
                if query_lower not in searchable:
                    continue

            rel_path = str(asr_file.relative_to(workspace_root)).replace("\\", "/")
            results.append(
                {
                    "number": meta.get("number", 0),
                    "title": meta.get("title", ""),
                    "status": meta.get("status", ""),
                    "date": meta.get("date", ""),
                    "quality_attribute": meta.get("quality_attribute", ""),
                    "priority": meta.get("priority", ""),
                    "path": rel_path,
                }
            )
        except (ValueError, OSError):
            continue

    # Sort by number descending (most recent first)
    results.sort(key=lambda r: r.get("number", 0), reverse=True)
    total = len(results)

    return {
        "results": results[:effective_limit],
        "total": total,
    }
