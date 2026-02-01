#!/usr/bin/env python3
"""ML-optimized Call Chain Tracer (Standalone)

Traces function call chains starting from a given function/method.
Returns the complete call tree with file locations.

Use case: Reduce token count when you know the entry point but need
to find buried methods without loading entire files.

Usage:
    # Standalone
    python scripts/mcp/trace_calls_ml.py nomarr.interfaces.api.web.library_if.scan_library

    # As module
    from .trace_calls import trace_calls
    result = trace_calls("nomarr.interfaces.api.web.library_if.scan_library")
"""

from __future__ import annotations

__all__ = ["trace_calls"]

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from .helpers.config_loader import (
    get_tracing_config,
    load_config,
)

# Maximum depth to prevent infinite recursion
MAX_DEPTH = 8


@dataclass
class CallInfo:
    """Information about a function call."""

    name: str  # The call expression (e.g., "library_svc.scan")
    resolved: str | None  # Fully qualified name if resolved
    file: str | None  # File where the called function is defined
    line: int | None  # Line number of the definition
    calls: list[CallInfo] = field(default_factory=list)  # Nested calls


def _mock_unavailable_dependencies() -> None:
    """Mock Docker-only dependencies for discovery in dev environment.

    Must create proper package structure - parent modules need submodule
    attributes for 'from x.y import z' to work.
    """
    # Define hierarchy: parent -> list of submodules
    package_hierarchy = {
        "arango": ["aql", "collection", "cursor", "database", "exceptions"],
        "essentia": ["standard"],
        "tensorflow": ["lite"],
        "tensorflow.lite": ["python"],
        "tensorflow.lite.python": ["interpreter"],
    }

    # Create all modules with proper structure
    for parent, children in package_hierarchy.items():
        if parent not in sys.modules:
            parent_mock = MagicMock()
            sys.modules[parent] = parent_mock
        else:
            parent_mock = sys.modules[parent]  # type: ignore[assignment]

        # Attach child modules to parent
        for child in children:
            full_name = f"{parent}.{child}"
            if full_name not in sys.modules:
                child_mock = MagicMock()
                sys.modules[full_name] = child_mock
                setattr(parent_mock, child, child_mock)


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

        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local_name = alias.asname or alias.name
                imports[local_name] = f"{node.module}.{alias.name}"

    return imports


def _extract_param_types(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str],
    project_root: Path | None = None,
) -> dict[str, str]:
    """Extract parameter type annotations, including FastAPI Depends() patterns.

    Returns dict mapping parameter names to their resolved type.
    E.g., {"library_service": "nomarr.services.domain.library_svc.LibraryService"}

    Handles:
    1. Direct type annotations: `service: LibraryService`
    2. FastAPI Depends: `service: LibraryService = Depends(get_library_service)`
    3. Depends with Any type: `service: Any = Depends(get_library_service)` - resolves via return annotation
    """
    param_types: dict[str, str] = {}

    for arg in func_node.args.args:
        type_str = None
        depends_func = None

        # Check for type annotation
        if arg.annotation:
            type_str = _annotation_to_string(arg.annotation)

        # Check for default value that's a Depends() call
        # Find the default for this arg (in func_node.args.defaults aligned from the right)
        arg_index = func_node.args.args.index(arg)
        num_defaults = len(func_node.args.defaults)
        num_args = len(func_node.args.args)
        default_index = arg_index - (num_args - num_defaults)

        if default_index >= 0:
            default = func_node.args.defaults[default_index]
            depends_info = _extract_depends_function(default)
            if depends_info:
                depends_func = depends_info

        # If we have a Depends() and type is Any/unresolved, resolve from dependency function
        if depends_func and (type_str is None or type_str == "Any"):
            resolved_type = _resolve_depends_return_type(depends_func, imports, project_root)
            if resolved_type:
                param_types[arg.arg] = resolved_type
                continue

        # Standard type resolution
        if type_str:
            parts = type_str.split(".")
            if parts[0] in imports:
                resolved = imports[parts[0]]
                if len(parts) > 1:
                    resolved = f"{resolved}.{'.'.join(parts[1:])}"
                param_types[arg.arg] = resolved
            else:
                param_types[arg.arg] = type_str

    return param_types


def _extract_depends_function(node: ast.expr) -> str | None:
    """Extract the function name from a Depends(func) call.

    Returns the function name (e.g., 'get_library_service') or None.
    """
    if not isinstance(node, ast.Call):
        return None

    # Check if it's Depends(...)
    if (
        (isinstance(node.func, ast.Name) and node.func.id == "Depends")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "Depends")
    ) and node.args:
        return _call_to_string(node.args[0])

    return None


