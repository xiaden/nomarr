"""
Read file tool - minimal fallback for non-Python files.

Deliberately second-class to encourage AST-based tools for Python code.
"""

from pathlib import Path


def read_file(
    file_path: str,
    start_line: int,
    end_line: int,
    workspace_root: Path,
) -> dict:
    """
    Read a specific line range from any file in the workspace.

    Fallback tool for non-Python files or when AST-based tools fail.
    Returns raw file contents without parsing.

    Maximum 100 lines per read. Only returns 'end' field when clamped.

    Args:
        file_path: Workspace-relative or absolute path to the file
        start_line: Starting line number (1-indexed, inclusive)
        end_line: Ending line number (1-indexed, inclusive)

    Returns:
        dict with:
        - path: The resolved workspace-relative path
        - content: The requested lines as a string
        - end: Only present when clamped/EOF (e.g., "249(clamped)" or "270(EOF)")
        - warning: If lines were reversed or Python file detected
        - error: Error message if reading fails
    """
    try:
        # Resolve path relative to workspace root
        target_path = Path(file_path)
        if not target_path.is_absolute():
            target_path = workspace_root / file_path

        # Security check: ensure path is within workspace
        try:
            target_path = target_path.resolve()
            target_path.relative_to(workspace_root)
        except (ValueError, RuntimeError):
            return {"error": f"Path {file_path} is outside workspace root"}

        # Check file exists
        if not target_path.exists():
            return {"error": f"File not found: {file_path}"}

        if not target_path.is_file():
            return {"error": f"Path is not a file: {file_path}"}

        # Read file
        content = target_path.read_text(encoding="utf-8")
        all_lines = content.splitlines(keepends=True)
        total_lines = len(all_lines)

        # Validate start_line
        if start_line < 1:
            return {"error": f"start_line must be >= 1, got {start_line}"}

        if start_line > total_lines:
            return {"error": f"start_line {start_line} exceeds file length ({total_lines} lines)"}

        # Fix reversed line ranges
        warning = None
        if start_line > end_line:
            start_line, end_line = end_line, start_line
            warning = f"Line range reversed: was {end_line}-{start_line}, reading {start_line}-{end_line}"

        # Clamp to 100 lines max
        requested_end = end_line
        if requested_end - start_line + 1 > 100:
            requested_end = start_line + 99

        # Clamp to file length
        actual_end = min(requested_end, total_lines)

        # Extract requested lines (convert to 0-indexed)
        requested_lines = all_lines[start_line - 1 : actual_end]
        result_content = "".join(requested_lines)

        # Build minimal response
        result = {
            "path": str(target_path.relative_to(workspace_root)),
            "content": result_content,
        }

        # Add warning if lines were reversed
        if warning:
            result["warning"] = warning

        # Add Python file suggestion
        if target_path.suffix == ".py":
            suggestion = (
                "Tip: For Python files, prefer discover_api, get_source, or locate_symbol "
                "for structured code navigation instead of raw file reading."
            )
            result["warning"] = f"{warning}. {suggestion}" if warning else suggestion

        # Only include 'end' if it differs from request
        if actual_end != end_line:
            if actual_end == total_lines:
                result["end"] = f"{actual_end}(EOF)"
            else:
                result["end"] = f"{actual_end}(clamped)"

        return result

    except UnicodeDecodeError:
        return {"error": f"File is not valid UTF-8: {file_path}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
