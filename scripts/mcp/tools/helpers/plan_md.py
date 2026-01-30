"""Pure functions for parsing and mutating task plan markdown files.

This module handles markdown mechanics only - no file I/O, logging, or MCP logic.
All functions operate on strings and return structured data or modified strings.

Generic markdown-to-JSON parsing:
- Headers create nodes keyed to their value
- Checkboxes become steps with id/text/done
- **Key:** patterns become keyed nodes (arrays if repeated)
- Bulleted lists become arrays
- Phase headers (### Phase N: Title) are collected into a phases array
- Raw text becomes multi-line string values
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- Regex patterns ---

TITLE_PATTERN = re.compile(r"^#\s+(?:Task:\s*)?(.+)$", re.IGNORECASE)
H2_PATTERN = re.compile(r"^##\s+(.+)$")
PHASE_PATTERN = re.compile(r"^###\s+[Pp]hase\s+(\d+)\s*[:\s]\s*(.+)$")
H3_PATTERN = re.compile(r"^###\s+(.+)$")
STEP_PATTERN = re.compile(r"^-\s*\[([ xX])\]\s+(.+)$")
BULLET_PATTERN = re.compile(r"^-\s+(.+)$")
BOLD_KEY_PATTERN = re.compile(r"^\*\*([a-zA-Z0-9_]+):\*\*\s*(.*)$")


# --- Internal dataclasses for mutation support ---


@dataclass
class Step:
    """Mutable step for internal use."""

    text: str
    checked: bool
    line_number: int  # 0-indexed line in original markdown


@dataclass
class Phase:
    """Mutable phase for internal use."""

    number: int
    title: str
    steps: list[Step] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    heading_line: int = 0


@dataclass
class Plan:
    """Mutable plan structure for internal use."""

    title: str | None = None
    sections: dict[str, Any] = field(default_factory=dict)
    phases: list[Phase] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)


# --- Parsing ---


def _add_to_dict(d: dict[str, Any], key: str, value: str) -> None:
    """Add value to dict, converting to array if key exists."""
    if key in d:
        existing = d[key]
        if isinstance(existing, list):
            existing.append(value)
        else:
            d[key] = [existing, value]
    else:
        d[key] = value


def _finalize_content(lines: list[str]) -> str | list[str] | None:
    """Convert accumulated content lines to final value."""
    if not lines:
        return None

    # Check if all lines are bullets
    bullet_items: list[str] | None = []
    for line in lines:
        m = BULLET_PATTERN.match(line)
        if m:
            bullet_items.append(m.group(1).strip())  # type: ignore[union-attr]
        elif line.strip():
            # Non-bullet, non-empty line - treat as raw text
            bullet_items = None
            break

    if bullet_items is not None and bullet_items:
        return bullet_items

    # Raw text - join with newlines, strip extra whitespace
    text = "\n".join(lines).strip()
    return text if text else None


def parse_plan(markdown: str) -> Plan:
    """Parse plan markdown into a mutable Plan structure.

    Generic parsing:
    - # Title → plan.title
    - ## Header → sections["Header"] = content
    - ### Phase N: Title → phases array
    - - [x] / - [ ] → steps
    - **Key:** value → properties dict
    - - bullet → array items
    - raw text → multi-line string

    Args:
        markdown: Raw markdown content

    Returns:
        Parsed Plan structure with line numbers preserved for mutation

    """
    plan = Plan()
    plan.raw_lines = markdown.splitlines(keepends=True)

    current_section: str | None = None
    current_phase: Phase | None = None
    content_buffer: list[str] = []
    target_dict: dict[str, Any] = plan.sections

    def flush_content() -> None:
        """Flush content buffer to current context."""
        nonlocal content_buffer
        if not content_buffer:
            return
        content = _finalize_content(content_buffer)
        if content is not None and current_section:
            # Store in appropriate place
            if current_section == "__phase__" and current_phase:
                # Content after phase heading but before steps - unusual, ignore
                pass
            else:
                plan.sections[current_section] = content
        content_buffer = []

    for line_num, raw_line in enumerate(plan.raw_lines):
        line = raw_line.rstrip()

        # Title: # Task: Name
        title_match = TITLE_PATTERN.match(line)
        if title_match and plan.title is None:
            flush_content()
            plan.title = title_match.group(1).strip()
            current_section = None
            current_phase = None
            continue

        # Phase: ### Phase N: Title
        phase_match = PHASE_PATTERN.match(line)
        if phase_match:
            flush_content()
            phase_num = int(phase_match.group(1))
            phase_title = phase_match.group(2).strip()
            current_phase = Phase(number=phase_num, title=phase_title, heading_line=line_num)
            plan.phases.append(current_phase)
            current_section = "__phase__"
            target_dict = current_phase.properties
            continue

        # H2: ## Section
        h2_match = H2_PATTERN.match(line)
        if h2_match:
            flush_content()
            section_name = h2_match.group(1).strip()
            current_section = section_name
            current_phase = None
            target_dict = plan.sections
            # Skip "Phases" header itself
            if section_name.lower() == "phases":
                current_section = None
            continue

        # H3 (non-phase): ### Subsection - treat as section
        h3_match = H3_PATTERN.match(line)
        if h3_match and not phase_match:
            flush_content()
            section_name = h3_match.group(1).strip()
            current_section = section_name
            current_phase = None
            target_dict = plan.sections
            continue

        # Step: - [x] or - [ ]
        step_match = STEP_PATTERN.match(line)
        if step_match and current_phase is not None:
            flush_content()
            checked = step_match.group(1).lower() == "x"
            text = step_match.group(2).strip()
            current_phase.steps.append(Step(text=text, checked=checked, line_number=line_num))
            continue

        # Bold key: **Key:** value
        bold_match = BOLD_KEY_PATTERN.match(line)
        if bold_match:
            flush_content()
            key = bold_match.group(1)
            value = bold_match.group(2).strip()
            if value:
                _add_to_dict(target_dict, key, value)
            continue

        # Bullet (non-checkbox): - item
        bullet_match = BULLET_PATTERN.match(line)
        if bullet_match and current_phase is None:
            # Accumulate for array conversion
            content_buffer.append(line)
            continue

        # Raw text - accumulate
        if line.strip():
            content_buffer.append(line)

    flush_content()
    return plan


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    """Convert internal Plan to output dict format.

    Args:
        plan: Parsed Plan structure

    Returns:
        Dict ready for JSON serialization

    """
    result: dict[str, Any] = {}

    if plan.title:
        result["title"] = plan.title

    # Add sections (Problem Statement, Completion Criteria, etc.)
    result.update(plan.sections)

    # Build phases array
    if plan.phases:
        phases_out: list[dict[str, Any]] = []
        next_step_id: str | None = None

        for phase in plan.phases:
            phase_dict: dict[str, Any] = {"number": phase.number, "title": phase.title}

            # Steps
            if phase.steps:
                steps_out: list[dict[str, Any]] = []
                for step_idx, step in enumerate(phase.steps, start=1):
                    step_id = f"P{phase.number}-S{step_idx}"
                    step_dict: dict[str, Any] = {"id": step_id, "text": step.text}
                    if step.checked:
                        step_dict["done"] = True
                    elif next_step_id is None:
                        next_step_id = step_id
                    steps_out.append(step_dict)
                phase_dict["steps"] = steps_out

            # Phase properties (Notes, Warning, Blocked, etc.)
            phase_dict.update(phase.properties)

            phases_out.append(phase_dict)

        result["phases"] = phases_out

        if next_step_id:
            result["next"] = next_step_id

    return result


def find_step(plan: Plan, step_id: str) -> tuple[Phase, Step, int, int] | None:
    """Find a step by its ID.

    Args:
        plan: Parsed plan
        step_id: Step ID in P<n>-S<m> format

    Returns:
        Tuple of (phase, step, phase_number, step_index) or None if not found.
        step_index is 1-based to match step_id format.

    """
    match = re.match(r"P(\d+)-S(\d+)", step_id, re.IGNORECASE)
    if not match:
        return None

    phase_num = int(match.group(1))
    step_idx = int(match.group(2))

    # Find phase by number
    phase = None
    for p in plan.phases:
        if p.number == phase_num:
            phase = p
            break

    if phase is None:
        return None

    if step_idx < 1 or step_idx > len(phase.steps):
        return None

    return (phase, phase.steps[step_idx - 1], phase_num, step_idx)


def get_next_step_info(plan: Plan) -> tuple[str | None, str | None, dict[str, str] | None]:
    """Compute next incomplete step.

    Args:
        plan: Parsed plan

    Returns:
        Tuple of (phase_title, next_step_id, next_step_dict)

    """
    for phase in plan.phases:
        for step_idx, step in enumerate(phase.steps, start=1):
            if not step.checked:
                step_id = f"P{phase.number}-S{step_idx}"
                return (phase.title, step_id, {"step_id": step_id, "phase_title": phase.title, "text": step.text})
    return (None, None, None)


def mark_step_complete(plan: Plan, step_id: str, annotation: tuple[str, str] | None = None) -> tuple[str, bool, bool]:
    """Mark a step as complete and optionally add an annotation.

    Mutates plan.raw_lines in place.

    Args:
        plan: Parsed plan (will be mutated)
        step_id: Step ID to mark complete
        annotation: Optional (marker, text) tuple to attach directly under the step

    Returns:
        Tuple of (updated_markdown, was_already_complete, annotation_written)

    Raises:
        ValueError: If step_id is not found

    """
    result = find_step(plan, step_id)
    if result is None:
        msg = f"Step {step_id} not found"
        raise ValueError(msg)

    _phase, step, _phase_num, _step_idx = result

    was_already_complete = step.checked

    if not was_already_complete:
        # Update the checkbox in raw_lines
        line = plan.raw_lines[step.line_number]
        updated_line = re.sub(r"\[\s\]", "[x]", line, count=1)
        plan.raw_lines[step.line_number] = updated_line
        step.checked = True

    # Add annotation if provided - attach directly to the step, not phase
    annotation_written = False
    if annotation:
        marker, text = annotation
        annotation_written = _add_annotation_to_step(plan, step, marker, text)

    return "".join(plan.raw_lines), was_already_complete, annotation_written


def _add_annotation_to_step(plan: Plan, step: Step, marker: str, text: str) -> bool:
    """Add an annotation directly under a step's checkbox line.

    Mutates plan.raw_lines in place.

    Format:
        - [x] Step text
            **Marker:** annotation text

    If the same marker block already exists under the step (anywhere in the
    indented block), appends to it. Returns False if identical annotation
    already present (idempotent).

    Args:
        plan: Parsed plan (will be mutated)
        step: The step to attach the annotation to
        marker: Annotation marker (e.g., "Notes", "Warning", "Blocked")
        text: Annotation text (must be non-empty)

    Returns:
        True if annotation was added, False if already present (duplicate)

    """
    step_line_idx = step.line_number
    next_line_idx = step_line_idx + 1
    marker_prefix = f"**{marker}:**"

    # Find the extent of the indented block under this step
    # (all contiguous lines that are indented and not a new checkbox)
    block_end_idx = step_line_idx
    for i in range(next_line_idx, len(plan.raw_lines)):
        line = plan.raw_lines[i]
        # Indented continuation (at least 2 spaces) and not a new checkbox bullet
        if line.startswith("  ") and not line.strip().startswith("- ["):
            block_end_idx = i
        else:
            break

    # Scan the block for an existing marker of the same type
    existing_marker_line_idx: int | None = None
    existing_marker_end_idx: int | None = None

    for i in range(next_line_idx, block_end_idx + 1):
        line = plan.raw_lines[i]
        stripped = line.strip()
        if stripped.startswith(marker_prefix):
            existing_marker_line_idx = i
            existing_marker_end_idx = i
            # Find end of this specific marker's block (deeper indented continuations)
            for j in range(i + 1, block_end_idx + 1):
                cont_line = plan.raw_lines[j]
                # Continuation if more indented than the marker line and not a new marker
                if cont_line.startswith("      ") and not cont_line.strip().startswith("**"):
                    existing_marker_end_idx = j
                else:
                    break
            break

    # Build the exact line we would insert for idempotency comparison
    # (either as first line of marker block or as continuation)
    if existing_marker_line_idx is not None:
        # Check if this exact text already exists (exact line match)
        expected_continuation = f"      {text}"
        expected_inline = f"{marker_prefix} {text}"
        for i in range(existing_marker_line_idx, (existing_marker_end_idx or existing_marker_line_idx) + 1):
            line_stripped = plan.raw_lines[i].rstrip()
            is_exact_text = line_stripped.strip() == text
            is_inline_match = line_stripped.endswith(expected_inline)
            is_continuation_match = line_stripped == expected_continuation
            if is_exact_text or is_inline_match or is_continuation_match:
                return False  # Already present, no-op

        # Append text as continuation line under existing marker block
        insert_idx = (existing_marker_end_idx or existing_marker_line_idx) + 1
        annotation_line = f"      {text}\n"
        plan.raw_lines.insert(insert_idx, annotation_line)
    else:
        # Create new indented annotation block at the start of the step's indented area
        annotation_line = f"    {marker_prefix} {text}\n"
        plan.raw_lines.insert(next_line_idx, annotation_line)

    return True


def get_phase_notes(plan: Plan, phase_title: str) -> str | list[str] | None:
    """Get notes for a specific phase by title.

    Args:
        plan: Parsed plan
        phase_title: Title of the phase

    Returns:
        Notes value or None if phase not found or has no notes

    """
    for phase in plan.phases:
        if phase.title.lower() == phase_title.lower():
            return phase.properties.get("Notes")
    return None
