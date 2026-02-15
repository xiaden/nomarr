"""Replace a content range identified by boundary text instead of line numbers.

This tool solves the "stale line numbers" problem: because line numbers shift
after every edit, using them as edit coordinates is fragile.  Instead, the
caller supplies *content boundaries* — text that marks the beginning and end
of the region to replace — plus an expected line count for safety.
"""

from __future__ import annotations

from pathlib import Path

from mcp_code_intel.helpers.content_boundaries import find_content_boundaries
from mcp_code_intel.helpers.file_helpers import (
    atomic_write,
    build_content,
    build_new_context,
    check_mtime,
    ensure_trailing_newline,
    read_file_with_metadata,
    resolve_file_path,
)
from mcp_code_intel.response_models import AppliedOp, BatchResponse, FailedOp


def edit_file_replace_by_content(
    file_path: str,
    start_boundary: str,
    end_boundary: str,
    expected_line_count: int,
    new_content: str,
    workspace_root: Path,
) -> dict:
    """Replace a range of lines identified by content boundaries.

    The range is located by finding the *start_boundary* and *end_boundary*
    text in the file.  Both boundaries are inclusive — they and everything
    between them are replaced by *new_content*.

    Args:
        file_path: Workspace-relative or absolute path to the file.
        start_boundary: Text that marks the beginning of the range.  May be
            multi-line (separated by ``\n``).  Each line is stripped and
            matched as a substring.
        end_boundary: Text that marks the end of the range.  Same rules as
            *start_boundary*.
        expected_line_count: Exact number of lines the matched range must
            span (inclusive of boundary lines).  Acts as a safety check —
            the tool fails if the actual count differs.
        new_content: Replacement text.  Replaces the *entire* matched range
            including boundary lines.
        workspace_root: Workspace root for path resolution and security.

    Returns:
        A ``BatchResponse`` dict.

    """
    resolved = resolve_file_path(file_path, workspace_root)
    if isinstance(resolved, dict):
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(index=0, filepath=file_path, reason=resolved["error"]),
            ],
        ).model_dump(exclude_none=True)

    file_path_obj: Path = resolved
    rel_path = str(file_path_obj.relative_to(workspace_root))

    # Read file ----------------------------------------------------------------
    file_data = read_file_with_metadata(file_path_obj)
    if "error" in file_data:
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(index=0, filepath=rel_path, reason=file_data["error"]),
            ],
        ).model_dump(exclude_none=True)

    content = file_data["content"]
    original_mtime = file_data["mtime"]
    original_eol = file_data["eol"]
    had_trailing_newline = content.endswith(("\n", "\r"))

    # Split into lines ---------------------------------------------------------
    lines = content.splitlines(keepends=True)
    lines = ensure_trailing_newline(lines)

    # Also build a stripped-line list for boundary matching
    plain_lines = [ln.rstrip("\n").rstrip("\r") for ln in lines]

    # Find boundaries ----------------------------------------------------------
    match_result = find_content_boundaries(
        plain_lines,
        start_boundary,
        end_boundary,
        expected_line_count,
    )

    if isinstance(match_result, str):
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(index=0, filepath=rel_path, reason=match_result),
            ],
        ).model_dump(exclude_none=True)

    start_line, end_line = match_result  # 1-indexed inclusive

    # Build replacement --------------------------------------------------------
    new_lines = new_content.splitlines(keepends=True)
    new_lines = ensure_trailing_newline(new_lines)
    new_line_count = len(new_lines)

    result_lines = lines[: start_line - 1] + new_lines + lines[end_line:]
    new_file_content = build_content(
        result_lines, had_trailing_newline=had_trailing_newline,
    )

    if new_file_content == content:
        return BatchResponse(
            status="applied", applied_ops=[],
        ).model_dump(exclude_none=True)

    # mtime guard --------------------------------------------------------------
    mtime_error = check_mtime(file_path_obj, original_mtime)
    if mtime_error:
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(index=0, filepath=rel_path, reason=mtime_error),
            ],
        ).model_dump(exclude_none=True)

    # Write atomically ---------------------------------------------------------
    write_error = atomic_write(file_path_obj, new_file_content, eol=original_eol)
    if write_error:
        return BatchResponse(
            status="failed",
            failed_ops=[
                FailedOp(
                    index=0, filepath=rel_path, reason=write_error["error"],
                ),
            ],
        ).model_dump(exclude_none=True)

    # Context for confirmation -------------------------------------------------
    final_start = start_line
    final_end = start_line + new_line_count - 1
    context = build_new_context(result_lines, final_start, final_end)

    applied_op = AppliedOp(
        index=0,
        filepath=str(file_path_obj),
        start_line=final_start,
        end_line=final_end,
        new_context=context,
        bytes_written=len(new_file_content.encode("utf-8")),
    )

    return BatchResponse(
        status="applied", applied_ops=[applied_op],
    ).model_dump(exclude_none=True)
