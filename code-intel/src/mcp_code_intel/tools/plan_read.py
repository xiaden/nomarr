"""MCP tool: Read a task plan and return structured JSON summary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..helpers.plan_md import parse_plan, plan_to_dict

PLANS_DIR = "plans"


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


def plan_read(plan_name: str, workspace_root: Path) -> dict[str, Any]:
    """Read a task plan and return structured JSON summary.

    Parses the entire plan markdown into a structured representation.
    Does not return raw markdown - only structured JSON for context efficiency.

    Output principle: Omit defaults and derivable data.
    - checked/done: only present if true
    - notes/warnings: only present if non-empty
    - active_phase/next: only present if progress has been made

    Args:
        plan_name: Plan name (with or without .md extension).
                   Must not contain path separators or traversal.
        workspace_root: Workspace root path (injected by MCP server).

    Returns:
        Structured plan data with phases and steps.

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

    # Parse and convert
    try:
        markdown = plan_path.read_text(encoding="utf-8")
        plan = parse_plan(markdown)
        return plan_to_dict(plan)
    except Exception as e:
        return {"error": "parse_error", "message": f"Failed to parse plan: {e}"}
