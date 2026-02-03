"""File helper utilities for MCP tools.

Common file operations for reading, writing, and validating files.
"""

from pathlib import Path


def _try_read_file(file_path: Path) -> dict[str, str]:
    """Attempt to read file and return content or error.

    Returns:
        dict with either 'content' or 'error' key

    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": f"File is not valid UTF-8: {file_path}"}
    except FileNotFoundError:
        return {"error": f"File not found: {file_path}"}
    except PermissionError:
        return {"error": f"Permission denied: {file_path}"}
    except OSError as e:
        return {"error": f"Failed to read file: {e}"}
    else:
        return {"content": content}


def normalize_eol(text: str, target_eol: str) -> str:
    """Normalize line endings in text to target EOL style.

    Args:
        text: Text with any line ending style
        target_eol: Target EOL style (Unix, Windows, or old Mac)

    Returns:
        Text with normalized line endings

    """
    # First normalize to \n
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # Then convert to target EOL if not \n
    if target_eol == "\r\n":
        return normalized.replace("\n", "\r\n")
    if target_eol == "\r":
        return normalized.replace("\n", "\r")

    return normalized


def detect_eol(content: str) -> str:
    """Detect the line ending style used in content.

    Args:
        content: File content

    Returns:
        Detected EOL (CRLF, LF, or CR). Defaults to LF if no line endings found

    """
    if "\r\n" in content:
        return "\r\n"
    if "\n" in content:
        return "\n"
    if "\r" in content:
        return "\r"
    return "\n"  # Default to Unix


def read_file_with_metadata(file_path: Path) -> dict:
    """Read file and return content with metadata.

    Args:
        file_path: Path to file

    Returns:
        dict with:
        - content: str - File content as UTF-8 text
        - mtime: float - File modification time
        - eol: str - Detected line ending style
        - error: str - Error message if read failed

    """
    read_result = _try_read_file(file_path)
    if "error" in read_result:
        return read_result

    content = read_result["content"]

    try:
        mtime = file_path.stat().st_mtime
    except OSError as e:
        return {"error": f"Failed to get file metadata: {e}"}

    eol = detect_eol(content)

    # Check for tabs in leading whitespace
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        if line and line[0] == "\t":
            return {
                "error": f"File contains tab in leading whitespace at line {i}. "
                "Please convert tabs to spaces before editing.",
            }
        # Check for tabs after spaces at line start
        stripped = line.lstrip(" ")
        if stripped and stripped[0] == "\t":
            return {
                "error": f"File contains mixed spaces and tabs in leading whitespace at line {i}. "
                "Please convert tabs to spaces before editing.",
            }

    return {
        "content": content,
        "mtime": mtime,
        "eol": eol,
    }


def resolve_file_path(file_path: str, workspace_root: Path) -> Path | dict:
    """Resolve and validate a file path.

    Args:
        file_path: Workspace-relative or absolute path
        workspace_root: Workspace root for security validation

    Returns:
        Resolved Path if successful, or error dict with 'error' key

    """
    # Convert to Path
    path = Path(file_path)

    # Resolve to absolute path
    if not path.is_absolute():
        path = workspace_root / path

    try:
        path = path.resolve()
    except (OSError, RuntimeError) as e:
        return {"error": f"Failed to resolve path: {e}"}

    # Security: ensure path is within workspace
    try:
        path.relative_to(workspace_root)
    except ValueError:
        return {"error": f"Path is outside workspace: {file_path}"}

    # Check file exists
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    if not path.is_file():
        return {"error": f"Not a file: {file_path}"}

    return path


def resolve_path_for_create(file_path: str, workspace_root: Path) -> Path | dict:
    """Resolve a file path for creation (file doesn't need to exist).

    Args:
        file_path: Workspace-relative or absolute path
        workspace_root: Workspace root for security validation

    Returns:
        Resolved Path if successful, or error dict with 'error' key

    """
    # Convert to Path
    path = Path(file_path)

    # Resolve to absolute path
    if not path.is_absolute():
        path = workspace_root / path

    try:
        path = path.resolve()
    except (OSError, RuntimeError) as e:
        return {"error": f"Failed to resolve path: {e}"}

    # Security: ensure path is within workspace
    try:
        path.relative_to(workspace_root)
    except ValueError:
        return {"error": f"Path is outside workspace: {file_path}"}

    # Check that path is not a directory
    if path.exists() and path.is_dir():
        return {"error": f"Path is a directory: {file_path}"}

    return path


def atomic_write(file_path: Path, content: str, eol: str = "\n") -> dict | None:
    """Write content to file atomically with specified line endings.

    Args:
        file_path: Path to file
        content: Content to write
        eol: Line ending style to use (defaults to LF)

    Returns:
        None if successful, or error dict with 'error' key

    """
    # Normalize line endings
    normalized_content = normalize_eol(content, eol)

    try:
        file_path.write_text(normalized_content, encoding="utf-8")
    except PermissionError:
        return {"error": f"Permission denied: {file_path}"}
    except OSError as e:
        return {"error": f"Failed to write file: {e}"}

    return None


def validate_line_range(start_line: int, end_line: int, total_lines: int) -> str | None:
    """Validate a line range against file bounds.

    Args:
        start_line: Starting line (1-indexed, inclusive)
        end_line: Ending line (1-indexed, inclusive)
        total_lines: Total lines in file

    Returns:
        Error message if invalid, None if valid

    """
    if start_line < 1:
        return f"start_line must be >= 1, got {start_line}"
    if end_line < start_line:
        return f"end_line ({end_line}) must be >= start_line ({start_line})"
    if start_line > total_lines:
        return f"start_line ({start_line}) exceeds file length ({total_lines} lines)"
    if end_line > total_lines:
        return f"end_line ({end_line}) exceeds file length ({total_lines} lines)"
    return None


def validate_col(col: int | None, line_length: int) -> str | None:
    """Validate a column position against line bounds.

    Args:
        col: Column position (0-indexed, None=BOL, -1=EOL)
        line_length: Length of the line

    Returns:
        Error message if invalid, None if valid

    """
    if col is None:
        return None  # BOL is always valid
    if col == -1:
        return None  # EOL is always valid
    if col < 0:
        return f"col must be None, -1, or >= 0, got {col}"
    if col > line_length:
        return f"col ({col}) exceeds line length ({line_length})"
    return None


def extract_context(
    lines: list[str],
    start_line: int,
    end_line: int,
    context_before: int = 2,
    context_after: int = 2,
) -> tuple[list[str], int]:
    """Extract lines with context around a changed region.

    Args:
        lines: All lines in file (1-indexed access)
        start_line: First changed line (1-indexed)
        end_line: Last changed line (1-indexed)
        context_before: Lines of context before changed region
        context_after: Lines of context after changed region

    Returns:
        Tuple of (extracted_lines, first_line_number)

    """
    total_lines = len(lines)

    # Calculate context bounds
    first_line = max(1, start_line - context_before)
    last_line = min(total_lines, end_line + context_after)

    # Extract lines (convert to 0-indexed for slicing)
    extracted = lines[first_line - 1 : last_line]

    return extracted, first_line


def group_ops_by_file(ops: list[tuple[int, dict, Path]]) -> dict[Path, list[tuple[int, dict]]]:
    """Group operations by target file path.

    Args:
        ops: List of (original_index, op_dict, resolved_path) tuples

    Returns:
        Dict mapping Path to list of (original_index, op_dict) tuples

    """
    grouped: dict[Path, list[tuple[int, dict]]] = {}
    for idx, op_dict, path in ops:
        if path not in grouped:
            grouped[path] = []
        grouped[path].append((idx, op_dict))
    return grouped


def sort_ops_for_application(
    ops: list[tuple[int, dict]], line_key: str = "line"
) -> list[tuple[int, dict]]:
    """Sort operations by line number in descending order (bottom-to-top application).

    Args:
        ops: List of (original_index, op_dict) tuples
        line_key: Key in op_dict that contains the line number

    Returns:
        Sorted list in descending line order

    """
    return sorted(ops, key=lambda x: x[1].get(line_key, 0), reverse=True)


def format_context_with_line_numbers(lines: list[str], start_line: int) -> list[str]:
    """Format lines with line numbers for display.

    Args:
        lines: List of lines (without trailing newlines)
        start_line: Starting line number (1-indexed)

    Returns:
        List of formatted lines like "  1 | content"

    """
    if not lines:
        return []

    # Calculate padding based on last line number
    last_line = start_line + len(lines) - 1
    padding = len(str(last_line))

    formatted = []
    for i, line in enumerate(lines):
        line_num = start_line + i
        formatted.append(f"{line_num:>{padding}} | {line}")

    return formatted
