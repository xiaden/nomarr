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

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from jsonschema import ValidationError, validate
except ImportError:
    raise ImportError(
        "jsonschema is required for plan validation. Install with: pip install jsonschema"
    )

try:
    from tree_sitter import Language, Parser
    from tree_sitter_markdown import language as md_language

    HAS_TREE_SITTER = True
except ImportError:
    raise ImportError(
        "tree-sitter-markdown is required for plan parsing. "
        "Install with: pip install tree-sitter tree-sitter-markdown"
    )

# --- Regex patterns ---

TITLE_PATTERN = re.compile(r"^#\s+(?:Task:\s*)?(.+)$", re.IGNORECASE)
H2_PATTERN = re.compile(r"^##\s+(.+)$")
PHASE_PATTERN = re.compile(r"^###\s+[Pp]hase\s+(\d+)\s*[:\s]\s*(.+)$")
H3_PATTERN = re.compile(r"^###\s+(.+)$")
# Valid step: exactly "- [ ] text" or "- [x] text"
# (one space before [, one space/x/X inside, space after])
STEP_PATTERN = re.compile(r"^(\s*)-\s\[([ xX])\]\s+(.+)$")
BULLET_PATTERN = re.compile(r"^-\s+(.+)$")
BOLD_KEY_PATTERN = re.compile(r"^\*\*([a-zA-Z0-9_]+):\*\*\s*(.*)$")

# Patterns for malformed step-like items (should fail validation)
# These catch things that look like they're trying to be steps but don't match the exact grammar
MALFORMED_CHECKBOX_PATTERN = re.compile(
    r"^\s*-\s*\[[ xX]?\](?!\s+).+"  # Checkbox without space after ] (e.g., "- [ ]No space")
    r"|^\s*-\s*\[\]"  # Empty checkbox brackets (e.g., "- []")
    r"|^\s*-\[[ xX]?\]\s"  # No space before [ (e.g., "-[ ] text")
    r"|^\s*-\s\[[ xX]\s\]\s"  # Extra space inside (e.g., "- [x ] text")
    r"|^\s*-\s\[\s{2,}\]\s",  # Multiple spaces inside (e.g., "- [  ] text")
)
NUMBERED_LIST_PATTERN = re.compile(r"^\s*\d+[.)]\s+.+$")  # 1. Item or 1) Item
# Bare bullet that could be mistaken for a step (at step indentation level)
# Catches all markdown bullet markers: -, *, +
BARE_BULLET_AT_STEP_LEVEL = re.compile(r"^[-*+]\s+(?!\[).+$")  # "- text", "* text", "+ text"
# Checkbox with wrong bullet marker (* or + instead of -)
WRONG_BULLET_CHECKBOX = re.compile(r"^[*+]\s*\[[ xX]?\]\s+.+$")  # "* [ ] text", "+ [x] text"


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


