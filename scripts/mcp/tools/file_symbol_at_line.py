"""Get symbol body at line - combines find_symbol_at_line and get_source.

Convenience tool to avoid the common two-step hop.
"""

__all__ = ["file_symbol_at_line"]
import ast
import sys
from pathlib import Path

from scripts.mcp.tools.helpers.file_lines import read_raw_line_range

# Project root (would be set by caller, but for imports)
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


def file_symbol_at_line(file_path: str, line_number: int, workspace_root: Path) -> dict:
    """Get source code of the symbol containing a specific line number.

    Use this when you have a line number (from error, search result, etc.) and want
    to see the full symbol containing it without two separate calls.

    Returns the innermost containing symbol (function/method/class) with 2 lines
    of context padding before and after. If the line is module-level/whitespace,
    returns that line with 2-line context.

    Python files only.

    Args:
        file_path: Path to Python file (absolute or relative to workspace)
        line_number: Line number (1-indexed)
        workspace_root: Project root path

    Returns:
        dict with source, start/end lines, qualified_name (if symbol), kind, file path

    """
    try:
        # Resolve path relative to workspace root
        target_path = Path(file_path)
        if not target_path.is_absolute():
            target_path = workspace_root / file_path

        # Security check
        try:
            target_path = target_path.resolve()
            rel_path = target_path.relative_to(workspace_root)
        except (ValueError, RuntimeError):
            return {"error": f"Path {file_path} is outside workspace root"}

        # Check file exists
        if not target_path.exists():
            return {"error": f"File not found: {file_path}"}

        if not target_path.is_file():
            return {"error": f"Path is not a file: {file_path}"}

        # Check it's a Python file
        if target_path.suffix != ".py":
            return {"error": f"File is not a Python file: {file_path}"}

        # Read and parse file
        source_code = target_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source_code, filename=str(target_path))
        except SyntaxError as e:
            return {"error": f"Syntax error in {file_path}: {e}"}

        # Find containing symbol
        containing_symbol: tuple[ast.AST, str, str, int, int] | None = None
        symbol_kind = None

        def find_containing(node, path=""):
            nonlocal containing_symbol, symbol_kind

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno
                end = node.end_lineno

                if end is not None and start <= line_number <= end:
                    # This node contains the line
                    current_path = f"{path}.{node.name}" if path else node.name

                    if isinstance(node, ast.ClassDef):
                        kind = "Class"
                    elif isinstance(node, ast.AsyncFunctionDef):
                        kind = "AsyncFunction"
                    else:
                        kind = "Method" if path else "Function"

                    # Store this as a candidate
                    containing_symbol = (node, current_path, kind, start, end)

                    # Check children for more specific match
                    for child in ast.iter_child_nodes(node):
                        find_containing(child, current_path)

        # Walk the AST
        for node in ast.iter_child_nodes(tree):
            find_containing(node)

        if not containing_symbol:
            # Return the line with context instead of just an error
            source_lines = source_code.splitlines(keepends=True)
            total_lines = len(source_lines)

            # Calculate context range (2 lines before and after)
            context_start = max(1, line_number - 2)
            context_end = min(total_lines, line_number + 2)

            # Extract the lines with context using raw bytes
            context_source = read_raw_line_range(str(target_path), context_start, context_end)

            return {
                "error": f"No symbol contains line {line_number} in {file_path}",
                "hint": "This IS module level code, whitespace, or comments",
                "start_line": context_start,
                "end_line": context_end,
                "source": context_source,
                "file": str(rel_path),
            }

        # Type guard for mypy
        assert containing_symbol is not None
        node, qualified_name, kind, start_line, end_line = containing_symbol

        # Extract source with context padding (2 lines before and after)
        source_lines = source_code.splitlines(keepends=True)
        total_lines = len(source_lines)

        context_start = max(1, start_line - 2)
        context_end = min(total_lines, end_line + 2)

        # Extract source with context using raw bytes (preserves exact line endings)
        symbol_source = read_raw_line_range(str(target_path), context_start, context_end)

        return {
            "qualified_name": qualified_name,
            "kind": kind,
            "start_line": context_start,
            "end_line": context_end,
            "source": symbol_source,
            "file": str(rel_path),
        }

    except UnicodeDecodeError:
        return {"error": f"File is not valid UTF-8: {file_path}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
