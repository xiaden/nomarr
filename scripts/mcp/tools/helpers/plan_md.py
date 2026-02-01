"""Pure functions for parsing and mutating task plan markdown files.

This module handles markdown mechanics only - no file I/O, logging, or MCP logic.
All functions operate on strings and return structured data or modified strings.

Generic markdown-to-JSON parsing:
- Headers create nodes keyed to their value
- Checkboxes become steps with id/text/done (nested checkboxes become children)
- **Key:** patterns become keyed nodes (arrays if repeated)
- Bulleted lists become arrays
- Phase headers (### Phase N: Title) are collected into a phases array
- Raw text becomes multi-line string values

Uses tree-sitter-markdown for proper nested list parsing when available.
Falls back to indentation-based depth calculation if tree-sitter is not installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

try:
    from tree_sitter import Language, Parser
    from tree_sitter_markdown import language as md_language

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

# --- Regex patterns ---

TITLE_PATTERN = re.compile(r"^#\s+(?:Task:\s*)?(.+)$", re.IGNORECASE)
H2_PATTERN = re.compile(r"^##\s+(.+)$")
PHASE_PATTERN = re.compile(r"^###\s+[Pp]hase\s+(\d+)\s*[:\s]\s*(.+)$")
H3_PATTERN = re.compile(r"^###\s+(.+)$")
STEP_PATTERN = re.compile(r"^\s*-\s*\[([ xX])\]\s+(.+)$")  # Allow leading whitespace
BULLET_PATTERN = re.compile(r"^-\s+(.+)$")
BOLD_KEY_PATTERN = re.compile(r"^\*\*([a-zA-Z0-9_]+):\*\*\s*(.*)$")


# --- Internal dataclasses for mutation support ---


@dataclass
class Step:
    """Mutable step for internal use."""

    text: str
    checked: bool
    line_number: int  # 0-indexed line in original markdown
    depth: int = 0  # Nesting depth (0 = top-level, 1 = first indent, etc.)
    children: list[Step] = field(default_factory=list)  # Nested sub-steps
    properties: dict[str, Any] = field(default_factory=dict)  # **Notes:**, **Blocked:**, etc.


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


def _parse_steps_with_tree_sitter(phase_heading_line: int, raw_lines: list[str]) -> list[Step]:
    """Parse steps for a phase using tree-sitter for proper nested list handling.

    Args:
        phase_heading_line: 0-indexed line where phase heading starts
        raw_lines: All markdown lines

    Returns:
        List of Steps with proper parent-child relationships
    """
    if not HAS_TREE_SITTER:
        return []

    # Extract phase content (from heading to next heading or end)
    phase_end = len(raw_lines)
    for i in range(phase_heading_line + 1, len(raw_lines)):
        if raw_lines[i].strip().startswith("###"):
            phase_end = i
            break

    phase_markdown = "".join(raw_lines[phase_heading_line:phase_end])

    parser = Parser(Language(md_language()))
    tree = parser.parse(bytes(phase_markdown, "utf8"))

    steps: list[Step] = []

    def extract_checkbox_from_item(node, parent_step: Step | None = None) -> Step | None:
        """Recursively extract checkbox from list_item node."""
        # Find task list marker and paragraph content
        has_checkbox = False
        is_checked = False
        text_content = ""

        for child in node.children:
            if child.type == "task_list_marker":
                has_checkbox = True
                marker_text = phase_markdown[child.start_byte : child.end_byte]
                is_checked = "x" in marker_text.lower()
            elif child.type == "paragraph":
                # Extract text from paragraph
                para_text = phase_markdown[child.start_byte : child.end_byte].strip()
                # Remove checkbox marker if present
                para_text = re.sub(r"^\[([ xX])\]\s*", "", para_text)
                text_content = para_text

        if not has_checkbox:
            return None

        # Calculate absolute line number
        line_num = phase_heading_line + node.start_point[0]

        step = Step(text=text_content, checked=is_checked, line_number=line_num, depth=0)

        # Look for nested list as child
        for child in node.children:
            if child.type == "list":
                # Process nested items
                for nested_item in child.children:
                    if nested_item.type == "list_item":
                        nested_step = extract_checkbox_from_item(nested_item, step)
                        if nested_step:
                            step.children.append(nested_step)

        return step

    def walk_node(node):
        """Walk AST looking for top-level list items."""
        if node.type == "list":
            for child in node.children:
                if child.type == "list_item":
                    step = extract_checkbox_from_item(child)
                    if step:
                        steps.append(step)

        for child in node.children:
            walk_node(child)

    walk_node(tree.root_node)
    return steps


def parse_plan(markdown: str) -> Plan:
    """Parse plan markdown into a mutable Plan structure.

    Generic parsing:
    - # Title → plan.title
    - ## Header → sections["Header"] = content
    - ### Phase N: Title → phases array
    - - [x] / - [ ] → steps (with nested children if tree-sitter available)
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

        # Step: - [x] or - [ ] (now matches indented)
        step_match = STEP_PATTERN.match(line)
        if step_match and current_phase is not None:
            flush_content()
            checked = step_match.group(1).lower() == "x"
            text = step_match.group(2).strip()
            # Calculate depth from leading whitespace
            depth = (len(line) - len(line.lstrip())) // 2  # Assume 2-space indents
            current_phase.steps.append(Step(text=text, checked=checked, line_number=line_num, depth=depth))
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

    # Post-process: Validate no nested steps exist
    for phase in plan.phases:
        for step in phase.steps:
            if step.depth > 0:
                raise ValueError(
                    f"Plan contains nested steps, which are not allowed per PLAN_SCHEMA.json.\n"
                    f"Found indented step at line {step.line_number + 1}: '{step.text}'\n"
                    f"Phase {phase.number}: {phase.title}\n\n"
                    f"Nested steps create ambiguous execution models:\n"
                    f"  - If substeps are distinct outcomes → unnest them as separate steps\n"
                    f"  - If substeps are implementation details → convert to **Notes:** annotations\n"
                    f"  - If substeps need grouping → they belong in a separate phase\n\n"
                    f"Please flatten the plan structure and try again."
                )

        # Capture annotations under each step
        _capture_step_annotations(phase.steps, plan.raw_lines)

    return plan


