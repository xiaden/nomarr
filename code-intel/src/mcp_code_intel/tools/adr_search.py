"""Tool implementation for adr_search — search ADRs by tag, status, or query."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.adr_md import (
    DECISIONS_DIR,
    parse_adr,
    parse_adr_metadata,
)

_MAX_LIMIT = 50


def adr_search(
    query: str = "",
    tag: str = "",
    status: str = "",
    limit: int = 50,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Search ADRs by tag, status, and/or text query.

    Returns {"results": [...], "total": N} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    effective_limit = min(limit, _MAX_LIMIT) if limit > 0 else _MAX_LIMIT

    decisions_dir = workspace_root / DECISIONS_DIR
    if not decisions_dir.exists():
        return {"results": [], "total": 0}

    adr_files = sorted(decisions_dir.glob("ADR-*.md"))
    if not adr_files:
        return {"results": [], "total": 0}

    # Need full parse only when searching body text
    needs_body_search = bool(query.strip())
    query_lower = query.strip().lower()
    tag_lower = tag.strip().lower()

    results: list[dict[str, Any]] = []

    for adr_file in adr_files:
        try:
            markdown = adr_file.read_text(encoding="utf-8")

            if needs_body_search:
                adr = parse_adr(markdown)
                meta: dict[str, Any] = {
                    "number": adr.number,
                    "title": adr.title,
                    "status": adr.status,
                    "date": adr.date,
                    "tags": adr.tags,
                    "source_log": adr.source_log,
                }
                body_text = " ".join(adr.sections.values()).lower()
            else:
                meta = parse_adr_metadata(markdown)
                body_text = ""

            # Filter by status
            if status and meta.get("status", "") != status:
                continue

            # Filter by tag (case-insensitive)
            if tag_lower:
                meta_tags_lower = [t.lower() for t in meta.get("tags", [])]
                if tag_lower not in meta_tags_lower:
                    continue

            # Filter by query (case-insensitive substring in title + tags + body)
            if query_lower:
                title_lower = meta.get("title", "").lower()
                tags_text = " ".join(meta.get("tags", [])).lower()
                searchable = f"{title_lower} {tags_text} {body_text}"
                if query_lower not in searchable:
                    continue

            rel_path = str(adr_file.relative_to(workspace_root)).replace("\\", "/")
            results.append(
                {
                    "number": meta.get("number", 0),
                    "title": meta.get("title", ""),
                    "status": meta.get("status", ""),
                    "date": meta.get("date", ""),
                    "tags": meta.get("tags", []),
                    "path": rel_path,
                }
            )
        except (ValueError, OSError):
            continue

    # Sort by number descending
    results.sort(key=lambda r: r.get("number", 0), reverse=True)
    total = len(results)
    results = results[:effective_limit]

    return {"results": results, "total": total}
