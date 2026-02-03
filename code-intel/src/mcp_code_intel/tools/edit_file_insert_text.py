r"""Insert text at specific positions without string matching.

MCP tool for inserting text at precise positions
(BOF, EOF, before/after line, with optional column).
Ensures atomicity: all insertions applied or none on any failure.

Design Principles:
- Position-based insertion (no fuzzy string matching)
- Supports both line-only and row+col modes
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

Insert at character position (row+col mode):
>>> file_insert_text([
...     {"path": "code.py", "content": ", arg2", "at": "after_line", "line": 5, "col": 20}
... ])

Batch same-file ops (coordinates refer to original state):
>>> file_insert_text([
...     {"path": "test.py", "content": "import b\n", "at": "after_line", "line": 2},
...     {"path": "test.py", "content": "import a\n", "at": "after_line", "line": 1}
... ])

"""

import contextlib
from pathlib import Path

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from mcp_code_intel.file_helpers import (
    atomic_write,
    extract_context,
    format_context_with_line_numbers,
    group_ops_by_file,
    read_file_with_metadata,
    resolve_file_path,
    validate_col,
    validate_line_range,
)
from mcp_code_intel.response_models import (
    AppliedOp,
    BatchResponse,
    FailedOp,
)


class InsertOp(BaseModel):
    """Operation for inserting text at a specific position."""

    path: str = Field(description="File path (workspace-relative or absolute)")
    content: str = Field(description="Text to insert")
    at: str = Field(
        description="Insertion mode: bof, eof, before_line, after_line",
        pattern=r"^(bof|eof|before_line|after_line)$",
    )
    line: int | None = Field(
        default=None,
        description="Line number (1-indexed, required for before_line/after_line)",
    )
    col: int | None = Field(
        default=None,
        description="Column position (0-indexed, None=BOL, -1=EOL, N=char N)",
    )

    @field_validator("line")
    @classmethod
    def validate_line_required(cls, v: int | None, info: ValidationInfo) -> int | None:
        """Require line for before_line/after_line modes."""
        at_value = info.data.get("at")
        if at_value in ("before_line", "after_line") and v is None:
            msg = f"line is required when at='{at_value}'"
            raise ValueError(msg)
        return v


def _validate_operations(
    ops: list[dict],
    workspace_root: Path,
) -> tuple[list[tuple[int, InsertOp, Path]], list[FailedOp]]:
    """Validate all insert operations before execution."""
    failed_ops: list[FailedOp] = []
    validated_ops: list[tuple[int, InsertOp, Path]] = []

    for idx, op_dict in enumerate(ops):
        try:
            insert_op = InsertOp.model_validate(op_dict)
        except (ValueError, TypeError) as e:
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=op_dict.get("path", "<unknown>"),
                    reason=f"Invalid operation: {e}",
                ),
            )
            continue

        # Resolve path (file must exist)
        result = resolve_file_path(insert_op.path, workspace_root)
        if isinstance(result, dict):  # Error
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=insert_op.path,
                    reason=result["error"],
                ),
            )
            continue

        resolved_path: Path = result
        validated_ops.append((idx, insert_op, resolved_path))

    return validated_ops, failed_ops


def _insert_text(  # noqa: PLR0911
    lines: list[str],
    insert_op: InsertOp,
) -> tuple[list[str], int, int] | str:
    """Insert text into lines at specified position.

    Args:
        lines: File lines (without trailing newlines)
        insert_op: Insert operation

    Returns:
        Tuple of (modified_lines, start_line, end_line) or error message

    """
    total_lines = len(lines)

    if insert_op.at == "bof":
        # Insert at beginning of file
        insert_lines = insert_op.content.rstrip("\n").split("\n")
        modified_lines = insert_lines + lines
        return modified_lines, 1, len(insert_lines)

    if insert_op.at == "eof":
        # Insert at end of file
        insert_lines = insert_op.content.rstrip("\n").split("\n")
        start_line = total_lines + 1
        modified_lines = lines + insert_lines
        return modified_lines, start_line, start_line + len(insert_lines) - 1

    # before_line or after_line modes
    if insert_op.line is None:
        return "line is required for before_line/after_line"

    # Validate line number
    line_error = validate_line_range(insert_op.line, insert_op.line, total_lines)
    if line_error:
        return line_error

    target_line_idx = insert_op.line - 1  # Convert to 0-indexed

    if insert_op.col is None:
        # Line-only mode: insert content as new line(s)
        insert_lines = insert_op.content.rstrip("\n").split("\n")

        if insert_op.at == "before_line":
            modified_lines = lines[:target_line_idx] + insert_lines + lines[target_line_idx:]
            return modified_lines, insert_op.line, insert_op.line + len(insert_lines) - 1

        # after_line
        modified_lines = lines[: target_line_idx + 1] + insert_lines + lines[target_line_idx + 1 :]
        return modified_lines, insert_op.line + 1, insert_op.line + len(insert_lines)

    # Row+col mode: insert at exact character position
    target_line = lines[target_line_idx]

    # Validate column
    col_error = validate_col(insert_op.col, len(target_line))
    if col_error:
        return col_error

    # Resolve column position
    col_pos = len(target_line) if insert_op.col == -1 else insert_op.col

    # Insert at character position (no newlines in content for char-precise mode)
    modified_line = target_line[:col_pos] + insert_op.content + target_line[col_pos:]

    if insert_op.at == "before_line":
        lines[target_line_idx] = modified_line
        return lines, insert_op.line, insert_op.line

    # after_line with col: still inserts AT the line (col positioning happens within line)
    lines[target_line_idx] = modified_line
    return lines, insert_op.line, insert_op.line


def _apply_insertions_to_file(
    file_path: Path,
    ops_for_file: list[tuple[int, dict]],
) -> tuple[list[AppliedOp], list[FailedOp]]:
    """Apply all insertions to a single file (bottom-to-top to preserve coordinates)."""
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
    lines = content.split("\n")

    # Parse operations and sort bottom-to-top (descending line order)
    parsed_ops = [(idx, InsertOp.model_validate(op_dict)) for idx, op_dict in ops_for_file]
    sorted_ops = sorted(parsed_ops, key=lambda x: x[1].line or 0, reverse=True)

    # Apply insertions bottom-to-top
    applied_ops: list[AppliedOp] = []

    for idx, insert_op in sorted_ops:
        result = _insert_text(lines, insert_op)

        if isinstance(result, str):  # Error
            return [], [
                FailedOp(
                    index=idx,
                    filepath=str(file_path),
                    reason=result,
                ),
            ]

        lines, start_line, end_line = result

        # Extract context (changed region ± 2 lines)
        context_lines, context_start = extract_context(lines, start_line, end_line)
        formatted_context = format_context_with_line_numbers(context_lines, context_start)

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
        ops: List of InsertOp dicts
        workspace_root: Workspace root path for resolution and security

    Returns:
        BatchResponse dict with status and operation results

    Behavior:
        - All target files must exist
        - Line-only mode (col=None): Inserts content as new line(s)
        - Row+col mode: Inserts at exact character position
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
        [(idx, op.__dict__, path) for idx, op, path in validated_ops],
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
