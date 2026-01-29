#!/usr/bin/env python3
"""ML-optimized Source Code Retrieval Tool (Standalone).

Self-contained module for retrieving source code of Python functions,
methods, and classes. Returns the actual implementation.

This is intentionally decoupled from other scripts so changes don't break the MCP server.

Usage:
    # Standalone
    python scripts/mcp/get_source_ml.py nomarr.persistence.db.Database.close

    # As module
    from scripts.mcp.tools.get_source import get_source
    result = get_source("nomarr.persistence.db.Database.close")
"""

from __future__ import annotations

__all__ = ["get_source"]

import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

try:
    from scripts.mcp.tools.helpers.log_suppressor import suppress_logs
except ImportError:
    # Fallback if not available (standalone mode)
    from contextlib import contextmanager
    from typing import Iterator

    @contextmanager
    def suppress_logs() -> Iterator[None]:
        yield


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


def get_source(qualified_name: str, *, context_lines: int = 0, max_lines: int | None = None) -> dict[str, Any]:
    """Get source code of a Python function, method, or class.

    Args:
        qualified_name: Fully qualified name with dots
            Examples:
            - "nomarr.persistence.db.Database" (class)
            - "nomarr.persistence.db.Database.close" (method)
            - "nomarr.helpers.time_helper.now_ms" (function)
        context_lines: Include N lines before the entity (for edit context)
        max_lines: Truncate source to this many lines (None = full source)

    Returns:
        Dict with:
            - name: The qualified name requested
            - type: "function", "method", "class", or "unknown"
            - source: The source code as a string
            - file: Source file path
            - line: Starting line number (of context if included)
            - line_count: Total lines returned
            - error: Optional error message

    """
    _mock_unavailable_dependencies()

    result: dict[str, Any] = {"name": qualified_name}

    # Parse the qualified name
    parts = qualified_name.rsplit(".", 1)
    if len(parts) == 1:
        result["error"] = f"Invalid qualified name: {qualified_name} (need at least module.name)"
        return result

    parent_path, target_name = parts

    # Try to import and resolve
    obj = None
    obj_type = "unknown"

    # First, try treating parent_path as a module
    try:
        with suppress_logs():
            module = importlib.import_module(parent_path)
        if hasattr(module, target_name):
            obj = getattr(module, target_name)
            if inspect.isclass(obj):
                obj_type = "class"
            elif inspect.isfunction(obj):
                obj_type = "function"
    except ImportError:
        pass

    # If that didn't work, try parent_path as module.Class
    if obj is None:
        parent_parts = parent_path.rsplit(".", 1)
        if len(parent_parts) == 2:
            module_path, class_name = parent_parts
            try:
                with suppress_logs():
                    module = importlib.import_module(module_path)
                if hasattr(module, class_name):
                    cls = getattr(module, class_name)
                    if inspect.isclass(cls) and hasattr(cls, target_name):
                        obj = getattr(cls, target_name)
                        obj_type = "method"
            except ImportError:
                pass

    if obj is None:
        result["error"] = f"Could not resolve: {qualified_name}"
        return result

    result["type"] = obj_type

    # Get source code
    try:
        # For methods, we need to unwrap
        source_obj = obj
        if hasattr(obj, "__func__"):
            source_obj = obj.__func__

        source_lines_raw, line_number = inspect.getsourcelines(source_obj)

        # Get file path first (needed for context)
        source_file = None
        try:
            source_file = inspect.getfile(source_obj)
            result["file"] = source_file
        except (OSError, TypeError):
            pass

        # Prepend context lines if requested
        if context_lines > 0 and source_file:
            context_start = max(1, line_number - context_lines)
            with open(source_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                context = all_lines[context_start - 1 : line_number - 1]
                source_lines_raw = context + source_lines_raw
                line_number = context_start

        # Truncate if requested
        if max_lines is not None and len(source_lines_raw) > max_lines:
            source_lines_raw = source_lines_raw[:max_lines]

        result["source"] = "".join(source_lines_raw)
        result["line"] = line_number
        result["line_count"] = len(source_lines_raw)

    except (OSError, TypeError) as e:
        result["error"] = f"Could not get source: {e}"

    return result


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Get source code of a Python function/method/class")
    parser.add_argument("name", help="Qualified name (e.g., nomarr.persistence.db.Database.close)")
    parser.add_argument(
        "--context-lines", type=int, default=0, help="Include N lines before the entity (for edit context)"
    )
    parser.add_argument("--max-lines", type=int, default=None, help="Truncate to N lines (default: full source)")

    args = parser.parse_args()

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    result = get_source(args.name, context_lines=args.context_lines, max_lines=args.max_lines)

    print(json.dumps(result, indent=2))

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
