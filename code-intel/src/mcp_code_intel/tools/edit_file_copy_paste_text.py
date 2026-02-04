r"""Copy text from source locations and paste to target locations.

MCP tool for duplicating text across files with caching for efficiency.
Primary use case: "stamp decorator 50 times" - copy same source to many targets.

Design Principles:
- Pure insertion (no overwrite/replace semantics)
- Source caching (read once per unique range)
- Coordinate space: all line numbers in batch refer to ORIGINAL file state
- Bottom-to-top application within each target file
- Context validation: returns changed region ± 2 lines at target

Examples
--------
Copy full lines to new location:
>>> file_copy_paste_text([
...     {
...         "source_path": "decorators.py",
...         "source_start_line": 10,
...         "source_end_line": 15,
...         "target_path": "service.py",
...         "target_line": 5
...     }
... ])

Character-precise copy with row+col:
>>> file_copy_paste_text([
...     {
...         "source_path": "a.py",
...         "source_start_line": 3,
...         "source_start_col": 10,
...         "source_end_line": 3,
...         "source_end_col": 25,
...         "target_path": "b.py",
...         "target_line": 7,
...         "target_col": 15
...     }
... ])

Stamp decorator 50 times (same source, many targets):
>>> file_copy_paste_text([
...     {
...         "source_path": "decorators.py",
...         "source_start_line": 1,
...         "source_end_line": 3,
...         "target_path": "service1.py",
...         "target_line": 10
...     },
...     {
...         "source_path": "decorators.py",
...         "source_start_line": 1,
...         "source_end_line": 3,
...         "target_path": "service2.py",
...         "target_line": 15
...     },
...     # ... repeat for 48 more targets
... ])

"""

import contextlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from mcp_code_intel.helpers.file_helpers import (
    atomic_write,
    check_mtime,
    extract_context,
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


class CopyPasteOp(BaseModel):
    """Operation for copying text from source to target location."""

    source_path: str = Field(description="Source file path (workspace-relative or absolute)")
    source_start_line: int = Field(description="First line to copy (1-indexed, inclusive)")
    source_start_col: int | None = Field(
        default=None,
        description="Start column (0-indexed, None=BOL)",
    )
    source_end_line: int = Field(description="Last line to copy (1-indexed, inclusive)")
    source_end_col: int | None = Field(
        default=None,
        description="End column (0-indexed, None=EOL, -1=EOL)",
    )
    target_path: str = Field(description="Target file path (workspace-relative or absolute)")
    target_line: int = Field(
        description="Line where text will be inserted (1-indexed, -1=EOF)",
    )
    target_col: int | None = Field(
        default=None,
        description="Column for insertion (0-indexed, None=BOL, -1=EOL)",
    )

    @field_validator("source_end_line")
    @classmethod
    def validate_source_range(cls, v: int, info: ValidationInfo) -> int:
        """Ensure source_end_line >= source_start_line."""
        source_start = info.data.get("source_start_line")
        if source_start is not None and v < source_start:
            msg = f"source_end_line ({v}) must be >= source_start_line ({source_start})"
            raise ValueError(msg)
        return v


def _extract_source_text(
    source_path: Path,
    source_start_line: int,
    source_start_col: int | None,
    source_end_line: int,
    source_end_col: int | None,
) -> tuple[str, str] | str:
    """Extract text from source file.

    Returns:
        Tuple of (extracted_text, eol_style) or error message

    """
    # Read source file
    file_data = read_file_with_metadata(source_path)
    if "error" in file_data:
        return str(file_data["error"])

    content = file_data["content"]
    eol = file_data["eol"]
    lines = content.split("\n")
    total_lines = len(lines)

    # Validate source range
    range_error = validate_line_range(source_start_line, source_end_line, total_lines)
    if range_error:
        return range_error

    # Line-only mode (both cols are None)
    if source_start_col is None and source_end_col is None:
        # Extract full lines (1-indexed, inclusive)
        extracted_lines = lines[source_start_line - 1 : source_end_line]
        return "\n".join(extracted_lines) + "\n", eol

    # Row+col mode: extract character-precise range
    start_line_idx = source_start_line - 1
    end_line_idx = source_end_line - 1

    # Validate columns
    if source_start_col is not None:
        col_error = validate_col(source_start_col, len(lines[start_line_idx]))
        if col_error:
            return col_error

    if source_end_col is not None:
        col_error = validate_col(source_end_col, len(lines[end_line_idx]))
        if col_error:
            return col_error

    # Resolve column positions
    start_col = 0 if source_start_col is None else source_start_col
    end_col = (
        len(lines[end_line_idx])
        if source_end_col is None or source_end_col == -1
        else source_end_col
    )

    # Extract text
    if source_start_line == source_end_line:
        # Single line extraction
        extracted_text = lines[start_line_idx][start_col:end_col]
    else:
        # Multi-line extraction
        parts = []
        # First line: from start_col to end
        parts.append(lines[start_line_idx][start_col:])
        # Middle lines: full lines
        parts.extend(lines[start_line_idx + 1 : end_line_idx])
        # Last line: from beginning to end_col
        parts.append(lines[end_line_idx][:end_col])
        extracted_text = "\n".join(parts)

    return extracted_text, eol


def _insert_at_target(
    target_lines: list[str],
    target_line: int,
    target_col: int | None,
    text_to_insert: str,
) -> tuple[list[str], int, int] | str:
    """Insert text at target location.

    Returns:
        Tuple of (modified_lines, start_line, end_line) or error message

    """
    total_lines = len(target_lines)

    # Handle EOF insertion
    if target_line == -1:
        target_line = total_lines + 1

    # Validate target line
    if target_line < 1 or target_line > total_lines + 1:
        return f"target_line ({target_line}) out of range (1 to {total_lines + 1})"

    # Line-only mode (col is None)
    if target_col is None:
        insert_lines = text_to_insert.rstrip("\n").split("\n")
        insert_idx = target_line - 1

        # Insert as new lines
        modified_lines = target_lines[:insert_idx] + insert_lines + target_lines[insert_idx:]
        return modified_lines, target_line, target_line + len(insert_lines) - 1

    # Row+col mode: insert at character position
    if target_line > total_lines:
        return f"target_line ({target_line}) exceeds file length ({total_lines})"

    target_line_idx = target_line - 1
    target_line_text = target_lines[target_line_idx]

    # Validate column
    col_error = validate_col(target_col, len(target_line_text))
    if col_error:
        return col_error

    # Resolve column position
    col_pos = len(target_line_text) if target_col == -1 else target_col

    # Insert at character position
    modified_line = target_line_text[:col_pos] + text_to_insert + target_line_text[col_pos:]
    target_lines[target_line_idx] = modified_line

    return target_lines, target_line, target_line


def _validate_and_cache_sources(
    ops: list[tuple[int, CopyPasteOp, Path, Path]],
) -> tuple[dict[tuple[Path, int, int | None, int, int | None], tuple[str, str]], list[FailedOp]]:
    """Validate all source files and cache extracted text.

    Returns:
        Tuple of (source_cache, failed_ops) where source_cache maps
        (source_path, start_line, start_col, end_line, end_col) to (text, eol)

    """
    source_cache: dict[tuple[Path, int, int | None, int, int | None], tuple[str, str]] = {}
    failed_ops: list[FailedOp] = []

    # Build dict of unique source ranges (keyed by source_key to avoid hashing ops)
    unique_sources: dict[
        tuple[Path, int, int | None, int, int | None], tuple[int, CopyPasteOp]
    ] = {}
    for idx, op, source_path, _target_path in ops:
        source_key = (
            source_path,
            op.source_start_line,
            op.source_start_col,
            op.source_end_line,
            op.source_end_col,
        )
        if source_key not in unique_sources:
            unique_sources[source_key] = (idx, op)

    # Extract and cache each unique source range once
    for source_key, (idx, _op) in unique_sources.items():
        if source_key in source_cache:
            continue  # Already cached

        result = _extract_source_text(
            source_key[0],  # source_path
            source_key[1],  # source_start_line
            source_key[2],  # source_start_col
            source_key[3],  # source_end_line
            source_key[4],  # source_end_col
        )

        if isinstance(result, str):  # Error
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=str(source_key[0]),
                    reason=f"Failed to extract source text: {result}",
                ),
            )
            continue

        text, eol = result
        source_cache[source_key] = (text, eol)

    return source_cache, failed_ops


