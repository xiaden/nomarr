"""Read single line with context - quick inspection tool.

Deliberately simple for error investigation and search result inspection.
"""

__all__ = ["read_line"]

from pathlib import Path


def read_line(file_path: str, line_number: int, workspace_root: Path) -> dict:
    """Read a single line with 2 lines of context before and after.

    Quick inspection tool for error messages, search results, and spot checks.
    For Python code analysis, prefer discover_api, get_source, or locate_symbol.

    Args:
        file_path: Workspace-relative or absolute path to the file
        line_number: Line number to read (1-indexed)
        workspace_root: Project root path

    Returns:
        dict with:
        - path: The resolved workspace-relative path
        - content: 5 lines (2 before, target, 2 after) or fewer at file boundaries
        - line_range: Actual range returned (e.g., "48-52" or "1-3(start)" or "268-270(EOF)")
        - warning: If Python file detected
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

        # Validate line_number
        if line_number < 1:
            return {"error": f"line_number must be >= 1, got {line_number}"}

        if line_number > total_lines:
            return {"error": f"line_number {line_number} exceeds file length ({total_lines} lines)"}

        # Calculate range with 2-line context
        start = max(1, line_number - 2)
        end = min(total_lines, line_number + 2)

        # Extract lines (convert to 0-indexed)
        lines = all_lines[start - 1 : end]
        result_content = "".join(lines)

        # Build line range label
        if start == 1 and end < total_lines:
            line_range = f"{start}-{end}(start)"
        elif end == total_lines and start > 1:
            line_range = f"{start}-{end}(EOF)"
        elif start == 1 and end == total_lines:
            line_range = f"{start}-{end}(entire file)"
        else:
            line_range = f"{start}-{end}"

        # Build minimal response
        result = {
            "path": str(target_path.relative_to(workspace_root)),
            "content": result_content,
            "line_range": line_range,
        }

        # Add Python file suggestion
        if target_path.suffix == ".py":
            result["warning"] = (
                "WARNING: Reading Python files with read_line wastes tokens and loses structure. "
                "Use discover_api (module overview), locate_symbol (find definitions), or "
                "get_symbol_body_at_line (get function/class at line) instead."
            )

        return result

    except UnicodeDecodeError:
        return {"error": f"File is not valid UTF-8: {file_path}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
