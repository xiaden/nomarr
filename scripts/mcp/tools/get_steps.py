"""MCP tool: Get steps for a specific phase of a task plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.mcp.tools.helpers.plan_md import parse_plan, plan_to_dict

PLANS_DIR = "docs/dev/plans"


def _normalize_plan_name(plan_name: str) -> str:
    """Normalize plan name, stripping .md if present."""
    if plan_name.endswith(".md"):
        return plan_name[:-3]
    return plan_name


def _validate_plan_name(plan_name: str) -> str | None:
    """Validate plan name. Returns error message or None if valid."""
    if "/" in plan_name or "\\" in plan_name or ".." in plan_name:
        return f"Invalid plan_name '{plan_name}': path separators and traversal not allowed"
    return None


def _resolve_plan_path(plan_name: str, workspace_root: Path) -> Path:
    """Resolve plan name to full path."""
    normalized = _normalize_plan_name(plan_name)
    return workspace_root / PLANS_DIR / f"{normalized}.md"


def get_steps(plan_name: str, workspace_root: Path, phase_name: str | None = None) -> dict[str, Any]:
    """Get steps for a specific phase of a task plan.

    Returns a focused view for a single phase. Useful when you know
    which phase you're working on and don't need the full plan.

    Output principle: Omit defaults and derivable data.
    - done: only present if true
    - notes/warnings: only present if non-empty
    - next: just the step ID

    Args:
        plan_name: Plan name (with or without .md extension).
        workspace_root: Workspace root path (injected by MCP server).
        phase_name: Phase to retrieve. If None, uses the active phase
                    (first phase with incomplete steps).

    Returns:
        Focused phase data: phase name, steps, optional notes/warnings, optional next step.

    """
    # Validate plan name
    error = _validate_plan_name(plan_name)
    if error:
        return {"error": "invalid_plan_name", "message": error}

    # Resolve path
    plan_path = _resolve_plan_path(plan_name, workspace_root)

    # Check file exists
    if not plan_path.exists():
        return {
            "error": "plan_not_found",
            "message": f"Plan not found: {plan_name}",
            "expected_path": str(plan_path.relative_to(workspace_root)),
        }

    # Parse plan and convert to dict (single source of truth)
    markdown = plan_path.read_text(encoding="utf-8")
    plan = parse_plan(markdown)
    plan_dict = plan_to_dict(plan)

    # Check if plan has phases/steps
    if not plan_dict.get("phases"):
        return {
            "error": "not_a_task_plan",
            "message": "This file has no phases or steps. Use read_plan for unstructured plans.",
        }

    # Determine which phase to show
    # If no phase specified, find active phase (first with incomplete step)
    target_phase_title = phase_name  # param name kept for API compatibility
    if not target_phase_title:
        for phase in plan_dict["phases"]:
            for step in phase.get("steps", []):
                if not step.get("done"):
                    target_phase_title = phase["title"]
                    break
            if target_phase_title:
                break

    # If still no target (all complete), default to first phase
    if target_phase_title is None:
        first_phase = plan_dict["phases"][0]
        result: dict[str, Any] = {
            "title": first_phase["title"],
            "steps": first_phase.get("steps", []),
            "complete": True,
        }
        result.update({k: v for k, v in first_phase.items() if k not in ("number", "title", "steps") and v})
        return result

    # Find the target phase
    target_phase: dict[str, Any] | None = None
    for phase in plan_dict["phases"]:
        if phase["title"].lower() == target_phase_title.lower():
            target_phase = phase
            break

    if target_phase is None:
        return {
            "error": "phase_not_found",
            "message": f"Phase '{target_phase_title}' not found",
            "available_phases": [p["title"] for p in plan_dict["phases"]],
        }

    # Build output from the dict
    result = {"title": target_phase["title"], "steps": target_phase.get("steps", [])}

    # Include all phase properties (Notes, Warning, Blocked, etc.)
    for key, value in target_phase.items():
        if key not in ("number", "title", "steps") and value:
            result[key] = value

    # Include next step if there is one
    next_info = plan_dict.get("next")
    if next_info:
        result["next"] = next_info

    return result
