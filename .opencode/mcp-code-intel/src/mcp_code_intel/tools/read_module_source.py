#!/usr/bin/env python3
"""Static Source Code Retrieval Tool.

Uses AST parsing (no code execution) to retrieve source code of Python
functions, methods, and classes. Safe for use with any module.

Usage:
    # Standalone
    python -m mcp_code_intel.module_get_source mypackage.module.Class.method

    # As module
    from .module_get_source import module_get_source
    result = module_get_source("mypackage.module.Class.method")
"""

from __future__ import annotations

__all__ = ["read_module_source"]

import ast
import json
import sys
from pathlib import Path
from typing import Any

from ..helpers.config_loader import get_workspace_root, resolve_module_path
from ..helpers.file_lines import read_raw_line_range

# Default context lines for edit operations
DEFAULT_CONTEXT_LINES = 2
LARGE_CONTEXT_LINES = 10
MIN_QUALIFIED_NAME_PARTS = 2


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

    # Iteratively walk the AST: start at module body, descend one level per path part
    current_body = tree.body

    for i, name in enumerate(symbol_path):
        is_last = i == len(symbol_path) - 1
        found = None

        for node in current_body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                if is_last:
                    return node
                # Descend into class body for next part
                current_body = node.body
                found = node
                break
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                if is_last:
                    return node
                return None  # Functions don't have nested symbols we support

        if found is None:
            return None

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


