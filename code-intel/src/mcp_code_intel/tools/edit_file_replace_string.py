"""Atomic multi-replacement tool.

Apply multiple string replacements to a file in a single atomic write.
All replacements are validated upfront and applied only if ALL succeed.
"""

from pathlib import Path

from ..file_helpers import (
    normalize_eol,
    read_file_with_metadata,
    resolve_file_path,
)

_PREVIEW_MAX_LEN = 50


def _validate_replacements(replacements: list[dict]) -> dict | None:
    """Validate replacement list structure. Returns error dict or None if valid."""
    if not replacements:
        return {"error": "No replacements provided"}

    for i, rep in enumerate(replacements):
        if "old_string" not in rep:
            return {"error": f"Replacement {i}: missing 'old_string'"}
        if "new_string" not in rep:
            return {"error": f"Replacement {i}: missing 'new_string'"}

    return None


def _find_all_matches(content: str, old_string: str) -> list[tuple[int, int]]:
    """Find all non-overlapping occurrences of old_string, return (start, end) spans."""
    matches = []
    start = 0
    while True:
        pos = content.find(old_string, start)
        if pos == -1:
            break
        matches.append((pos, pos + len(old_string)))
        start = pos + len(old_string)
    return matches


def _spans_overlap(span1: tuple[int, int], span2: tuple[int, int]) -> bool:
    """Check if two (start, end) spans overlap."""
    return span1[0] < span2[1] and span2[0] < span1[1]


def _preview(s: str) -> str:
    """Create a preview string for logging."""
    preview = s[:_PREVIEW_MAX_LEN] + "..." if len(s) > _PREVIEW_MAX_LEN else s
    return preview.replace("\n", "\\n").replace("\r", "\\r")


def _extract_line_context(
    content: str,
    char_start: int,
    char_end: int,
    context_lines: int = 2,
) -> str:
    """Extract lines containing char_start to char_end with N lines of context on each side.

    Args:
        content: The full file content
        char_start: Character position where the replacement starts
        char_end: Character position where the replacement ends
        context_lines: Number of lines before/after to include (default 2)

    Returns:
        String showing the affected lines with context, line numbers included
    """
    lines = content.splitlines(keepends=True)

    # Find which lines contain the start and end positions
    char_pos = 0
    start_line_idx = 0
    end_line_idx = 0

    for i, line in enumerate(lines):
        line_end = char_pos + len(line)
        if char_pos <= char_start < line_end:
            start_line_idx = i
        if char_pos <= char_end <= line_end:
            end_line_idx = i
            break
        char_pos = line_end

    # Calculate context range
    context_start = max(0, start_line_idx - context_lines)
    context_end = min(len(lines), end_line_idx + context_lines + 1)

    # Build the context with line numbers
    result_lines = []
    for i in range(context_start, context_end):
        line_num = i + 1  # 1-indexed for display
        line_content = lines[i].rstrip('\n\r')  # Remove trailing newlines for display
        result_lines.append(f"{line_num:4d} | {line_content}")

    return "\n".join(result_lines)


def _calculate_new_positions(
    edits: list[tuple[int, int, str]],
    details: list[dict],
) -> list[tuple[int, int] | None]:
    """Calculate where each edit ends up in the new content after all edits are applied.

    Edits are applied from end to start, so we need to track cumulative offset changes.

    Args:
        edits: List of (start, end, new_string) tuples, in original order
        details: List of detail dicts with original_span and new_string_len

    Returns:
        List of (new_start, new_end) tuples or None showing final positions in new content
    """
    # Create list of (original_start, original_end, new_string_len, original_index)
    indexed_edits = []
    for i, ((start, end, new_string), detail) in enumerate(zip(edits, details)):
        if "original_span" in detail:  # Only for valid edits
            indexed_edits.append((start, end, detail["new_string_len"], i))

    # Sort by position (ascending) to process from start to end
    indexed_edits.sort(key=lambda x: x[0])

    # Calculate new positions with cumulative offset
    new_positions: list[tuple[int, int] | None] = [None] * len(details)
    cumulative_offset = 0

    for orig_start, orig_end, new_len, idx in indexed_edits:
        old_len = orig_end - orig_start
        new_start = orig_start + cumulative_offset
        new_end = new_start + new_len
        new_positions[idx] = (new_start, new_end)

        # Update cumulative offset for next edit
        cumulative_offset += (new_len - old_len)

    return new_positions


