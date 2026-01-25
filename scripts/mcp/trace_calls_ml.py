#!/usr/bin/env python3
"""
ML-optimized Call Chain Tracer (Standalone)

Traces function call chains starting from a given function/method.
Returns the complete call tree with file locations.

Use case: Reduce token count when you know the entry point but need
to find buried methods without loading entire files.

Usage:
    # Standalone
    python scripts/mcp/trace_calls_ml.py nomarr.interfaces.api.web.library_if.scan_library

    # As module
    from scripts.mcp.trace_calls_ml import trace_calls
    result = trace_calls("nomarr.interfaces.api.web.library_if.scan_library")
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Maximum depth to prevent infinite recursion
MAX_DEPTH = 8


@dataclass
class CallInfo:
    """Information about a function call."""

    name: str  # The call expression (e.g., "library_svc.scan")
    resolved: str | None  # Fully qualified name if resolved
    file: str | None  # File where the called function is defined
    line: int | None  # Line number of the definition
    calls: list["CallInfo"] = field(default_factory=list)  # Nested calls


def _mock_unavailable_dependencies() -> None:
    """Mock Docker-only dependencies for discovery in dev environment."""
    mock_modules = [
        "essentia",
        "essentia.standard",
        "tensorflow",
        "tensorflow.lite",
        "tensorflow.lite.python",
        "tensorflow.lite.python.interpreter",
    ]
    for mod in mock_modules:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()


def _resolve_module_to_path(module_name: str, project_root: Path) -> Path | None:
    """Resolve module name to file path."""
    parts = module_name.split(".")

    # Try as .py file
    file_path = project_root / "/".join(parts)
    py_file = file_path.with_suffix(".py")
    if py_file.exists():
        return py_file

    # Try as package (__init__.py)
    init_file = file_path / "__init__.py"
    if init_file.exists():
        return init_file

    return None


def _parse_file(file_path: Path) -> ast.Module | None:
    """Parse a Python file into AST."""
    try:
        source = file_path.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _extract_imports(tree: ast.Module) -> dict[str, str]:
    """Extract import mappings from AST.

    Returns dict mapping local names to fully qualified module paths.
    E.g., {"library_svc": "nomarr.services.domain.library_svc"}
    """
    imports: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[-1]
                imports[local_name] = alias.name

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    imports[local_name] = f"{node.module}.{alias.name}"

    return imports


def _extract_param_types(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str],
) -> dict[str, str]:
    """Extract parameter type annotations.

    Returns dict mapping parameter names to their resolved type.
    E.g., {"library_service": "nomarr.services.domain.library_svc.LibraryService"}
    """
    param_types: dict[str, str] = {}

    for arg in func_node.args.args:
        if arg.annotation:
            type_str = _annotation_to_string(arg.annotation)
            if type_str:
                # Resolve through imports
                parts = type_str.split(".")
                if parts[0] in imports:
                    resolved = imports[parts[0]]
                    if len(parts) > 1:
                        resolved = f"{resolved}.{'.'.join(parts[1:])}"
                    param_types[arg.arg] = resolved
                else:
                    param_types[arg.arg] = type_str

    return param_types


def _annotation_to_string(node: ast.expr) -> str | None:
    """Convert type annotation to string."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        # Handle string annotations like "LibraryService"
        return node.value
    elif isinstance(node, ast.Attribute):
        value_str = _annotation_to_string(node.value)
        if value_str:
            return f"{value_str}.{node.attr}"
    elif isinstance(node, ast.Subscript):
        # Handle Optional[X], List[X], etc. - just return the base
        return _annotation_to_string(node.value)
    return None


