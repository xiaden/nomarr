#!/usr/bin/env python3
"""Import Chain Discovery and Architecture Violation Detector.

Traces full import chains starting from a root module and identifies
violations of Nomarr's layered architecture rules.

Usage:
    python scripts/discover_import_chains.py nomarr.workflows.library.scan_library
    python scripts/discover_import_chains.py nomarr.services.queue --format=json
    python scripts/discover_import_chains.py nomarr/interfaces/api/coordinator.py
"""

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

# Maximum recursion depth to prevent infinite loops
MAX_DEPTH = 10

# Architecture rules: layer -> set of allowed dependencies
ARCHITECTURE_RULES = {
    "interfaces": {"services", "helpers"},
    "services": {"workflows", "persistence", "components", "helpers"},
    "workflows": {"persistence", "components", "helpers"},
    "components": {"persistence", "helpers", "components"},  # components can import each other
    "persistence": {"helpers"},
    "helpers": set(),  # helpers cannot import any nomarr.* modules
}

# Reverse mapping for error messages
LAYER_VIOLATIONS = {
    "interfaces": "must NOT import workflows, components, or persistence",
    "services": "must NOT import interfaces",
    "workflows": "must NOT import services or interfaces",
    "components": "must NOT import workflows, services, or interfaces",
    "persistence": "must NOT import workflows, components, services, or interfaces",
    "helpers": "must NOT import any nomarr.* modules",
}


def extract_layer(module_path: str) -> str | None:
    """Extract the architecture layer from a module path.

    Args:
        module_path: Fully qualified module path (e.g., "nomarr.services.queue")

    Returns:
        Layer name or None if not a nomarr module

    """
    if not module_path.startswith("nomarr."):
        return None

    parts = module_path.split(".")
    if len(parts) < 2:
        return None

    layer = parts[1]

    # Handle components subpackages (analytics, tagging, ml)
    if layer in ("analytics", "tagging", "ml"):
        return "components"

    # Map legacy paths
    if layer == "data":
        return "persistence"
    if layer == "core":
        # core was old workflows location
        return "workflows"

    # Standard layers
    if layer in ARCHITECTURE_RULES:
        return layer

    return None


def check_violation(from_module: str, to_module: str) -> str | None:
    """Check if an import violates architecture rules.

    Args:
        from_module: Module doing the importing
        to_module: Module being imported

    Returns:
        Violation message or None if allowed

    """
    from_layer = extract_layer(from_module)
    to_layer = extract_layer(to_module)

    # Not a nomarr module or can't determine layer
    if not from_layer or not to_layer:
        return None

    # Check if this import is allowed
    allowed_deps = ARCHITECTURE_RULES.get(from_layer, set())

    if to_layer not in allowed_deps:
        return f"{from_layer} {LAYER_VIOLATIONS.get(from_layer, 'has invalid import')}"

    return None


def resolve_module_to_path(module_name: str, project_root: Path) -> Path | None:
    """Resolve a module name to a file path.

    Args:
        module_name: Fully qualified module name (e.g., "nomarr.services.queue")
        project_root: Project root directory

    Returns:
        Path to the module file or None if not found

    """
    # Convert module path to file path
    parts = module_name.split(".")

    # Try as a .py file
    file_path = project_root / "/".join(parts)
    py_file = file_path.with_suffix(".py")
    if py_file.exists():
        return py_file

    # Try as a package (__init__.py)
    init_file = file_path / "__init__.py"
    if init_file.exists():
        return init_file

    return None


def extract_imports_from_file(file_path: Path, current_module: str) -> list[str]:
    """Extract all imports from a Python file using AST.

    Args:
        file_path: Path to the Python file
        current_module: Current module name for resolving relative imports

    Returns:
        List of absolute module names imported

    """
    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports = []
    current_package = ".".join(current_module.split(".")[:-1])  # Parent package

    for node in ast.walk(tree):
        # Skip TYPE_CHECKING blocks (they're not runtime imports)
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            continue

        if isinstance(node, ast.ImportFrom):
            if node.module:
                # Handle relative imports
                if node.level > 0:
                    # Relative import: from . import X or from .. import Y
                    if node.level == 1:
                        base = current_package
                    else:
                        # Go up (node.level - 1) levels
                        parts = current_package.split(".")
                        base = ".".join(parts[: -(node.level - 1)])

                    if node.module:
                        module = f"{base}.{node.module}"
                    else:
                        module = base
                else:
                    module = node.module

                imports.append(module)

                # Also track specific imports for more granular chains
                for alias in node.names:
                    if alias.name != "*":
                        imports.append(f"{module}.{alias.name}")

        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

    return imports