def edit_file_copy_paste_text(ops: list[dict[str, Any]], workspace_root: Path) -> dict[str, Any]:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Copy text from source locations and paste to targets atomically.

    Args:
        ops: List of CopyPasteOp dicts
        workspace_root: Workspace root path for resolution and security

    Returns:
        BatchResponse dict with status and operation results

    Behavior:
        - Source files must exist (read-only, never modified)
        - Target files must exist (fail if missing, no creation)
        - Pure insertion only (no overwrite/replace semantics)
        - Line-only mode (all col=None): Copy full lines, insert as new lines
        - Row+col mode: Character-precise copy/paste
        - Source text cached (read once per unique source range)
        - For same-file targets: coordinates refer to ORIGINAL state
        - Operations applied bottom-to-top per target file

    """
    # Phase 1: Validate all operations and resolve paths
    validated_ops: list[tuple[int, CopyPasteOp, Path, Path]] = []
    failed_ops: list[FailedOp] = []

    for idx, op_dict in enumerate(ops):
        try:
            copy_op = CopyPasteOp.model_validate(op_dict)
        except (ValueError, TypeError) as e:
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=op_dict.get("source_path", "<unknown>"),
                    reason=f"Invalid operation: {e}",
                ),
            )
            continue

        # Resolve source path
        source_result = resolve_file_path(copy_op.source_path, workspace_root)
        if isinstance(source_result, dict):
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=copy_op.source_path,
                    reason=source_result["error"],
                ),
            )
            continue

        # Resolve target path (must exist)
        target_result = resolve_file_path(copy_op.target_path, workspace_root)
        if isinstance(target_result, dict):
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=copy_op.target_path,
                    reason=f"Target file not found: {target_result['error']}",
                ),
            )
            continue

        validated_ops.append((idx, copy_op, source_result, target_result))

    if failed_ops:
        return BatchResponse(
            status="failed",
            failed_ops=failed_ops,
        ).model_dump(exclude_none=True)

    # Phase 2: Cache source text (read once per unique range)
    source_cache, cache_errors = _validate_and_cache_sources(validated_ops)

    if cache_errors:
        return BatchResponse(
            status="failed",
            failed_ops=cache_errors,
        ).model_dump(exclude_none=True)

    # Phase 3: Group operations by target file
    ops_by_target: dict[Path, list[tuple[int, CopyPasteOp, Path]]] = {}
    for idx, copy_op, source_path, target_path in validated_ops:
        if target_path not in ops_by_target:
            ops_by_target[target_path] = []
        ops_by_target[target_path].append((idx, copy_op, source_path))

    # Phase 4: Apply insertions bottom-to-top per target file
    all_applied_ops: list[AppliedOp] = []
    original_contents: dict[Path, bytes] = {}
    target_mtimes: dict[Path, float] = {}

    for target_path, target_ops in ops_by_target.items():
        # Backup original content
        try:
            original_contents[target_path] = target_path.read_bytes()
        except OSError as e:
            # Rollback any files we've modified
            for path, backup in original_contents.items():
                with contextlib.suppress(OSError):
                    path.write_bytes(backup)

            return BatchResponse(
                status="failed",
                failed_ops=[
                    FailedOp(
                        index=target_ops[0][0],
                        filepath=str(target_path),
                        reason=f"Failed to backup file: {e}",
                    ),
                ],
            ).model_dump(exclude_none=True)

        # Read target file
        target_data = read_file_with_metadata(target_path)
        if "error" in target_data:
            # Rollback
            for path, backup in original_contents.items():
                with contextlib.suppress(OSError):
                    path.write_bytes(backup)

            return BatchResponse(
                status="failed",
                failed_ops=[
                    FailedOp(
                        index=target_ops[0][0],
                        filepath=str(target_path),
                        reason=target_data["error"],
                    ),
                ],
            ).model_dump(exclude_none=True)

        target_content = target_data["content"]
        target_eol = target_data["eol"]
        target_mtimes[target_path] = target_data["mtime"]
        target_lines = target_content.split("\n")

        # Sort operations by target_line descending (bottom-to-top)
        sorted_ops = sorted(
            target_ops,
            key=lambda x: x[1].target_line if x[1].target_line != -1 else float("inf"),
            reverse=True,
        )

        # Apply each insertion
        for idx, copy_op, source_path in sorted_ops:
            # Get cached source text
            source_key = (
                source_path,
                copy_op.source_start_line,
                copy_op.source_start_col,
                copy_op.source_end_line,
                copy_op.source_end_col,
            )

            if source_key not in source_cache:
                # This shouldn't happen (already cached), but handle gracefully
                # Rollback
                for path, backup in original_contents.items():
                    with contextlib.suppress(OSError):
                        path.write_bytes(backup)

                return BatchResponse(
                    status="failed",
                    failed_ops=[
                        FailedOp(
                            index=idx,
                            filepath=str(source_path),
                            reason="Source text not in cache (internal error)",
                        ),
                    ],
                ).model_dump(exclude_none=True)

            text_to_insert, _source_eol = source_cache[source_key]

            # Insert at target
            result = _insert_at_target(
                target_lines,
                copy_op.target_line,
                copy_op.target_col,
                text_to_insert,
            )

            if isinstance(result, str):  # Error
                # Rollback
                for path, backup in original_contents.items():
                    with contextlib.suppress(OSError):
                        path.write_bytes(backup)

                return BatchResponse(
                    status="failed",
                    failed_ops=[
                        FailedOp(
                            index=idx,
                            filepath=str(target_path),
                            reason=result,
                        ),
                    ],
                ).model_dump(exclude_none=True)

            target_lines, start_line, end_line = result

            # Extract context for this operation
            context_lines, context_start = extract_context(target_lines, start_line, end_line)
            formatted_context = "\n".join(context_lines)

            all_applied_ops.append(
                AppliedOp(
                    index=idx,
                    filepath=str(target_path),
                    start_line=start_line,
                    end_line=end_line,
                    new_context=formatted_context,
                    bytes_written=None,
                ),
            )


        # Phase 5: Check mtime, then write modified target file atomically
        mtime_error = check_mtime(target_path, target_mtimes[target_path])
        if mtime_error:
            # Rollback
            for path, backup in original_contents.items():
                with contextlib.suppress(OSError):
                    path.write_bytes(backup)

            return BatchResponse(
                status="failed",
                failed_ops=[
                    FailedOp(
                        index=target_ops[0][0],
                        filepath=str(target_path),
                        reason=mtime_error,
                    ),
                ],
            ).model_dump(exclude_none=True)


        new_content = "\n".join(target_lines)
        write_error = atomic_write(target_path, new_content, eol=target_eol)
        if write_error:
            # Rollback
            for path, backup in original_contents.items():
                with contextlib.suppress(OSError):
                    path.write_bytes(backup)

            return BatchResponse(
                status="failed",
                failed_ops=[
                    FailedOp(
                        index=target_ops[0][0],
                        filepath=str(target_path),
                        reason=write_error["error"],
                    ),
                ],
            ).model_dump(exclude_none=True)

    # Success: sort by original index
    all_applied_ops.sort(key=lambda op: op.index)

    return BatchResponse(
        status="applied",
        applied_ops=all_applied_ops,
    ).model_dump(exclude_none=True)