def _capture_step_annotations(steps: list[Step], raw_lines: list[str]) -> None:
    """Capture annotation properties under each step from raw markdown.

    Mutates steps in place to add properties like Notes, Blocked, Warning, etc.

    Format expected:
        - [x] Step text
            **Notes:** annotation text
            **Blocked:** reason text

    Args:
        steps: List of steps (with nested children) to annotate
        raw_lines: Raw markdown lines
    """

    def process_step(step: Step) -> None:
        """Process one step and its children recursively."""
        step_line_idx = step.line_number

        # Find the extent of indented content under this step
        # (until we hit a line that's not more indented than the step itself)
        step_indent = len(raw_lines[step_line_idx]) - len(raw_lines[step_line_idx].lstrip())

        # Scan lines after the step
        for i in range(step_line_idx + 1, len(raw_lines)):
            line = raw_lines[i]
            if not line.strip():
                continue  # Skip blank lines

            line_indent = len(line) - len(line.lstrip())

            # If this line is not more indented, we've left this step's block
            if line_indent <= step_indent:
                break

            # Check if it's a nested checkbox (child step) - skip those
            if STEP_PATTERN.match(line):
                break

            # Check for bold key pattern: **Key:** value
            bold_match = BOLD_KEY_PATTERN.match(line.strip())
            if bold_match:
                key = bold_match.group(1)
                value = bold_match.group(2).strip()

                # Collect continuation lines (more deeply indented)
                continuation_lines = [value] if value else []
                for j in range(i + 1, len(raw_lines)):
                    cont_line = raw_lines[j]
                    if not cont_line.strip():
                        continue
                    cont_indent = len(cont_line) - len(cont_line.lstrip())
                    # Continuation must be more indented than the marker line
                    # and not start with a new marker
                    if cont_indent > line_indent and not cont_line.strip().startswith("**"):
                        continuation_lines.append(cont_line.strip())
                    else:
                        break

                # Store in properties
                full_value = " ".join(continuation_lines).strip()
                if full_value:
                    _add_to_dict(step.properties, key, full_value)

        # Process children recursively
        for child in step.children:
            process_step(child)

    for step in steps:
        process_step(step)


def _build_step_tree(flat_steps: list[Step]) -> list[Step]:
    """Convert flat steps with depth info into nested tree structure.

    Args:
        flat_steps: List of steps with depth attribute

    Returns:
        List of top-level steps with children properly nested
    """
    if not flat_steps:
        return []

    root_steps: list[Step] = []
    stack: list[tuple[int, Step]] = []  # (depth, step)

    for step in flat_steps:
        # Pop stack until we find the parent level
        while stack and stack[-1][0] >= step.depth:
            stack.pop()

        if not stack:
            # Top-level step
            root_steps.append(step)
        else:
            # Child of the last step in stack
            parent = stack[-1][1]
            parent.children.append(step)

        stack.append((step.depth, step))

    return root_steps


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

            # Steps (flat list only - nesting is rejected during parsing)
            if phase.steps:
                steps_out: list[dict[str, Any]] = []
                for step_idx, step in enumerate(phase.steps, start=1):
                    step_id = f"P{phase.number}-S{step_idx}"
                    step_dict: dict[str, Any] = {"id": step_id, "text": step.text}
                    if step.checked:
                        step_dict["done"] = True
                    # Add step annotations (Notes, Blocked, Warning, etc.)
                    step_dict.update(step.properties)

                    if not step.checked and next_step_id is None:
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


def mark_step_complete(plan: Plan, step_id: str, annotation: dict[str, str] | None = None) -> tuple[str, bool, bool]:
    """Mark a step as complete and optionally add an annotation.

    Mutates plan.raw_lines in place.

    Args:
        plan: Parsed plan (will be mutated)
        step_id: Step ID to mark complete
        annotation: Optional {marker, text} dict to attach directly under the step

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
        marker = annotation["marker"]
        text = annotation["text"]
        annotation_written = _add_annotation_to_step(plan, step, marker, text)

    # Re-parse from raw_lines to capture any annotations in structure
    updated_markdown = "".join(plan.raw_lines)
    reparsed = parse_plan(updated_markdown)
    # Update plan in place with reparsed structure
    plan.phases = reparsed.phases
    plan.sections = reparsed.sections

    return updated_markdown, was_already_complete, annotation_written


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
