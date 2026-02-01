"""AST utilities for extracting type annotations."""

from __future__ import annotations

import ast


def extract_type_names_from_annotation(annotation: ast.expr) -> list[str]:
    """Extract class/type names from a type annotation.

    Handles:
    - Simple: Foo
    - Optional: Foo | None
    - Generic: list[Foo], dict[str, Foo]
    - Complex: list[Foo | Bar] | None

    Returns a list of type names (e.g., ["Foo", "Bar"])
    """
    type_names: list[str] = []

    if isinstance(annotation, ast.Name):
        # Simple type: Foo
        # Skip builtin types
        if annotation.id not in {
            "str",
            "int",
            "float",
            "bool",
            "dict",
            "list",
            "set",
            "tuple",
            "None",
            "Any",
        }:
            type_names.append(annotation.id)

    elif isinstance(annotation, ast.Subscript):
        # Generic type: list[Foo], Optional[Foo], dict[str, Foo]
        # Recursively extract from the subscript value
        type_names.extend(extract_type_names_from_annotation(annotation.slice))

    elif isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        # Union type: Foo | Bar | None
        type_names.extend(extract_type_names_from_annotation(annotation.left))
        type_names.extend(extract_type_names_from_annotation(annotation.right))

    elif isinstance(annotation, ast.Tuple):
        # Tuple of types: tuple[Foo, Bar]
        for elt in annotation.elts:
            type_names.extend(extract_type_names_from_annotation(elt))

    elif isinstance(annotation, ast.Attribute):
        # Qualified name: module.ClassName
        # Build the dotted path
        parts: list[str] = []
        current: ast.expr = annotation
        while isinstance(current, ast.Attribute):
            parts.insert(0, current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.insert(0, current.id)
            full_name = ".".join(parts)
            # Only track if it looks like a custom type (starts with uppercase)
            if parts[-1][0].isupper():
                type_names.append(full_name)

    elif isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        # String annotation: "Foo" (forward reference)
        # Simple extraction: just get identifier-like words that start with uppercase
        # This handles "Foo", "list[Foo]", "Foo | Bar", etc.
        import re

        identifiers = re.findall(r"\b([A-Z][a-zA-Z0-9_]*)\b", annotation.value)
        type_names.extend(identifiers)

    return type_names


def extract_type_annotations_from_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    func_id: str,
    module_id: str,
    graph,
    callable_index: dict[str, list[str]] | None = None,
) -> None:
    """Extract USES_TYPE edges from function type annotations.

    Creates edges from the function to any classes used in:
    - Parameter type hints
    - Return type hints
    """
    from ..models import Edge

    type_names: set[str] = set()

    # Extract from return annotation
    if func_node.returns:
        type_names.update(extract_type_names_from_annotation(func_node.returns))

    # Extract from parameter annotations
    for arg in func_node.args.args:
        if arg.annotation:
            type_names.update(extract_type_names_from_annotation(arg.annotation))

    # Also check kwonly args
    for arg in func_node.args.kwonlyargs:
        if arg.annotation:
            type_names.update(extract_type_names_from_annotation(arg.annotation))

    # Resolve type names to full node IDs using callable index
    if callable_index:
        for type_name in type_names:
            # Try to find the class in the callable index
            # The type might be a simple name (Foo) or a qualified name (module.Foo)
            candidates: list[str] = []

            # Check if it's in the index directly
            if type_name in callable_index:
                candidates.extend(callable_index[type_name])
            else:
                # Try to find it as a class name anywhere
                for node_ids in callable_index.values():
                    for node_id in node_ids:
                        if node_id.endswith(f".{type_name}"):
                            candidates.append(node_id)

            # Create USES_TYPE edges to all candidates
            for target_id in candidates:
                # Only create edge if target is a class (not function/method)
                # We'll filter by checking if it looks like a class path
                graph.edges.append(
                    Edge(
                        source_id=func_id,
                        target_id=target_id,
                        type="USES_TYPE",
                        linenos=[func_node.lineno],
                        ast_case="TypeAnnotation",
                    ),
                )
