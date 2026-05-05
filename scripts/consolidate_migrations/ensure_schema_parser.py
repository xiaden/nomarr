"""AST parser for extracting SchemaShape from arango_bootstrap_comp.py.

Reads the bootstrap source file as text, parses it into an AST, and extracts
collections, indexes, graphs, and seed documents without importing or
executing any nomarr code.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from .schema_model import (
    Collection,
    EdgeDefinition,
    Graph,
    Index,
    SchemaShape,
    SeedDocument,
)

if TYPE_CHECKING:
    from pathlib import Path


def parse_ensure_schema(source_path: Path) -> SchemaShape:
    """Parse the bootstrap source file and return a SchemaShape.

    Locates four target functions in the AST:
    - ``_create_collections`` -> collections
    - ``_create_indexes`` -> indexes
    - ``_create_graphs`` -> graphs
    - ``_seed_file_states`` -> seed documents

    Does NOT parse ``_create_vectors_track_collections`` (dynamic/blacklisted).
    """
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    collections = _extract_collections(_find_function(tree, "_create_collections"))
    indexes = _extract_indexes(_find_function(tree, "_create_indexes"))
    graphs = _extract_graphs(_find_function(tree, "_create_graphs"))
    seed_documents = _extract_seed_documents(_find_function(tree, "_seed_file_states"))

    return SchemaShape(
        collections=frozenset(collections),
        indexes=frozenset(indexes),
        graphs=frozenset(graphs),
        seed_documents=frozenset(seed_documents),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _find_function(module: ast.Module, name: str) -> ast.FunctionDef:
    """Locate a top-level function by name in the AST."""
    for node in ast.iter_child_nodes(module):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    msg = f"Function {name!r} not found in module"
    raise ValueError(msg)


def _extract_collections(func_node: ast.FunctionDef) -> list[Collection]:
    """Extract document and edge collections from ``_create_collections``.

    Finds ``document_collections = [...]`` and ``edge_collections = [...]``
    list-literal assignments and extracts string constants from each.
    """
    collections: list[Collection] = []

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue

        if target.id == "document_collections" and isinstance(node.value, ast.List):
            for elt in node.value.elts:
                name = _extract_string_constant(elt)
                if name is not None:
                    collections.append(Collection(name=name, edge=False))

        elif target.id == "edge_collections" and isinstance(node.value, ast.List):
            for elt in node.value.elts:
                name = _extract_string_constant(elt)
                if name is not None:
                    collections.append(Collection(name=name, edge=True))

    return collections


def _extract_indexes(func_node: ast.FunctionDef) -> list[Index]:
    """Extract indexes from ``_create_indexes``.

    Walks all ``_ensure_index(db, collection, index_type, fields, ...)`` calls,
    resolving positional and keyword arguments.
    """
    indexes: list[Index] = []

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        if not _is_call_to(node, "_ensure_index"):
            continue

        # Positional args: db, collection, index_type, fields
        args = node.args
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}

        # collection (positional 1 or keyword)
        collection = _resolve_arg_string(args, 1, kwargs, "collection")
        if collection is None:
            continue

        # index_type (positional 2 or keyword)
        index_type = _resolve_arg_string(args, 2, kwargs, "index_type")
        if index_type is None:
            continue

        # fields (positional 3 or keyword) — list of strings
        fields = _resolve_arg_string_list(args, 3, kwargs, "fields")
        if fields is None:
            continue

        # Optional keyword-only arguments
        unique = _resolve_arg_bool(kwargs, "unique", default=False)
        sparse = _resolve_arg_bool(kwargs, "sparse", default=False)
        expire_after = _resolve_arg_int_or_none(kwargs, "expireAfter")

        indexes.append(
            Index(
                collection=collection,
                index_type=index_type,
                fields=tuple(fields),
                unique=unique,
                sparse=sparse,
                expire_after=expire_after,
            )
        )

    return indexes


def _extract_graphs(func_node: ast.FunctionDef) -> list[Graph]:
    """Extract graphs from ``_create_graphs``.

    Finds ``db.create_graph(name=..., edge_definitions=[...])`` calls,
    resolving graph name from keyword args or preceding variable assignments.
    """
    # Build a map of simple variable assignments for name resolution
    var_map = _build_var_map(func_node)
    graphs: list[Graph] = []

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "create_graph"):
            continue

        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}

        # Graph name: keyword "name" or positional 0
        name_node = kwargs.get("name")
        if name_node is None and node.args:
            name_node = node.args[0]

        graph_name = _resolve_string_or_var(name_node, var_map)
        if graph_name is None:
            continue

        # Edge definitions: keyword "edge_definitions"
        edge_defs_node = kwargs.get("edge_definitions")
        if edge_defs_node is None:
            continue

        edge_definitions = _parse_edge_definitions(edge_defs_node)
        graphs.append(Graph(name=graph_name, edge_definitions=tuple(edge_definitions)))

    return graphs


def _extract_seed_documents(func_node: ast.FunctionDef) -> list[SeedDocument]:
    """Extract seed documents from ``_seed_file_states``.

    Finds the ``for key in (...)`` loop, extracts the tuple of string constants,
    and pairs each with the collection name from ``db.collection("...")``.
    """
    collection_name: str | None = None
    keys: list[str] = []

    for node in ast.walk(func_node):
        # Find db.collection("file_states") to get the collection name
        if isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Attribute) and node.func.attr == "collection" and node.args
        ):
            name = _extract_string_constant(node.args[0])
            if name is not None:
                collection_name = name

        # Find for key in ("ml_tagged", "calibrated", "reconciled"):
        if isinstance(node, ast.For):
            iter_node = node.iter
            if isinstance(iter_node, ast.Tuple):
                for elt in iter_node.elts:
                    val = _extract_string_constant(elt)
                    if val is not None:
                        keys.append(val)

    if collection_name is None:
        collection_name = "file_states"  # fallback

    return [SeedDocument(collection=collection_name, key=k) for k in keys]


# ---------------------------------------------------------------------------
# AST value resolution helpers
# ---------------------------------------------------------------------------


def _extract_string_constant(node: ast.expr) -> str | None:
    """Extract a string constant from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_call_to(node: ast.Call, func_name: str) -> bool:
    """Check if a Call node calls a function by name."""
    return isinstance(node.func, ast.Name) and node.func.id == func_name


