"""AST utilities for extracting function/method calls."""

from __future__ import annotations

import ast

from .import_extraction import extract_imports_from_function

# Type alias for case results
CaseResult = list[tuple[str, str]]  # [(target_id, case_label), ...]


def _add_call_edges(
    graph,
    caller_id: str,
    target_ids: CaseResult,
    lineno: int,
) -> None:
    """Helper to add CALLS edges to graph for all resolved targets."""
    from ..edge_types import get_edge_type_from_ast_case
    from ..models import Edge

    for target_id, ast_case in target_ids:
        edge_type = get_edge_type_from_ast_case(ast_case)
        graph.edges.append(
            Edge(
                source_id=caller_id,
                target_id=target_id,
                type=edge_type,
                linenos=[lineno] if lineno else [],
                ast_case=ast_case,
            )
        )


def _case1b_local_import(
    func_name: str,
    local_imports: dict[str, str],
    callable_index: dict[str, list[str]] | None,
    caller_id: str,
) -> CaseResult:
    """Case 1b: Resolve local import to full path (HIGHEST PRIORITY)."""
    if func_name not in local_imports or not callable_index:
        return []

    imported_path = local_imports[func_name]
    candidates = callable_index.get(func_name, [])

    # Extract package from imported_path
    import_parts = imported_path.rsplit(".", 1)
    if len(import_parts) != 2:
        return []

    import_package, import_name = import_parts

    for candidate in candidates:
        if candidate == caller_id:
            continue

        if candidate.startswith(import_package + "."):
            # Match function: ends with ".function_name"
            if candidate.endswith("." + import_name):
                return [(candidate, "Case1b-LocalImport")]
            # Match class instantiation: ends with ".ClassName.__init__"
            if candidate.endswith(f".{import_name}.__init__"):
                return [(candidate, "Case1b-LocalImport")]

    return []


def _case1c_class_instantiation(
    func_name: str,
    callable_index: dict[str, list[str]] | None,
    caller_id: str,
) -> CaseResult:
    """Case 1c: Class instantiation fallback (no import found).

    When a class is instantiated, create edges to:
    1. ClassName.__init__ (constructor)
    2. ClassName.__call__ (if it exists - for callable classes)
    """
    if not func_name[0].isupper() or not callable_index:
        return []

    # Try to find the __init__ method in callable index
    results: CaseResult = []
    for candidates in callable_index.values():
        for candidate in candidates:
            if candidate.endswith(f".{func_name}.__init__") and candidate != caller_id:
                results.append((candidate, "Case1c-ClassInstantiation"))

                # Also check if this class has __call__ (callable class pattern)
                # Check __call__ index (if it exists as a callable name)
                call_method = candidate.replace(".__init__", ".__call__")
                for call_candidates in callable_index.values():
                    if call_method in call_candidates:
                        results.append((call_method, "Case1c-CallableClass"))
                        break

                return results

    return []


def _case1d_callable_fallback(
    func_name: str,
    callable_index: dict[str, list[str]] | None,
    caller_id: str,
) -> CaseResult:
    """Case 1d: Try callable index by name (LOWEST PRIORITY - fallback only)."""
    if not callable_index or func_name not in callable_index:
        return []

    results = []
    for candidate in callable_index[func_name]:
        if candidate != caller_id:
            results.append((candidate, "Case1d-CallableIndexFallback"))

    return results


def _case2a_self_method(
    method_name: str,
    class_methods: dict[str, str],
) -> CaseResult:
    """Case 2a: self.method_name (intra-class call)."""
    if method_name in class_methods:
        return [(class_methods[method_name], "Case2a-SelfMethod")]
    return []


def _case2b_class_method(
    class_name: str,
    method_name: str,
    local_imports: dict[str, str],
    caller_id: str,
    callable_index: dict[str, list[str]] | None,
) -> CaseResult:
    """Case 2b: ClassName.method_name (class method call with explicit class name)."""
    if not callable_index or method_name not in callable_index:
        return []

    expected_target = None

    # Check if imported from another module
    if class_name in local_imports:
        expected_target = f"{local_imports[class_name]}.{method_name}"
    # Check if it's a class in the same module
    else:
        caller_parts = caller_id.split(".")
        if len(caller_parts) >= 2:
            module_path = ".".join(caller_parts[:-2]) if len(caller_parts) >= 3 else ".".join(caller_parts[:-1])
            expected_target = f"{module_path}.{class_name}.{method_name}"

    if expected_target:
        for candidate in callable_index[method_name]:
            if candidate == expected_target:
                return [(candidate, "Case2b-ClassMethod")]

    return []


