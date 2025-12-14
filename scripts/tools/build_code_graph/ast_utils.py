"""AST utility functions for code graph builder."""

from __future__ import annotations

import ast

from .models import CodeGraph, Edge


def get_layer_from_module_path(module_id: str) -> str:
    """
    Extract layer from module path.

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
    """
    Extract variable names from return statements.

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
    """
    Extract attribute names from a class.

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
    """
    Check if a decorator is a FastAPI route decorator.

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


def extract_type_names_from_annotation(annotation: ast.expr) -> list[str]:
    """
    Extract class/type names from a type annotation.

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
    graph: CodeGraph,
    callable_index: dict[str, list[str]] | None = None,
) -> None:
    """
    Extract USES_TYPE edges from function type annotations.

    Creates edges from the function to any classes used in:
    - Parameter type hints
    - Return type hints
    """
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
                    )
                )


def extract_decorator_targets(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    decorated_id: str,
    module_id: str,
    graph: CodeGraph,
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
                )
            )


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


def extract_calls_from_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    caller_id: str,
    module_functions: dict[str, str],
    class_methods: dict[str, str],
    graph: CodeGraph,
    callable_index: dict[str, list[str]] | None = None,
) -> None:
    """Extract CALLS edges from a function/method body.

    Args:
        callable_index: Optional global index of {method_name: [full_node_ids]}
                       for resolving attribute calls across modules.
    """
    # Extract local imports from this function
    local_imports = extract_imports_from_function(func_node)

    # Walk both the function body AND function arguments (for Depends() in FastAPI)
    nodes_to_check: list[ast.AST] = [func_node]

    # Add default argument values (where Depends() typically appears)
    for default in func_node.args.defaults:
        nodes_to_check.append(default)
    for kw_default in func_node.args.kw_defaults:
        if kw_default:  # Can be None
            nodes_to_check.append(kw_default)

    # Walk all nodes
    for root in nodes_to_check:
        for node in ast.walk(root):
            target_ids: list[str] = []

            # Case A: Function/method call
            if isinstance(node, ast.Call):
                # Case 1: Direct function call (Name)
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id

                    # Case 1a: Check for local import first (applies to both classes and functions)
                    # Case 1b: Local import - resolve to full path (HIGHEST PRIORITY)
                    if func_name in local_imports:
                        imported_path = local_imports[func_name]
                        # Try to find exact match in callable index
                        if callable_index:
                            # Get all candidates with this function name
                            candidates = callable_index.get(func_name, [])

                            # Try to match the imported path against candidates
                            # imported_path format: "nomarr.components.library.reconcile_library_paths"
                            # candidate format: "nomarr.components.library.reconcile_paths_comp.reconcile_library_paths"
                            #
                            # The import is from a package __init__.py, so the candidate will have
                            # an extra module name between the package and the function name.
                            # We need to match based on the package path.

                            # Extract package from imported_path
                            import_parts = imported_path.rsplit(".", 1)
                            if len(import_parts) != 2:
                                continue  # Skip malformed imports

                            import_package, import_name = import_parts
                            # import_package: "nomarr.components.library"
                            # import_name: "reconcile_library_paths"

                            for candidate in candidates:
                                # Skip if this would be a self-reference
                                if candidate == caller_id:
                                    continue

                                # Check if candidate starts with the import package
                                # and ends with the function name or __init__ (for classes)
                                if candidate.startswith(import_package + "."):
                                    # Match function: ends with ".function_name"
                                    if candidate.endswith("." + import_name):
                                        target_ids.append(candidate)
                                        break
                                    # Match class instantiation: ends with ".ClassName.__init__"
                                    if candidate.endswith(f".{import_name}.__init__"):
                                        target_ids.append(candidate)
                                        break

                    # Case 1c: Class instantiation fallback (no import found)
                    # Check if this looks like a class name (CamelCase convention)
                    if not target_ids and func_name[0].isupper() and callable_index:
                        # Try to find the __init__ method in callable index
                        for candidates in callable_index.values():
                            for candidate in candidates:
                                if candidate.endswith(f".{func_name}.__init__") and candidate != caller_id:
                                    target_ids.append(candidate)

                    # Case 1d: Try callable index by name (LOWEST PRIORITY - fallback only)
                    # Only use if we haven't found a target yet
                    if not target_ids and callable_index and func_name in callable_index:
                        # Filter to avoid self-references when using broad index
                        candidates = callable_index[func_name]
                        for candidate in candidates:
                            # Skip if candidate == caller (exact self-reference)
                            if candidate != caller_id:
                                target_ids.append(candidate)

                # Case 2: Attribute call (obj.method_name)
                elif isinstance(node.func, ast.Attribute):
                    method_name = node.func.attr

                    # Case 2a: self.method_name (intra-class call)
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
                        if method_name in class_methods:
                            target_ids.append(class_methods[method_name])

                    # Case 2b: Any other attribute call - try global index
                    elif callable_index and method_name in callable_index:
                        # Filter candidates to avoid false self-references
                        # If caller is a module-level function (not a method), exclude module-level functions
                        # If caller is a method, exclude methods in the same class
                        candidates = callable_index[method_name]

                        for candidate in candidates:
                            # Determine if this is a valid target
                            is_valid = True

                            # Extract context from caller_id
                            # caller_id format: "module" or "module.Class.method" or "module.function"
                            caller_parts = caller_id.split(".")
                            candidate_parts = candidate.split(".")

                            # Heuristic: Attribute calls on objects (obj.method()) shouldn't resolve to:
                            # 1. Module-level functions in the same module with the same name
                            # 2. The exact same function/method (self-reference)

                            # Rule 1: Exact self-reference (same full ID)
                            if candidate == caller_id:
                                is_valid = False

                            # Rule 2: If caller is "module.function" and candidate is also "module.function" with same name
                            # This catches: auth.validate_session() calling auth.validate_session (impossible via obj.method())
                            elif len(caller_parts) >= 2 and len(candidate_parts) >= 2:
                                # Both are at least module.something
                                caller_is_module_function = len(caller_parts) == 2 and caller_parts[1] == method_name
                                candidate_is_module_function = (
                                    len(candidate_parts) == 2 and candidate_parts[1] == method_name
                                )

                                # If both are module-level functions in same module with same name, skip
                                if caller_is_module_function and candidate_is_module_function:
                                    if caller_parts[0] == candidate_parts[0]:
                                        is_valid = False

                            # Rule 3: Methods should prefer calling methods on other classes, not standalone functions
                            # If caller is a method (3+ parts) and candidate is a module-level function (2 parts) with same name
                            # This is likely wrong unless it's an explicit import
                            elif len(caller_parts) >= 3 and len(candidate_parts) == 2:
                                # Caller is a method, candidate is module.function
                                if candidate_parts[1] == method_name and caller_parts[-1] == method_name:
                                    # Same method name - likely want the method version, not function
                                    # But allow if it's from a different module (cross-module call)
                                    if ".".join(caller_parts[:-2]) == candidate_parts[0]:
                                        # Same module - skip the function, prefer other method
                                        is_valid = False

                            if is_valid:
                                target_ids.append(candidate)

            # Case B: Callable reference as argument (e.g., Depends(get_service))
            # DON'T process bare Name nodes - they're either:
            # 1. The func of a Call (already handled in Case A)
            # 2. A variable reference (not a call)
            # Only process Name nodes that appear as arguments to dependency injection functions
            # We handle this by looking for Call nodes with Name arguments
            elif isinstance(node, ast.Call) and callable_index:
                # Check if this is a dependency injection call like Depends(func)
                if isinstance(node.func, ast.Name) and node.func.id in ("Depends", "Annotated"):
                    # Extract callable references from arguments
                    for arg in node.args:
                        if isinstance(arg, ast.Name) and arg.id in callable_index:
                            target_ids.extend(callable_index[arg.id])

            # Create CALLS edges for all resolved targets
            for target_id in target_ids:
                lineno = getattr(node, "lineno", 0)
                graph.edges.append(
                    Edge(
                        source_id=caller_id,
                        target_id=target_id,
                        type="CALLS",
                        linenos=[lineno] if lineno else [],
                    )
                )
