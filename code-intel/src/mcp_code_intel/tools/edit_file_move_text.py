"""Move text tool.

Extract lines from one location and insert them at another.
Supports both same-file moves and cross-file moves.
"""

from pathlib import Path

from ..helpers.file_helpers import (
    build_content,
    check_mtime,
    ensure_trailing_newline,
    normalize_eol,
    read_file_with_metadata,
    resolve_file_path,
)


def _validate_source_range(
    source_start: int,
    source_end: int,
    total_lines: int,
) -> dict | None:
    """Validate source line range. Returns error dict or None if valid."""
    if source_start < 1:
        return {"error": f"source_start must be >= 1, got {source_start}"}
    if source_end < source_start:
        return {"error": f"source_end ({source_end}) must be >= source_start ({source_start})"}
    if source_start > total_lines:
        return {"error": f"source_start ({source_start}) exceeds file length ({total_lines} lines)"}
    if source_end > total_lines:
        return {"error": f"source_end ({source_end}) exceeds file length ({total_lines} lines)"}
    return None


def _validate_target_line(
    target_line: int,
    total_lines: int,
) -> dict | None:
    """Validate target line. Returns error dict or None if valid."""
    if target_line < 1:
        return {"error": f"target_line must be >= 1, got {target_line}"}
    # target_line can be total_lines + 1 to append at end
    if target_line > total_lines + 1:
        return {"error": f"target_line ({target_line}) exceeds file length + 1 ({total_lines + 1})"}
    return None


def _extract_lines(lines: list[str], start: int, end: int) -> list[str]:
    """Extract lines from start to end (1-indexed, inclusive)."""
    return lines[start - 1 : end]


def _remove_lines(lines: list[str], start: int, end: int) -> list[str]:
    """Remove lines from start to end (1-indexed, inclusive)."""
    return lines[: start - 1] + lines[end:]


def _insert_lines(lines: list[str], insert_before: int, new_lines: list[str]) -> list[str]:
    """Insert new_lines before insert_before (1-indexed)."""
    idx = insert_before - 1
    return lines[:idx] + new_lines + lines[idx:]


def _perform_same_file_move(
    lines: list[str],
    source_start: int,
    source_end: int,
    target_line: int,
) -> tuple[list[str], int]:
    """Extract lines from source and insert at target in same file.

    Returns:
        Tuple of (modified lines, actual insertion line in final file)
    """
    # Extract the lines to move
    lines_to_move = _extract_lines(lines, source_start, source_end)

    # Remove from source location
    result = _remove_lines(lines, source_start, source_end)

    # Adjust target index if it was after the source
    adjusted_target = target_line
    if target_line > source_end:
        adjusted_target -= source_end - source_start + 1

    # Insert at target location
    return _insert_lines(result, adjusted_target, lines_to_move), adjusted_target



def _generate_context(lines: list[str], target_line: int, context_lines: int = 2) -> str:
    """Generate context showing lines around target insertion point.

    Args:
        lines: File lines after the move operation
        target_line: Line where content was inserted (1-indexed)
        context_lines: Number of lines to show before/after (default: 2)

    Returns:
        Formatted string with line numbers and content
    """
    start = max(1, target_line - context_lines)
    end = min(len(lines), target_line + context_lines)

    context_parts = []
    for i in range(start - 1, end):
        line_num = i + 1
        line_content = lines[i].rstrip('\n\r')
        context_parts.append(f"   {line_num:3d} | {line_content}")

    return "\n".join(context_parts)


