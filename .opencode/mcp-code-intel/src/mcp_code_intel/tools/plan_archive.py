"""Tool implementation for plan_archive — archive a completed task plan."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..helpers.plan_md import parse_plan

PLANS_PENDING_DIR = "artifacts/plans/pending"
PLANS_COMPLETED_DIR = "artifacts/plans/completed"


def plan_archive(
    plan_name: str,
    ignore_blocked: bool = False,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Archive a completed task plan from pending to completed.

    Verifies all steps are checked. Warns on blocked annotations unless overridden.
    Returns {"archived": True, "path": "...", "steps_completed": N} on success.
    Returns {"error": "...", "message": "..."} on failure.
    """
    if not plan_name.strip():
        return {"error": "invalid_name", "message": "Plan name cannot be empty"}

    # Reject path traversal
    if "/" in plan_name or "\\" in plan_name or ".." in plan_name:
        return {
            "error": "invalid_name",
            "message": "Plan name must not contain path separators",
        }

    # Normalize name
    if plan_name.endswith(".md"):
        plan_name = plan_name[:-3]
    filename = f"{plan_name}.md"

    source = workspace_root / PLANS_PENDING_DIR / filename
    if not source.exists():
        return {
            "error": "not_found",
            "message": f"Plan not found in pending: {filename}",
        }

    # Parse and validate
    try:
        markdown = source.read_text(encoding="utf-8")
        plan = parse_plan(markdown)
    except (ValueError, OSError) as exc:
        return {"error": "parse_error", "message": str(exc)}

    # Check all steps complete
    incomplete: list[str] = []
    blocked: list[str] = []
    total_steps = 0

    for phase_idx, phase in enumerate(plan.phases, 1):
        for step_idx, step in enumerate(phase.steps, 1):
            total_steps += 1
            step_id = f"P{phase_idx}-S{step_idx}"
            if not step.checked:
                incomplete.append(step_id)
            # Check for blocked annotations
            blocked_val = step.properties.get("Blocked")
            if blocked_val:
                blocked.append(step_id)

    if incomplete:
        return {
            "error": "incomplete_steps",
            "message": (f"Cannot archive: {len(incomplete)} steps not complete"),
            "incomplete_steps": incomplete,
        }

    if blocked and not ignore_blocked:
        return {
            "error": "blocked_steps",
            "message": (
                f"{len(blocked)} steps have Blocked annotations. "
                "Verify blockers are resolved and retry with ignore_blocked=True."
            ),
            "blocked_steps": blocked,
        }

    # Move to completed
    dest_dir = workspace_root / PLANS_COMPLETED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    shutil.move(str(source), str(dest))

    rel_path = f"{PLANS_COMPLETED_DIR}/{filename}"
    return {
        "archived": True,
        "path": rel_path,
        "steps_completed": total_steps,
    }