def _find_function_node(tree: ast.Module, func_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find a function or method definition in AST."""
    # Check if it's a method (contains a dot suggesting Class.method)
    if "." in func_name:
        class_name, method_name = func_name.rsplit(".", 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name == method_name:
                            return item
    else:
        # Top-level function
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    return node

    return None


def _extract_calls_from_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[str, int]]:
    """Extract all function calls from a function body.

    Returns list of (call_expression, line_number).
    """
    calls: list[tuple[str, int]] = []

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            call_str = _call_to_string(node.func)
            if call_str:
                calls.append((call_str, node.lineno))

    return calls


def _call_to_string(node: ast.expr) -> str | None:
    """Convert a call expression to a string."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        value_str = _call_to_string(node.value)
        if value_str:
            return f"{value_str}.{node.attr}"
    elif isinstance(node, ast.Subscript):
        # Handle things like dict[str, int]() - skip type expressions
        return None
    return None


def _resolve_call(
    call_expr: str,
    imports: dict[str, str],
    param_types: dict[str, str],
    current_module: str,
    project_root: Path,
) -> tuple[str | None, Path | None, int | None]:
    """Resolve a call expression to its definition.

    Returns (fully_qualified_name, file_path, line_number).
    """
    parts = call_expr.split(".")

    # Check if first part is a typed parameter (e.g., library_service.start_scan)
    if parts[0] in param_types and len(parts) >= 2:
        # Resolve through the parameter's type
        type_name = param_types[parts[0]]
        method_name = parts[1]  # Just the method name
        full_qualified = f"{type_name}.{method_name}"

        # Try to find the class and method
        # Type name format: nomarr.module.path.ClassName
        type_parts = type_name.rsplit(".", 1)
        if len(type_parts) == 2:
            mod_path, class_name = type_parts
            file_path = _resolve_module_to_path(mod_path, project_root)
            if file_path:
                tree = _parse_file(file_path)
                if tree:
                    # Look for Class.method
                    func_node = _find_function_node(tree, f"{class_name}.{method_name}")
                    if func_node:
                        return full_qualified, file_path, func_node.lineno

            # If not found directly, check if it's a package with mixins
            # Look for method in submodules (common for mixin patterns)
            package_dir = project_root / mod_path.replace(".", "/")
            if package_dir.is_dir():
                for py_file in package_dir.glob("*.py"):
                    if py_file.name == "__init__.py":
                        continue
                    tree = _parse_file(py_file)
                    if tree:
                        # Search for any class with this method
                        for node in ast.walk(tree):
                            if isinstance(node, ast.ClassDef):
                                for item in node.body:
                                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                        if item.name == method_name:
                                            rel_path = py_file.relative_to(project_root)
                                            submod = ".".join(rel_path.with_suffix("").parts)
                                            found_qualified = f"{submod}.{node.name}.{method_name}"
                                            return found_qualified, py_file, item.lineno

        return full_qualified, None, None

    # Check if first part is an imported name
    if parts[0] in imports:
        base_module = imports[parts[0]]

        # If it's a direct function import
        if len(parts) == 1:
            # The import is the function itself
            module_parts = base_module.rsplit(".", 1)
            if len(module_parts) == 2:
                mod_path, func_name = module_parts
                file_path = _resolve_module_to_path(mod_path, project_root)
                if file_path:
                    tree = _parse_file(file_path)
                    if tree:
                        func_node = _find_function_node(tree, func_name)
                        if func_node:
                            return base_module, file_path, func_node.lineno
            return base_module, None, None

        # It's module.something or module.Class.method
        remaining = ".".join(parts[1:])
        full_qualified = f"{base_module}.{remaining}"

        # Try to find the file
        # First, try base_module as the file
        file_path = _resolve_module_to_path(base_module, project_root)
        if file_path:
            tree = _parse_file(file_path)
            if tree:
                func_node = _find_function_node(tree, remaining)
                if func_node:
                    return full_qualified, file_path, func_node.lineno

        return full_qualified, None, None

    # Check if it's a method call on self
    if parts[0] == "self" and len(parts) >= 2:
        # Would need class context to resolve - mark as self call
        return f"self.{'.'.join(parts[1:])}", None, None

    # Unresolved local call
    return None, None, None


def _is_nomarr_call(resolved: str | None) -> bool:
    """Check if a resolved call is within the nomarr package."""
    return resolved is not None and resolved.startswith("nomarr.")


def _trace_calls_recursive(
    qualified_name: str,
    project_root: Path,
    visited: set[str],
    depth: int,
) -> CallInfo | None:
    """Recursively trace calls from a function."""
    if depth >= MAX_DEPTH:
        return None

    if qualified_name in visited:
        return None

    visited.add(qualified_name)

    # Parse the qualified name
    # Format: nomarr.module.path.function or nomarr.module.path.Class.method
    parts = qualified_name.split(".")

    # Find the module file
    # Try progressively shorter module paths
    file_path = None
    func_name = None

    for i in range(len(parts) - 1, 0, -1):
        module_path = ".".join(parts[:i])
        candidate = _resolve_module_to_path(module_path, project_root)
        if candidate:
            file_path = candidate
            func_name = ".".join(parts[i:])
            break

    if not file_path or not func_name:
        return CallInfo(
            name=qualified_name,
            resolved=qualified_name,
            file=None,
            line=None,
        )

    tree = _parse_file(file_path)
    if not tree:
        return CallInfo(
            name=qualified_name,
            resolved=qualified_name,
            file=str(file_path),
            line=None,
        )

    func_node = _find_function_node(tree, func_name)
    if not func_node:
        return CallInfo(
            name=qualified_name,
            resolved=qualified_name,
            file=str(file_path),
            line=None,
        )

    # Extract imports for resolution
    imports = _extract_imports(tree)

    # Extract parameter types for resolving injected dependencies
    param_types = _extract_param_types(func_node, imports)

    # Get module name from file path
    rel_path = file_path.relative_to(project_root)
    current_module = ".".join(rel_path.with_suffix("").parts)

    # Extract calls from function body
    raw_calls = _extract_calls_from_function(func_node)

    call_info = CallInfo(
        name=qualified_name.split(".")[-1],
        resolved=qualified_name,
        file=str(file_path.relative_to(project_root)).replace("\\", "/"),
        line=func_node.lineno,
        calls=[],
    )

    # Process each call
    seen_calls: set[str] = set()
    for call_expr, _call_line in raw_calls:
        resolved, resolved_path, resolved_line = _resolve_call(
            call_expr, imports, param_types, current_module, project_root
        )

        # Skip non-nomarr calls and duplicates
        if not _is_nomarr_call(resolved):
            continue

        if resolved in seen_calls:
            continue
        seen_calls.add(resolved)

        # Recursively trace
        nested = _trace_calls_recursive(
            resolved,
            project_root,
            visited.copy(),  # Copy to allow different branches
            depth + 1,
        )

        if nested:
            call_info.calls.append(nested)
        else:
            # Add as leaf node
            call_info.calls.append(
                CallInfo(
                    name=call_expr,
                    resolved=resolved,
                    file=(str(resolved_path.relative_to(project_root)).replace("\\", "/") if resolved_path else None),
                    line=resolved_line,
                )
            )

    return call_info


def _call_info_to_dict(info: CallInfo) -> dict[str, Any]:
    """Convert CallInfo to dict for JSON serialization."""
    result: dict[str, Any] = {
        "name": info.name,
        "resolved": info.resolved,
        "file": info.file,
        "line": info.line,
    }

    if info.calls:
        result["calls"] = [_call_info_to_dict(c) for c in info.calls]

    return result


def _flatten_chain(info: CallInfo, prefix: str = "") -> list[dict[str, Any]]:
    """Flatten call tree into a list for easier reading."""
    result: list[dict[str, Any]] = []

    indent = prefix
    result.append(
        {
            "indent": indent,
            "name": info.name,
            "resolved": info.resolved,
            "location": f"{info.file}:{info.line}" if info.file and info.line else None,
        }
    )

    for call in info.calls:
        result.extend(_flatten_chain(call, prefix + "  "))

    return result


def trace_calls(
    qualified_name: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """
    Trace the call chain starting from a function/method.

    Args:
        qualified_name: Fully qualified function name
            Examples:
            - "nomarr.interfaces.api.web.library_if.scan_library"
            - "nomarr.services.domain.library_svc.LibraryService.scan"
        project_root: Path to project root. Defaults to auto-detect.

    Returns:
        Dict with:
            - root: The starting function
            - tree: Nested call tree
            - flat: Flattened list with indentation for easy reading
            - depth: Maximum call depth found
            - call_count: Total unique calls traced
            - error: Optional error message
    """
    _mock_unavailable_dependencies()

    if project_root is None:
        project_root = Path(__file__).parent.parent.parent

    # Trace the calls
    result = _trace_calls_recursive(qualified_name, project_root, set(), 0)

    if result is None:
        return {"error": f"Could not find function: {qualified_name}"}

    # Convert to serializable format
    tree = _call_info_to_dict(result)
    flat = _flatten_chain(result)

    # Calculate stats
    def count_calls(info: CallInfo) -> tuple[int, int]:
        """Count total calls and max depth."""
        if not info.calls:
            return 1, 0
        total = 1
        max_depth = 0
        for call in info.calls:
            count, depth = count_calls(call)
            total += count
            max_depth = max(max_depth, depth + 1)
        return total, max_depth

    call_count, depth = count_calls(result)

    return {
        "root": qualified_name,
        "tree": tree,
        "flat": flat,
        "depth": depth,
        "call_count": call_count,
    }


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Trace function call chains")
    parser.add_argument(
        "function",
        help="Fully qualified function name (e.g., nomarr.interfaces.api.web.library_if.scan_library)",
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        help="Show flattened output instead of tree",
    )

    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    result = trace_calls(args.function, project_root)

    if args.flat and "flat" in result:
        # Pretty print flat format
        for item in result["flat"]:
            loc = item["location"] or "?"
            print(f"{item['indent']}{item['name']} ({loc})")
    else:
        print(json.dumps(result, indent=2))

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
