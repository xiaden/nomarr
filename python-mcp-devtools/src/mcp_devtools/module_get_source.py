#!/usr/bin/env python3
"""Static Source Code Retrieval Tool.

Uses AST parsing (no code execution) to retrieve source code of Python
functions, methods, and classes. Safe for use with any module.

Usage:
    # Standalone
    python scripts/mcp/tools/get_source.py nomarr.app.Application.__init__

    # As module
    from .get_source import get_source
    result = get_source("nomarr.app.Application.__init__")
"""

from __future__ import annotations

__all__ = ["module_get_source"]

import ast
import json
import sys
from pathlib import Path
from typing import Any

from .helpers.file_lines import read_raw_line_range

# Default context lines for edit operations
DEFAULT_CONTEXT_LINES = 2
LARGE_CONTEXT_LINES = 10
MIN_QUALIFIED_NAME_PARTS = 2


def _find_project_root() -> Path:
    """Find the project root by looking for pyproject.toml or .git."""
    current = Path.cwd()

    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent

    return current


def _resolve_module_path(module_name: str, project_root: Path) -> Path | None:
    """Resolve a module name to its file path without importing.

    Args:
        module_name: Dotted module name (e.g., "nomarr.services.config_svc")
        project_root: Project root directory

    Returns:
        Path to the module file, or None if not found.

    """
    # Convert module name to path components
    parts = module_name.split(".")

    # Try as a direct module file
    module_path = project_root / Path(*parts).with_suffix(".py")
    if module_path.exists():
        return module_path

    # Try as a package __init__.py
    package_path = project_root / Path(*parts) / "__init__.py"
    if package_path.exists():
        return package_path

    return None


def _find_symbol_in_ast(
    tree: ast.Module,
    symbol_path: list[str],
) -> ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find a symbol in the AST by its path.

    Args:
        tree: Parsed AST module
        symbol_path: List of names to traverse (e.g., ["Application", "__init__"])

    Returns:
        The AST node for the symbol, or None if not found.

    """
    if not symbol_path:
        return None

    current_name = symbol_path[0]
    remaining = symbol_path[1:]

    # Search in module body
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == current_name:
            if not remaining:
                return node
            # Search in class body for methods
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == remaining[0]:
                    if len(remaining) == 1:
                        return item
                    # Nested classes/functions not supported for now
                    return None
            return None

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == current_name:
            if not remaining:
                return node
            return None  # Functions don't have nested symbols we support

    return None


def _get_symbol_type(node: ast.AST) -> str:
    """Determine the type of an AST node."""
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async_function"
    if isinstance(node, ast.FunctionDef):
        # Check if it's inside a class (method) by looking for 'self' or 'cls' first param
        if node.args.args and node.args.args[0].arg in ("self", "cls"):
            return "method"
        return "function"
    return "unknown"


def module_get_source(qualified_name: str, *, large_context: bool = False) -> dict[str, Any]:
    """Get source code of a Python function, method, or class using static AST parsing.

    No code is executed - this is safe for any module.

    Args:
        qualified_name: Fully qualified name with dots
            Examples:
            - "nomarr.persistence.db.Database" (class)
            - "nomarr.persistence.db.Database.close" (method)
            - "nomarr.helpers.time_helper.now_ms" (function)
            - "nomarr.app.Application.__init__" (constructor)
        large_context: If True, include 10 lines of context before/after.
            Default includes 2 lines for typical edit operations.

    Returns:
        Dict with:
            - name: The qualified name requested
            - type: "function", "method", "class", "async_function", or "unknown"
            - source: The source code as a string (with context lines)
            - file: Source file path
            - line: Starting line number (includes context)
            - line_count: Total lines returned
            - error: Optional error message if resolution failed

    """
    result: dict[str, Any] = {"name": qualified_name}

    # Determine context lines
    context_lines = LARGE_CONTEXT_LINES if large_context else DEFAULT_CONTEXT_LINES

    # Parse the qualified name
    parts = qualified_name.split(".")
    if len(parts) < MIN_QUALIFIED_NAME_PARTS:
        result["error"] = f"Invalid qualified name: {qualified_name} (need at least module.name)"
        return result

    # Try to find the file by progressively removing symbols from the end
    file_path = None
    symbol_path: list[str] = []
    project_root = _find_project_root()

    for i in range(len(parts), 0, -1):
        module_name = ".".join(parts[:i])
        candidate = _resolve_module_path(module_name, project_root)
        if candidate:
            file_path = candidate
            symbol_path = parts[i:]
            break

    if file_path is None:
        result["error"] = f"Could not find module file for: {qualified_name}"
        return result

    result["file"] = str(file_path)

    # Read and parse the file
    try:
        source_text = file_path.read_text(encoding="utf-8")
        source_lines = source_text.splitlines(keepends=True)
    except OSError as e:
        result["error"] = f"Could not read file: {e}"
        return result

    try:
        tree = ast.parse(source_text, filename=str(file_path))
    except SyntaxError as e:
        result["error"] = f"Syntax error in file: {e}"
        return result

    # If no symbol path, they want the whole module (unusual but handle it)
    if not symbol_path:
        result["type"] = "module"
        result["source"] = source_text
        result["line"] = 1
        result["line_count"] = len(source_lines)
        return result

    # Find the symbol in the AST
    node = _find_symbol_in_ast(tree, symbol_path)

    if node is None:
        result["error"] = f"Symbol not found: {'.'.join(symbol_path)} in {file_path}"
        return result

    result["type"] = _get_symbol_type(node)

    # Get line range for the symbol
    start_line = node.lineno  # 1-indexed
    end_line = node.end_lineno or start_line

    # Add context lines
    context_start = max(1, start_line - context_lines)
    context_end = min(len(source_lines), end_line + context_lines)

    # Extract source with context using raw bytes (preserves exact line endings)
    result["source"] = read_raw_line_range(str(file_path), context_start, context_end)
    result["line"] = context_start
    result["line_count"] = context_end - context_start + 1

    return result


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Get source code of a Python function/method/class (static analysis)")
    parser.add_argument("name", help="Qualified name (e.g., nomarr.app.Application.__init__)")
    parser.add_argument("--large-context", action="store_true", help="Include 10 lines of context instead of default 2")

    args = parser.parse_args()

    result = module_get_source(args.name, large_context=args.large_context)

    print(json.dumps(result, indent=2))

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
