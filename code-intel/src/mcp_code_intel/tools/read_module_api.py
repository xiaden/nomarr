#!/usr/bin/env python3
"""Static API Discovery Tool (Pure AST - No Runtime Imports)

Discovers Python module APIs using only static AST parsing.
Never executes code or imports modules, making it safe to use
even when the codebase has broken/stale imports.

Returns structured JSON with complete information for LLM consumption:
- Full docstrings (not truncated)
- Complete method signatures with types
- Base class information for inheritance
- Methods from base classes when resolvable

Usage:
    # Standalone
    python -m mcp_code_intel.module_discover_api mypackage.module

    # As module
    from .module_discover_api import module_discover_api
    result = module_discover_api("mypackage.module")
"""

from __future__ import annotations

__all__ = ["read_module_api"]

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

from ..helpers.config_loader import get_workspace_root

# Constants that should be excluded (typing artifacts, not real constants)
EXCLUDED_CONSTANTS = frozenset({"TYPE_CHECKING"})


def _module_to_path(module_name: str, workspace_root: Path | None = None) -> Path | None:
    """Convert module name to file path.

    Handles both package/__init__.py and module.py cases.
    Searches in workspace root first, then in configured search paths.
    Returns None if module file not found.
    """
    if workspace_root is None:
        workspace_root = get_workspace_root()

    parts = module_name.split(".")

    # List of base directories to search
    search_bases = [workspace_root]

    # Also search in configured search paths (e.g., code-intel/src)
    from ..helpers.config_loader import get_python_search_paths, load_config

    try:
        config = load_config(workspace_root)
        for search_path in get_python_search_paths(config, workspace_root):
            # For paths like code-intel/src/mcp_code_intel, add the parent (code-intel/src)
            # so we can resolve mcp_code_intel.helpers.plan_md
            if search_path.name == parts[0]:
                search_bases.append(search_path.parent)
            else:
                search_bases.append(search_path)
    except Exception:
        pass  # Fall back to just workspace root

    for base in search_bases:
        # Try as package (dir with __init__.py)
        package_path = base / "/".join(parts) / "__init__.py"
        if package_path.exists():
            return package_path

        # Try as module (file.py)
        module_path = (
            base / "/".join(parts[:-1]) / f"{parts[-1]}.py"
            if len(parts) > 1
            else base / f"{parts[0]}.py"
        )
        if module_path.exists():
            return module_path

        # Try top-level as package
        if len(parts) == 1:
            package_path = base / parts[0] / "__init__.py"
            if package_path.exists():
                return package_path

    return None


def _resolve_relative_import(
    base_module: str,
    import_level: int,
    import_module: str | None,
    *,
    is_package: bool = False,
) -> str:
    """Resolve a relative import to an absolute module name.

    Args:
        base_module: The module where the import statement appears
        import_level: Number of dots (1 = ., 2 = .., etc.)
        import_module: The module name after the dots (can be None for 'from . import x')
        is_package: True if base_module is a package (__init__.py), affects level interpretation

    Returns:
        Absolute module path

    """
    parts = base_module.split(".")

    # For packages (__init__.py), level=1 means "same package" (no going up)
    # For regular modules, level=1 means "parent package"
    effective_level = import_level if not is_package else import_level - 1

    if effective_level > 0:
        base_parts = parts[:-effective_level] if effective_level <= len(parts) else []
    else:
        base_parts = parts

    if import_module:
        return ".".join([*base_parts, import_module])
    return ".".join(base_parts)


def _format_arg(arg: ast.arg) -> str:
    """Format a single function argument with optional annotation."""
    if arg.annotation:
        return f"{arg.arg}: {ast.unparse(arg.annotation)}"
    return arg.arg


def _format_arguments(args: ast.arguments) -> str:
    """Convert AST arguments to signature string."""
    parts: list[str] = []

    # Positional-only args (before /)
    for i, arg in enumerate(args.posonlyargs):
        formatted = _format_arg(arg)
        # Defaults for posonlyargs come from the end of args.defaults
        default_offset = len(args.defaults) - len(args.posonlyargs) - len(args.args)
        if default_offset + i >= 0 and default_offset + i < len(args.defaults):
            formatted += f" = {ast.unparse(args.defaults[default_offset + i])}"
        parts.append(formatted)

    if args.posonlyargs:
        parts.append("/")

    # Regular positional args
    num_defaults = len(args.defaults)
    num_args = len(args.args)
    for i, arg in enumerate(args.args):
        formatted = _format_arg(arg)
        # Defaults align to the end
        default_idx = i - (num_args - num_defaults)
        if default_idx >= 0:
            formatted += f" = {ast.unparse(args.defaults[default_idx])}"
        parts.append(formatted)

    # *args
    if args.vararg:
        parts.append(f"*{_format_arg(args.vararg)}")
    elif args.kwonlyargs:
        parts.append("*")

    # Keyword-only args
    for i, arg in enumerate(args.kwonlyargs):
        formatted = _format_arg(arg)
        kw_default = args.kw_defaults[i]
        if kw_default is not None:
            formatted += f" = {ast.unparse(kw_default)}"
        parts.append(formatted)

    # **kwargs
    if args.kwarg:
        parts.append(f"**{_format_arg(args.kwarg)}")

    return ", ".join(parts)


