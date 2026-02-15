"""Replace line range tool.

Line-anchored replace for deterministic edits when line numbers are known.
Complements string-based replace by removing ambiguity and reducing blast radius.
"""

from pathlib import Path

from ..helpers.file_helpers import (
    atomic_write,
    build_content,
    build_new_context,
    check_mtime,
    ensure_trailing_newline,
    read_file_with_metadata,
    resolve_file_path,
    validate_line_range,
)
from ..response_models import AppliedOp, BatchResponse, FailedOp


def edit_file_replace_line_range(
    file_path: str,
    start_line: int,
    end_line: int,
    new_content: str,
    workspace_root: Path,
    expected_content: str | None = None,
) -> dict:

    Line-anchored replacement for deterministic edits when line numbers are known
    from prior read operations. Removes ambiguity of string matching and reduces
    blast radius compared to large block string replacements.

    Args:
        file_path: Workspace-relative or absolute path to file
        start_line: First line to replace (1-indexed, inclusive)
        end_line: Last line to replace (1-indexed, inclusive)
        new_content: New content to insert (can be multiple lines)
        workspace_root: Path to workspace root for security validation

    Returns:
        BatchResponse dict with:
        - status: "applied" or "failed"
        - applied_ops: List with AppliedOp if successful
        - failed_ops: List with FailedOp if failed

    Behavior:
        - Atomic: validates everything before writing
        - mtime guard: fails if file changed since last read
        - Preserves file's trailing newline behavior
        - Preserves file's EOL style (CRLF/LF)
        - Returns context showing 2 lines before/after replaced region

    """
    # Resolve and validate path
    resolved = resolve_file_path(file_path, workspace_root)
    if isinstance(resolved, dict):
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(
                    index=0,
                    filepath=file_path,
                    reason=resolved["error"],
                ),
            ],
        ).model_dump(exclude_none=True)

    file_path_obj = resolved
    rel_path = str(file_path_obj.relative_to(workspace_root))

    # Read file with metadata
    file_data = read_file_with_metadata(file_path_obj)
    if "error" in file_data:
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(
                    index=0,
                    filepath=rel_path,
                    reason=file_data["error"],
                ),
            ],
        ).model_dump(exclude_none=True)

    content = file_data["content"]
    original_mtime = file_data["mtime"]
    original_eol = file_data["eol"]
    had_trailing_newline = content.endswith(("\n", "\r"))

    # Split into lines and ensure trailing newlines for consistent handling
    lines = content.splitlines(keepends=True)
    lines = ensure_trailing_newline(lines)
    total_lines = len(lines)

    # Validate range using standard helper
    range_error = validate_line_range(start_line, end_line, total_lines)
    if range_error:
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(
                    index=0,
                    filepath=rel_path,
                    reason=range_error,
                ),
            ],
        ).model_dump(exclude_none=True)

    # Parse new content into lines
    new_lines = new_content.splitlines(keepends=True)
    new_lines = ensure_trailing_newline(new_lines)
    new_line_count = len(new_lines)

    # Build new file content
    result_lines = lines[: start_line - 1] + new_lines + lines[end_line:]
    new_file_content = build_content(result_lines, had_trailing_newline=had_trailing_newline)

    # Check if content actually changed
    if new_file_content == content:
        return BatchResponse(
            status="applied",
            applied_ops=[],
        ).model_dump(exclude_none=True)

    # Check mtime before write
    mtime_error = check_mtime(file_path_obj, original_mtime)
    if mtime_error:
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(
                    index=0,
                    filepath=rel_path,
                    reason=mtime_error,
                ),
            ],
        ).model_dump(exclude_none=True)

    # Write atomically with EOL preservation
    write_error = atomic_write(file_path_obj, new_file_content, eol=original_eol)
    if write_error:
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(
                    index=0,
                    filepath=rel_path,
                    reason=write_error["error"],
                ),
            ],
        ).model_dump(exclude_none=True)

    # Calculate final line range
    final_start = start_line
    final_end = start_line + new_line_count - 1

    # Build context using standard helper
    context = build_new_context(result_lines, final_start, final_end)

    # Build response
    applied_op = AppliedOp(
        index=0,
        filepath=str(file_path_obj),
        start_line=final_start,
        end_line=final_end,
        new_context=context,
        bytes_written=len(new_file_content.encode("utf-8")),
    )

    return BatchResponse(
        status="applied",
        applied_ops=[applied_op],
    ).model_dump(exclude_none=True)
