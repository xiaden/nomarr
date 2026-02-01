"""Read file tool - minimal fallback for non-Python files.

Deliberately second-class to encourage AST-based tools for Python code.
"""

__all__ = ["file_read_range"]

import ast
from pathlib import Path

from scripts.mcp.tools.helpers.file_lines import read_raw_line_range
from scripts.mcp.tools.helpers.semantic_tool_examples import get_semantic_tool_examples


def _find_imports_end(all_lines: list[str]) -> int:
    """Find the last line of the imports block at the top of a Python file.

    Returns the 1-indexed line number of the last import statement,
    or 0 if no imports found.
    """
    # Join and parse to find import statements
    content = "".join(all_lines)
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return 0

    last_import_line = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # end_lineno is the last line of this import statement
            end = getattr(node, "end_lineno", node.lineno)
            last_import_line = max(last_import_line, end)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            # Skip module docstrings at the top
            continue
        elif last_import_line > 0:
            # First non-import after imports - stop
            break

    return last_import_line


def file_read_range(
    file_path: str,
    start_line: int,
    end_line: int,
    workspace_root: Path,
    *,
    include_imports: bool = False,
) -> dict:
    """Read a specific line range from any file in the workspace.

    Fallback tool for non-Python files or when AST-based tools fail.
    Returns raw file contents without parsing.

    Maximum 100 lines per read. Only returns 'end' field when clamped.

    Args:
        file_path: Workspace-relative or absolute path to the file
        start_line: Starting line number (1-indexed, inclusive)
        end_line: Ending line number (1-indexed, inclusive)
        include_imports: If True and file is Python, prepend the imports block
            (plus 2 lines of context) to the output. Useful for debugging
            undefined symbol errors. Merges with requested range if overlapping.

    Returns:
        dict with:
        - path: The resolved workspace-relative path
        - requested: {content, start, end} - The requested lines
        - imports: {content, start, end} - Imports block (only when non-overlapping)
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

        # Handle include_imports for Python files
        imports_included = False
        effective_start = start_line
        if include_imports and target_path.suffix == ".py":
            imports_end = _find_imports_end(all_lines)
            if imports_end > 0:
                # Add 2 lines of context after imports
                imports_block_end = min(imports_end + 2, total_lines)
                # Merge if overlapping, otherwise prepend
                if imports_block_end >= start_line:
                    # Overlapping - extend start to include imports
                    effective_start = 1
                else:
                    # Non-overlapping - will read both ranges
                    effective_start = 1
                imports_included = True

        # Extract requested lines using raw bytes (preserves exact line endings)
        if imports_included and effective_start == 1 and start_line > 1:
            imports_end = _find_imports_end(all_lines)
            imports_block_end = min(imports_end + 2, total_lines)
            if imports_block_end < start_line:
                # Non-overlapping: return both ranges as separate structured blocks
                imports_content = read_raw_line_range(str(target_path), 1, imports_block_end)
                main_content = read_raw_line_range(str(target_path), start_line, actual_end)

                result: dict = {
                    "path": str(target_path.relative_to(workspace_root)),
                    "imports": {"content": imports_content, "start": 1, "end": imports_block_end},
                    "requested": {"content": main_content, "start": start_line, "end": actual_end},
                }

                if warning:
                    result["warning"] = warning

                if target_path.suffix == ".py":
                    result["semantic_tools_available"] = {
                        "hint": "Python files: semantic tools provide structured output",
                        "example_outputs": get_semantic_tool_examples(),
                    }

                return result
            # Overlapping: single contiguous read from line 1
            result_content = read_raw_line_range(str(target_path), 1, actual_end)
        else:
            result_content = read_raw_line_range(str(target_path), start_line, actual_end)

        # Build minimal response
        result = {
            "path": str(target_path.relative_to(workspace_root)),
            "requested": {"content": result_content, "start": start_line, "end": actual_end},
        }

        # Add warning if lines were reversed
        if warning:
            result["warning"] = warning

        # Add Python file semantic tool guidance
        if target_path.suffix == ".py":
            result["semantic_tools_available"] = {
                "hint": "Python files: semantic tools provide structured output",
                "example_outputs": get_semantic_tool_examples(),
            }

        return result

    except UnicodeDecodeError:
        return {"error": f"File is not valid UTF-8: {file_path}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