def _validate_all_replacements_upfront(
    content: str,
    replacements: list[dict],
    eol: str,
) -> tuple[list[tuple[int, int, str]], list[dict]] | dict:
    """Validate all replacements against original content.

    Returns (edits, details) where edits is list of (start, end, new_string),
    or an error dict if validation fails.

    Edits are validated for:
    - Exactly one match per old_string
    - No overlapping spans between different replacements

    Each new_string is normalized to match the document's EOL style.
    Details now include original_span for context extraction after editing.
    """
    edits: list[tuple[int, int, str]] = []
    details: list[dict] = []
    errors: list[str] = []

    for i, rep in enumerate(replacements):
        old_string = rep["old_string"]
        new_string = rep["new_string"]
        # Normalize old_string to match document EOL so LLM-provided strings match file content
        normalized_old = normalize_eol(old_string, eol)
        old_preview = _preview(old_string)

        matches = _find_all_matches(content, normalized_old)

        if len(matches) == 0:
            errors.append(f"Replacement {i}: not found: {old_preview}")
            details.append({"old_string_preview": old_preview, "status": "not_found"})
        elif len(matches) > 1:
            errors.append(f"Replacement {i}: ambiguous ({len(matches)} occurrences): {old_preview}")
            details.append(
                {
                    "old_string_preview": old_preview,
                    "status": f"ambiguous ({len(matches)} occurrences)",
                },
            )
        else:
            # Exactly one match - check for overlap with previous edits
            span = matches[0]
            overlap_idx = None
            for j, (prev_start, prev_end, _) in enumerate(edits):
                if _spans_overlap(span, (prev_start, prev_end)):
                    overlap_idx = j
                    break

            if overlap_idx is not None:
                errors.append(
                    f"Replacement {i} overlaps with replacement {overlap_idx}: {old_preview}",
                )
                details.append(
                    {
                        "old_string_preview": old_preview,
                        "status": f"overlaps with replacement {overlap_idx}",
                    },
                )
            else:
                # Normalize new_string to match document's EOL style
                normalized_new = normalize_eol(new_string, eol)
                edits.append((span[0], span[1], normalized_new))
                # Track original span and new string length for later context extraction
                details.append({
                    "old_string_preview": old_preview,
                    "status": "valid",
                    "original_span": span,
                    "new_string_len": len(normalized_new),
                })

    if errors:
        return {
            "error": "Validation failed - no changes made",
            "validation_errors": errors,
            "details": details,
            "changed": False,
        }

    return edits, details