def _get_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Extract function signature from AST node."""
    args_str = _format_arguments(node.args)
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    if node.returns:
        return f"{prefix}({args_str}) -> {ast.unparse(node.returns)}"
    return f"{prefix}({args_str})"


def _get_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    """Extract full docstring from AST node. No truncation."""
    if not node.body:
        return ""
    first = node.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first.value.value.strip()
    return ""


def _extract_methods(class_node: ast.ClassDef) -> dict[str, dict[str, Any]]:
    """Extract methods from a class node.

    Returns dict mapping method name to {sig: str, doc?: str}
    """
    methods: dict[str, dict[str, Any]] = {}

    for item in class_node.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            method_info: dict[str, Any] = {"sig": _get_signature(item)}
            doc = _get_docstring(item)
            if doc:
                method_info["doc"] = doc
            methods[item.name] = method_info

    return methods


def _extract_fields(class_node: ast.ClassDef) -> dict[str, dict[str, Any]]:
    """Extract class fields (annotated assignments) from a class node.

    Useful for dataclasses, TypedDicts, and classes with type-annotated attributes.

    Returns dict mapping field name to {type: str, default?: str}
    """
    fields: dict[str, dict[str, Any]] = {}

    for item in class_node.body:
        # Annotated assignment: field: Type or field: Type = value
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            field_name = item.target.id
            field_info: dict[str, Any] = {}

            # Get type annotation
            try:
                field_info["type"] = ast.unparse(item.annotation)
            except Exception:
                field_info["type"] = "Any"

            # Get default value if present
            if item.value is not None:
                try:
                    default_str = ast.unparse(item.value)
                    # Truncate long defaults
                    if len(default_str) > 50:
                        default_str = default_str[:47] + "..."
                    field_info["default"] = default_str
                except Exception:
                    pass

            fields[field_name] = field_info

    return fields


def _resolve_base_classes(
    class_node: ast.ClassDef,
    current_module: str,
    imports: dict[str, str],
    visited: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve methods from base classes (mixins, parents).

    Recursively follows inheritance chain to collect all inherited methods.
    Only resolves classes within the project (not stdlib/third-party).

    Args:
        class_node: The AST ClassDef node
        current_module: Module path where this class is defined
        imports: Mapping of local names to module paths from imports in current file
        visited: Set of already-visited class paths to prevent cycles

    Returns:
        Dict of method_name -> {sig, doc?} from all base classes

    """
    if visited is None:
        visited = set()

    all_methods: dict[str, dict[str, Any]] = {}

    for base in class_node.bases:
        base_name: str | None = None
        base_module: str | None = None

        # Simple name: class Foo(BarMixin)
        if isinstance(base, ast.Name):
            base_name = base.id
            # Look up in imports
            if base_name in imports:
                base_module = imports[base_name]
            else:
                # Might be defined in same file - skip for now
                continue

        # Attribute: class Foo(some_module.Bar)
        elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
            module_alias = base.value.id
            base_name = base.attr
            if module_alias in imports:
                base_module = f"{imports[module_alias]}.{base_name}"
            else:
                continue
        else:
            continue

        if not base_module:
            continue

        # Prevent cycles
        class_path = (
            f"{base_module}.{base_name}" if base_name and "." not in base_module else base_module
        )
        if class_path in visited:
            continue
        visited.add(class_path)

        # Try to find and parse the base class file
        # Extract module path (without class name at end)
        if base_name and base_module.endswith(f".{base_name}"):
            module_path = base_module[: -len(base_name) - 1]
        else:
            module_path = base_module

        source_path = _module_to_path(module_path)
        if source_path is None:
            continue

        base_is_package = source_path.name == "__init__.py"

        try:
            source = source_path.read_bytes().decode("utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue

        # Find the class in the parsed file
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == base_name:
                # Extract imports from this file for recursive resolution
                base_imports = _extract_imports(tree, module_path, is_package=base_is_package)

                # Get methods from this base class
                base_methods = _extract_methods(node)
                # Child methods override parent methods, so only add if not present
                for name, info in base_methods.items():
                    if name not in all_methods:
                        all_methods[name] = info

                # Recursively get methods from this class's bases
                parent_methods = _resolve_base_classes(node, module_path, base_imports, visited)
                for name, info in parent_methods.items():
                    if name not in all_methods:
                        all_methods[name] = info

                break

    return all_methods


def _extract_imports(
    tree: ast.Module, current_module: str, *, is_package: bool = False
) -> dict[str, str]:
    """Extract import mappings from an AST.

    Returns dict mapping local name -> absolute module path

    Args:
        tree: Parsed AST module
        current_module: Module path of the file being parsed
        is_package: True if this is an __init__.py file

    """
    imports: dict[str, str] = {}

    for node in tree.body:
        # from .foo import Bar  or  from ..foo import Bar
        if isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # Relative import
                abs_module = _resolve_relative_import(
                    current_module,
                    node.level,
                    node.module,
                    is_package=is_package,
                )
            else:
                abs_module = node.module or ""

            for alias in node.names:
                local_name = alias.asname or alias.name
                imports[local_name] = f"{abs_module}.{alias.name}" if abs_module else alias.name

        # import foo.bar  or  import foo.bar as fb
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                imports[local_name] = alias.name

    return imports


def read_module_api(
    module_name: str,
    *,
    include_docstrings: bool = True,
    include_inherited: bool = True,
) -> dict[str, Any]:
    """Discover the entire API of any Python module.

    Uses pure static AST parsing - never imports or executes code.
    Safe to use even when modules have broken dependencies.

    Args:
        module_name: Fully qualified module name (e.g., 'nomarr.helpers.dto')
        include_docstrings: Include full docstrings in output (default: True)
        include_inherited: Include methods from base classes/mixins (default: True)

    Returns:
        Dict with:
            - module: Module name
            - classes: {name: {bases: [...], methods: {name: {sig, doc?}}, doc?: str}}
            - functions: {name: {sig: str, doc?: str}}
            - constants: {name: value}
            - file: Source file path (if found)
            - error: Optional error message if file not found or parse failed

    """
    result: dict[str, Any] = {"module": module_name}

    # Find the source file
    source_path = _module_to_path(module_name)
    if source_path is None:
        result["error"] = f"Could not find module file for: {module_name}"
        return result

    is_package = source_path.name == "__init__.py"
    result["file"] = str(source_path)

    # Read and parse source
    try:
        source = source_path.read_bytes().decode("utf-8")
        tree = ast.parse(source)
    except SyntaxError as e:
        result["error"] = f"Syntax error in {source_path}: {e}"
        return result
    except OSError as e:
        result["error"] = f"Could not read {source_path}: {e}"
        return result

    # Extract imports for base class resolution
    imports = _extract_imports(tree, module_name, is_package=is_package)

    classes: dict[str, Any] = {}
    functions: dict[str, Any] = {}
    constants: dict[str, Any] = {}

    for node in tree.body:
        # Classes
        if isinstance(node, ast.ClassDef):
            # Get base class names for display
            bases: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(ast.unparse(base))

            # Get methods defined directly on this class
            methods = _extract_methods(node)

            # Get fields (annotated assignments) - important for dataclasses
            fields = _extract_fields(node)

            # Add inherited methods if requested
            if include_inherited:
                inherited = _resolve_base_classes(node, module_name, imports)
                for name, info in inherited.items():
                    if name not in methods:
                        # Mark as inherited
                        info_with_source = dict(info)
                        info_with_source["inherited"] = True
                        methods[name] = info_with_source

            class_info: dict[str, Any] = {}
            if fields:
                class_info["fields"] = fields
            if methods:
                class_info["methods"] = methods
            if bases:
                class_info["bases"] = bases
            if include_docstrings:
                doc = _get_docstring(node)
                if doc:
                    class_info["doc"] = doc

            classes[node.name] = class_info

        # Functions
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func_info: dict[str, Any] = {"sig": _get_signature(node)}
            if include_docstrings:
                doc = _get_docstring(node)
                if doc:
                    func_info["doc"] = doc

            functions[node.name] = func_info

        # Constants (uppercase names with simple value assignments)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id.isupper()
                    and target.id not in EXCLUDED_CONSTANTS
                ):
                    try:
                        val = ast.unparse(node.value)
                        if len(val) > 100:
                            val = val[:97] + "..."
                        constants[target.id] = val
                    except Exception:
                        # Can't unparse complex values, skip
                        pass
                # Capture __all__ explicitly
                elif isinstance(target, ast.Name) and target.id == "__all__":
                    try:
                        if isinstance(node.value, ast.List):
                            all_items = [
                                elt.value
                                for elt in node.value.elts
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            ]
                            result["__all__"] = all_items
                    except Exception:
                        pass

    if classes:
        result["classes"] = classes
    if functions:
        result["functions"] = functions
    if constants:
        result["constants"] = constants

    return result


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Discover module API (static AST, no imports)")
    parser.add_argument("module", help="Module name (e.g., nomarr.helpers.dto)")
    parser.add_argument("--no-docs", action="store_true", help="Omit docstrings from output")
    parser.add_argument(
        "--no-inherited", action="store_true", help="Omit inherited methods from base classes"
    )

    args = parser.parse_args()

    result = read_module_api(
        args.module,
        include_docstrings=not args.no_docs,
        include_inherited=not args.no_inherited,
    )

    sys.stdout.write(json.dumps(result, indent=2))
    sys.stdout.write("\n")

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
