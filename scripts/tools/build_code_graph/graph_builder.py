"""Graph building functions for code graph builder."""

from __future__ import annotations

import ast
from pathlib import Path

from .ast_utils import (
    extract_calls_from_function,
    extract_class_attributes,
    extract_decorator_targets,
    extract_function_params,
    extract_return_var_names,
    extract_type_annotations_from_function,
    get_docstring,
    get_layer_from_module_path,
    get_return_annotation,
)
from .models import CodeGraph, Edge, Node


def build_graph_for_file(
    file_path: Path,
    project_root: Path,
    build_calls: bool = True,
    callable_index: dict[str, list[str]] | None = None,
) -> CodeGraph:
    """
    Parse a Python file and build a subgraph.

    Returns a CodeGraph with nodes and edges for this file.
    """
    graph = CodeGraph()

    # Read and parse file
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as e:
        import sys

        print(f"Warning: Failed to parse {file_path}: {e}", file=sys.stderr)
        return graph

    # Calculate module ID from file path
    rel_path = file_path.relative_to(project_root)
    module_parts = [*list(rel_path.parts[:-1]), rel_path.stem]
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    module_id = ".".join(module_parts)

    layer = get_layer_from_module_path(module_id)
    file_str = str(rel_path).replace("\\", "/")

    # Create module node (only during first pass to avoid duplicates)
    if not build_calls:
        module_node = Node(
            id=module_id,
            kind="module",
            layer=layer,
            file=file_str,
            name=module_parts[-1] if module_parts else "",
            lineno=1,
            end_lineno=len(source.splitlines()),
            loc=len(source.splitlines()),
            docstring=get_docstring(tree),
        )
        graph.nodes.append(module_node)

    # Track module-level functions and class methods for CALLS edge creation
    module_functions: dict[str, str] = {}  # func_name -> node_id
    class_methods: dict[str, dict[str, str]] = {}  # class_name -> {method_name -> node_id}

    # Process imports (only during first pass to avoid duplicates)
    if not build_calls:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target_id = alias.name
                    graph.edges.append(
                        Edge(
                            source_id=module_id,
                            target_id=target_id,
                            type="IMPORTS",
                            lineno=node.lineno,
                        )
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                # from X import Y -> we import X (or X.Y)
                for alias in node.names:
                    if alias.name == "*":
                        target_id = node.module
                    else:
                        target_id = f"{node.module}.{alias.name}"
                    graph.edges.append(
                        Edge(
                            source_id=module_id,
                            target_id=target_id,
                            type="IMPORTS",
                            linenos=[node.lineno],
                        )
                    )

    # Process top-level classes and functions
    for stmt in tree.body:
        if isinstance(stmt, ast.ClassDef):
            class_id = f"{module_id}.{stmt.name}"

            # Create nodes and CONTAINS edges only during first pass
            if not build_calls:
                class_node = Node(
                    id=class_id,
                    kind="class",
                    layer=layer,
                    file=file_str,
                    name=stmt.name,
                    lineno=stmt.lineno,
                    end_lineno=stmt.end_lineno or stmt.lineno,
                    loc=(stmt.end_lineno or stmt.lineno) - stmt.lineno + 1,
                    docstring=get_docstring(stmt),
                    attributes=extract_class_attributes(stmt),
                )
                graph.nodes.append(class_node)
                graph.edges.append(
                    Edge(source_id=module_id, target_id=class_id, type="CONTAINS", linenos=[stmt.lineno])
                )

            # Track methods for this class (needed for CALLS resolution in second pass)
            methods_in_class: dict[str, str] = {}

            # Process methods
            for item in stmt.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    method_id = f"{class_id}.{item.name}"

                    # Create nodes and CONTAINS edges only during first pass
                    if not build_calls:
                        method_node = Node(
                            id=method_id,
                            kind="method",
                            layer=layer,
                            file=file_str,
                            name=item.name,
                            lineno=item.lineno,
                            end_lineno=item.end_lineno or item.lineno,
                            loc=(item.end_lineno or item.lineno) - item.lineno + 1,
                            docstring=get_docstring(item),
                            params=extract_function_params(item),
                            return_annotation=get_return_annotation(item),
                            return_var_names=extract_return_var_names(item),
                        )
                        graph.nodes.append(method_node)
                        graph.edges.append(
                            Edge(source_id=class_id, target_id=method_id, type="CONTAINS", linenos=[item.lineno])
                        )

                    methods_in_class[item.name] = method_id

            class_methods[stmt.name] = methods_in_class

        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            func_id = f"{module_id}.{stmt.name}"

            # Create nodes and CONTAINS edges only during first pass
            if not build_calls:
                func_node = Node(
                    id=func_id,
                    kind="function",
                    layer=layer,
                    file=file_str,
                    name=stmt.name,
                    lineno=stmt.lineno,
                    end_lineno=stmt.end_lineno or stmt.lineno,
                    loc=(stmt.end_lineno or stmt.lineno) - stmt.lineno + 1,
                    docstring=get_docstring(stmt),
                    params=extract_function_params(stmt),
                    return_annotation=get_return_annotation(stmt),
                    return_var_names=extract_return_var_names(stmt),
                )
                graph.nodes.append(func_node)
                graph.edges.append(Edge(source_id=module_id, target_id=func_id, type="CONTAINS", linenos=[stmt.lineno]))

            module_functions[stmt.name] = func_id

    # Second pass: build CALLS edges (if requested)
    if build_calls:
        # 2a: Extract calls from function bodies and decorators
        for stmt in tree.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                # Top-level function
                func_id = f"{module_id}.{stmt.name}"
                # Extract decorator targets
                extract_decorator_targets(stmt, func_id, module_id, graph, callable_index)
                # Extract type annotations
                extract_type_annotations_from_function(stmt, func_id, module_id, graph, callable_index)
                # Extract calls from function body
                extract_calls_from_function(stmt, func_id, module_functions, {}, graph, callable_index)

            elif isinstance(stmt, ast.ClassDef):
                class_methods_dict = class_methods.get(stmt.name, {})
                for item in stmt.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        method_id = f"{module_id}.{stmt.name}.{item.name}"
                        # Extract decorator targets
                        extract_decorator_targets(item, method_id, module_id, graph, callable_index)
                        # Extract type annotations
                        extract_type_annotations_from_function(item, method_id, module_id, graph, callable_index)
                        # Extract calls from method body
                        extract_calls_from_function(
                            item, method_id, module_functions, class_methods_dict, graph, callable_index
                        )

        # 2b: Extract calls/references from module-level code
        # This handles things like FastAPI(lifespan=lifespan) or @app.exception_handler(handler)
        if callable_index:
            for node in ast.walk(tree):
                target_ids: list[str] = []

                # Module-level function calls
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in callable_index:
                        target_ids.extend(callable_index[func_name])

                # Module-level callable references (like lifespan=lifespan)
                elif isinstance(node, ast.Name):
                    name = node.id
                    if name in callable_index:
                        target_ids.extend(callable_index[name])

                # Create CALLS edges from module to referenced callables
                for target_id in target_ids:
                    lineno = getattr(node, "lineno", 0)
                    graph.edges.append(
                        Edge(
                            source_id=module_id,
                            target_id=target_id,
                            type="CALLS",
                            linenos=[lineno] if lineno else [],
                        )
                    )

    return graph


def merge_graphs(graphs: list[CodeGraph]) -> CodeGraph:
    """Merge multiple subgraphs into a single graph."""
    merged = CodeGraph()

    for g in graphs:
        merged.nodes.extend(g.nodes)
        merged.edges.extend(g.edges)

    return merged


def build_callable_index(graph: CodeGraph) -> dict[str, list[str]]:
    """Build an index of callable and class nodes for resolution.

    Returns a dict mapping both:
    - Simple names (e.g., "remove_job", "JobResponse") -> [full_node_ids]
    - Full paths (e.g., "nomarr.workflows.processing.process_file_wf.process_file_workflow") -> [full_node_id]

    This allows resolving:
    - Attribute calls like `service.method()` via simple name
    - Imported calls like `process_file_workflow()` via full path
    - Type annotations like `-> JobResponse` via simple class name
    """
    index: dict[str, list[str]] = {}

    for node in graph.nodes:
        if node.kind in {"function", "method", "class"}:
            # Index by simple name (e.g., "remove_job", "JobResponse")
            simple_name = node.name
            if simple_name not in index:
                index[simple_name] = []
            index[simple_name].append(node.id)

            # Also index by full ID for direct lookups
            if node.id not in index:
                index[node.id] = []
            index[node.id].append(node.id)

    return index
