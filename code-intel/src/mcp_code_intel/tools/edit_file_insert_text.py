r"""Insert text at specific positions without string matching.

MCP tool for inserting text at precise positions
(BOF, EOF, before/after line).
Ensures atomicity: all insertions applied or none on any failure.

Design Principles:
- Position-based insertion (no fuzzy string matching)
- Line-level insertion only (no character-level positioning)
- Coordinate space: all line numbers in batch refer to ORIGINAL file state
- Bottom-to-top application preserves coordinates
- Context validation: returns changed region ± 2 lines

Examples
--------
Insert at beginning of file:
>>> file_insert_text([
...     {"path": "service.py", "content": "# Copyright 2026\n", "at": "bof"}
... ])

Insert after specific line:
>>> file_insert_text([
...     {"path": "service.py", "content": "    pass\n", "at": "after_line", "line": 10}
... ])

Batch same-file ops (coordinates refer to original state):
>>> file_insert_text([
...     {"path": "test.py", "content": "import b\n", "at": "after_line", "line": 2},
...     {"path": "test.py", "content": "import a\n", "at": "after_line", "line": 1}
... ])

"""

import contextlib
from pathlib import Path

from pydantic import BaseModel, Field

from mcp_code_intel.helpers.content_boundaries import find_anchor_line
from mcp_code_intel.helpers.file_helpers import (
    atomic_write,
    build_new_context,
    check_mtime,
    group_ops_by_file,
    read_file_with_metadata,
    resolve_file_path,
    validate_line_range,
)
from mcp_code_intel.response_models import (
    AppliedOp,
    BatchResponse,
    FailedOp,
)


class InsertBoundaryOp(BaseModel):
    """Operation for inserting text at file boundaries (beginning or end)."""

    path: str = Field(description="File path (workspace-relative or absolute)")
    content: str = Field(description="Text to insert")


class InsertLineOp(BaseModel):
    """Operation for inserting text before or after a content anchor."""

    path: str = Field(description="File path (workspace-relative or absolute)")
    content: str = Field(description="Text to insert")
    anchor: str = Field(
        description=(
            "Content to anchor insertion. Stripped substring match against "
            "file lines. Must match exactly one line."
        ),
    )
    position: str = Field(
        description="Insert before or after the anchor line",
        pattern=r"^(before|after)$",
    )


def _validate_operations(
    ops: list[dict],
    workspace_root: Path,
) -> tuple[list[tuple[int, dict, Path]], list[FailedOp]]:
    """Validate all insert operations before execution."""
    failed_ops: list[FailedOp] = []
    validated_ops: list[tuple[int, dict, Path]] = []

    for idx, op_dict in enumerate(ops):
        # Basic structure validation
        path = op_dict.get("path")
        if not path:
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath="<unknown>",
                    reason="Missing required field: path",
                ),
            )
            continue

        if "content" not in op_dict:
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=path,
                    reason="Missing required field: content",
                ),
            )
            continue

        # Resolve path (file must exist)
        result = resolve_file_path(path, workspace_root)
        if isinstance(result, dict):  # Error
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=path,
                    reason=result["error"],
                ),
            )
            continue

        resolved_path: Path = result
        validated_ops.append((idx, op_dict, resolved_path))

    return validated_ops, failed_ops


def _insert_at_boundary(
    lines: list[str],
    content: str,
    *,
    position: str,
) -> tuple[list[str], int, int]:
    """Insert text at beginning or end of file.

    Args:
        lines: File lines (without trailing newlines)
        content: Text to insert
        position: 'bof' or 'eof'

    Returns:
        Tuple of (modified_lines, start_line, end_line)

    """
    insert_lines = content.rstrip("\n").split("\n")

    if position == "bof":
        modified_lines = insert_lines + lines
        return modified_lines, 1, len(insert_lines)

    # eof
    start_line = len(lines) + 1
    modified_lines = lines + insert_lines
    return modified_lines, start_line, start_line + len(insert_lines) - 1


def _insert_at_line(
    lines: list[str],
    content: str,
    *,
    anchor: str,
    position: str,
) -> tuple[list[str], int, int] | str:
    """Insert text before or after a line identified by content anchor.

    Args:
        lines: File lines (without trailing newlines)
        content: Text to insert
        anchor: Content substring to locate the target line
        position: 'before' or 'after'

    Returns:
        Tuple of (modified_lines, start_line, end_line) or error message

    """
    anchor_result = find_anchor_line(lines, anchor)
    if isinstance(anchor_result, str):
        return anchor_result

    line: int = anchor_result  # 1-indexed
    total_lines = len(lines)

    # Validate line number (should always be valid from find_anchor_line)
    line_error = validate_line_range(line, line, total_lines)
    if line_error:
        return line_error

    target_line_idx = line - 1  # Convert to 0-indexed
    insert_lines = content.rstrip("\n").split("\n")

    if position == "before":
        modified_lines = lines[:target_line_idx] + insert_lines + lines[target_line_idx:]
        return modified_lines, line, line + len(insert_lines) - 1

    # after
    modified_lines = lines[: target_line_idx + 1] + insert_lines + lines[target_line_idx + 1 :]
    return modified_lines, line + 1, line + len(insert_lines)


