#!/usr/bin/env python3
"""
ML-optimized API Discovery Tool (Standalone)

Self-contained module for discovering Python module APIs.
Returns structured JSON optimized for LLM consumption.

This is intentionally decoupled from scripts/discover_api.py (human version)
so changes to the human script don't break the MCP server.

Usage:
    # Standalone
    python scripts/mcp/discover_api_ml.py nomarr.helpers.dto.library_dto

    # As module
    from scripts.mcp.discover_api_ml import discover_api
    result = discover_api("nomarr.helpers.dto")
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


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
            parent_mock = sys.modules[parent]

        # Attach child modules to parent
        for child in children:
            full_name = f"{parent}.{child}"
            if full_name not in sys.modules:
                child_mock = MagicMock()
                sys.modules[full_name] = child_mock
                setattr(parent_mock, child, child_mock)


def _get_signature(obj: Any) -> str:
    """Get function/method signature as string (includes return type if annotated)."""
    try:
        return str(inspect.signature(obj))
    except (ValueError, TypeError):
        return "(...)"


def _get_docstring(obj: Any, max_lines: int = 1) -> str:
    """Get first N lines of docstring, cleaned. Returns single line by default."""
    doc = inspect.getdoc(obj)
    if not doc:
        return ""
    lines = doc.strip().split("\n")[:max_lines]
    # Join with space for single-line output (common case), newline for multi-line
    return " ".join(line.strip() for line in lines) if max_lines == 1 else "\n".join(line.strip() for line in lines)


def discover_api(
    module_name: str,
    *,
    include_docstrings: bool = True,
    max_doc_lines: int = 1,
) -> dict[str, Any]:
    """
    Discover the public API of a Python module.

    Returns structured JSON with classes, functions, methods, and constants.
    Optimized for LLM consumption with compact format.

    Args:
        module_name: Fully qualified module name (e.g., 'nomarr.helpers.dto')
        include_docstrings: Include docstrings in output (default: True)
        max_doc_lines: Max lines of docstring to include (default: 1 = first line only)

    Returns:
        Dict with:
            - module: Module name
            - classes: {name: {methods: {name: sig}, doc?: str}}
            - functions: {name: {sig: str, doc?: str}}
            - constants: {name: value}
            - error: Optional error message if import failed
    """
    _mock_unavailable_dependencies()

    result: dict[str, Any] = {"module": module_name}

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        result["error"] = str(e)
        return result

    classes: dict[str, Any] = {}
    functions: dict[str, Any] = {}
    constants: dict[str, Any] = {}

    for name in dir(module):
        # Skip private/dunder
        if name.startswith("_"):
            continue

        obj = getattr(module, name)

        # Skip imported modules
        if inspect.ismodule(obj):
            continue

        # Classes
        if inspect.isclass(obj):
            # Only include if defined in this module
            if obj.__module__ != module_name:
                continue

            methods: dict[str, str] = {}
            # Get methods defined directly on this class
            for method_name, method_obj in obj.__dict__.items():
                if method_name == "__init__" or (not method_name.startswith("_") and callable(method_obj)):
                    methods[method_name] = _get_signature(method_obj)

            class_info: dict[str, Any] = {"methods": methods}
            if include_docstrings:
                doc = _get_docstring(obj, max_doc_lines)
                if doc:
                    class_info["doc"] = doc

            classes[name] = class_info

        # Functions
        elif inspect.isfunction(obj):
            if obj.__module__ != module_name:
                continue

            func_info: dict[str, Any] = {"sig": _get_signature(obj)}
            if include_docstrings:
                doc = _get_docstring(obj, max_doc_lines)
                if doc:
                    func_info["doc"] = doc

            functions[name] = func_info

        # Constants (uppercase names, not callable)
        elif name.isupper() and not callable(obj):
            # Truncate long values
            val = repr(obj)
            if len(val) > 100:
                val = val[:97] + "..."
            constants[name] = val

    if classes:
        result["classes"] = classes
    if functions:
        result["functions"] = functions
    if constants:
        result["constants"] = constants

    return result


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Discover module API (ML-optimized output)")
    parser.add_argument("module", help="Module name (e.g., nomarr.helpers.dto)")
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="Omit docstrings from output",
    )
    parser.add_argument(
        "--max-doc-lines",
        type=int,
        default=1,
        help="Max docstring lines (default: 1 = first line only)",
    )

    args = parser.parse_args()

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    result = discover_api(
        args.module,
        include_docstrings=not args.no_docs,
        max_doc_lines=args.max_doc_lines,
    )

    print(json.dumps(result, indent=2))

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