def _case2c_attribute_call(
    method_name: str,
    caller_id: str,
    callable_index: dict[str, list[str]] | None,
) -> CaseResult:
    """Case 2c: Any other attribute call - try global index (but be very conservative)."""
    if not callable_index or method_name not in callable_index:
        return []

    results = []
    candidates = callable_index[method_name]
    caller_parts = caller_id.split(".")

    for candidate in candidates:
        candidate_parts = candidate.split(".")

        # Rule 1: Exact self-reference
        if candidate == caller_id:
            continue

        # Rule 2: Same-module same-name function calls
        caller_is_module_function = len(caller_parts) == 2 and caller_parts[1] == method_name
        candidate_is_module_function = len(candidate_parts) == 2 and candidate_parts[1] == method_name
        if caller_is_module_function and candidate_is_module_function and caller_parts[0] == candidate_parts[0]:
            continue

        # Rule 3: Method calling same-named module function in same module
        if (
            len(caller_parts) >= 3
            and len(candidate_parts) == 2
            and candidate_parts[1] == method_name
            and caller_parts[-1] == method_name
            and ".".join(caller_parts[:-2]) == candidate_parts[0]
        ):
            continue

        results.append((candidate, "Case2c-AttributeCall"))

    return results


def _caseb_dependency_injection(
    arg: ast.Name,
    local_imports: dict[str, str],
    callable_index: dict[str, list[str]] | None,
) -> CaseResult:
    """Case B: Callable reference as argument (e.g., Depends(get_service)).

    Only matches callables that are locally imported, to avoid false positives
    from unrelated functions with the same name in different modules.
    """
    if not callable_index or arg.id not in callable_index:
        return []

    # Filter to only locally imported callables
    if arg.id not in local_imports:
        return []

    imported_path = local_imports[arg.id]
    candidates = callable_index[arg.id]

    # Extract package from imported_path
    import_parts = imported_path.rsplit(".", 1)
    if len(import_parts) != 2:
        return []

    import_package, import_name = import_parts

    # Return all candidates from the correct package
    results = []
    for candidate in candidates:
        if candidate.startswith(import_package + ".") and (
            candidate.endswith("." + import_name) or candidate.endswith(f".{import_name}.__init__")
        ):
            results.append((candidate, "CaseB-DependencyInjection"))

    return results


def _casea_module_attribute_access(
    attr_node: ast.Attribute,
    local_imports: dict[str, str],
) -> CaseResult:
    """Case A: Module attribute access in call arguments (e.g., func(web.router)).

    When a call argument is module.attribute, create USES_TYPE edge to the attribute.
    Example: api_app.include_router(web.router) -> edge to web.router module
    """
    # Must be: module_name.attribute_name where module_name is locally imported
    if not isinstance(attr_node.value, ast.Name):
        return []

    module_name = attr_node.value.id
    attr_name = attr_node.attr

    # Check if this module is locally imported
    if module_name not in local_imports:
        return []

    # Build the full path to the attribute
    module_path = local_imports[module_name]
    full_attr_path = f"{module_path}.{attr_name}"

    # Return as CALLS edge (accessing module-level object that gets used/executed)
    return [(full_attr_path, "CaseA-ModuleAttributeAccess")]