def _resolve_depends_return_type(
    depends_func: str,
    imports: dict[str, str],
    project_root: Path | None = None,
) -> str | None:
    """Resolve the return type of a dependency function.

    Looks up the function in the dependencies module and extracts its return annotation.
    """
    if project_root is None:
        return None

    # Resolve the depends function through imports
    if depends_func in imports:
        full_path = imports[depends_func]
    else:
        # Not imported directly - might be local or from dependencies module
        return None

    # Parse the module containing the depends function
    parts = full_path.rsplit(".", 1)
    if len(parts) != 2:
        return None

    mod_path, func_name = parts
    file_path = _resolve_module_to_path(mod_path, project_root)
    if not file_path:
        return None

    tree = _parse_file(file_path)
    if not tree:
        return None

    # Find the function and extract return annotation
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name and node.returns:
            return_type = _annotation_to_string(node.returns)
            if return_type:
                # Resolve the return type through the deps module's imports
                deps_imports = _extract_imports(tree)
                type_parts = return_type.split(".")
                if type_parts[0] in deps_imports:
                    resolved = deps_imports[type_parts[0]]
                    if len(type_parts) > 1:
                        resolved = f"{resolved}.{'.'.join(type_parts[1:])}"
                    return resolved
                return return_type

    return None


def _annotation_to_string(node: ast.expr) -> str | None:
    """Convert type annotation to string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # Handle string annotations like "LibraryService"
        return node.value
    if isinstance(node, ast.Attribute):
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
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                        return item
    else:
        # Top-level function
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                return node

    return None


def _find_class_node(tree: ast.Module, class_name: str) -> tuple[ast.ClassDef | None, int | None]:
    """Find a class definition in AST.

    Returns (ClassDef node, line number) or (None, None).
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node, node.lineno
    return None, None


def _extract_calls_from_function(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, int]]:
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
    if isinstance(node, ast.Attribute):
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
                                    if (
                                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                                        and item.name == method_name
                                    ):
                                        rel_path = py_file.relative_to(project_root)
                                        submod = ".".join(rel_path.with_suffix("").parts)
                                        found_qualified = f"{submod}.{node.name}.{method_name}"
                                        return found_qualified, py_file, item.lineno
    # Check if first part is an imported name
    if parts[0] in imports:
        base_module = imports[parts[0]]

        # If it's a direct function/class import (len(parts) == 1)
        if len(parts) == 1:
            # The import could be a function or a class (for instantiation)
            module_parts = base_module.rsplit(".", 1)
            if len(module_parts) == 2:
                mod_path, name = module_parts
                file_path = _resolve_module_to_path(mod_path, project_root)
                if file_path:
                    tree = _parse_file(file_path)
                    if tree:
                        # First try as function
                        func_node = _find_function_node(tree, name)
                        if func_node:
                            return base_module, file_path, func_node.lineno
                        # Then try as class (for instantiation like SystemInfoResult())
                        class_node, class_line = _find_class_node(tree, name)
                        if class_node and class_line:
                            return base_module, file_path, class_line
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


def _is_nomarr_call(resolved: str | None, include_patterns: list[str] | None = None) -> bool:
    """Check if a resolved call matches configured include patterns.

    Args:
        resolved: Fully qualified name of the call
        include_patterns: List of patterns like ["nomarr.*", "myapp.*"]
                         If None, defaults to ["nomarr.*"]

    Returns:
        True if resolved matches any pattern

    """
    if resolved is None:
        return False

    if include_patterns is None:
        include_patterns = ["nomarr.*"]

    for pattern in include_patterns:
        # Simple pattern matching: convert "nomarr.*" to prefix check
        if pattern.endswith(".*"):
            prefix = pattern[:-2]  # Remove ".*"
            if resolved.startswith(prefix + "."):
                return True
        else:
            # Exact match
            if resolved == pattern:
                return True

    return False


