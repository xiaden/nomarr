#!/usr/bin/env python3
"""
API Discovery Tool - Quickly show the public API of a module.

This helps developers and AI agents understand what's actually available
in a module without guessing or reading full source files.

Usage:
    python scripts/discover_api.py nomarr.data.db
    python scripts/discover_api.py nomarr.data.queue
    python scripts/discover_api.py nomarr.interfaces.api.auth
"""

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any


def discover_module_api(module_name: str, *, silent: bool = False) -> dict[str, Any]:
    """
    Discover the public API of a module.

    Args:
        module_name: Fully qualified module name
        silent: If True, suppress error messages (for --summary mode)

    Returns dict with:
        - classes: list of class names and their public methods
        - functions: list of function names and signatures
        - constants: list of module-level constants
        - error: (optional) error message if import failed
    """
    # Mock Docker-only dependencies for discovery
    import sys
    from unittest.mock import MagicMock

    mock_modules = [
        "essentia",
        "essentia.standard",
        "tensorflow",
        "tensorflow.lite",
        "tensorflow.lite.python",
        "tensorflow.lite.python.interpreter",
        "scipy",
        "scipy.stats",
        "scipy.signal",
    ]
    for mock_module in mock_modules:
        if mock_module not in sys.modules:
            sys.modules[mock_module] = MagicMock()

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        if not silent:
            print(f"❌ Failed to import {module_name}: {e}")
        # Return dict with error field instead of empty dict
        return {"classes": {}, "functions": {}, "constants": {}, "error": str(e)}

    api: dict[str, Any] = {"classes": {}, "functions": {}, "constants": {}}

    # Get all public members (not starting with _)
    for name in dir(module):
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

            methods = {}
            # Only include methods defined directly on this class
            for method_name, method_obj in obj.__dict__.items():
                # Include __init__ and public methods only
                if method_name == "__init__" or (not method_name.startswith("_") and callable(method_obj)):
                    try:
                        sig = inspect.signature(method_obj)
                        methods[method_name] = str(sig)
                    except (ValueError, TypeError):
                        methods[method_name] = "(...)"

            api["classes"][name] = {"methods": methods, "doc": inspect.getdoc(obj) or ""}

        # Functions
        elif inspect.isfunction(obj):
            if obj.__module__ != module_name:
                continue

            try:
                sig = inspect.signature(obj)
                api["functions"][name] = {"signature": str(sig), "doc": inspect.getdoc(obj) or ""}
            except (ValueError, TypeError):
                api["functions"][name] = {"signature": "(...)", "doc": inspect.getdoc(obj) or ""}

        # Constants (uppercase variables)
        elif name.isupper() and not callable(obj):
            api["constants"][name] = repr(obj)[:100]  # Truncate long values

    return api


def print_json_summary(module_name: str, api: dict[str, Any]) -> None:
    """Print machine-readable JSON summary."""
    summary = {
        "module": module_name,
        "classes": api.get("classes", {}),
        "functions": api.get("functions", {}),
        "constants": api.get("constants", {}),
    }
    # Include error field if present
    if "error" in api:
        summary["error"] = api["error"]
    print(json.dumps(summary, indent=2, sort_keys=True))


def print_api(module_name: str, api: dict[str, Any]):
    """Pretty print the API."""
    print(f"\n{'=' * 80}")
    print(f"Module: {module_name}")
    print(f"{'=' * 80}\n")

    # Classes
    if api.get("classes"):
        print("📦 CLASSES:\n")
        for class_name, class_info in sorted(api["classes"].items()):
            print(f"  class {class_name}:")
            doc = class_info["doc"].split("\n")[0][:60]
            if doc:
                print(f"    {doc}")

            methods = class_info["methods"]
            if methods:
                print(f"\n    Methods ({len(methods)}):")
                for method_name, sig in sorted(methods.items()):
                    print(f"      • {method_name}{sig}")
            print()

    # Functions
    if api.get("functions"):
        print("🔧 FUNCTIONS:\n")
        for func_name, func_info in sorted(api["functions"].items()):
            sig = func_info["signature"]
            print(f"  def {func_name}{sig}:")
            doc = func_info["doc"].split("\n")[0][:60]
            if doc:
                print(f"      {doc}")
            print()

    # Constants
    if api.get("constants"):
        print("📌 CONSTANTS:\n")
        for const_name, const_value in sorted(api["constants"].items()):
            print(f"  {const_name} = {const_value}")
        print()

    if not any([api.get("classes"), api.get("functions"), api.get("constants")]):
        print("  (No public API found)")


def main():
    parser = argparse.ArgumentParser(description="Discover module API")
    parser.add_argument("module", help="Module name (e.g., nomarr.data.db)")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print machine-readable JSON summary instead of formatted text",
    )

    args = parser.parse_args()

    # Add current directory to path for imports
    sys.path.insert(0, str(Path.cwd()))

    # Handle plural/singular module name variations
    module_name = args.module

    # Common pluralization fixes: try both forms
    if "nomarr.ml.model" in module_name and "nomarr.ml.models" not in module_name:
        module_name = module_name.replace("nomarr.ml.model", "nomarr.ml.models")
    elif module_name.rstrip("s") == "nomarr.persistence.database":
        # Handle both 'database' and 'databases'
        pass  # Already correct

    # In summary mode, wrap everything in try/except to always return valid JSON
    if args.summary:
        try:
            api = discover_module_api(module_name, silent=True)

            # Check if import failed (api has error field)
            if "error" in api:
                # Try alternate pluralization
                if module_name.endswith("s"):
                    alt_module = module_name[:-1]  # Try singular
                else:
                    alt_module = module_name + "s"  # Try plural

                alt_api = discover_module_api(alt_module, silent=True)
                if "error" not in alt_api:
                    # Alternate worked!
                    module_name = alt_module
                    api = alt_api
                else:
                    # Both failed, combine error messages
                    api["error"] = f"{api['error']} (also tried {alt_module})"

            # Print summary (with or without error field)
            print_json_summary(module_name, api)
            return 0

        except Exception as e:
            # Catch any other unexpected errors
            error_json = {
                "module": module_name,
                "classes": {},
                "functions": {},
                "constants": {},
                "error": str(e),
            }
            print(json.dumps(error_json, indent=2, sort_keys=True))
            return 0  # Exit with 0 so downstream tooling can parse JSON

    # Non-summary mode: preserve existing behavior
    api = discover_module_api(module_name)

    # If import failed and we haven't tried the alternate form, try it
    if not api and module_name != args.module:
        # Already tried alternate, fail
        return 1
    elif not api:
        # Try alternate pluralization
        if module_name.endswith("s"):
            alt_module = module_name[:-1]  # Try singular
        else:
            alt_module = module_name + "s"  # Try plural

        api = discover_module_api(alt_module)
        if api:
            module_name = alt_module
            print(f"ℹ️  Note: Using '{alt_module}' (you typed '{args.module}')\n")
        else:
            return 1

    print_api(module_name, api)
    return 0


if __name__ == "__main__":
    sys.exit(main())