def _same_file_move(
    file_path: str,
    source_start: int,
    source_end: int,
    target_line: int,
    workspace_root: Path,
) -> dict:
    """Move lines within a single file."""
    # Resolve and validate path
    resolved = resolve_file_path(file_path, workspace_root)
    if isinstance(resolved, dict):
        resolved["changed"] = False
        return resolved
    source_path = resolved
    rel_path = str(source_path.relative_to(workspace_root))

    # Read file with metadata
    file_data = read_file_with_metadata(source_path)
    if "error" in file_data:
        file_data["changed"] = False
        return file_data

    content = file_data["content"]
    original_mtime = file_data["mtime"]
    had_trailing_newline = content.endswith(("\n", "\r"))

    lines = content.splitlines(keepends=True)
    lines = ensure_trailing_newline(lines)
    total_lines = len(lines)

    # Validate ranges
    source_error = _validate_source_range(source_start, source_end, total_lines)
    if source_error:
        source_error["changed"] = False
        return source_error

    target_error = _validate_target_line(target_line, total_lines)
    if target_error:
        target_error["changed"] = False
        return target_error

    # Check if target is within source range (no-op)
    if source_start <= target_line <= source_end + 1:
        return {
            "path": rel_path,
            "changed": False,
            "lines_moved": 0,
            "source_range": {"start": source_start, "end": source_end},
            "target_line": target_line,
            "note": "Target is within source range - no change needed",
        }

    # Perform the move
    new_lines, actual_target = _perform_same_file_move(lines, source_start, source_end, target_line)
    new_content = build_content(new_lines, had_trailing_newline=had_trailing_newline)

    # Check mtime before write
    mtime_error = check_mtime(source_path, original_mtime)
    if mtime_error:
        return {"error": mtime_error, "changed": False}

    # Check if content actually changed
    if new_content == content:
        return {
            "path": rel_path,
            "changed": False,
            "lines_moved": 0,
            "source_range": {"start": source_start, "end": source_end},
            "target_line": target_line,
            "note": "Move resulted in identical content",
        }

    # Write
    source_path.write_bytes(new_content.encode("utf-8"))

    # Generate context showing the result at actual insertion location
    context = _generate_context(new_lines, actual_target)

    return {
        "path": rel_path,
        "changed": True,
        "lines_moved": source_end - source_start + 1,
        "source_range": {"start": source_start, "end": source_end},
        "target_line": target_line,
        "new_context": context,
    }