def _apply_edits(content: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply edits (start, end, new_string) to content.

    Edits are applied from end to start to preserve positions.
    """
    # Sort by start position descending so we apply from end first
    sorted_edits = sorted(edits, key=lambda e: e[0], reverse=True)

    for start, end, new_string in sorted_edits:
        content = content[:start] + new_string + content[end:]

    return content


def _write_and_build_result(
    target_path: Path,
    rel_path: str,
    content: str,
    new_content: str,
    original_mtime: float,
    details: list[dict],
    num_replacements: int,
    edits: list[tuple[int, int, str]],
) -> dict:
    """Check mtime, write if changed, and build result dict with new_context."""
    # Check mtime before write (detect concurrent modification)
    current_mtime = target_path.stat().st_mtime
    if current_mtime != original_mtime:
        return {
            "path": rel_path,
            "error": (
                f"MTIME MISMATCH: File may have changed during operation. "
                f"Expected mtime {original_mtime}, got {current_mtime}. "
                f"Aborting to prevent data loss - re-read and retry if needed."
            ),
            "changed": False,
            "details": [{
                "old_string_preview": d.get("old_string_preview", ""),
                "status": d["status"]
            } for d in details],
        }

    # Check if content actually changed
    if new_content == content:
        return {
            "path": rel_path,
            "changed": False,
            "replacements_applied": 0,
            "details": [
                {"old_string_preview": d["old_string_preview"], "status": "no_change"}
                for d in details
            ],
            "note": "Replacements resulted in identical content",
        }

    # Write atomically
    target_path.write_bytes(new_content.encode("utf-8"))

    # Calculate new positions and extract context from new content
    new_positions = _calculate_new_positions(edits, details)

    # Build final details with new_context
    final_details = []
    for i, d in enumerate(details):
        if d["status"] == "valid" and new_positions[i] is not None:
            pos = new_positions[i]
            assert pos is not None  # Type narrowing for mypy
            new_start, new_end = pos
            new_context = _extract_line_context(new_content, new_start, new_end, context_lines=2)
            final_details.append({
                "status": "applied",
                "new_context": new_context,
            })
        else:
            # For non-valid edits (not_found, ambiguous, overlapping), keep old_string_preview
            final_details.append({
                "old_string_preview": d.get("old_string_preview", ""),
                "status": d["status"],
            })

    return {
        "path": rel_path,
        "changed": True,
        "replacements_applied": num_replacements,
        "details": final_details,
    }


def edit_file_replace_string(
    file_path: str,
    replacements: list[dict],
    workspace_root: Path,
) -> dict:
    """Apply multiple string replacements atomically (single write).

    All replacements are validated against the ORIGINAL content before any
    changes are made. If ANY replacement fails validation, NO changes are
    written to disk.

    Validation checks:
    - Each old_string must match exactly once (not zero, not multiple)
    - No two replacements can have overlapping spans
    - File must be valid UTF-8
    - File must not contain tabs in leading whitespace

    Args:
        file_path: Workspace-relative or absolute path to the file
        replacements: List of dicts, each with:
            - old_string: Exact text to find and replace
            - new_string: Text to replace with
        workspace_root: Path to workspace root for security validation

    Returns:
        dict with:
        - path: The resolved workspace-relative path
        - changed: bool - whether file was modified
        - replacements_applied: Number of replacements (all or none)
        - details: List of {new_context, status} for each successful replacement
                   or {old_string_preview, status} for failed validations
        - error: Error message if operation fails
        - validation_errors: List of specific errors if validation failed

    Note: For successfully applied replacements, new_context shows the modified
    lines with 2 lines of context on each side, enabling immediate verification
    without needing to re-read the file.

    """
    # Resolve and validate path
    resolved = resolve_file_path(file_path, workspace_root)
    if isinstance(resolved, dict):
        resolved["changed"] = False
        return resolved
    target_path = resolved
    rel_path = str(target_path.relative_to(workspace_root))

    # Validate replacements structure
    validation_error = _validate_replacements(replacements)
    if validation_error:
        validation_error["changed"] = False
        return validation_error

    # Read file with metadata
    file_data = read_file_with_metadata(target_path)
    if "error" in file_data:
        file_data["changed"] = False
        return file_data

    content = file_data["content"]
    original_mtime = file_data["mtime"]
    eol = file_data["eol"]

    # Validate all replacements upfront against original content
    validation_result = _validate_all_replacements_upfront(content, replacements, eol)
    if isinstance(validation_result, dict):
        validation_result["path"] = rel_path
        return validation_result

    edits, details = validation_result

    # Apply all edits
    new_content = _apply_edits(content, edits)

    # Write and build result (checks mtime, handles no-change case)
    return _write_and_build_result(
        target_path=target_path,
        rel_path=rel_path,
        content=content,
        new_content=new_content,
        original_mtime=original_mtime,
        details=details,
        num_replacements=len(replacements),
        edits=edits,
    )