def _add_to_dict(d: dict[str, Any], key: str, value: str | list[str]) -> None:
    """Add value to dict, converting to array if key exists."""
    if key in d:
        existing = d[key]
        if isinstance(existing, list):
            if isinstance(value, list):
                existing.extend(value)
            else:
                existing.append(value)
        else:
            if isinstance(value, list):
                d[key] = [existing] + value
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

    def extract_checkbox_from_item(node, depth: int = 0) -> Step | None:
        """Recursively extract checkbox from list_item node."""
        # Find task list marker and paragraph content
        has_checkbox = False
        is_checked = False
        text_content = ""

        for child in node.children:
            # Tree-sitter markdown uses specific marker types
            if child.type in ("task_list_marker_checked", "task_list_marker_unchecked"):
                has_checkbox = True
                is_checked = child.type == "task_list_marker_checked"
            elif child.type == "paragraph":
                # Extract text from paragraph's inline content (first line only)
                # Indented continuation is handled by _capture_step_annotations
                for para_child in child.children:
                    if para_child.type == "inline":
                        inline_text = phase_markdown[
                            para_child.start_byte : para_child.end_byte
                        ].strip()
                        # Only take first line - rest is annotations
                        text_content = inline_text.split("\n")[0].strip()
                        break

        if not has_checkbox:
            return None

        # Calculate absolute line number
        line_num = phase_heading_line + node.start_point[0]

        step = Step(text=text_content, checked=is_checked, line_number=line_num, depth=depth)

        # Look for nested list as child - add nested items to flat steps list with depth+1
        for child in node.children:
            if child.type == "list":
                # Process nested items
                for nested_item in child.children:
                    if nested_item.type == "list_item":
                        nested_step = extract_checkbox_from_item(nested_item, depth + 1)
                        if nested_step:
                            steps.append(nested_step)

        return step

    def walk_node(node) -> None:
        """Walk AST looking for top-level list items."""
        if node.type == "list":
            for child in node.children:
                if child.type == "list_item":
                    step = extract_checkbox_from_item(child, depth=0)
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
    - - bullet (in phase, not under step) → phase annotations["bullets"]
    - raw text (in phase, not under step) → phase annotations["notes"]

    Step-level content (indented under steps) is captured separately by
    _capture_step_annotations after the main parse.

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
    phase_bullets: list[str] = []  # Bare bullets within current phase (not under steps)
    phase_notes: list[str] = []  # Raw text within current phase (not under steps)
    target_dict: dict[str, Any] = plan.sections
    malformed_items: list[tuple[int, str, str]] = []  # (line_num, line, reason)

    # Track step context to skip indented content (handled by _capture_step_annotations)
    last_step_line: int = -1
    last_step_indent: int = 0

    # Track phase-level bold marker for continuation
    current_phase_marker: str | None = None
    phase_marker_lines: list[str] = []

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

    def flush_phase_marker() -> None:
        """Flush current phase-level marker with continuation."""
        nonlocal current_phase_marker, phase_marker_lines
        if current_phase_marker and phase_marker_lines and current_phase is not None:
            # Check if all lines are bullets - if so, store as array
            all_bullets = all(line.startswith("- ") for line in phase_marker_lines)
            if all_bullets:
                # Extract bullet text (strip "- " prefix)
                value: str | list[str] = [line[2:] for line in phase_marker_lines]
            else:
                # Mixed content - keep as string
                value = "\n".join(phase_marker_lines)
            _add_to_dict(current_phase.properties, current_phase_marker, value)
        current_phase_marker = None
        phase_marker_lines = []

    def flush_phase_extras() -> None:
        """Flush phase bullets and notes to phase annotations."""
        nonlocal phase_bullets, phase_notes
        flush_phase_marker()  # Flush any pending marker first
        if current_phase is not None:
            if phase_bullets:
                existing = current_phase.properties.get("bullets", [])
                if isinstance(existing, str):
                    # Convert old string format to array (shouldn't happen in practice)
                    existing = []
                current_phase.properties["bullets"] = existing + phase_bullets
            if phase_notes:
                existing = current_phase.properties.get("notes", "")
                if existing:
                    existing += "\n"
                current_phase.properties["notes"] = existing + "\n".join(phase_notes)
        phase_bullets = []
        phase_notes = []

    for line_num, raw_line in enumerate(plan.raw_lines):
        line = raw_line.rstrip()
        line_indent = len(raw_line) - len(raw_line.lstrip()) if raw_line.strip() else 0

        # Check if we're in indented content under a step (skip - handled later)
        if last_step_line >= 0 and line.strip():
            if line_indent > last_step_indent:
                # This line is indented under the last step - skip for now
                # It will be captured by _capture_step_annotations
                continue
            # No longer under a step
            last_step_line = -1

        # Title: # Task: Name
        title_match = TITLE_PATTERN.match(line)
        if title_match and plan.title is None:
            flush_content()
            plan.title = title_match.group(1).strip()
            current_section = None
            current_phase = None
            last_step_line = -1
            continue

        # Phase: ### Phase N: Title
        phase_match = PHASE_PATTERN.match(line)
        if phase_match:
            flush_content()
            flush_phase_extras()
            phase_num = int(phase_match.group(1))
            phase_title = phase_match.group(2).strip()
            current_phase = Phase(number=phase_num, title=phase_title, heading_line=line_num)
            plan.phases.append(current_phase)
            current_section = "__phase__"
            target_dict = current_phase.properties
            last_step_line = -1
            continue

        # H2: ## Section
        h2_match = H2_PATTERN.match(line)
        if h2_match:
            flush_content()
            flush_phase_extras()
            section_name = h2_match.group(1).strip()
            current_section = section_name
            current_phase = None
            target_dict = plan.sections
            last_step_line = -1
            # Skip "Phases" header itself
            if section_name.lower() == "phases":
                current_section = None
            continue

        # H3 (non-phase): ### Subsection - treat as section
        h3_match = H3_PATTERN.match(line)
        if h3_match and not phase_match:
            flush_content()
            flush_phase_extras()
            section_name = h3_match.group(1).strip()
            current_section = section_name
            current_phase = None
            target_dict = plan.sections
            last_step_line = -1
            continue

        # Steps are parsed by tree-sitter in phase post-processing
        # Skip checkbox lines here to avoid treating them as content
        if current_phase is not None and STEP_PATTERN.match(line):
            flush_content()
            last_step_line = line_num
            last_step_indent = len(raw_line) - len(raw_line.lstrip())
            continue

        # Bold key: **Key:** value (at phase level, not under step)
        bold_match = BOLD_KEY_PATTERN.match(line)
        if bold_match:
            flush_content()
            flush_phase_marker()  # Flush previous marker if any
            key = bold_match.group(1)
            value = bold_match.group(2).strip()
            if current_phase is not None:
                # Phase-level marker - set up for continuation capture
                current_phase_marker = key
                if value:
                    phase_marker_lines.append(value)
            else:
                # Section-level marker - add directly
                if value:
                    _add_to_dict(target_dict, key, value)
            continue

        # Check for malformed step-like items (only in phases, at step level = not indented)
        if current_phase is not None:
            if MALFORMED_CHECKBOX_PATTERN.match(line):
                malformed_items.append((line_num + 1, line.strip(), "malformed checkbox syntax"))
            elif WRONG_BULLET_CHECKBOX.match(line):
                malformed_items.append(
                    (line_num + 1, line.strip(), "wrong bullet marker (use - [ ] not * or +)"),
                )
            elif NUMBERED_LIST_PATTERN.match(line):
                malformed_items.append(
                    (line_num + 1, line.strip(), "numbered list (use - [ ] for steps)"),
                )
            elif BARE_BULLET_AT_STEP_LEVEL.match(line):
                # Bare bullet at step level (not indented) - should be a step with checkbox
                malformed_items.append(
                    (line_num + 1, line.strip(), "bare bullet at step level (use - [ ] for steps)"),
                )

        # Check if this is indented continuation of a phase-level marker
        if current_phase_marker and current_phase is not None and line_indent > 0:
            stripped = line.strip()
            # Continuation line for current phase marker
            if stripped.startswith("- "):
                # Indented bullet
                phase_marker_lines.append(stripped)
            elif stripped:
                # Indented text
                phase_marker_lines.append(stripped)
            continue

        # Bullet (non-checkbox): - item
        bullet_match = BULLET_PATTERN.match(line)
        if bullet_match:
            if current_phase is not None:
                # Inside a phase - capture as phase bullets annotation
                phase_bullets.append(bullet_match.group(1).strip())
            else:
                # Outside phase - accumulate for section array conversion
                content_buffer.append(line)
            continue

        # Raw text - accumulate
        if line.strip():
            if current_phase is not None:
                # Inside a phase - capture as phase notes annotation
                phase_notes.append(line.strip())
            else:
                content_buffer.append(line)

    flush_content()
    flush_phase_extras()

    # Validate no malformed step-like items
    if malformed_items:
        items_desc = "\n".join(
            f"  Line {num}: '{text}' ({reason})" for num, text, reason in malformed_items
        )
        raise ValueError(
            f"Plan contains malformed step-like items:\n{items_desc}\n\n"
            f"Valid step format: - [ ] Step text (or - [x] for completed)\n"
            f"Ensure space after checkbox and use - [ ] instead of numbered lists."
        )

    # Parse steps with tree-sitter for each phase
    for phase in plan.phases:
        phase.steps = _parse_steps_with_tree_sitter(phase.heading_line, plan.raw_lines)

        # Validate no nested steps exist
        for step in phase.steps:
            if step.depth > 0:
                raise ValueError(
                    f"Plan contains nested steps, which are not allowed per PLAN_SCHEMA.json.\n"
                    f"Found indented step at line {step.line_number + 1}: '{step.text}'\n"
                    f"Phase {phase.number}: {phase.title}\n\n"
                    f"Nested steps create ambiguous execution models:\n"
                    f"  - If substeps are distinct outcomes: unnest them as separate steps\n"
                    f"  - If substeps are implementation details: use **Notes:** annotations\n"
                    f"  - If substeps need grouping: they belong in a separate phase\n\n"
                    f"Please flatten the plan structure and try again."
                )

        # Capture annotations under each step
        _capture_step_annotations(phase.steps, plan.raw_lines)

    return plan


