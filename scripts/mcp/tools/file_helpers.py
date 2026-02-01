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
