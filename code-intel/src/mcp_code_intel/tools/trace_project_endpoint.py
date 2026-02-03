#!/usr/bin/env python3
"""ML-optimized Endpoint Tracer (Standalone).

Higher-level tool that traces API endpoints through FastAPI DI to services.
Automatically resolves Depends() injection and follows service method calls.

Use case: Trace from API endpoint through all layers without manually
finding injected services.

Usage:
    # Standalone
    python -m mcp_code_intel.trace_endpoint mypackage.interfaces.api.endpoint

    # As module
    from .trace_endpoint import trace_endpoint
    result = trace_endpoint("mypackage.interfaces.api.endpoint")
"""

from __future__ import annotations

__all__ = ["trace_endpoint"]

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..helpers.config_loader import (
    get_backend_config,
    get_workspace_root,
    load_config,
)
from .trace_module_calls import (
    CallInfo,
    _call_info_to_dict,
    _extract_imports,
    _find_function_node,
    _mock_unavailable_dependencies,
    _parse_file,
    _resolve_module_to_path,
    _trace_calls_recursive,
)


@dataclass
class InjectedDependency:
    """Information about a FastAPI injected dependency."""

    param_name: str  # Parameter name in function signature
    depends_function: str  # e.g., "get_library_service"
    resolved_type: (
        str | None
    )  # Fully qualified type e.g., "nomarr.services.domain.library_svc.LibraryService"
    source_file: str | None  # Dependencies file where the getter is defined


@dataclass
class EndpointTrace:
    """Complete trace of an endpoint including DI."""

    endpoint: str  # Qualified endpoint name
    file: str | None  # Endpoint file
    line: int | None  # Endpoint line number
    injected_dependencies: list[InjectedDependency]  # DI-injected services
    call_tree: CallInfo | None  # Direct calls from endpoint
    service_traces: dict[str, CallInfo]  # param_name -> service method call tree


def _annotation_to_string(node: ast.expr) -> str | None:
    """Convert type annotation to string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute):
        value_str = _annotation_to_string(node.value)
        if value_str:
            return f"{value_str}.{node.attr}"
    elif isinstance(node, ast.Subscript):
        return _annotation_to_string(node.value)
    return None


def _call_to_string(node: ast.expr) -> str | None:
    """Convert a call expression to a string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value_str = _call_to_string(node.value)
        if value_str:
            return f"{value_str}.{node.attr}"
    return None


def _extract_depends_info(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str],
    project_root: Path,
    di_patterns: list[str] | None = None,
) -> list[InjectedDependency]:
    """Extract all DI injections from a function's parameters.

    Args:
        func_node: AST node for the function
        imports: Dictionary of imports
        project_root: Path to project root
        di_patterns: List of DI patterns like ["Depends(", "Inject("]

    """
    if di_patterns is None:
        di_patterns = ["Depends("]

    dependencies: list[InjectedDependency] = []

    for arg in func_node.args.args:
        depends_func = None

        if arg.annotation:
            _annotation_to_string(arg.annotation)

        # Find default value (aligned from right)
        arg_index = func_node.args.args.index(arg)
        num_defaults = len(func_node.args.defaults)
        num_args = len(func_node.args.args)
        default_index = arg_index - (num_args - num_defaults)

        if default_index >= 0:
            default = func_node.args.defaults[default_index]
            depends_func = _extract_depends_function(
                default, di_patterns=[p.rstrip("(") for p in di_patterns]
            )

        if depends_func:
            resolved_type, source_file = _resolve_depends_return_type_with_source(
                depends_func, imports, project_root
            )
            dependencies.append(
                InjectedDependency(
                    param_name=arg.arg,
                    depends_function=depends_func,
                    resolved_type=resolved_type,
                    source_file=source_file,
                ),
            )

    return dependencies


def _extract_depends_function(node: ast.expr, di_patterns: list[str] | None = None) -> str | None:
    """Extract the function name from a Depends(func) or similar DI call.

    Args:
        node: AST node to check for DI pattern
        di_patterns: List of DI patterns like ["Depends", "Inject"]
                     If None, defaults to ["Depends"]

    Returns:
        Function name if DI pattern is found, otherwise None

    """
    if di_patterns is None:
        di_patterns = ["Depends"]

    if not isinstance(node, ast.Call):
        return None

    # Check for patterns like Depends(), Inject(), etc.
    di_function_names = {pattern.rstrip("(") for pattern in di_patterns}

    if isinstance(node.func, ast.Name) and node.func.id in di_function_names:
        if node.args:
            return _call_to_string(node.args[0])
    elif isinstance(node.func, ast.Attribute) and node.func.attr in di_function_names and node.args:
        return _call_to_string(node.args[0])

    return None