def _capture_step_annotations(steps: list[Step], raw_lines: list[str]) -> None:
    r"""Capture annotation properties under each step from raw markdown.

    Mutates steps in place to add properties like Notes, Blocked, Warning, etc.

    Handles:
        - **Key:** value patterns with multi-line continuation
        - Bare bullets as 'bullets' annotation
        - Raw text appended to step text (multi-line step)
        - Bullet continuation of markers (e.g., **Warning:** risk of:\n- theft)

    Format expected:
        - [x] Step text
            continuation of step text (appended)
            **Notes:** annotation text
            **Blocked:** reason text
            - bare bullet becomes bullets annotation

    Args:
        steps: List of steps (with nested children) to annotate
        raw_lines: Raw markdown lines

    """

    def process_step(step: Step) -> None:
        """Process one step and its children recursively."""
        step_line_idx = step.line_number

        # Find the extent of indented content under this step
        step_indent = len(raw_lines[step_line_idx]) - len(raw_lines[step_line_idx].lstrip())

        # Collect all content under this step
        current_marker: str | None = None
        marker_lines: list[str] = []
        bare_bullets: list[str] = []
        text_continuation: list[str] = []  # Raw text appended to step

        def flush_marker() -> None:
            """Flush current marker to step properties."""
            nonlocal current_marker, marker_lines
            if current_marker and marker_lines:
                # Check if all lines are bullets - if so, store as array
                all_bullets = all(line.startswith("- ") for line in marker_lines)
                if all_bullets:
                    # Extract bullet text (strip "- " prefix)
                    value: str | list[str] = [line[2:] for line in marker_lines]
                else:
                    # Mixed content - keep as string
                    value = "\n".join(marker_lines)
                _add_to_dict(step.properties, current_marker, value)
            current_marker = None
            marker_lines = []

        # Scan lines after the step
        for i in range(step_line_idx + 1, len(raw_lines)):
            line = raw_lines[i]
            if not line.strip():
                continue  # Skip blank lines

            line_indent = len(line) - len(line.lstrip())
            stripped = line.strip()

            # If this line is not more indented, we've left this step's block
            if line_indent <= step_indent:
                break

            # Check if it's a nested checkbox (child step) - skip those
            if STEP_PATTERN.match(line):
                break

            # Check for bold key pattern: **Key:** value
            bold_match = BOLD_KEY_PATTERN.match(stripped)
            if bold_match:
                flush_marker()
                current_marker = bold_match.group(1)
                value = bold_match.group(2).strip()
                if value:
                    marker_lines.append(value)
                continue

            # Check for bare bullet
            bullet_match = BULLET_PATTERN.match(stripped)
            if bullet_match:
                bullet_text = bullet_match.group(1).strip()
                if current_marker:
                    # Bullet continues current marker
                    marker_lines.append(f"- {bullet_text}")
                else:
                    # Standalone bullet
                    bare_bullets.append(bullet_text)
                continue

            # Raw text
            if current_marker:
                # Text continues current marker
                marker_lines.append(stripped)
            else:
                # Standalone text - append to step text (multi-line step)
                text_continuation.append(stripped)

        # Flush any remaining marker
        flush_marker()

        # Append text continuation to step text (join with spaces - wrapping, not semantic breaks)
        if text_continuation:
            step.text = step.text + " " + " ".join(text_continuation)

        # Add bare bullets as annotation (as array)
        if bare_bullets:
            step.properties["bullets"] = bare_bullets

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


