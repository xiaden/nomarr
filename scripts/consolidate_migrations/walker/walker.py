"""Migration AST walking logic and the ``replay_migrations`` public entry point.

This module drives the full replay pass:

1. ``replay_migrations`` discovers migration files and iterates over them.
2. ``_walk_upgrade`` sets up per-migration context (constants, helper functions).
3. ``_walk_statements`` / ``_walk_function_body`` recurse into compound statements.
4. ``_process_call`` dispatches each discovered call to the appropriate recognizer
   and mutator from the ``recognizers`` and ``mutators`` sub-modules.

Constants:
    ``_MAX_WALK_DEPTH`` -- guards against infinite recursion through helper calls.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

from scripts.consolidate_migrations.blacklist import is_blacklisted
from scripts.consolidate_migrations.schema_model import SchemaShape

from .ast_helpers import (
    _build_collection_bindings,
    _resolve_call_arguments,
    _resolve_str,
    _resolve_str_list,
)
from .discovery import _extract_module_constants, _parse_upgrade_function, discover_migrations
from .mutators import (
    MutableSchemaShape,
    _apply_add_index,
    _apply_create_collection,
    _apply_create_graph,
    _apply_delete_collection,
    _apply_delete_index,
    _apply_insert,
    _apply_rename_collection,
)
from .recognizers import (
    _is_dynamic_loop,
    _recognize_add_index,
    _recognize_aql_execute,
    _recognize_create_collection,
    _recognize_create_graph,
    _recognize_delete_collection,
    _recognize_delete_index,
    _recognize_insert,
    _recognize_rename,
)

logger = logging.getLogger(__name__)

_MAX_WALK_DEPTH = 10


# ---------------------------------------------------------------------------
# Condition evaluation helper
# ---------------------------------------------------------------------------


def _try_eval_condition(
    test: ast.expr,
    bool_bindings: dict[str, bool],
) -> bool | None:
    """Evaluate an *if*-condition using known boolean bindings.

    Returns ``True`` or ``False`` if the condition can be resolved using tracked
    ``db.has_collection()`` assignments.  Returns ``None`` when the condition
    references unknown names or uses unsupported constructs -- callers should
    then process both branches (conservative fallback).
    """
    if isinstance(test, ast.Name):
        return bool_bindings.get(test.id)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _try_eval_condition(test.operand, bool_bindings)
        return None if inner is None else not inner
    if isinstance(test, ast.BoolOp):
        if isinstance(test.op, ast.And):
            for val in test.values:
                ev = _try_eval_condition(val, bool_bindings)
                if ev is None:
                    return None
                if not ev:
                    return False
            return True
        if isinstance(test.op, ast.Or):
            for val in test.values:
                ev = _try_eval_condition(val, bool_bindings)
                if ev is None:
                    return None
                if ev:
                    return True
            return False
    return None


# ---------------------------------------------------------------------------
# Core walking functions
# ---------------------------------------------------------------------------


def _walk_function_body(
    stmts: list[ast.stmt],
    module_funcs: dict[str, ast.FunctionDef],
    constants: dict[str, Any],
    shape: MutableSchemaShape,
    migration_name: str,
    warnings: list[str],
    depth: int,
) -> None:
    """Walk statements within a function scope with fresh sequential bindings."""
    coll_bindings: dict[str, str] = {}
    bool_bindings: dict[str, bool] = {}
    _walk_statements(
        stmts,
        stmts,
        module_funcs,
        constants,
        coll_bindings,
        bool_bindings,
        shape,
        migration_name,
        warnings,
        depth,
    )


def _walk_statements(
    stmts: list[ast.stmt],
    func_body: list[ast.stmt],
    module_funcs: dict[str, ast.FunctionDef],
    constants: dict[str, Any],
    coll_bindings: dict[str, str],
    bool_bindings: dict[str, bool],
    shape: MutableSchemaShape,
    migration_name: str,
    warnings: list[str],
    depth: int,
) -> None:
    """Walk a list of statements, dispatching recognizable operations."""
    for stmt in stmts:
        # Track sequential variable assignments for binding resolution.
        # Must come before For/If/compound checks so that ``has_old = db.has_collection(...)``
        # assignments before ``if has_old:`` blocks are captured in order.
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                func = call.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "db"
                    and call.args
                ):
                    arg_str = _resolve_str(call.args[0], constants)
                    if func.attr == "collection" and arg_str is not None and not is_blacklisted(arg_str):
                        # db.collection("name") -> sequential coll binding update
                        coll_bindings[target.id] = arg_str
                    elif func.attr == "has_collection" and arg_str is not None:
                        # db.has_collection("name") -> bool binding
                        bool_bindings[target.id] = arg_str in shape.collections

        # For loops
        if isinstance(stmt, ast.For):
            if _is_dynamic_loop(stmt, func_body):
                warnings.append(f"{migration_name}: Skipped dynamic loop (db.collections() iteration)")
                continue
            _handle_for_loop(
                stmt,
                func_body,
                module_funcs,
                constants,
                coll_bindings,
                bool_bindings,
                shape,
                migration_name,
                warnings,
                depth,
            )
            continue

        # Compound statements: recurse into bodies
        if isinstance(stmt, ast.If):
            condition = _try_eval_condition(stmt.test, bool_bindings)
            if condition is True:
                # Condition is known-true: only process the body
                _walk_statements(
                    stmt.body,
                    func_body,
                    module_funcs,
                    constants,
                    coll_bindings,
                    bool_bindings,
                    shape,
                    migration_name,
                    warnings,
                    depth,
                )
            elif condition is False:
                # Condition is known-false: only process the else branch
                if stmt.orelse:
                    _walk_statements(
                        stmt.orelse,
                        func_body,
                        module_funcs,
                        constants,
                        coll_bindings,
                        bool_bindings,
                        shape,
                        migration_name,
                        warnings,
                        depth,
                    )
            else:
                # Cannot evaluate -- process both branches (conservative fallback)
                _walk_statements(
                    stmt.body,
                    func_body,
                    module_funcs,
                    constants,
                    coll_bindings,
                    bool_bindings,
                    shape,
                    migration_name,
                    warnings,
                    depth,
                )
                if stmt.orelse:
                    _walk_statements(
                        stmt.orelse,
                        func_body,
                        module_funcs,
                        constants,
                        coll_bindings,
                        bool_bindings,
                        shape,
                        migration_name,
                        warnings,
                        depth,
                    )
            continue

        if isinstance(stmt, ast.With):
            _walk_statements(
                stmt.body,
                func_body,
                module_funcs,
                constants,
                coll_bindings,
                bool_bindings,
                shape,
                migration_name,
                warnings,
                depth,
            )
            continue

        if isinstance(stmt, ast.Try):
            _walk_statements(
                stmt.body,
                func_body,
                module_funcs,
                constants,
                coll_bindings,
                bool_bindings,
                shape,
                migration_name,
                warnings,
                depth,
            )
            continue

        # Expression statements with calls
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            _process_call(
                stmt.value,
                func_body,
                module_funcs,
                constants,
                coll_bindings,
                shape,
                migration_name,
                warnings,
                depth,
            )
            continue

        # Assignments with calls (e.g. result = db.aql.execute(...))
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            _process_call(
                stmt.value,
                func_body,
                module_funcs,
                constants,
                coll_bindings,
                shape,
                migration_name,
                warnings,
                depth,
            )


def _handle_for_loop(
    stmt: ast.For,
    func_body: list[ast.stmt],
    module_funcs: dict[str, ast.FunctionDef],
    constants: dict[str, Any],
    coll_bindings: dict[str, str],
    bool_bindings: dict[str, bool],
    shape: MutableSchemaShape,
    migration_name: str,
    warnings: list[str],
    depth: int,
) -> None:
    """Handle for-loops: unroll constant iterables or walk body once."""
    # Try to unroll if target is a simple name and iterable is a constant list
    if isinstance(stmt.target, ast.Name):
        iterable_values = _resolve_str_list(stmt.iter, constants)
        if iterable_values is not None:
            for value in iterable_values:
                loop_constants = {**constants, stmt.target.id: value}
                loop_bindings = _build_collection_bindings(stmt.body, loop_constants)
                merged_bindings = {**coll_bindings, **loop_bindings}
                _walk_statements(
                    stmt.body,
                    func_body,
                    module_funcs,
                    loop_constants,
                    merged_bindings,
                    bool_bindings,
                    shape,
                    migration_name,
                    warnings,
                    depth,
                )
            return

    # Can't unroll -- walk body once to catch any recognizable operations
    # (e.g. AQL calls inside data migration loops)
    _walk_statements(
        stmt.body,
        func_body,
        module_funcs,
        constants,
        coll_bindings,
        bool_bindings,
        shape,
        migration_name,
        warnings,
        depth,
    )


def _process_call(
    call: ast.Call,
    func_body: list[ast.stmt],
    module_funcs: dict[str, ast.FunctionDef],
    constants: dict[str, Any],
    coll_bindings: dict[str, str],
    shape: MutableSchemaShape,
    migration_name: str,
    warnings: list[str],
    depth: int,
) -> None:
    """Try recognizers on a call node and dispatch to the matching mutator."""
    # 1. AQL execute -- log and return
    aql_summary = _recognize_aql_execute(call)
    if aql_summary is not None:
        warnings.append(f"{migration_name}: AQL data transform (not validated): {aql_summary}")
        return

    # 2. Create collection
    create_coll = _recognize_create_collection(call, constants)
    if create_coll is not None:
        name, edge = create_coll
        _apply_create_collection(shape, name, edge, warnings, migration_name)
        return

    # 3. Delete collection
    delete_coll = _recognize_delete_collection(call, constants)
    if delete_coll is not None:
        _apply_delete_collection(shape, delete_coll, warnings, migration_name)
        return

    # 4. Rename collection
    rename = _recognize_rename(call, constants, coll_bindings)
    if rename is not None:
        old_name, new_name = rename
        _apply_rename_collection(shape, old_name, new_name, warnings, migration_name)
        return

    # 5. Add index
    add_idx = _recognize_add_index(call, coll_bindings, constants)
    if add_idx is not None:
        _apply_add_index(shape, add_idx, warnings, migration_name)
        return

    # 6. Delete index
    del_idx = _recognize_delete_index(call, func_body, coll_bindings, constants)
    if del_idx is not None:
        coll_name, idx_type, fields = del_idx
        _apply_delete_index(shape, coll_name, idx_type, fields, warnings, migration_name)
        return

    # 7. Create graph
    graph = _recognize_create_graph(call, constants)
    if graph is not None:
        _apply_create_graph(shape, graph, warnings, migration_name)
        return

    # 8. Insert seed document
    seed = _recognize_insert(call, coll_bindings, constants)
    if seed is not None:
        _apply_insert(shape, seed, warnings, migration_name)
        return

    # 9. Call to module-level helper function -- resolve and walk
    if depth < _MAX_WALK_DEPTH:
        _try_resolve_helper_call(
            call,
            module_funcs,
            constants,
            shape,
            migration_name,
            warnings,
            depth,
        )


def _try_resolve_helper_call(
    call: ast.Call,
    module_funcs: dict[str, ast.FunctionDef],
    constants: dict[str, Any],
    shape: MutableSchemaShape,
    migration_name: str,
    warnings: list[str],
    depth: int,
) -> None:
    """Resolve a call to a module-level function and walk its body recursively."""
    if not isinstance(call.func, ast.Name):
        return

    func_name = call.func.id
    if func_name not in module_funcs:
        return

    func_def = module_funcs[func_name]
    extended_constants = _resolve_call_arguments(call, func_def, constants)

    _walk_function_body(
        func_def.body,
        module_funcs,
        extended_constants,
        shape,
        migration_name,
        warnings,
        depth + 1,
    )


# ---------------------------------------------------------------------------
# Upgrade walker
# ---------------------------------------------------------------------------


def _walk_upgrade(
    func_node: ast.FunctionDef,
    module_node: ast.Module,
    shape: MutableSchemaShape,
    migration_name: str,
    warnings: list[str],
) -> None:
    """Walk all statements in ``upgrade()`` and apply mutations to *shape*.

    Builds context (module-level constants, collection bindings), calls
    recognizers on each ``ast.Call`` node, and dispatches to mutators.
    Handles dynamic loop detection, constant-loop unrolling, and recursive
    resolution of calls to module-level helper functions.
    """
    constants = _extract_module_constants(module_node)

    # Collect module-level function definitions (excluding upgrade itself)
    module_funcs: dict[str, ast.FunctionDef] = {}
    for node in ast.iter_child_nodes(module_node):
        if isinstance(node, ast.FunctionDef) and node.name != "upgrade":
            module_funcs[node.name] = node

    _walk_function_body(
        func_node.body,
        module_funcs,
        constants,
        shape,
        migration_name,
        warnings,
        depth=0,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def replay_migrations(
    base_shape: SchemaShape,
    migrations_dir: Path,
) -> tuple[SchemaShape, list[str]]:
    """Replay all V004--V019 migrations onto *base_shape* and return the result.

    This is the main public API of the replay engine.  It:

    1. Discovers migration files in *migrations_dir* (sorted by version).
    2. Converts *base_shape* to a ``MutableSchemaShape`` for in-place mutation.
    3. For each migration: parses the ``upgrade()`` function AST, walks it,
       and applies recognised DDL operations to the mutable shape.
    4. Freezes the result back to an immutable ``SchemaShape``.
    5. Returns ``(frozen_shape, warnings)``.

    Args:
        base_shape: The baseline schema (Shape A from ``ensure_schema()``).
        migrations_dir: Path to ``nomarr/migrations/``.

    Returns:
        A tuple of ``(SchemaShape, list[str])`` -- the resulting schema after
        all migrations are replayed, and a list of human-readable warnings
        about skipped/unvalidated operations.
    """
    warnings: list[str] = []
    migration_paths = discover_migrations(migrations_dir)
    mutable = MutableSchemaShape.from_shape(base_shape)

    for source_path in migration_paths:
        migration_name = source_path.stem
        try:
            module_node, func_node = _parse_upgrade_function(source_path)
        except ValueError:
            warnings.append(f"{migration_name}: No upgrade() function found -- skipped")
            continue

        _walk_upgrade(func_node, module_node, mutable, migration_name, warnings)

    return mutable.freeze(), warnings