def extract_calls_from_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    caller_id: str,
    module_functions: dict[str, str],
    class_methods: dict[str, str],
    graph,
    callable_index: dict[str, list[str]] | None = None,
    module_imports: dict[str, str] | None = None,
) -> None:
    """Extract CALLS edges from a function/method body.

    Args:
        callable_index: Optional global index of {method_name: [full_node_ids]}
                       for resolving attribute calls across modules.
        module_imports: Optional dict of module-level imports {name -> full_path}
                       for resolving Depends() calls.

    """

    # Extract local imports from this function
    function_imports = extract_imports_from_function(func_node)

    # Merge module-level and function-level imports (function-level takes precedence)
    local_imports = {**(module_imports or {}), **function_imports}

    # Walk both the function body AND function arguments (for Depends() in FastAPI)
    nodes_to_check: list[ast.AST] = [func_node]

    # Add default argument values (where Depends() typically appears)
    for default in func_node.args.defaults:
        nodes_to_check.append(default)
    for kw_default in func_node.args.kw_defaults:
        if kw_default:  # Can be None
            nodes_to_check.append(kw_default)

    # Walk all nodes and exhaustively match all Call patterns
    for root in nodes_to_check:
        for node in ast.walk(root):
            target_ids: CaseResult = []
            lineno = getattr(node, "lineno", 0)

            # Exhaustive match on all possible Call node structures
            match node:
                # ==================== Dependency injection: Depends(func) ====================
                # MUST come before general func() case to avoid false matches
                case ast.Call(func=ast.Name(id=dep_func), args=args) if (
                    dep_func in ("Depends", "Annotated") and callable_index
                ):
                    # Depends(get_service) or Annotated[..., Depends(get_service)]
                    for arg in args:
                        if isinstance(arg, ast.Name):
                            target_ids.extend(_caseb_dependency_injection(arg, local_imports, callable_index))

                # ==================== Direct function calls: func() ====================
                case ast.Call(func=ast.Name(id=func_name)):
                    # Try cases in priority order (local import > class > fallback)
                    target_ids = _case1b_local_import(func_name, local_imports, callable_index, caller_id)
                    if not target_ids:
                        target_ids = _case1c_class_instantiation(func_name, callable_index, caller_id)
                    if not target_ids:
                        target_ids = _case1d_callable_fallback(func_name, callable_index, caller_id)

                # ==================== Attribute calls: obj.method() ====================
                case ast.Call(func=ast.Attribute(attr=method_name, value=ast.Name(id="self"))):
                    # Special case: self.method()
                    target_ids = _case2a_self_method(method_name, class_methods)

                case ast.Call(func=ast.Attribute(attr=method_name, value=ast.Name(id=obj_name))) if (
                    obj_name and obj_name[0].isupper()
                ):
                    # ClassName.method() - static/class method call
                    target_ids = _case2b_class_method(obj_name, method_name, local_imports, caller_id, callable_index)

                case ast.Call(func=ast.Attribute(attr=method_name, value=ast.Name())):
                    # obj.method() - lowercase variable
                    target_ids = _case2c_attribute_call(method_name, caller_id, callable_index)

                case ast.Call(func=ast.Attribute(attr=method_name, value=ast.Attribute())):
                    # obj.attr.method() - chained attribute
                    target_ids = _case2c_attribute_call(method_name, caller_id, callable_index)

                case ast.Call(func=ast.Attribute(attr=method_name, value=ast.Call())):
                    # func().method() - call result
                    target_ids = _case2c_attribute_call(method_name, caller_id, callable_index)

                case ast.Call(func=ast.Attribute(attr=method_name, value=ast.Subscript())):
                    # obj[key].method() - subscript result
                    target_ids = _case2c_attribute_call(method_name, caller_id, callable_index)

                case ast.Call(func=ast.Attribute(attr=method_name)):
                    # Any other attribute call pattern (rare: BoolOp, BinOp, etc.)
                    target_ids = _case2c_attribute_call(method_name, caller_id, callable_index)

                # ==================== Uncaught Call patterns (should never happen) ====================
                case ast.Call():
                    # If we hit this, we have a hole in our pattern matching!
                    # This means there's a Call node structure we didn't anticipate
                    # Log it so we can detect and fix missing patterns
                    import sys

                    print(
                        f"WARNING: Unmatched Call pattern at {caller_id}:{lineno} - func type: {type(node.func).__name__}",
                        file=sys.stderr,
                    )
                    # Create a debug edge so it shows up in the graph
                    target_ids = [(f"UNMATCHED_CALL_PATTERN_{type(node.func).__name__}", "CaseX-UnmatchedPattern")]

                # ==================== Not a call ====================
                case _:
                    # Not a Call node - skip
                    continue

            # Check for callable references in keyword arguments (Thread(target=method), etc.)
            # This applies to ALL Call nodes, so checked after match statement
            if isinstance(node, ast.Call) and callable_index:
                for kw in node.keywords:
                    if kw.arg == "target" and isinstance(kw.value, ast.Attribute):
                        # target=self.method or target=obj.method
                        method_name = kw.value.attr
                        if isinstance(kw.value.value, ast.Name) and kw.value.value.id == "self":
                            # target=self.method
                            if method_name in class_methods:
                                target_ids.append((class_methods[method_name], "CaseT-ThreadTarget"))
                        else:
                            # target=obj.method - try attribute call resolution
                            target_ids.extend(_case2c_attribute_call(method_name, caller_id, callable_index))
                    elif kw.arg == "target" and isinstance(kw.value, ast.Name):
                        # target=func_name (locally imported or module-level)
                        target_ids.extend(_caseb_dependency_injection(kw.value, local_imports, callable_index))

            # Check for module attribute accesses in call arguments
            # Example: api_app.include_router(web.router) -> creates edge to web.router
            # This applies to ALL Call nodes, so checked after match statement
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Attribute):
                        target_ids.extend(_casea_module_attribute_access(arg, local_imports))

            # Add edges for all resolved targets using centralized helper
            if target_ids:
                _add_call_edges(graph, caller_id, target_ids, lineno)
