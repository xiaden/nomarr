"""AST utilities for extracting metadata from nodes."""

from __future__ import annotations

import ast


def get_layer_from_module_path(module_id: str) -> str:
    """Extract layer from module path.

    Examples:
        "nomarr.interfaces.api.web.router" -> "interfaces"
        "nomarr.services.queue_svc" -> "services"
        "nomarr.workflows.queue.enqueue_files" -> "workflows"

    """
    parts = module_id.split(".")
    if len(parts) < 2:
        return "root"

    # First part should be package name (e.g., "nomarr")
    # Second part is the layer
    layer_candidates = {"interfaces", "services", "workflows", "components", "persistence", "helpers"}

    if parts[1] in layer_candidates:
        return parts[1]

    return "other"


def get_docstring(node: ast.AST) -> str | None:
    """Extract docstring from a node if present."""
    if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        docstring = ast.get_docstring(node)
        return docstring if docstring else None
    return None


def get_return_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Extract return annotation as a string."""
    if node.returns:
        return ast.unparse(node.returns)
    return None


def extract_return_var_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract variable names from return statements.

    Handles:
    - return some_var
    - return self.attribute
    - return result.data
    - return (a, b, c)
    """
    var_names = []

    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value:
            var_names.extend(_extract_names_from_expr(child.value))

    return list(dict.fromkeys(var_names))  # Deduplicate while preserving order


def _extract_names_from_expr(expr: ast.expr) -> list[str]:
    """Recursively extract Name and Attribute paths from an expression."""
    names = []

    if isinstance(expr, ast.Name):
        names.append(expr.id)
    elif isinstance(expr, ast.Attribute):
        # Build dotted path like "result.data" or "self.tags"
        path_parts: list[str] = []
        current: ast.expr = expr
        while isinstance(current, ast.Attribute):
            path_parts.insert(0, current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            path_parts.insert(0, current.id)
            names.append(".".join(path_parts))
    elif isinstance(expr, ast.Tuple | ast.List):
        for elt in expr.elts:
            names.extend(_extract_names_from_expr(elt))

    return names


def extract_class_attributes(class_node: ast.ClassDef) -> list[str]:
    """Extract attribute names from a class.

    Includes:
    - Class-level assignments
    - self.attribute assignments in methods
    """
    attributes = set()

    # Class-level assignments
    for stmt in class_node.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        attributes.add(target.id)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                attributes.add(stmt.target.id)

    # self.attribute assignments in methods
    for stmt in class_node.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            for child in ast.walk(stmt):
                if isinstance(child, ast.Assign | ast.AnnAssign):
                    targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                    for target in targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            attributes.add(target.attr)

    return sorted(attributes)


def extract_function_params(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract parameter names from a function/method."""
    params = []

    args = func_node.args
    # Regular args
    for arg in args.args:
        params.append(arg.arg)

    # *args
    if args.vararg:
        params.append(f"*{args.vararg.arg}")

    # Keyword-only args
    for arg in args.kwonlyargs:
        params.append(arg.arg)

    # **kwargs
    if args.kwarg:
        params.append(f"**{args.kwarg.arg}")

    return params


def is_fastapi_route_decorator(decorator: ast.expr) -> bool:
    """Check if a decorator is a FastAPI route decorator.

    Examples:
        @router.get(...)
        @router.post(...)
        @app.get(...)

    """
    # Handle @router.get(...) or @router.get
    if isinstance(decorator, ast.Attribute) and decorator.attr in {
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "options",
        "head",
    }:
        return True

    # Handle @router.get("/path")
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in {"get", "post", "put", "delete", "patch", "options", "head"}
    )


def extract_decorator_targets(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    decorated_id: str,
    module_id: str,
    graph,
    callable_index: dict[str, list[str]] | None = None,
) -> None:
    """Extract CALLS edges from decorators that register the function.

    For example:
        @api_app.exception_handler(Exception)
        async def exception_handler(...):
            ...

    This creates a CALLS edge from api_app.exception_handler to the decorated function,
    because the decorator effectively calls/registers it.
    """
    from ..models import Edge

    for decorator in func_node.decorator_list:
        # Case 1: @decorator_func or @decorator_func()
        if isinstance(decorator, ast.Name | ast.Call):
            # The decorator "calls" the function by wrapping/registering it
            # Create reverse edge: module -> decorated_function (because decorators run at module load time)
            lineno = decorator.lineno if hasattr(decorator, "lineno") else None
            graph.edges.append(
                Edge(
                    source_id=module_id,
                    target_id=decorated_id,
                    type="CALLS",
                    linenos=[lineno] if lineno else [],
                    details=["decorator_registration"],
                    ast_case="DecoratorRegistration",
                )
            )
