"""Locate symbol definitions by name across the codebase.

Searches all Python files for classes, functions, or variables
matching the given name. Supports partially qualified names for scoped search.
"""

__all__ = ["locate_symbol"]
import ast
from pathlib import Path
from typing import Any


def locate_symbol(symbol_name: str) -> dict[str, Any]:
    """Find all definitions of a symbol by name.

    Args:
        symbol_name: Symbol name to search for. Can be:
            - Simple name: "MyClass"
            - Partially qualified: "services.ConfigService" (scopes to services/ folder)
            - Method scoped: "ConfigService.get_config" (finds method in class)

    Returns:
        Dict with:
        - query: The symbol name searched
        - matches: List of dicts with:
            - file: Relative path from project root
            - line: Start line number (1-indexed)
            - length: Number of lines in definition
            - kind: "Class", "Function", "AsyncFunction", "Variable", or "Assignment"
            - context: Parent class name if method (optional)
            - qualified_name: Full dotted name for use with get_source
        - total_matches: Count of matches found
        - warning: Present if > 5 matches (symbol too common, simplified output)

    """
    # Parse partially qualified names
    parts = symbol_name.split(".")
    path_filter = None
    parent_filter = None
    target_name = symbol_name

    if len(parts) == 2:
        # Disambiguate: path filter vs parent scope
        # If first token looks like a folder (no uppercase), treat as path filter
        if parts[0].islower():
            path_filter = parts[0]
            target_name = parts[1]
        else:
            # Otherwise treat as parent scope (Class.method)
            parent_filter = parts[0]
            target_name = parts[1]
    elif len(parts) > 2:
        # e.g., "components.ml.MLService.process" → path filter "components/ml", parent "MLService"
        path_filter = "/".join(parts[:-2])
        parent_filter = parts[-2]
        target_name = parts[-1]

    # Find project root (walk up until we find a Python package structure)
    current = Path(__file__).resolve().parent
    root = current

    # Walk up to find workspace root (looks for common markers)
    while root.name:
        # Look for common project markers
        if (root / ".git").exists() or (root / "pyproject.toml").exists() or (root / "setup.py").exists():
            break
        # If we find a Python package at this level, use it
        python_dirs = [
            d for d in root.iterdir() if d.is_dir() and (d / "__init__.py").exists() and not d.name.startswith(".")
        ]
        if python_dirs:
            break
        parent = root.parent
        if parent == root:  # Hit filesystem root
            # Fall back to current directory
            root = Path.cwd()
            break
        root = parent

    matches = []

    # Search all Python files from root
    for py_file in root.rglob("*.py"):
        # Skip hidden, cache, and virtual environment directories
        if any(
            part.startswith(".") or part == "__pycache__" or part in {"venv", ".venv", "env", ".env", "node_modules"}
            for part in py_file.parts
        ):
            continue

        # Apply path filter if present
        relative_path = py_file.relative_to(root).as_posix()
        if path_filter and path_filter not in relative_path:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except Exception:
            # Skip unparseable files
            continue

        # Search for matching symbols
        file_matches = _search_tree(tree, target_name, py_file, root, parent_filter)
        matches.extend(file_matches)

    # Sort by file, then line
    matches.sort(key=lambda m: (m["file"], m["line"]))

    # If too many matches (> 5), return simplified output
    if len(matches) > 5:
        simplified = [
            {"file": m["file"], "line": m["line"], "qualified_name": m["qualified_name"], "kind": m["kind"]}
            for m in matches
        ]
        return {
            "query": symbol_name,
            "matches": simplified,
            "total_matches": len(matches),
            "warning": f"Symbol '{symbol_name}' is too common ({len(matches)} matches). "
            f"Showing file, line, and qualified name only. Use a more specific query with a path filter.",
        }

    return {"query": symbol_name, "matches": matches, "total_matches": len(matches)}


def _search_tree(
    tree: ast.AST, symbol_name: str, file_path: Path, root: Path, parent_filter: str | None = None
) -> list[dict]:
    """Search AST for symbols matching name.

    Args:
        tree: AST to search
        symbol_name: Target symbol name (simple name, not qualified)
        file_path: Path to file being searched
        root: Project root for relative path calculation
        parent_filter: If set, only match symbols inside this parent class

    Returns:
        List of match dicts with file, line, length, kind, context, qualified_name.

    """
    matches = []
    relative_path = file_path.relative_to(root).as_posix()

    # Build module name from file path (e.g., "myapp/services/config.py" → "myapp.services.config")
    module_parts = list(file_path.relative_to(root).parts)
    module_parts[-1] = module_parts[-1].replace(".py", "")  # Remove .py extension
    module_name = ".".join(module_parts)

    def visit_node(node: ast.AST, parent_class: str | None = None) -> None:
        # Classes
        if isinstance(node, ast.ClassDef):
            if node.name == symbol_name:
                # Check parent filter (only applies if we're inside a parent class)
                if parent_filter and parent_class and parent_class != parent_filter:
                    pass  # Skip if nested in wrong parent class
                else:
                    qualified = f"{module_name}.{node.name}"
                    if parent_class:
                        qualified = f"{module_name}.{parent_class}.{node.name}"
                    matches.append(
                        {
                            "file": relative_path,
                            "line": node.lineno,
                            "length": (node.end_lineno or node.lineno) - node.lineno + 1,
                            "kind": "Class",
                            "qualified_name": qualified,
                        }
                    )
            # Recurse into class body with context
            for child in node.body:
                visit_node(child, parent_class=node.name)

        # Functions/Methods
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol_name:
                # Check parent filter (only applies if we're inside a parent class)
                if parent_filter and parent_class and parent_class != parent_filter:
                    pass  # Skip if nested in wrong parent class
                else:
                    kind = "AsyncFunction" if isinstance(node, ast.AsyncFunctionDef) else "Function"
                    qualified = f"{module_name}.{node.name}"
                    match_info = {
                        "file": relative_path,
                        "line": node.lineno,
                        "length": (node.end_lineno or node.lineno) - node.lineno + 1,
                        "kind": kind,
                        "qualified_name": qualified,
                    }
                    if parent_class:
                        qualified = f"{module_name}.{parent_class}.{node.name}"
                        match_info["context"] = f"{parent_class} (method)"
                        match_info["qualified_name"] = qualified
                    matches.append(match_info)
            # Don't recurse into function bodies (avoid nested functions cluttering results)

        # Module-level assignments (e.g., constants, type aliases)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol_name:
                    qualified = f"{module_name}.{symbol_name}"
                    matches.append(
                        {
                            "file": relative_path,
                            "line": node.lineno,
                            "length": (node.end_lineno or node.lineno) - node.lineno + 1,
                            "kind": "Assignment",
                            "qualified_name": qualified,
                        }
                    )

        # AnnAssign for type-annotated module variables (e.g., logger: Logger = ...)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol_name:
                qualified = f"{module_name}.{symbol_name}"
                matches.append(
                    {
                        "file": relative_path,
                        "line": node.lineno,
                        "length": (node.end_lineno or node.lineno) - node.lineno + 1,
                        "kind": "Variable",
                        "qualified_name": qualified,
                    }
                )

        # Recurse for other node types
        else:
            for child in ast.iter_child_nodes(node):
                visit_node(child, parent_class)

    # Start traversal
    for node in ast.iter_child_nodes(tree):
        visit_node(node)

    return matches
