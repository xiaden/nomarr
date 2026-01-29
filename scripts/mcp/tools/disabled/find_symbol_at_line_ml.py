"""Find which Python symbol (function/class/method) contains a specific line number.

Returns the qualified name suitable for use with get_source().
"""

import ast
from pathlib import Path


def find_symbol_at_line(file_path: str, line_number: int) -> dict:
    """Find the qualified name of the symbol containing the given line number.

    Args:
        file_path: Absolute or relative path to Python file
        line_number: Line number (1-indexed)

    Returns:
        Dict with:
        - file: Resolved file path
        - line: The queried line number
        - qualified_name: Full dotted name (e.g., 'nomarr.components.ml.compute_embeddings')
        - symbol_type: 'function', 'method', 'class', or 'module'
        - start_line: Where the symbol definition starts
        - end_line: Where the symbol definition ends
        - error: Error message if lookup fails

    """
    path = Path(file_path).resolve()

    if not path.exists():
        return {"file": str(path), "line": line_number, "error": f"File not found: {path}"}

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except Exception as e:
        return {"file": str(path), "line": line_number, "error": f"Failed to parse file: {e}"}

    # Convert file path to module name (relative to project root)
    # Assume ROOT is grandparent of scripts/mcp/
    root = path.parent
    while root.name and not (root / "nomarr").exists():
        root = root.parent
        if root == root.parent:  # Hit filesystem root
            return {
                "file": str(path),
                "line": line_number,
                "error": "Could not determine project root (no 'nomarr' directory found)",
            }

    try:
        rel_path = path.relative_to(root)
        module_parts = list(rel_path.with_suffix("").parts)
        base_module = ".".join(module_parts)
    except ValueError:
        return {"file": str(path), "line": line_number, "error": f"File is outside project root: {path}"}

    # Walk AST to find containing symbol
    result = _find_containing_node(tree, line_number, base_module)

    if result:
        return {
            "file": str(path),
            "line": line_number,
            "qualified_name": result["qualified_name"],
            "symbol_type": result["symbol_type"],
            "start_line": result["start_line"],
            "end_line": result["end_line"],
        }
    else:
        return {
            "file": str(path),
            "line": line_number,
            "qualified_name": base_module,
            "symbol_type": "module",
            "error": f"Line {line_number} is at module level (not inside any function or class)",
        }


def _find_containing_node(tree: ast.AST, line_number: int, module_name: str) -> dict | None:
    """Recursively find the deepest AST node containing the line number.

    Returns dict with qualified_name, symbol_type, start_line, end_line or None.
    """
    best_match = None

    def visit_node(node: ast.AST, parent_names: list[str]) -> None:
        nonlocal best_match

        # Only interested in named definitions
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Still recurse into children
            for child in ast.iter_child_nodes(node):
                visit_node(child, parent_names)
            return

        node_start = getattr(node, "lineno", None)
        node_end = getattr(node, "end_lineno", None)

        if node_start is None or node_end is None:
            # Recurse anyway
            for child in ast.iter_child_nodes(node):
                visit_node(child, parent_names)
            return

        # Check if line is within this node
        if node_start <= line_number <= node_end:
            # This node contains the line
            current_name = node.name
            full_name = ".".join([*parent_names, current_name])
            qualified_name = f"{module_name}.{full_name}" if parent_names else f"{module_name}.{current_name}"

            symbol_type = "class" if isinstance(node, ast.ClassDef) else "function"
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and parent_names:
                # Method inside a class
                symbol_type = "method"

            # Update best match (prefer deeper matches)
            if best_match is None or node_start >= best_match["start_line"]:
                best_match = {
                    "qualified_name": qualified_name,
                    "symbol_type": symbol_type,
                    "start_line": node_start,
                    "end_line": node_end,
                }

            # Recurse to find deeper matches (e.g., nested functions)
            new_parent_names = [*parent_names, current_name]
            for child in ast.iter_child_nodes(node):
                visit_node(child, new_parent_names)
        else:
            # Not in this node, but still check siblings
            for child in ast.iter_child_nodes(node):
                visit_node(child, parent_names)

    # Start traversal from module root
    for node in ast.iter_child_nodes(tree):
        visit_node(node, [])

    return best_match
