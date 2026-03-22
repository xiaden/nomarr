"""Pure AST value-resolution helpers.

All functions in this module are pure transformations of AST nodes into Python
values.  They have no side effects and no imports from within the walker
package beyond what is needed for type annotations.

These helpers are used by recognizers, mutators, and the walker to resolve
constant expressions, collection bindings, and call arguments from migration
AST nodes.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


# ---------------------------------------------------------------------------
# Scalar resolution helpers
# ---------------------------------------------------------------------------


def _resolve_str(node: ast.expr, constants: dict[str, Any]) -> str | None:
    """Resolve an AST expression to a string value.

    Handles string literals and name references to known constants.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        val = constants.get(node.id)
        if isinstance(val, str):
            return val
    return None


def _resolve_bool(node: ast.expr, constants: dict[str, Any]) -> bool | None:
    """Resolve an AST expression to a boolean value."""
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        val = constants.get(node.id)
        if isinstance(val, bool):
            return val
    return None


def _resolve_int(node: ast.expr, constants: dict[str, Any]) -> int | None:
    """Resolve an AST expression to an integer value (excluding bools)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        val = constants.get(node.id)
        if isinstance(val, int) and not isinstance(val, bool):
            return val
    return None


def _resolve_str_list(node: ast.expr, constants: dict[str, Any]) -> tuple[str, ...] | None:
    """Resolve an AST expression to a tuple of strings.

    Handles list literals (``["a", "b"]``) and name references to known
    list constants.
    """
    if isinstance(node, ast.List):
        items: list[str] = []
        for elt in node.elts:
            s = _resolve_str(elt, constants)
            if s is None:
                return None
            items.append(s)
        return tuple(items)
    if isinstance(node, ast.Name):
        val = constants.get(node.id)
        if isinstance(val, list) and all(isinstance(v, str) for v in val):
            return tuple(val)
    return None


def _resolve_literal_str_list(node: ast.expr) -> tuple[str, ...] | None:
    """Resolve a list literal of strings to a tuple -- no constant lookup."""
    if not isinstance(node, ast.List):
        return None
    items: list[str] = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            items.append(elt.value)
        else:
            return None
    return tuple(items)


# ---------------------------------------------------------------------------
# Collection binding helpers
# ---------------------------------------------------------------------------


def _resolve_collection_receiver(
    receiver: ast.expr,
    coll_bindings: dict[str, str],
    constants: dict[str, Any],
) -> str | None:
    """Resolve the collection name from an attribute call receiver.

    Handles:
    - ``coll`` (Name) -- lookup in *coll_bindings*
    - ``db.collection("name")`` (Call) -- resolve the string argument
    """
    if isinstance(receiver, ast.Name):
        return coll_bindings.get(receiver.id)
    if isinstance(receiver, ast.Call) and (
        isinstance(receiver.func, ast.Attribute)
        and receiver.func.attr == "collection"
        and isinstance(receiver.func.value, ast.Name)
        and receiver.func.value.id == "db"
        and receiver.args
    ):
        return _resolve_str(receiver.args[0], constants)
    return None


def _build_collection_bindings(
    stmts: list[ast.stmt],
    constants: dict[str, Any],
) -> dict[str, str]:
    """Build a mapping of variable names to collection names.

    Scans statements for the ``var = db.collection("name")`` pattern and
    returns ``{var: collection_name}``.

    Args:
        stmts: The list of statements to scan (typically a function body).
        constants: Resolved constants for name lookups.

    Returns:
        A dict mapping local variable names to their bound collection names.
    """
    bindings: dict[str, str] = {}
    for stmt in stmts:
        if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        call = stmt.value
        if not isinstance(call, ast.Call):
            continue
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "collection"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "db"
            and call.args
        ):
            continue
        name = _resolve_str(call.args[0], constants)
        if name is not None:
            bindings[target.id] = name
    return bindings


def _deep_collect_bindings(
    stmts: list[ast.stmt],
    constants: dict[str, Any],
) -> dict[str, str]:
    """Collect ``db.collection(...)`` bindings from all nesting levels.

    Unlike ``_build_collection_bindings`` (which only scans the immediate
    statement list), this helper walks the full AST subtree so that bindings
    inside ``if``/``with``/``try`` blocks are captured.
    """
    bindings: dict[str, str] = {}
    for stmt in stmts:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            if not (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "collection"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "db"
                and call.args
            ):
                continue
            name = _resolve_str(call.args[0], constants)
            if name is not None:
                bindings[target.id] = name
    return bindings


# ---------------------------------------------------------------------------
# Argument resolution helpers
# ---------------------------------------------------------------------------


def _resolve_arg_value(node: ast.expr, constants: dict[str, Any]) -> Any:
    """Resolve an AST expression to a Python literal for argument binding."""
    s = _resolve_str(node, constants)
    if s is not None:
        return s
    b = _resolve_bool(node, constants)
    if b is not None:
        return b
    i = _resolve_int(node, constants)
    if i is not None:
        return i
    sl = _resolve_str_list(node, constants)
    if sl is not None:
        return list(sl)  # stored as list for _resolve_str_list compat
    return None


def _resolve_call_arguments(
    call: ast.Call,
    func_def: ast.FunctionDef,
    constants: dict[str, Any],
) -> dict[str, Any]:
    """Build extended constants by mapping call-site arguments to function parameters.

    The first positional parameter (typically ``db``) is skipped since it
    is the database handle and not a resolvable constant.
    """
    extended: dict[str, Any] = dict(constants)
    params = func_def.args.args
    defaults = func_def.args.defaults
    kw_only = func_def.args.kwonlyargs
    kw_defaults = func_def.args.kw_defaults

    # Map positional arguments (skip first param -- typically 'db')
    for i, arg_node in enumerate(call.args):
        param_idx = i + 1  # skip 'db'
        if param_idx < len(params):
            param_name = params[param_idx].arg
            val = _resolve_arg_value(arg_node, constants)
            if val is not None:
                extended[param_name] = val

    # Map keyword arguments
    for kw in call.keywords:
        if kw.arg is not None:
            val = _resolve_arg_value(kw.value, constants)
            if val is not None:
                extended[kw.arg] = val

    # Apply defaults for keyword-only params not already bound
    for param, default in zip(kw_only, kw_defaults, strict=False):
        if param.arg not in extended and default is not None:
            val = _resolve_arg_value(default, {})
            if val is not None:
                extended[param.arg] = val

    # Apply defaults for regular positional params not already bound
    num_defaults = len(defaults)
    if num_defaults > 0:
        defaulted_params = params[-num_defaults:]
        for param, default in zip(defaulted_params, defaults, strict=False):
            if param.arg not in extended:
                val = _resolve_arg_value(default, {})
                if val is not None:
                    extended[param.arg] = val

    return extended


# ---------------------------------------------------------------------------
# Predicate helpers
# ---------------------------------------------------------------------------


def _contains_db_collections_call(node: ast.AST) -> bool:
    """Check whether an AST subtree contains a ``db.collections()`` call."""
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "collections"
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "db"
        ):
            return True
    return False


def _is_dict_get(node: ast.expr, key: str) -> bool:
    """Check if *node* is a ``.get(key, ...)`` call on any object."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and len(node.args) >= 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == key
    )


def _flatten_bool_op(node: ast.expr, out: list[ast.expr]) -> None:
    """Recursively flatten ``BoolOp(And, ...)`` into a flat list of operands."""
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        for value in node.values:
            _flatten_bool_op(value, out)
    else:
        out.append(node)