def read_module_source(
    qualified_name: str | None = None,
    *,
    file_path: str | None = None,
    symbol: str | None = None,
    large_context: bool = False,
) -> dict[str, Any]:
    """Get source code of a Python function, method, or class using static AST parsing.

    No code is executed - this is safe for any module.

    Args:
        qualified_name: Fully qualified dotted import path (mutually exclusive with
            file_path+symbol).
            Examples:
            - "nomarr.persistence.db.Database" (class)
            - "nomarr.persistence.db.Database.close" (method)
            - "nomarr.helpers.time_helper.now_ms" (function)
            - "nomarr.app.Application.__init__" (constructor)
        file_path: Workspace-relative or absolute path to the Python file.
            Must be paired with 'symbol'. Mutually exclusive with 'qualified_name'.
        symbol: Dotted symbol name within the file (e.g. 'Database.close').
            Only valid alongside 'file_path'.
        large_context: If True, include 10 lines of context before/after.
            Default includes 2 lines for typical edit operations.

    Returns:
        Dict with:
            - name: The input identifier (qualified_name or file_path::symbol)
            - type: "function", "method", "class", "async_function", or "unknown"
            - source: The source code as a string (with context lines)
            - file: Source file path
            - line: Starting line number (includes context)
            - line_count: Total lines returned (includes context)
            - symbol_start_line: First line of actual symbol definition (1-indexed)
            - symbol_end_line: Last line of actual symbol definition (1-indexed)
            - error: Error message with usage guidance if inputs are invalid

    Usage:
        For replacements, use symbol_start_line and symbol_end_line.
        The line/line_count fields include surrounding context for reading.

    """
    has_fqn = bool(qualified_name and qualified_name.strip())
    has_file = bool(file_path and file_path.strip())
    has_symbol = bool(symbol and symbol.strip())

    if has_fqn and has_file:
        return {
            "error": (
                "Conflicting inputs: provide 'qualified_name' OR 'file_path'+'symbol', not both. "
                "Use 'qualified_name' for dotted import paths "
                "(e.g. 'nomarr.persistence.db.Database.close'), or 'file_path'+'symbol' when "
                "you already know the file path (e.g. from locate_module_symbol output)."
            )
        }
    if has_fqn and has_symbol:
        return {
            "error": (
                "Conflicting inputs: 'symbol' is only valid alongside 'file_path'. "
                "When using 'qualified_name', the symbol is embedded in the dotted path."
            )
        }
    if has_file and not has_symbol:
        return {
            "error": (
                "Missing 'symbol': 'file_path' requires 'symbol' "
                "(e.g. symbol='Database.close'). "
                "To inspect a whole module, use read_module_api instead."
            )
        }
    if has_symbol and not has_file:
        return {
            "error": (
                "Missing 'file_path': 'symbol' must be paired with 'file_path'. "
                "To use a dotted import path, use 'qualified_name' instead."
            )
        }
    if not has_fqn and not has_file:
        return {
            "error": (
                "No input provided. Use either:\n"
                "  qualified_name='nomarr.persistence.db.Database.close'\n"
                "  file_path='nomarr/persistence/db.py', symbol='Database.close'"
            )
        }

    context_lines = LARGE_CONTEXT_LINES if large_context else DEFAULT_CONTEXT_LINES
    workspace_root = get_workspace_root()

    if has_file:
        # file_path + symbol: resolve file directly, skip module discovery
        raw = Path(file_path)  # type: ignore[arg-type]
        resolved_path: Path = raw if raw.is_absolute() else workspace_root / raw
        result: dict[str, Any] = {"name": f"{file_path}::{symbol}"}
        if not resolved_path.exists():
            result["error"] = f"File not found: {file_path}"
            return result
        symbol_path = symbol.split(".")  # type: ignore[union-attr]
    else:
        # qualified_name: discover file via module resolution
        result = {"name": qualified_name}
        parts = qualified_name.split(".")  # type: ignore[union-attr]
        if len(parts) < MIN_QUALIFIED_NAME_PARTS:
            result["error"] = (
                f"Invalid qualified name: {qualified_name!r} (need at least module.name, "
                "e.g. 'nomarr.helpers.time_helper.now_ms')"
            )
            return result

        found: Path | None = None
        symbol_path = []
        for i in range(len(parts), 0, -1):
            module_name = ".".join(parts[:i])
            candidate = resolve_module_path(module_name, workspace_root)
            if candidate:
                found = candidate
                symbol_path = parts[i:]
                break

        if found is None:
            result["error"] = f"Could not find module file for: {qualified_name}"
            return result
        resolved_path = found

    result["file"] = str(resolved_path)

    # Read and parse the file
    try:
        source_text = resolved_path.read_text(encoding="utf-8")
        source_lines = source_text.splitlines(keepends=True)
    except OSError as e:
        result["error"] = f"Could not read file: {e}"
        return result

    try:
        tree = ast.parse(source_text, filename=str(resolved_path))
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
        result["error"] = f"Symbol not found: {'.'.join(symbol_path)} in {resolved_path}"
        return result

    result["type"] = _get_symbol_type(node)

    # Get line range for the symbol
    start_line = node.lineno  # 1-indexed
    end_line = node.end_lineno or start_line

    # Add context lines
    context_start = max(1, start_line - context_lines)
    context_end = min(len(source_lines), end_line + context_lines)

    # Extract source with context using raw bytes (preserves exact line endings)
    result["source"] = read_raw_line_range(str(resolved_path), context_start, context_end)
    result["line"] = context_start
    result["line_count"] = context_end - context_start + 1

    # Add actual symbol boundaries (for replacement operations)
    result["symbol_start_line"] = start_line
    result["symbol_end_line"] = end_line

    return result


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Get source code of a Python function/method/class (static analysis)"
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="Qualified name (e.g. nomarr.app.Application.__init__)",
    )
    parser.add_argument("--file", metavar="FILE_PATH", help="Workspace-relative file path")
    parser.add_argument("--symbol", metavar="SYMBOL", help="Dotted symbol within --file")
    parser.add_argument(
        "--large-context",
        action="store_true",
        help="Include 10 lines of context instead of default 2",
    )

    args = parser.parse_args()

    result = read_module_source(
        qualified_name=args.name,
        file_path=args.file,
        symbol=args.symbol,
        large_context=args.large_context,
    )

    print(json.dumps(result, indent=2))

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
