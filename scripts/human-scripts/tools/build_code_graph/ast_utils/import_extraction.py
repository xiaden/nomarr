"""AST utilities for extracting import statements."""

from __future__ import annotations

import ast


def extract_imports_from_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, str]:
    """Extract local imports from a function body.

    Returns a dict mapping {local_name: full_module_path}.
    For example: {'process_file_workflow': 'nomarr.workflows.processing.process_file_wf.process_file_workflow'}
    """
    imports: dict[str, str] = {}

    for node in ast.walk(func_node):
        # from X import Y
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name != "*":
                    local_name = alias.asname if alias.asname else alias.name
                    full_path = f"{node.module}.{alias.name}"
                    imports[local_name] = full_path

        # import X or import X as Y
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname if alias.asname else alias.name
                imports[local_name] = alias.name

    return imports