def discover_import_chains(
    root_module: str,
    project_root: Path,
    visited: set[str] | None = None,
    depth: int = 0,
    chain: list[str] | None = None,
) -> dict[str, Any]:
    """Recursively discover import chains starting from a root module.

    Args:
        root_module: Starting module name
        project_root: Project root directory
        visited: Set of already-visited modules (prevents cycles)
        depth: Current recursion depth
        chain: Current import chain

    Returns:
        Dictionary containing chains and violations

    """
    if visited is None:
        visited = set()
    if chain is None:
        chain = [root_module]

    result: dict[str, Any] = {
        "chains": [],
        "violations": [],
    }

    # Prevent infinite recursion
    if depth >= MAX_DEPTH:
        return result

    # Prevent circular imports
    if root_module in visited:
        return result

    visited.add(root_module)

    # Resolve module to file
    file_path = resolve_module_to_path(root_module, project_root)
    if not file_path:
        return result

    # Extract imports from this module
    imports = extract_imports_from_file(file_path, root_module)

    # Filter to only nomarr modules
    nomarr_imports = [imp for imp in imports if imp.startswith("nomarr.")]

    for imported_module in nomarr_imports:
        # Check for violation
        violation = check_violation(root_module, imported_module)

        new_chain = [*chain, imported_module]
        result["chains"].append(new_chain)

        if violation:
            result["violations"].append(
                {
                    "rule": violation,
                    "chain": new_chain,
                    "from": root_module,
                    "to": imported_module,
                }
            )

        # Recursively discover imports from this module
        sub_result = discover_import_chains(
            imported_module,
            project_root,
            visited.copy(),  # Copy to allow different branches
            depth + 1,
            new_chain,
        )

        result["chains"].extend(sub_result["chains"])
        result["violations"].extend(sub_result["violations"])

    return result


def format_text_output(root_module: str, result: dict[str, Any]) -> str:
    """Format results as human-readable text."""
    lines = []
    lines.append("=" * 80)
    lines.append(f"Import Chain Analysis: {root_module}")
    lines.append("=" * 80)
    lines.append("")

    # Violations
    if result["violations"]:
        lines.append(f"[!] ARCHITECTURE VIOLATIONS ({len(result['violations'])}):")
        lines.append("")

        for violation in result["violations"]:
            lines.append(f"  Rule: {violation['rule']}")
            lines.append(f"  From: {violation['from']}")
            lines.append(f"  To:   {violation['to']}")
            lines.append(f"  Chain: {' → '.join(violation['chain'])}")
            lines.append("")
    else:
        lines.append("[OK] No architecture violations found")
        lines.append("")

    # Import chains summary
    unique_chains = list({tuple(chain) for chain in result["chains"]})
    if unique_chains:
        lines.append(f"IMPORT CHAINS ({len(unique_chains)} unique):")
        lines.append("")

        # Show first 20 chains
        for chain in sorted(unique_chains)[:20]:
            lines.append(f"  {' → '.join(chain)}")

        if len(unique_chains) > 20:
            lines.append(f"  ... and {len(unique_chains) - 20} more chains")
        lines.append("")

    return "\n".join(lines)


def format_json_output(root_module: str, result: dict[str, Any]) -> str:
    """Format results as JSON."""
    # Deduplicate chains
    unique_chains = list({tuple(chain) for chain in result["chains"]})

    output = {
        "root": root_module,
        "violations": result["violations"],
        "chains": [list(chain) for chain in unique_chains],
        "summary": {
            "violation_count": len(result["violations"]),
            "chain_count": len(unique_chains),
        },
    }

    return json.dumps(output, indent=2)


def resolve_input_to_module(input_path: str, project_root: Path) -> str:
    """Resolve input (module path or file path) to a module name.

    Args:
        input_path: User input (e.g., "nomarr.services.queue" or "nomarr/services/queue.py")
        project_root: Project root directory

    Returns:
        Fully qualified module name

    """
    # If it looks like a file path, convert to module path
    if "/" in input_path or "\\" in input_path or input_path.endswith(".py"):
        file_path = Path(input_path)

        # Make relative to project root
        try:
            rel_path = file_path.relative_to(project_root)
        except ValueError:
            # Try as absolute path
            if file_path.is_absolute() and file_path.exists():
                rel_path = file_path.relative_to(project_root)
            else:
                # Assume it's relative to cwd
                rel_path = file_path

        # Convert to module path
        module_parts = rel_path.with_suffix("").parts

        # Remove __init__ if present
        if module_parts[-1] == "__init__":
            module_parts = module_parts[:-1]

        return ".".join(module_parts)

    # Already a module path
    return input_path


def main():
    parser = argparse.ArgumentParser(description="Discover import chains and detect architecture violations")
    parser.add_argument(
        "module",
        help="Module name or file path (e.g., nomarr.services.queue or nomarr/services/queue.py)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (human-readable) or json (machine-readable)",
    )

    args = parser.parse_args()

    # Determine project root
    project_root = Path.cwd()
    if not (project_root / "nomarr").exists():
        # Try to find nomarr directory
        script_dir = Path(__file__).parent
        potential_root = script_dir.parent
        if (potential_root / "nomarr").exists():
            project_root = potential_root
        else:
            print("Error: Cannot find nomarr directory. Run from project root.")
            return 1

    # Resolve input to module name
    try:
        module_name = resolve_input_to_module(args.module, project_root)
    except Exception as e:
        print(f"Error resolving module: {e}")
        return 1

    # Verify module exists
    module_path = resolve_module_to_path(module_name, project_root)
    if not module_path:
        print(f"Error: Module not found: {module_name}")
        return 1

    # Discover import chains
    result = discover_import_chains(module_name, project_root)

    # Output results
    if args.format == "json":
        print(format_json_output(module_name, result))
    else:
        print(format_text_output(module_name, result))

    # Exit with error code if violations found
    return 1 if result["violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
