#!/usr/bin/env python3
"""
ML-optimized Source Code Retrieval Tool (Standalone)

Self-contained module for retrieving source code of Python functions,
methods, and classes. Returns the actual implementation.

This is intentionally decoupled from other scripts so changes don't break the MCP server.

Usage:
    # Standalone
    python scripts/mcp/get_source_ml.py nomarr.persistence.db.Database.close

    # As module
    from scripts.mcp.get_source_ml import get_source
    result = get_source("nomarr.persistence.db.Database.close")
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


def get_source(
    qualified_name: str,
    *,
    max_lines: int | None = None,
) -> dict[str, Any]:
    """
    Get source code of a Python function, method, or class.

    Args:
        qualified_name: Fully qualified name with dots
            Examples:
            - "nomarr.persistence.db.Database" (class)
            - "nomarr.persistence.db.Database.close" (method)
            - "nomarr.helpers.time_helper.now_ms" (function)
        max_lines: Truncate source to this many lines (None = full source)

    Returns:
        Dict with:
            - name: The qualified name requested
            - type: "function", "method", "class", or "unknown"
            - source: The source code (or None if unavailable)
            - file: Source file path
            - line: Starting line number
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

        source = inspect.getsource(source_obj)

        # Truncate if requested
        if max_lines is not None:
            lines = source.split("\n")
            if len(lines) > max_lines:
                source = "\n".join(lines[:max_lines]) + f"\n# ... ({len(lines) - max_lines} more lines)"

        result["source"] = source

        # Get file and line info
        try:
            source_file = inspect.getfile(source_obj)
            result["file"] = source_file
            _, line_number = inspect.getsourcelines(source_obj)
            result["line"] = line_number
        except (OSError, TypeError):
            pass

    except (OSError, TypeError) as e:
        result["error"] = f"Could not get source: {e}"

    return result


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Get source code of a Python function/method/class")
    parser.add_argument(
        "name",
        help="Qualified name (e.g., nomarr.persistence.db.Database.close)",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=None,
        help="Truncate to N lines (default: full source)",
    )

    args = parser.parse_args()

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    result = get_source(args.name, max_lines=args.max_lines)

    print(json.dumps(result, indent=2))

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