def _resolve_arg_string(
    args: list[ast.expr],
    pos: int,
    kwargs: dict[str | None, ast.expr],
    name: str,
) -> str | None:
    """Resolve a string argument from positional or keyword position."""
    if name in kwargs:
        return _extract_string_constant(kwargs[name])
    if pos < len(args):
        return _extract_string_constant(args[pos])
    return None


def _resolve_arg_string_list(
    args: list[ast.expr],
    pos: int,
    kwargs: dict[str | None, ast.expr],
    name: str,
) -> list[str] | None:
    """Resolve a list-of-strings argument from positional or keyword position."""
    node: ast.expr | None = None
    if name in kwargs:
        node = kwargs[name]
    elif pos < len(args):
        node = args[pos]

    if node is None or not isinstance(node, ast.List):
        return None

    result: list[str] = []
    for elt in node.elts:
        val = _extract_string_constant(elt)
        if val is not None:
            result.append(val)
    return result


def _resolve_arg_bool(
    kwargs: dict[str | None, ast.expr],
    name: str,
    *,
    default: bool,
) -> bool:
    """Resolve a boolean keyword argument with a default value."""
    node = kwargs.get(name)
    if node is None:
        return default
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return default


def _resolve_arg_int_or_none(
    kwargs: dict[str | None, ast.expr],
    name: str,
) -> int | None:
    """Resolve an optional integer keyword argument."""
    node = kwargs.get(name)
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _build_var_map(func_node: ast.FunctionDef) -> dict[str, str]:
    """Build a mapping of simple ``name = "string"`` assignments in a function."""
    var_map: dict[str, str] = {}
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            var_map[target.id] = node.value.value
    return var_map


def _resolve_string_or_var(
    node: ast.expr | None,
    var_map: dict[str, str],
) -> str | None:
    """Resolve an AST node to a string, either directly or via variable lookup."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in var_map:
        return var_map[node.id]
    return None


def _parse_edge_definitions(node: ast.expr) -> list[EdgeDefinition]:
    """Parse a list-of-dicts literal into EdgeDefinition objects."""
    if not isinstance(node, ast.List):
        return []

    result: list[EdgeDefinition] = []
    for elt in node.elts:
        if not isinstance(elt, ast.Dict):
            continue

        d: dict[str, ast.expr] = {}
        for k, v in zip(elt.keys, elt.values, strict=False):
            key_str = _extract_string_constant(k) if k is not None else None
            if key_str is not None and v is not None:
                d[key_str] = v

        edge_coll = _extract_string_constant(d["edge_collection"]) if "edge_collection" in d else None
        from_colls = _extract_string_list(d.get("from_vertex_collections"))
        to_colls = _extract_string_list(d.get("to_vertex_collections"))

        if edge_coll is not None:
            result.append(
                EdgeDefinition(
                    edge_collection=edge_coll,
                    from_vertex_collections=tuple(from_colls),
                    to_vertex_collections=tuple(to_colls),
                )
            )

    return result


def _extract_string_list(node: ast.expr | None) -> list[str]:
    """Extract a list of string constants from a List AST node."""
    if node is None or not isinstance(node, ast.List):
        return []
    result: list[str] = []
    for elt in node.elts:
        val = _extract_string_constant(elt)
        if val is not None:
            result.append(val)
    return result


if __name__ == "__main__":
    from pathlib import Path

    bootstrap_path = Path("nomarr/components/platform/arango_bootstrap_comp.py")
    shape = parse_ensure_schema(bootstrap_path)

    doc_colls = sorted(c.name for c in shape.collections if not c.edge)
    edge_colls = sorted(c.name for c in shape.collections if c.edge)

    print("\n=== Schema Shape Summary ===")
    print(f"Document collections: {len(doc_colls)}")
    print(f"Edge collections:     {len(edge_colls)}")
    print(f"Indexes:              {len(shape.indexes)}")
    print(f"Graphs:               {len(shape.graphs)}")
    print(f"Seed documents:       {len(shape.seed_documents)}")

    print("\n--- Document Collections ---")
    for name in doc_colls:
        print(f"  {name}")

    print("\n--- Edge Collections ---")
    for name in edge_colls:
        print(f"  {name}")

    print("\n--- Indexes ---")
    for idx in sorted(shape.indexes, key=lambda i: (i.collection, i.fields)):
        extras = []
        if idx.unique:
            extras.append("unique")
        if idx.sparse:
            extras.append("sparse")
        if idx.expire_after is not None:
            extras.append(f"expireAfter={idx.expire_after}")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        print(f"  {idx.collection}.{idx.index_type}{list(idx.fields)}{extra_str}")

    print("\n--- Graphs ---")
    for g in sorted(shape.graphs, key=lambda g: g.name):
        print(f"  {g.name}:")
        for ed in g.edge_definitions:
            print(f"    {ed.from_vertex_collections} --[{ed.edge_collection}]--> {ed.to_vertex_collections}")

    print("\n--- Seed Documents ---")
    for sd in sorted(shape.seed_documents, key=lambda s: s.key):
        print(f"  {sd.collection}/{sd.key}")