def _trace_calls_recursive(
    qualified_name: str,
    project_root: Path,
    visited: set[str],
    depth: int,
    include_patterns: list[str] | None = None,
) -> CallInfo | None:
    """Recursively trace calls from a function.

    Args:
        qualified_name: Fully qualified function name
        project_root: Path to project root
        visited: Set of already visited functions to prevent cycles
        depth: Current recursion depth
        include_patterns: List of module patterns to include (e.g., ["nomarr.*"])

    """
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
        return CallInfo(name=qualified_name, resolved=qualified_name, file=None, line=None)

    tree = _parse_file(file_path)
    if not tree:
        return CallInfo(name=qualified_name, resolved=qualified_name, file=str(file_path), line=None)

    func_node = _find_function_node(tree, func_name)

    # If not found and file_path is a package __init__.py, search mixin files
    if not func_node and file_path.name == "__init__.py":
        package_dir = file_path.parent
        # func_name might be "ClassName.method_name"
        if "." in func_name:
            class_name, method_name = func_name.split(".", 1)
        else:
            class_name = None
            method_name = func_name

        # Search all .py files in the package for the method
        for py_file in package_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            mixin_tree = _parse_file(py_file)
            if mixin_tree:
                # Search for any class with this method
                for node in ast.walk(mixin_tree):
                    if isinstance(node, ast.ClassDef):
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                                item.name == method_name or (class_name and item.name == method_name)
                            ):
                                # Found it in a mixin
                                file_path = py_file
                                tree = mixin_tree
                                func_node = item
                                break
                    if func_node:
                        break
            if func_node:
                break

    if not func_node:
        # If no function found, try finding it as a class (for class instantiation like DTOs)
        # func_name might just be the class name without a method
        if "." not in func_name:
            class_node, class_line = _find_class_node(tree, func_name)
            if class_node and class_line:
                # It's a class instantiation - return as a leaf node (no calls to trace)
                return CallInfo(
                    name=qualified_name.split(".")[-1],
                    resolved=qualified_name,
                    file=str(file_path.relative_to(project_root)).replace("\\", "/"),
                    line=class_line,
                    calls=[],  # Classes typically don't have nested calls we care about
                )

        # Neither function nor class found
        return CallInfo(name=qualified_name, resolved=qualified_name, file=str(file_path), line=None)

    # Extract imports for resolution
    imports = _extract_imports(tree)

    # Extract parameter types for resolving injected dependencies (including Depends())
    param_types = _extract_param_types(func_node, imports, project_root)

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
            call_expr,
            imports,
            param_types,
            current_module,
            project_root,
        )

        # Skip non-matching calls and duplicates
        if not _is_nomarr_call(resolved, include_patterns):
            continue

        if resolved is None or resolved in seen_calls:
            continue
        seen_calls.add(resolved)

        # Recursively trace
        nested = _trace_calls_recursive(
            resolved,
            project_root,
            visited.copy(),  # Copy to allow different branches
            depth + 1,
            include_patterns=include_patterns,
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
                ),
            )

    return call_info


def _call_info_to_dict(info: CallInfo) -> dict[str, Any]:
    """Convert CallInfo to dict for JSON serialization."""
    result: dict[str, Any] = {"name": info.name, "resolved": info.resolved, "file": info.file, "line": info.line}

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
        },
    )

    for call in info.calls:
        result.extend(_flatten_chain(call, prefix + "  "))

    return result


def trace_calls(
    qualified_name: str, project_root: Path | str | None = None, config: dict | None = None
) -> dict[str, Any]:
    """Trace the call chain starting from a function/method.

    Uses configuration to determine which modules to include in the call trace.

    Configuration used:
        tracing.include_patterns: List of module name patterns to include in trace
            Example: ["nomarr.*", "custom_module.*"]
            Default: ["nomarr.*"]
        tracing.max_depth: Maximum recursion depth for call tracing
            Default: 10
        tracing.filter_external: Whether to filter external (non-project) calls
            Default: true

    Args:
        qualified_name: Fully qualified function name
            Examples:
            - "nomarr.interfaces.api.web.library_if.scan_library"
            - "nomarr.services.domain.library_svc.LibraryService.scan"
        project_root: Path to project root (str or Path). Defaults to auto-detect.
        config: Optional config dict. If not provided, loaded from project_root.
            Can be obtained from: load_config(project_root)

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
        project_root = Path(__file__).parent.parent.parent.parent
    else:
        project_root = Path(project_root)

    # Load config if not provided (dependency injection)
    if config is None:
        config = load_config(project_root)
    tracing_config = get_tracing_config(config)
    include_patterns: list[str] | None = tracing_config.get("include_patterns")

    # Trace the calls
    result = _trace_calls_recursive(qualified_name, project_root, set(), 0, include_patterns=include_patterns)

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

    return {"root": qualified_name, "tree": tree, "flat": flat, "depth": depth, "call_count": call_count}
