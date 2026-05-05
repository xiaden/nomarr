"""AST operation recognizers for migration replay.

Each ``_recognize_*`` function inspects a single AST ``Call`` node and returns
a structured value describing the recognised operation, or ``None`` if the node
does not match.  Recognizers are pure functions -- they do not mutate any state.

Also contains ``_is_dynamic_loop``, which detects for-loops that iterate over
runtime collection names (V007/V008/V018 patterns).
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

from scripts.consolidate_migrations.schema_model import (
    EdgeDefinition,
    Graph,
    Index,
    SeedDocument,
)

from .ast_helpers import (
    _contains_db_collections_call,
    _flatten_bool_op,
    _is_dict_get,
    _resolve_bool,
    _resolve_collection_receiver,
    _resolve_int,
    _resolve_literal_str_list,
    _resolve_str,
    _resolve_str_list,
)

# ---------------------------------------------------------------------------
# Dynamic loop detection
# ---------------------------------------------------------------------------


def _is_dynamic_loop(node: ast.For, func_body: list[ast.stmt]) -> bool:
    """Detect ``for`` loops that operate on dynamically-named collections.

    Returns ``True`` if the enclosing function contains a ``db.collections()``
    call before this loop, signalling that the migration enumerates collections
    at runtime (V007/V008/V018 patterns).  The replayer should skip such loops
    because the collection names cannot be resolved statically.

    Args:
        node: The ``for`` statement being checked.
        func_body: The full list of statements in the enclosing function.

    .. note::

        Signature expanded from plan's ``(node: ast.For) -> bool`` to accept
        *func_body* so the recognizer can scan for ``db.collections()`` in
        preceding statements rather than only the ``for`` iterator itself.
    """
    # Direct: for X in db.collections() or sorted(db.collections())
    if _contains_db_collections_call(node.iter):
        return True
    # Indirect: collections = db.collections() somewhere before this for-loop
    for stmt in func_body:
        if stmt is node:
            break
        if _contains_db_collections_call(stmt):
            return True
    return False


# ---------------------------------------------------------------------------
# Collection DDL recognizers
# ---------------------------------------------------------------------------


def _recognize_create_collection(
    node: ast.Call,
    constants: dict[str, Any],
) -> tuple[str, bool] | None:
    """Match ``db.create_collection(name)`` or ``db.create_collection(name, edge=True)``.

    Returns ``(collection_name, is_edge)`` or ``None``.
    """
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_collection"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
    ):
        return None

    if not node.args:
        return None

    name = _resolve_str(node.args[0], constants)
    if name is None:
        return None

    edge = False
    for kw in node.keywords:
        if kw.arg == "edge":
            resolved = _resolve_bool(kw.value, constants)
            if resolved is not None:
                edge = resolved

    return (name, edge)


def _recognize_delete_collection(
    node: ast.Call,
    constants: dict[str, Any],
) -> str | None:
    """Match ``db.delete_collection(name)`` and return the collection name."""
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "delete_collection"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
    ):
        return None

    if not node.args:
        return None

    return _resolve_str(node.args[0], constants)


def _recognize_rename(
    node: ast.Call,
    constants: dict[str, Any],
    coll_bindings: dict[str, str],
) -> tuple[str, str] | None:
    """Match collection rename patterns and return ``(old_name, new_name)``.

    Handles two forms:

    - Inline: ``db.collection(old).rename(new)``
    - Variable: ``coll.rename(new)`` where ``coll = db.collection(old)``
    """
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "rename"):
        return None
    if not node.args:
        return None

    new_name = _resolve_str(node.args[0], constants)
    if new_name is None:
        return None

    receiver = node.func.value

    # Case 1: db.collection(old_name).rename(new_name)
    if isinstance(receiver, ast.Call) and (
        isinstance(receiver.func, ast.Attribute)
        and receiver.func.attr == "collection"
        and isinstance(receiver.func.value, ast.Name)
        and receiver.func.value.id == "db"
        and receiver.args
    ):
        old_name = _resolve_str(receiver.args[0], constants)
        if old_name is not None:
            return (old_name, new_name)

    # Case 2: coll.rename(new_name) with coll bound via db.collection(...)
    if isinstance(receiver, ast.Name) and receiver.id in coll_bindings:
        return (coll_bindings[receiver.id], new_name)

    return None


# ---------------------------------------------------------------------------
# Index recognizers
# ---------------------------------------------------------------------------


def _recognize_add_index(
    node: ast.Call,
    coll_bindings: dict[str, str],
    constants: dict[str, Any],
) -> Index | None:
    """Match ``coll.add_persistent_index(...)`` or ``coll.add_ttl_index(...)``.

    Resolves the collection from either a bound variable or an inline
    ``db.collection(name)`` call.  Returns an ``Index`` dataclass or ``None``.
    """
    if not isinstance(node.func, ast.Attribute):
        return None

    attr = node.func.attr
    if attr == "add_persistent_index":
        index_type = "persistent"
    elif attr == "add_ttl_index":
        index_type = "ttl"
    else:
        return None

    coll_name = _resolve_collection_receiver(node.func.value, coll_bindings, constants)
    if coll_name is None:
        return None

    # Extract keyword arguments
    fields: tuple[str, ...] | None = None
    unique = False
    sparse = False
    expire_after: int | None = None

    for kw in node.keywords:
        if kw.arg == "fields":
            fields = _resolve_str_list(kw.value, constants)
        elif kw.arg == "unique":
            resolved = _resolve_bool(kw.value, constants)
            if resolved is not None:
                unique = resolved
        elif kw.arg == "sparse":
            resolved = _resolve_bool(kw.value, constants)
            if resolved is not None:
                sparse = resolved
        elif kw.arg == "expiry_time":
            expire_after = _resolve_int(kw.value, constants)

    # Also handle positional fields argument
    if fields is None and node.args:
        fields = _resolve_str_list(node.args[0], constants)

    if fields is None:
        return None

    return Index(
        collection=coll_name,
        index_type=index_type,
        fields=fields,
        unique=unique,
        sparse=sparse,
        expire_after=expire_after,
    )


def _recognize_delete_index(
    node: ast.Call,
    func_body: list[ast.stmt],
    coll_bindings: dict[str, str],
    constants: dict[str, Any],
) -> tuple[str, str, tuple[str, ...]] | None:
    """Match ``coll.delete_index(...)`` and resolve the target index.

    V011 uses a pattern where the index is found by type+fields via a
    generator expression, then deleted by runtime id.  This recognizer
    extracts the *semantic* intent (collection, type, fields) rather than
    the runtime id.

    Returns ``(collection_name, index_type, fields)`` or ``None``.

    .. note::

        The return type is expanded from the plan's ``tuple[str, str]``
        to ``tuple[str, str, tuple[str, ...]]`` so that Phase 3's
        ``_apply_delete_index`` can match by type *and* fields.
    """
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "delete_index"):
        return None

    coll_name = _resolve_collection_receiver(node.func.value, coll_bindings, constants)
    if coll_name is None:
        return None

    if not node.args:
        return None

    arg = node.args[0]

    # V011 pattern: coll.delete_index(ttl_index["id"])
    # where ttl_index = next((idx for idx in indexes if ...), None)
    if isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Name):
        var_name = arg.value.id
        info = _find_index_filter_assignment(var_name, func_body)
        if info is not None:
            return (coll_name, info[0], info[1])

    # Fallback -- detected a delete_index call but can't determine type/fields
    return (coll_name, "unknown", ())


def _find_index_filter_assignment(
    var_name: str,
    func_body: list[ast.stmt],
) -> tuple[str, tuple[str, ...]] | None:
    """Find the ``next(genexpr)`` assignment for *var_name* and extract filter info.

    Looks for the V011 pattern::

        ttl_index = next(
            (idx for idx in indexes if idx.get("type") == "ttl" and "last_seen_ms" in idx.get("fields", [])),
            None,
        )

    Returns ``(index_type, fields)`` if found, else ``None``.
    """
    for stmt in func_body:
        if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
            continue
        target = stmt.targets[0]
        if not (isinstance(target, ast.Name) and target.id == var_name):
            continue
        call = stmt.value
        if not isinstance(call, ast.Call):
            continue
        if not (isinstance(call.func, ast.Name) and call.func.id == "next"):
            continue
        if not call.args:
            continue
        gen = call.args[0]
        if isinstance(gen, ast.GeneratorExp):
            return _extract_index_filter_info(gen)
    return None


def _extract_index_filter_info(
    gen_expr: ast.GeneratorExp,
) -> tuple[str, tuple[str, ...]] | None:
    """Extract ``(index_type, fields)`` from a generator filtering by type and fields.

    Recognises conditions of the form::

        idx.get("type") == "ttl" and "field" in idx.get("fields", [])
    """
    conditions: list[ast.expr] = []
    for generator in gen_expr.generators:
        for if_clause in generator.ifs:
            _flatten_bool_op(if_clause, conditions)

    index_type: str | None = None
    fields: list[str] = []

    for cond in conditions:
        if not isinstance(cond, ast.Compare) or len(cond.ops) != 1:
            continue
        op = cond.ops[0]

        # idx.get("type") == "value"
        if isinstance(op, ast.Eq) and isinstance(cond.comparators[0], ast.Constant) and _is_dict_get(cond.left, "type"):
            val = cond.comparators[0].value
            if isinstance(val, str):
                index_type = val

        # "field_name" in idx.get("fields", [])
        if isinstance(op, ast.In) and isinstance(cond.left, ast.Constant):
            val = cond.left.value
            if isinstance(val, str) and _is_dict_get(cond.comparators[0], "fields"):
                fields.append(val)

    if index_type is not None and fields:
        return (index_type, tuple(fields))
    return None


# ---------------------------------------------------------------------------
# Graph recognizers
# ---------------------------------------------------------------------------


def _recognize_create_graph(
    node: ast.Call,
    constants: dict[str, Any],
) -> Graph | None:
    """Match ``db.create_graph(name=..., edge_definitions=[...])``.

    Parses the ``edge_definitions`` list-of-dicts into ``EdgeDefinition``
    tuples and returns a ``Graph`` instance or ``None``.
    """
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_graph"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
    ):
        return None

    name: str | None = None
    edge_defs_node: ast.List | None = None

    for kw in node.keywords:
        if kw.arg == "name":
            name = _resolve_str(kw.value, constants)
        elif kw.arg == "edge_definitions" and isinstance(kw.value, ast.List):
            edge_defs_node = kw.value

    if name is None:
        return None

    edge_definitions: list[EdgeDefinition] = []
    if edge_defs_node is not None:
        for elt in edge_defs_node.elts:
            ed = _parse_edge_definition_dict(elt)
            if ed is not None:
                edge_definitions.append(ed)

    return Graph(name=name, edge_definitions=tuple(edge_definitions))


def _parse_edge_definition_dict(node: ast.expr) -> EdgeDefinition | None:
    """Parse a dict literal into an ``EdgeDefinition``.

    Expects ``{"edge_collection": ..., "from_vertex_collections": [...],
    "to_vertex_collections": [...]}``.
    """
    if not isinstance(node, ast.Dict):
        return None

    key_map: dict[str, ast.expr] = {}
    for k, v in zip(node.keys, node.values, strict=False):
        if isinstance(k, ast.Constant) and isinstance(k.value, str) and v is not None:
            key_map[k.value] = v

    ec_node = key_map.get("edge_collection")
    from_node = key_map.get("from_vertex_collections")
    to_node = key_map.get("to_vertex_collections")

    if ec_node is None or from_node is None or to_node is None:
        return None

    edge_collection: str | None = None
    if isinstance(ec_node, ast.Constant) and isinstance(ec_node.value, str):
        edge_collection = ec_node.value

    from_colls = _resolve_literal_str_list(from_node)
    to_colls = _resolve_literal_str_list(to_node)

    if edge_collection is None or from_colls is None or to_colls is None:
        return None

    return EdgeDefinition(
        edge_collection=edge_collection,
        from_vertex_collections=from_colls,
        to_vertex_collections=to_colls,
    )


# ---------------------------------------------------------------------------
# Seed document / AQL recognizers
# ---------------------------------------------------------------------------


def _recognize_insert(
    node: ast.Call,
    coll_bindings: dict[str, str],
    constants: dict[str, Any],
) -> SeedDocument | None:
    """Match ``coll.insert({"_key": value})`` and return a ``SeedDocument``.

    Only recognises inserts with a dict literal containing a ``_key`` field
    whose value can be resolved to a string.  Loop-variable keys (e.g. the
    V016 ``for key in _STATE_KEYS`` pattern) are not resolvable here --
    the Phase 3 walker handles loop unrolling.
    """
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "insert"):
        return None

    coll_name = _resolve_collection_receiver(node.func.value, coll_bindings, constants)
    if coll_name is None:
        return None

    if not node.args:
        return None

    arg = node.args[0]
    if not isinstance(arg, ast.Dict):
        return None

    for k, v in zip(arg.keys, arg.values, strict=False):
        if isinstance(k, ast.Constant) and k.value == "_key" and v is not None:
            key_val = _resolve_str(v, constants)
            if key_val is not None:
                return SeedDocument(collection=coll_name, key=key_val)

    return None


def _recognize_aql_execute(node: ast.Call) -> str | None:
    """Match ``db.aql.execute(...)`` and return a summary of the AQL query.

    The returned string is a truncated representation of the query text,
    suitable for warning messages.  Returns ``None`` when the call does
    not match the expected pattern.
    """
    if not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != "execute":
        return None

    # Require db.aql.execute(...) pattern
    receiver = node.func.value
    if not (
        isinstance(receiver, ast.Attribute)
        and receiver.attr == "aql"
        and isinstance(receiver.value, ast.Name)
        and receiver.value.id == "db"
    ):
        return None

    # Try to extract a readable summary from the first argument
    max_len = 120
    if not node.args:
        return "<AQL query>"

    arg = node.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        query = " ".join(arg.value.split())  # normalise whitespace
        return query[:max_len] + "..." if len(query) > max_len else query

    if isinstance(arg, ast.JoinedStr):
        # f-string -- reconstruct readable approximation
        parts: list[str] = []
        for val in arg.values:
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                parts.append(val.value)
            else:
                parts.append("{...}")
        query = " ".join("".join(parts).split())
        return query[:max_len] + "..." if len(query) > max_len else query

    return "<AQL query>"
