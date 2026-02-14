"""MCP tool: Mark a step as complete in a task plan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..helpers.plan_md import find_step, mark_step_complete, parse_plan, plan_to_dict

PLANS_DIR = "plans"


@dataclass
class _ResponseContext:
    """Context for building the complete_step response."""

    step_id: str
    was_already_complete: bool
    annotation_written: bool
    annotation: dict[str, str] | None
    updated_dict: dict[str, Any]
    prev_active_phase: str | None


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


# Regex for validating annotation marker (single alphanumeric word)
_MARKER_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


def _validate_annotation(annotation: dict[str, str]) -> dict[str, str] | None:
    """Validate annotation dict. Returns error dict or None if valid."""
    marker = annotation.get("marker", "")
    ann_text = annotation.get("text", "")
    if not marker or not _MARKER_PATTERN.match(marker):
        return {
            "error": "invalid_annotation_marker",
            "message": (
                f"Marker '{marker}' must be a single alphanumeric word (pattern: [A-Za-z0-9]+)"
            ),
        }
    if not ann_text or not ann_text.strip():
        return {"error": "empty_annotation_text", "message": "Annotation text cannot be empty"}
    # Reject step-like syntax that would confuse the parser on re-read
    if "- [" in ann_text:
        return {
            "error": "invalid_annotation_text",
            "message": "Annotation text cannot contain checkbox syntax ('- [')",
        }
    return None


def _build_response(ctx: _ResponseContext) -> dict[str, Any]:
    """Build the response dict for complete_step."""
    result: dict[str, Any] = {"step_id": ctx.step_id}

    if ctx.was_already_complete:
        result["already_marked"] = True

    if ctx.annotation_written and ctx.annotation:
        result["applied_annotation"] = {
            "marker": ctx.annotation["marker"],
            "text": ctx.annotation["text"],
        }

    new_next = ctx.updated_dict.get("next")
    if new_next:
        # Include full step details
        next_step_details = _find_step_in_dict(ctx.updated_dict, new_next)
        if next_step_details:
            phase_props = _get_phase_properties(ctx.updated_dict, new_next)
            new_phase = _get_phase_for_step(ctx.updated_dict, new_next)
            is_phase_transition = new_phase and new_phase != ctx.prev_active_phase

            # Step-level markers: always include (TODO: when we have step markers)
            # Phase-level Warning: always include (reinforcement, not noise)
            # Phase-level Notes/Blocked/other: only on phase transition (one-time context)
            if phase_props:
                markers = {}
                for key, value in phase_props.items():
                    if key == "Warning":
                        # Always include warnings - they're behavioral guidance
                        markers[key] = value
                    elif is_phase_transition:
                        # Other markers only on phase entry
                        markers[key] = value
                if markers:
                    next_step_details["phase_markers"] = markers

            result["next_step"] = next_step_details
        else:
            result["next_step"] = {"id": new_next}
    else:
        result["next_step"] = None

    # Phase transition detection
    new_active_phase = _get_phase_for_step(ctx.updated_dict, new_next) if new_next else None
    if ctx.prev_active_phase and new_active_phase and ctx.prev_active_phase != new_active_phase:
        result["phase_transition"] = {"from": ctx.prev_active_phase, "to": new_active_phase}

    return result


def plan_complete_step(
    plan_name: str,
    step_id: str,
    workspace_root: Path,
    annotation: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Mark a step as complete in a task plan.

    Idempotent: if the step is already complete, returns current state without error.
    Optionally adds an annotation directly under the completed step as an indented block.

    Annotation format:
        - [x] Step text
            **Marker:** annotation text

    If the step already has a block with the same marker, appends to it.
    Duplicate annotations are ignored (idempotent).

    Args:
        plan_name: Plan name (with or without .md extension).
        step_id: Step ID in P<n>-S<m> format (e.g., "P1-S3").
        workspace_root: Workspace root path (injected by MCP server).
        annotation: Optional (marker, text) dict. Marker must be a single
            alphanumeric word (e.g., "Notes", "Warning", "Blocked").

    Returns:
        Response with step_id, next_step, and optional fields:
        - already_marked: True if step was already complete
        - applied_annotation: {marker, text} if annotation was written
        - phase_transition: {from, to} if completing this step advances phase

    """
    # Validate plan name
    error = _validate_plan_name(plan_name)
    if error:
        return {"error": "invalid_plan_name", "message": error}

    # Validate annotation if provided
    if annotation is not None:
        ann_error = _validate_annotation(annotation)
        if ann_error:
            return ann_error

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
    markdown = plan_path.read_bytes().decode("utf-8")
    plan = parse_plan(markdown)
    plan_dict = plan_to_dict(plan)

    # Check if plan has phases/steps
    if not plan_dict.get("phases"):
        return {
            "error": "not_a_task_plan",
            "message": "This file has no phases or steps. Use read_plan for unstructured plans.",
        }

    # Capture state before modification
    prev_next = plan_dict.get("next")
    prev_active_phase = _get_phase_for_step(plan_dict, prev_next) if prev_next else None

    # Find the step to complete
    step_result = find_step(plan, step_id)
    if step_result is None:
        return {"error": "unknown_step_id", "message": f"Step '{step_id}' not found in plan"}

    _phase, _step, _phase_idx, _step_idx = step_result

    # Mark complete and optionally add annotation
    updated_markdown, was_already_complete, annotation_written = mark_step_complete(
        plan, step_id, annotation
    )

    # Write back if step was marked complete or annotation was written
    if not was_already_complete or annotation_written:
        plan_path.write_bytes(updated_markdown.encode("utf-8"))

    # Re-parse updated file and convert to dict (single source of truth for response)
    updated_markdown = plan_path.read_bytes().decode("utf-8")
    updated_plan = parse_plan(updated_markdown)
    updated_dict = plan_to_dict(updated_plan)

    return _build_response(
        _ResponseContext(
            step_id=step_id,
            was_already_complete=was_already_complete,
            annotation_written=annotation_written,
            annotation=annotation,
            updated_dict=updated_dict,
            prev_active_phase=prev_active_phase,
        ),
    )


def _get_phase_for_step(plan_dict: dict[str, Any], step_id: str | None) -> str | None:
    """Get phase title for a step ID from plan dict."""
    if not step_id:
        return None
    for phase in plan_dict.get("phases", []):
        for step in phase.get("steps", []):
            if step.get("id", "").upper() == step_id.upper():
                return str(phase.get("title"))
    return None


def _find_step_in_dict(plan_dict: dict[str, Any], step_id: str) -> dict[str, Any] | None:
    """Find step details by ID from plan dict."""
    for phase in plan_dict.get("phases", []):
        for step in phase.get("steps", []):
            if step.get("id", "").upper() == step_id.upper():
                return dict(step)
    return None


def _get_phase_properties(plan_dict: dict[str, Any], step_id: str) -> dict[str, Any]:
    """Get phase properties for the phase containing a step."""
    for phase in plan_dict.get("phases", []):
        for step in phase.get("steps", []):
            if step.get("id", "").upper() == step_id.upper():
                # Return all properties except structural keys
                return {k: v for k, v in phase.items() if k not in ("number", "title", "steps")}
    return {}
