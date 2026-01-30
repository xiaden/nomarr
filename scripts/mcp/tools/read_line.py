"""Read single line with context - quick inspection tool.

Deliberately simple for error investigation and search result inspection.
"""

__all__ = ["read_line"]

import ast
from pathlib import Path

from scripts.mcp.tools.helpers.file_lines import read_raw_line_range


def _find_imports_end(all_lines: list[str]) -> int:
    """Find the last line of the imports block at the top of a Python file.

    Returns the 1-indexed line number of the last import statement,
    or 0 if no imports found.
    """
    content = "".join(all_lines)
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return 0

    last_import_line = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            end = getattr(node, "end_lineno", node.lineno)
            last_import_line = max(last_import_line, end)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            # Skip module docstrings
            continue
        elif last_import_line > 0:
            break

    return last_import_line


def read_line(file_path: str, line_number: int, workspace_root: Path, *, include_imports: bool = False) -> dict:
    """Read a single line with 2 lines of context before and after.

    Quick inspection tool for error messages, search results, and spot checks.
    For Python code analysis, prefer discover_api, get_source, or locate_symbol.

    Args:
        file_path: Workspace-relative or absolute path to the file
        line_number: Line number to read (1-indexed)
        workspace_root: Project root path
        include_imports: If True and file is Python, prepend the imports block
            (plus 2 lines of context). Useful for debugging undefined symbols.

    Returns:
        dict with:
        - path: The resolved workspace-relative path
        - requested: {content, start, end} - The target line with 2-line context
        - imports: {content, start, end} - Imports block (only when non-overlapping)
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

        # Handle include_imports for Python files
        if include_imports and target_path.suffix == ".py":
            imports_end = _find_imports_end(all_lines)
            if imports_end > 0:
                imports_block_end = min(imports_end + 2, total_lines)
                if imports_block_end >= start:
                    # Overlapping - extend start to include imports
                    start = 1
                else:
                    # Non-overlapping - return both ranges as separate structured blocks
                    imports_content = read_raw_line_range(str(target_path), 1, imports_block_end)
                    main_content = read_raw_line_range(str(target_path), start, end)

                    result: dict = {
                        "path": str(target_path.relative_to(workspace_root)),
                        "imports": {"content": imports_content, "start": 1, "end": imports_block_end},
                        "requested": {"content": main_content, "start": start, "end": end},
                    }
                    result["warning"] = (
                        "WARNING: Reading Python files with read_line wastes tokens and loses structure. "
                        "Use discover_api (module overview), locate_symbol (find definitions), or "
                        "get_symbol_body_at_line (get function/class at line) instead."
                    )
                    return result

        # Extract lines with context using raw bytes (preserves exact line endings)
        result_content = read_raw_line_range(str(target_path), start, end)

        # Build minimal response
        result = {
            "path": str(target_path.relative_to(workspace_root)),
            "requested": {"content": result_content, "start": start, "end": end},
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