def _load_plan_schema() -> dict[str, Any]:
    """Load the plan schema from the package's schemas directory."""
    schema_path = Path(__file__).parent.parent / "schemas" / "PLAN_MARKDOWN_SCHEMA.json"
    schema: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
    return schema


def _validate_plan_dict(plan_dict: dict[str, Any]) -> None:
    """Validate plan dict against JSON schema. Raises ValueError if invalid."""
    schema = _load_plan_schema()
    try:
        validate(instance=plan_dict, schema=schema)
    except ValidationError as e:
        # Build a helpful error message
        path = " -> ".join(str(p) for p in e.absolute_path) if e.absolute_path else "(root)"
        raise ValueError(
            f"Plan validation failed at {path}:\n"
            f"  {e.message}\n\n"
            f"Schema expects: {e.schema.get('description', 'see schema')}"
        ) from None


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    """Convert internal Plan to output dict format.

    Args:
        plan: Parsed Plan structure

    Returns:
        Dict ready for JSON serialization

    Raises:
        ValueError: If the resulting dict doesn't match the plan schema

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
                    step_dict: dict[str, Any] = {
                        "id": step_id,
                        "text": step.text,
                        "done": step.checked,
                    }
                    # Add step annotations nested under 'annotations' key
                    if step.properties:
                        step_dict["annotations"] = dict(step.properties)

                    if not step.checked and next_step_id is None:
                        next_step_id = step_id
                    steps_out.append(step_dict)
                phase_dict["steps"] = steps_out

            # Phase annotations nested under 'annotations' key
            if phase.properties:
                phase_dict["annotations"] = dict(phase.properties)

            phases_out.append(phase_dict)

        result["phases"] = phases_out

        if next_step_id:
            result["next"] = next_step_id

    # Validate against schema
    _validate_plan_dict(result)

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
                return (
                    phase.title,
                    step_id,
                    {"step_id": step_id, "phase_title": phase.title, "text": step.text},
                )
    return (None, None, None)


def mark_step_complete(
    plan: Plan,
    step_id: str,
    annotation: dict[str, str] | None = None,
) -> tuple[str, bool, bool]:
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
        for i in range(
            existing_marker_line_idx,
            (existing_marker_end_idx or existing_marker_line_idx) + 1,
        ):
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