def _cross_file_move(
    source_file: str,
    source_start: int,
    source_end: int,
    target_file: str,
    target_line: int,
    workspace_root: Path,
) -> dict:
    """Move lines from one file to another."""
    # Resolve source path
    resolved_source = resolve_file_path(source_file, workspace_root)
    if isinstance(resolved_source, dict):
        resolved_source["changed"] = False
        return resolved_source
    source_path = resolved_source
    source_rel = str(source_path.relative_to(workspace_root))

    # Resolve target path
    resolved_target = resolve_file_path(target_file, workspace_root)
    target_created = False

    if isinstance(resolved_target, dict):
        # Target doesn't exist - try to resolve for creation
        from ..helpers.file_helpers import resolve_path_for_create

        create_result = resolve_path_for_create(target_file, workspace_root)
        if isinstance(create_result, dict):
            create_result["changed"] = False
            return create_result

        target_path = create_result
        target_rel = str(target_path.relative_to(workspace_root))
        target_created = True

        # Create empty target file
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"")

        # Initialize target as empty
        target_content = ""
        target_mtime = target_path.stat().st_mtime
        target_eol = "\n"
        target_had_trailing = False
        target_lines = []
    else:
        target_path = resolved_target
        target_rel = str(target_path.relative_to(workspace_root))

        # Read existing target file
        target_data = read_file_with_metadata(target_path)
        if "error" in target_data:
            target_data["changed"] = False
            return target_data

        target_content = target_data["content"]
        target_mtime = target_data["mtime"]
        target_eol = target_data["eol"]
        target_had_trailing = target_content.endswith(("\n", "\r"))

        target_lines = target_content.splitlines(keepends=True)
        target_lines = ensure_trailing_newline(target_lines)
    # Read source file
    source_data = read_file_with_metadata(source_path)
    if "error" in source_data:
        source_data["changed"] = False
        return source_data

    source_content = source_data["content"]
    source_mtime = source_data["mtime"]
    source_had_trailing = source_content.endswith(("\n", "\r"))

    source_lines = source_content.splitlines(keepends=True)
    source_lines = ensure_trailing_newline(source_lines)
    source_total = len(source_lines)

    target_total = len(target_lines)

    # Validate source range
    source_error = _validate_source_range(source_start, source_end, source_total)
    if source_error:
        source_error["changed"] = False
        return source_error

    # Validate target line
    target_error = _validate_target_line(target_line, target_total)
    if target_error:
        target_error["changed"] = False
        return target_error

    # Extract lines from source
    lines_to_move = _extract_lines(source_lines, source_start, source_end)

    # Normalize extracted lines to target file's EOL style
    normalized_lines = [normalize_eol(line, target_eol) for line in lines_to_move]

    # Build new source content (lines removed)
    new_source_lines = _remove_lines(source_lines, source_start, source_end)
    new_source_content = build_content(new_source_lines, had_trailing_newline=source_had_trailing)

    # Build new target content (lines inserted)
    new_target_lines = _insert_lines(target_lines, target_line, normalized_lines)
    new_target_content = build_content(new_target_lines, had_trailing_newline=target_had_trailing)

    # Check both mtimes BEFORE writing either file
    source_mtime_error = check_mtime(source_path, source_mtime)
    if source_mtime_error:
        return {"error": source_mtime_error, "changed": False}

    # Only check target mtime if file existed (not if we just created it)
    if not target_created:
        target_mtime_error = check_mtime(target_path, target_mtime)
        if target_mtime_error:
            return {"error": target_mtime_error, "changed": False}

    # Write target first (if failure, we have duplication not loss)
    target_path.write_bytes(new_target_content.encode("utf-8"))

    # Write source second
    source_path.write_bytes(new_source_content.encode("utf-8"))

    # Generate context showing the result at target location
    context = _generate_context(new_target_lines, target_line)

    result = {
        "source_file": source_rel,
        "target_file": target_rel,
        "changed": True,
        "lines_moved": source_end - source_start + 1,
        "source_range": {"start": source_start, "end": source_end},
        "target_line": target_line,
        "target_created": target_created,
        "new_context": context,
    }

    if target_created:
        result["warnings"] = [f"Created new file: {target_rel}"]

    return result


def edit_file_move_text(
    file_path: str,
    source_start: int,
    source_end: int,
    target_line: int,
    workspace_root: Path,
    target_file: str | None = None,
) -> dict:
    """Move lines from one location to another within a file or across files.

    Extracts lines source_start through source_end (inclusive, 1-indexed)
    and inserts them before target_line. The operation is atomic per file -
    each file is only written once after all changes are computed in memory.

    Args:
        file_path: Workspace-relative or absolute path to the source file
        source_start: First line to move (1-indexed, inclusive)
        source_end: Last line to move (1-indexed, inclusive)
        target_line: Line number where extracted text will be inserted
                     (inserted BEFORE this line; use line_count+1 to append)
        workspace_root: Path to workspace root for security validation
        target_file: Optional path to target file. If None or same as file_path,
                     performs same-file move. If different, moves lines from
                     file_path to target_file.

    Returns:
        dict with:
        - changed: bool - whether files were modified
        - lines_moved: Number of lines moved
        - source_range: {start, end} - original location in source
        - target_line: Line number where text was inserted
        - new_context: Formatted context (2 lines before/after target location)
        - path: (same-file only) The file path
        - source_file, target_file: (cross-file only) Both file paths
        - error: Error message if operation fails

    For cross-file moves:
        - Target file must exist (use create_file first)
        - Lines are normalized to target file's EOL style
        - Target is written first, then source (duplication > loss on failure)

    """
    # Determine if this is a same-file or cross-file move
    if target_file is None or target_file == file_path:
        return _same_file_move(
            file_path=file_path,
            source_start=source_start,
            source_end=source_end,
            target_line=target_line,
            workspace_root=workspace_root,
        )

    return _cross_file_move(
        source_file=file_path,
        source_start=source_start,
        source_end=source_end,
        target_file=target_file,
        target_line=target_line,
        workspace_root=workspace_root,
    )
