"""file_replace MCP tool - Replace entire file contents.

Replaces entire file contents atomically. Fails if file doesn't exist.
All operations succeed or none apply (atomic batch semantics).
"""

import contextlib
import sys
from pathlib import Path

from pydantic import BaseModel, Field

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcp_code_intel.helpers.file_helpers import (
    atomic_write,
    resolve_file_path,
)
from mcp_code_intel.response_models import AppliedOp, BatchResponse, FailedOp

# Constants for context display
_MIN_LINES_FOR_SUMMARY = 2  # Minimum lines to show summary (last N lines)
_SMALL_FILE_THRESHOLD = 4  # Files with <= this many lines shown in full


class ReplaceOp(BaseModel):
    """Operation to replace entire file contents."""

    path: str = Field(description="File path to replace")
    content: str = Field(description="New file content (replaces entire file)")


def edit_file_replace_content(ops: list[ReplaceOp], workspace_root: Path) -> BatchResponse:
    """Replace entire file contents. Fails if file doesn't exist.

    Args:
        ops: List of replace operations
        workspace_root: Workspace root path for resolving relative paths

    Returns:
        BatchResponse with status='applied' or 'failed'

    Behavior:
        - Fails if any target file doesn't exist
        - Overwrites entire file contents
        - Atomic: all files replaced or none
        - Returns first 2 + last 2 lines with line numbers (not entire file)
    """
    # Phase 1: Validation - resolve paths and check files exist
    resolved_ops: list[tuple[int, ReplaceOp, Path]] = []
    failed_ops: list[FailedOp] = []
    seen_paths: dict[str, int] = {}  # Absolute path -> first index

    for idx, op in enumerate(ops):
        # Resolve path (requires file to exist)
        result = resolve_file_path(op.path, workspace_root)
        if isinstance(result, dict):  # Error
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=op.path,
                    reason=result["error"],
                ),
            )
            continue

        resolved_path: Path = result
        abs_path_str = str(resolved_path)

        # Check for duplicates in batch (BEFORE filesystem interaction)
        if abs_path_str in seen_paths:
            first_idx = seen_paths[abs_path_str]
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=abs_path_str,
                    reason=f"Duplicate path in batch (also at index {first_idx})",
                ),
            )
            continue

        seen_paths[abs_path_str] = idx
        resolved_ops.append((idx, op, resolved_path))

    # If any validation failed, return immediately (atomic failure)
    if failed_ops:
        return BatchResponse(
            status="failed",
            applied_ops=[],
            failed_ops=failed_ops,
        )

    # Phase 2: Staging + Commit - replace all files atomically
    applied_ops: list[AppliedOp] = []
    replaced_files: list[tuple[Path, bytes]] = []  # For rollback

    for idx, op, resolved_path in resolved_ops:
        # Backup original content for rollback
        try:
            original_content = resolved_path.read_bytes()
            replaced_files.append((resolved_path, original_content))
        except OSError as e:
            # Rollback any files we already replaced
            for path, backup_content in replaced_files:
                with contextlib.suppress(OSError):
                    path.write_bytes(backup_content)

            return BatchResponse(
                status="failed",
                applied_ops=[],
                failed_ops=[
                    FailedOp(
                        index=idx,
                        filepath=str(resolved_path),
                        reason=f"Failed to read original file: {e}",
                    ),
                ],
            )

        # Write new content atomically
        error = atomic_write(resolved_path, op.content, eol="\n")
        if error:
            # Rollback: restore all files we've replaced
            for path, backup_content in replaced_files:
                with contextlib.suppress(OSError):
                    path.write_bytes(backup_content)

            return BatchResponse(
                status="failed",
                applied_ops=[],
                failed_ops=[
                    FailedOp(
                        index=idx,
                        filepath=str(resolved_path),
                        reason=error["error"],
                    ),
                ],
            )

        # Extract context for response (first 2 + last 2 lines)
        lines = op.content.split("\n")
        if not lines or (len(lines) == 1 and lines[0] == ""):
            # Empty file
            context_lines = []
            start_line = 1
            end_line = 0
        else:
            # Get first 2 lines
            first_2 = lines[:2]
            # Get last 2 lines
            last_2 = lines[-2:] if len(lines) > _MIN_LINES_FOR_SUMMARY else []

            if len(lines) <= _SMALL_FILE_THRESHOLD:
                # File is small enough to show all lines
                context_lines = lines
                start_line = 1
                end_line = len(lines)
            else:
                # Show first 2 + last 2
                context_lines = [*first_2, "...", "", *last_2]
                start_line = 1
                end_line = len(lines)

        # Format for display
        if context_lines and "..." not in context_lines:
            formatted_context = "\n".join(context_lines)
        elif context_lines:
            # Mixed with ellipsis - format parts separately then join
            formatted_first = "\n".join(first_2)
            formatted_last = "\n".join(last_2)
            formatted_context = f"{formatted_first}\n...\n\n{formatted_last}"
        else:
            formatted_context = ""

        applied_ops.append(
            AppliedOp(
                index=idx,
                filepath=str(resolved_path),
                start_line=start_line,
                end_line=end_line,
                new_context=formatted_context,
                bytes_written=len(op.content.encode("utf-8")),
            ),
        )

    return BatchResponse(
        status="applied",
        applied_ops=applied_ops,
        failed_ops=[],
    )


# MCP tool registration
def main(ops: list[dict]) -> dict:
    """MCP tool entry point.

    Args:
        ops: List of operation dicts with 'path' and 'content'

    Returns:
        BatchResponse as dict

    """
    # Parse ops into Pydantic models
    parsed_ops = [ReplaceOp(**op) for op in ops]

    # Get workspace root (assume we're in tools/)
    workspace_root = Path(__file__).parent.parent.parent

    # Execute
    response = edit_file_replace_content(parsed_ops, workspace_root)

    return response.model_dump(exclude_none=True)


if __name__ == "__main__":
    # Test harness
    import json
    import logging

    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.DEBUG)

    # First create test files
    Path("test_replace_1.txt").write_text("Original content\n")
    Path("test_replace_2.txt").write_text("Line 1\nLine 2\nLine 3\n")

    test_ops = [
        {"path": "test_replace_1.txt", "content": "Replaced content!\n"},
        {"path": "test_replace_2.txt", "content": "New Line 1\nNew Line 2\nNew Line 3\n"},
    ]

    result = main(test_ops)
    logger.info(json.dumps(result, indent=2))

    # Cleanup
    Path("test_replace_1.txt").unlink(missing_ok=True)
    Path("test_replace_2.txt").unlink(missing_ok=True)
