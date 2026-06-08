"""Tool implementation for dd_archive — archive a completed design document."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ..helpers.dd_md import (
    DD_PREFIX,
    DESIGNS_COMPLETED_DIR,
    DESIGNS_PENDING_DIR,
    parse_dd,
)

PLANS_PENDING_DIR = "artifacts/plans/pending"


def dd_archive(
    name: str,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Archive a design document from pending to completed.

    Verifies all convention-linked plans are completed first.
    Updates status to Completed before moving.
    Returns {"archived": True, "path": "...", "linked_plans_completed": [...]} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    if not name.strip():
        return {"error": "invalid_name", "message": "Name cannot be empty"}

    # Reject path traversal
    if "/" in name or "\\" in name or ".." in name:
        return {
            "error": "invalid_name",
            "message": "Name must not contain path separators",
        }

    # Normalize name
    if name.endswith(".md"):
        name = name[:-3]
    if not name.startswith(DD_PREFIX):
        name = f"{DD_PREFIX}{name}"
    filename = f"{name}.md"

    source = workspace_root / DESIGNS_PENDING_DIR / filename
    if not source.exists():
        return {
            "error": "not_found",
            "message": f"Design document not found in pending: {filename}",
        }

    # Validate DD is parseable
    try:
        markdown = source.read_text(encoding="utf-8")
        parse_dd(markdown)
    except (ValueError, OSError) as exc:
        return {"error": "parse_error", "message": str(exc)}

    # Extract slug from filename: DD-{slug}.md
    slug = name.removeprefix(DD_PREFIX)

    # Check for linked plans still in pending
    pending_dir = workspace_root / PLANS_PENDING_DIR
    pending_plans: list[str] = []
    completed_plans: list[str] = []

    if pending_dir.exists():
        pattern = f"TASK-{slug}-*.md"
        for plan_file in pending_dir.glob(pattern):
            pending_plans.append(plan_file.name)

    if pending_plans:
        return {
            "error": "pending_plans",
            "message": (f"Cannot archive: {len(pending_plans)} linked plans still in pending"),
            "pending_plans": pending_plans,
        }

    # Check completed plans (for the report)
    completed_dir = workspace_root / "artifacts/plans/completed"
    if completed_dir.exists():
        pattern = f"TASK-{slug}-*.md"
        for plan_file in completed_dir.glob(pattern):
            completed_plans.append(plan_file.name)

    # Also check parts directory for plan names
    parts_readme = workspace_root / f"artifacts/designs/parts/{slug}/README.md"
    if parts_readme.exists():
        try:
            readme_text = parts_readme.read_text(encoding="utf-8")
            # Find TASK references
            task_refs = re.findall(r"TASK-[\w-]+", readme_text)
            for ref in task_refs:
                ref_file = f"{ref}.md"
                if (pending_dir / ref_file).exists():
                    if ref_file not in pending_plans:
                        pending_plans.append(ref_file)
        except OSError:
            pass

    if pending_plans:
        return {
            "error": "pending_plans",
            "message": (
                f"Cannot archive: {len(pending_plans)} linked plans "
                "still in pending (found via parts README)"
            ),
            "pending_plans": pending_plans,
        }

    # Update status to Completed in the markdown
    updated_markdown = re.sub(
        r"^\*\*Status:\*\*\s+\S+",
        "**Status:** Completed",
        markdown,
        count=1,
        flags=re.MULTILINE,
    )

    # Write updated content, then move
    source.write_text(updated_markdown, encoding="utf-8")

    dest_dir = workspace_root / DESIGNS_COMPLETED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    shutil.move(str(source), str(dest))

    rel_path = f"{DESIGNS_COMPLETED_DIR}/{filename}"
    return {
        "archived": True,
        "path": rel_path,
        "linked_plans_completed": completed_plans,
    }
