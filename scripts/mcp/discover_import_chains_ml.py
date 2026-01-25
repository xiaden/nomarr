#!/usr/bin/env python3
"""
ML-optimized Import Chain Discovery Tool (Standalone)

Self-contained module for discovering import chains and architecture violations.
Uses AST parsing - no runtime imports of nomarr modules.

This is intentionally decoupled from other scripts so changes don't break the MCP server.

Usage:
    # Standalone
    python scripts/mcp/discover_import_chains_ml.py nomarr.services.queue

    # As module
    from scripts.mcp.discover_import_chains_ml import discover_import_chains
    result = discover_import_chains("nomarr.services.queue")
"""

from __future__ import annotations

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
    "components": {"persistence", "helpers", "components"},
    "persistence": {"helpers"},
    "helpers": set(),  # helpers cannot import any nomarr.* modules
}

# Violation messages
LAYER_VIOLATIONS = {
    "interfaces": "must NOT import workflows, components, or persistence",
    "services": "must NOT import interfaces",
    "workflows": "must NOT import services or interfaces",
    "components": "must NOT import workflows, services, or interfaces",
    "persistence": "must NOT import workflows, components, services, or interfaces",
    "helpers": "must NOT import any nomarr.* modules",
}


def _extract_layer(module_path: str) -> str | None:
    """Extract architecture layer from module path."""
    if not module_path.startswith("nomarr."):
        return None

    parts = module_path.split(".")
    if len(parts) < 2:
        return None

    layer = parts[1]

    # Handle components subpackages
    if layer in ("analytics", "tagging", "ml"):
        return "components"

    if layer in ARCHITECTURE_RULES:
        return layer

    return None


def _check_violation(from_module: str, to_module: str) -> str | None:
    """Check if an import violates architecture rules."""
    from_layer = _extract_layer(from_module)
    to_layer = _extract_layer(to_module)

    if not from_layer or not to_layer:
        return None

    allowed_deps = ARCHITECTURE_RULES.get(from_layer, set())

    if to_layer not in allowed_deps:
        return f"{from_layer} {LAYER_VIOLATIONS.get(from_layer, 'has invalid import')}"

    return None


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


def _extract_imports_from_file(file_path: Path, current_module: str) -> list[str]:
    """Extract imports from Python file using AST."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports = []
    current_package = ".".join(current_module.split(".")[:-1])

    for node in ast.walk(tree):
        # Skip TYPE_CHECKING blocks
        if isinstance(node, ast.If):
            if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                continue

        if isinstance(node, ast.ImportFrom):
            if node.module:
                if node.level > 0:
                    # Relative import
                    if node.level == 1:
                        base = current_package
                    else:
                        parts = current_package.split(".")
                        base = ".".join(parts[: -(node.level - 1)])

                    module = f"{base}.{node.module}" if node.module else base
                else:
                    module = node.module

                imports.append(module)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

    return imports


def _discover_chains(
    root_module: str,
    project_root: Path,
    visited: set[str] | None = None,
    depth: int = 0,
    chain: list[str] | None = None,
) -> dict[str, Any]:
    """Recursively discover import chains."""
    if visited is None:
        visited = set()
    if chain is None:
        chain = [root_module]

    result: dict[str, Any] = {"chains": [], "violations": []}

    if depth >= MAX_DEPTH or root_module in visited:
        return result

    visited.add(root_module)

    file_path = _resolve_module_to_path(root_module, project_root)
    if not file_path:
        return result

    imports = _extract_imports_from_file(file_path, root_module)
    nomarr_imports = [imp for imp in imports if imp.startswith("nomarr.")]

    for imported_module in nomarr_imports:
        violation = _check_violation(root_module, imported_module)
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

        sub_result = _discover_chains(
            imported_module,
            project_root,
            visited.copy(),
            depth + 1,
            new_chain,
        )

        result["chains"].extend(sub_result["chains"])
        result["violations"].extend(sub_result["violations"])

    return result


def _resolve_input_to_module(input_path: str, project_root: Path) -> str | None:
    """Resolve file path or module name to module name."""
    if "/" in input_path or "\\" in input_path or input_path.endswith(".py"):
        file_path = Path(input_path)

        try:
            rel_path = file_path.relative_to(project_root)
        except ValueError:
            if file_path.is_absolute() and file_path.exists():
                try:
                    rel_path = file_path.relative_to(project_root)
                except ValueError:
                    return None
            else:
                rel_path = file_path

        module_parts = rel_path.with_suffix("").parts
        if module_parts[-1] == "__init__":
            module_parts = module_parts[:-1]

        return ".".join(module_parts)

    return input_path


def discover_import_chains(
    module: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """
    Discover import chains and architecture violations for a module.

    Args:
        module: Module name or file path (e.g., 'nomarr.services.queue')
        project_root: Path to project root. Defaults to auto-detect.

    Returns:
        Dict with:
            - root: The root module analyzed
            - violations: List of architecture violations
            - direct_imports: List of direct nomarr imports
            - summary: Counts
            - error: Optional error message
    """
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent

    # Resolve input
    module_name = _resolve_input_to_module(module, project_root)
    if not module_name:
        return {"error": f"Could not resolve module: {module}"}

    # Verify module exists
    module_path = _resolve_module_to_path(module_name, project_root)
    if not module_path:
        return {"error": f"Module not found: {module_name}"}

    # Discover chains
    result = _discover_chains(module_name, project_root)

    # Deduplicate chains
    unique_chains = list({tuple(chain) for chain in result["chains"]})

    # Extract direct imports (depth 1 only)
    direct_imports = [chain[1] for chain in unique_chains if len(chain) == 2]

    return {
        "root": module_name,
        "layer": _extract_layer(module_name),
        "violations": result["violations"],
        "direct_imports": sorted(set(direct_imports)),
        "chain_count": len(unique_chains),
        "summary": {
            "violation_count": len(result["violations"]),
            "direct_import_count": len(direct_imports),
            "total_chain_count": len(unique_chains),
        },
    }


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Discover import chains and architecture violations")
    parser.add_argument(
        "module",
        help="Module name or file path (e.g., nomarr.services.queue)",
    )

    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    result = discover_import_chains(args.module, project_root)

    print(json.dumps(result, indent=2))

    if "error" in result:
        return 1
    return 1 if result["violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