def _resolve_depends_return_type_with_source(
    depends_func: str,
    imports: dict[str, str],
    project_root: Path,
) -> tuple[str | None, str | None]:
    """Resolve the return type of a dependency function with source file.

    Returns (resolved_type, source_file).
    """
    if depends_func not in imports:
        return None, None

    full_path = imports[depends_func]
    parts = full_path.rsplit(".", 1)
    if len(parts) != 2:
        return None, None

    mod_path, func_name = parts
    file_path = _resolve_module_to_path(mod_path, project_root)
    tree = _parse_file(file_path) if file_path else None
    if not file_path or not tree:
        return None, None

    deps_imports = _extract_imports(tree)

    for node in ast.iter_child_nodes(tree):
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
            and node.returns
        ):
            continue

        return_type = _annotation_to_string(node.returns)
        if not return_type:
            continue

        rel_path = str(file_path.relative_to(project_root)).replace("\\", "/")
        type_parts = return_type.split(".")
        if type_parts[0] in deps_imports:
            resolved = deps_imports[type_parts[0]]
            if len(type_parts) > 1:
                resolved = f"{resolved}.{'.'.join(type_parts[1:])}"
            return resolved, rel_path
        return return_type, rel_path

    return None, None


def _extract_service_method_calls(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    dependencies: list[InjectedDependency],
) -> dict[str, list[str]]:
    """Extract method calls on injected dependencies.

    Returns dict mapping param_name to list of method names called.
    E.g., {"info_service": ["get_system_info", "get_health_status"]}
    """
    param_names = {dep.param_name for dep in dependencies}
    service_calls: dict[str, list[str]] = {name: [] for name in param_names}

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            value_str = _call_to_string(node.func.value)
            if value_str in param_names:
                method_name = node.func.attr
                if method_name not in service_calls[value_str]:
                    service_calls[value_str].append(method_name)

    return service_calls


def trace_project_endpoint(
    qualified_name: str, project_root: Path | None = None, config: dict | None = None
) -> dict[str, Any]:
    """Trace an API endpoint through DI to service methods.

    This is a higher-level tool that traces the complete call chain for an endpoint:
    1. Finds the endpoint function
    2. Extracts DI injections using configurable patterns
    3. Resolves service types
    4. Traces calls on those services

    Configuration used:
        backend.dependency_injection.patterns: List of DI patterns to detect
            Example: ["Depends(", "Inject(", "autowire"]
            Default: ["Depends("]
        backend.dependency_injection.module_resolution: How to map types to modules
            Example: {"Service": "nomarr.services"}

    Args:
        qualified_name: Fully qualified endpoint name
            Example: "nomarr.interfaces.api.web.info_if.web_info"
        project_root: Path to project root. Defaults to auto-detect.
        config: Optional config dict. If not provided, loaded from project_root.
            Can be obtained from: load_config(project_root)

    Returns:
        Dict with:
            - endpoint: {name, file, line} - The endpoint function location
            - dependencies: [{param, depends_on, resolved_type, source_file}]
              - Injected dependencies
            - service_calls: {param_name: [method_names]}
              - Methods called on services
            - traces: Call traces for each service method call
            - error: Optional error message

    """
    _mock_unavailable_dependencies()

    if project_root is None:
        project_root = get_workspace_root()

    # Load config if not provided (dependency injection)
    if config is None:
        config = load_config(project_root)
    backend_config = get_backend_config(config)
    di_config = backend_config.get("dependency_injection", {})
    di_patterns: list[str] = di_config.get("patterns", ["Depends("])

    # Parse the qualified name to find the file
    parts = qualified_name.split(".")

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
        return {"error": f"Could not find module for: {qualified_name}"}

    tree = _parse_file(file_path)
    if not tree:
        return {"error": f"Could not parse file: {file_path}"}

    func_node = _find_function_node(tree, func_name)
    if not func_node:
        return {"error": f"Could not find function: {func_name} in {file_path}"}

    imports = _extract_imports(tree)

    # Extract DI info with configurable patterns
    dependencies = _extract_depends_info(func_node, imports, project_root, di_patterns=di_patterns)

    # Extract method calls on injected services
    service_method_calls = _extract_service_method_calls(func_node, dependencies)

    # Build response
    rel_path = file_path.relative_to(project_root)

    result: dict[str, Any] = {
        "endpoint": {
            "name": qualified_name,
            "file": str(rel_path).replace("\\", "/"),
            "line": func_node.lineno,
        },
        "dependencies": [
            {
                "param": dep.param_name,
                "depends_on": dep.depends_function,
                "resolved_type": dep.resolved_type,
                "source_file": dep.source_file,
            }
            for dep in dependencies
        ],
        "service_calls": service_method_calls,
        "traces": {},
    }

    # Trace each service method call
    for dep in dependencies:
        if dep.resolved_type and dep.param_name in service_method_calls:
            for method_name in service_method_calls[dep.param_name]:
                # Build the fully qualified method name
                full_method = f"{dep.resolved_type}.{method_name}"
                trace = _trace_calls_recursive(full_method, project_root, set(), 0)
                if trace:
                    key = f"{dep.param_name}.{method_name}"
                    result["traces"][key] = _call_info_to_dict(trace)

    return result


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Trace API endpoint through DI")
    parser.add_argument(
        "endpoint",
        help="Fully qualified endpoint name (e.g., myapp.interfaces.api.web.info_if.web_info)",
    )

    args = parser.parse_args()

    result = trace_endpoint(args.endpoint)

    sys.stdout.write(json.dumps(result, indent=2) + "\n")

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