def _insert_text(
    lines: list[str],
    op_dict: dict,
) -> tuple[list[str], int, int] | str:
    """Insert text into lines — dispatcher for legacy dict compatibility.

    Delegates to _insert_at_boundary or _insert_at_line based on op.at value.

    """
    at = op_dict.get("at")
    content = op_dict.get("content", "")

    if at in ("bof", "eof"):
        return _insert_at_boundary(lines, content, position=at)

    # before_line or after_line
    anchor = op_dict.get("anchor")
    if anchor is None:
        return "anchor is required for before_line/after_line"

    position = "before" if at == "before_line" else "after"
    return _insert_at_line(lines, content, anchor=anchor, position=position)


def _apply_insertions_to_file(
    file_path: Path,
    ops_for_file: list[tuple[int, dict]],
) -> tuple[list[AppliedOp], list[FailedOp]]:
    """Apply all insertions to a single file.

    With content-anchor based operations, each insertion resolves its anchor
    against the current state of the file after previous insertions.
    Operations are applied in the order they are received.
    """
    # Read file
    file_data = read_file_with_metadata(file_path)
    if "error" in file_data:
        return [], [
            FailedOp(
                index=ops_for_file[0][0],
                filepath=str(file_path),
                reason=file_data["error"],
            ),
        ]

    content = file_data["content"]
    eol = file_data["eol"]
    original_mtime = file_data["mtime"]
    lines = content.split("\n")

    # Apply insertions in order (anchors resolve against current state)
    applied_ops: list[AppliedOp] = []

    for idx, op_dict in ops_for_file:
        result = _insert_text(lines, op_dict)

        if isinstance(result, str):  # Error
            return [], [
                FailedOp(
                    index=idx,
                    filepath=str(file_path),
                    reason=result,
                ),
            ]

        lines, start_line, end_line = result

        # Build context using standard helper
        formatted_context = build_new_context(lines, start_line, end_line)

        applied_ops.append(
            AppliedOp(
                index=idx,
                filepath=str(file_path),
                start_line=start_line,
                end_line=end_line,
                new_context=formatted_context,
                bytes_written=None,  # Not computed for insertions
            ),
        )

    # Check mtime before write (detect concurrent modification)
    mtime_error = check_mtime(file_path, original_mtime)
    if mtime_error:
        return [], [
            FailedOp(
                index=ops_for_file[0][0],
                filepath=str(file_path),
                reason=mtime_error,
            ),
        ]

    # Write modified content atomically
    new_content = "\n".join(lines)
    write_error = atomic_write(file_path, new_content, eol=eol)
    if write_error:
        return [], [
            FailedOp(
                index=ops_for_file[0][0],
                filepath=str(file_path),
                reason=write_error["error"],
            ),
        ]

    return applied_ops, []


def edit_file_insert_text(ops: list[dict], workspace_root: Path) -> dict:
    """Insert text at specific positions without string matching.

    Args:
        ops: List of operation dicts with: path, content, at, line (for at=before_line/after_line)
        workspace_root: Workspace root path for resolution and security

    Returns:
        BatchResponse dict with status and operation results

    Behavior:
        - All target files must exist
        - Inserts content as new line(s) at specified position
        - For same-file ops: all coordinates refer to ORIGINAL file state
        - Apply operations bottom-to-top to avoid coordinate drift

    """
    # Phase 1: Validate all operations
    validated_ops, failed_ops = _validate_operations(ops, workspace_root)

    if failed_ops:
        return BatchResponse(
            status="failed",
            failed_ops=failed_ops,
        ).model_dump(exclude_none=True)

    # Phase 2: Group operations by file
    grouped_ops = group_ops_by_file(
        [(idx, op_dict, path) for idx, op_dict, path in validated_ops],
    )

    # Phase 3: Apply insertions file by file
    all_applied_ops: list[AppliedOp] = []
    original_contents: dict[Path, bytes] = {}  # For rollback

    for file_path, ops_for_file in grouped_ops.items():
        # Backup original content
        try:
            original_contents[file_path] = file_path.read_bytes()
        except OSError as e:
            # Rollback any files we've modified
            for path, backup in original_contents.items():
                with contextlib.suppress(OSError):
                    path.write_bytes(backup)

            return BatchResponse(
                status="failed",
                failed_ops=[
                    FailedOp(
                        index=ops_for_file[0][0],
                        filepath=str(file_path),
                        reason=f"Failed to backup file: {e}",
                    ),
                ],
            ).model_dump(exclude_none=True)

        # Apply insertions (bottom-to-top within file)
        applied_ops, failed_ops = _apply_insertions_to_file(file_path, ops_for_file)

        if failed_ops:
            # Rollback all files
            for path, backup in original_contents.items():
                with contextlib.suppress(OSError):
                    path.write_bytes(backup)

            return BatchResponse(
                status="failed",
                failed_ops=failed_ops,
            ).model_dump(exclude_none=True)

        all_applied_ops.extend(applied_ops)

    # Success: sort by original index
    all_applied_ops.sort(key=lambda op: op.index)

    return BatchResponse(
        status="applied",
        applied_ops=all_applied_ops,
    ).model_dump(exclude_none=True)
