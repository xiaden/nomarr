from __future__ import annotations


def gather_concrete_names(
    document_collections: list,  # list[DocumentCollection] — avoid circular import
    edge_collections: list,  # list[EdgeCollection]
    extra_vector_names: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Derive concrete target and edge collection names from collection lists.

    Callers are expected to pass the concrete document and edge collections they
    derived from a live `Database` instance rather than relying on class scanning.
    This avoids abstract bases or template classes polluting cascade AQL with
    non-physical collection names.

    Args:
        document_collections: Concrete document collections to include in the
            cascade target set.
        edge_collections: Concrete edge collections to include in the cascade
            edge set.
        extra_vector_names: Optional registered vector collection names to add
            to the target collection set.

    Returns:
        A tuple of `(target_collection_names, all_edge_names)` where
        `target_collection_names` contains all document collection names plus
        any `extra_vector_names`, and `all_edge_names` contains all edge
        collection names.
    """
    target_names = [c._name for c in document_collections]
    if extra_vector_names:
        target_names = target_names + extra_vector_names
    edge_names = [c._name for c in edge_collections]
    return sorted(set(target_names)), sorted(set(edge_names))


def _cascade_edge_names(owner_cls: type) -> list[str]:
    """Collect cascade-via edge collection names reachable from owner_cls."""
    from nomarr.persistence.base_types import CASCADE, OUTBOUND, collection_name_for_class

    names: list[str] = []
    seen: set[type] = set()

    def visit(cls: type) -> None:
        if cls in seen:
            return
        seen.add(cls)
        for edge in getattr(cls, "EDGES", []):
            if edge.on_delete != CASCADE or edge.direction != OUTBOUND:
                continue
            name = collection_name_for_class(edge.via)
            if name not in names:
                names.append(name)
            visit(edge.target)

    visit(owner_cls)
    return names


def _compile_cascade_aql(
    collection_name: str,
    owner_cls: type,
    target_collection_names: list[str],
    all_edge_names: list[str],
) -> str:
    """Compile a static cascade-delete AQL template.

    Pure function — no global state, no class scanning.

    Args:
        collection_name: The ArangoDB collection name being deleted from.
        owner_cls: The collection class declaring EDGES (to derive cascade edge names).
        target_collection_names: All concrete document/vector collection names. Derived
            from Database._document_collections + _registered — never class scanning.
        all_edge_names: All concrete edge collection names. Derived from
            Database._edge_collections — never class scanning.

    Returns:
        AQL string with @starts bind variable.
    """
    cascade_edge_names = _cascade_edge_names(owner_cls)
    if not cascade_edge_names:
        return f"FOR start_id IN @starts\n    REMOVE PARSE_IDENTIFIER(start_id).key IN {collection_name}\nRETURN 1"
    target_names = sorted(set(target_collection_names) - {collection_name})
    cascade_edges_clause = ", ".join(cascade_edge_names)
    all_edges_clause = ", ".join(all_edge_names)

    lines = [
        "LET subgraph = (",
        "    FOR start_id IN @starts",
        f"        FOR v IN 1..100 OUTBOUND start_id {cascade_edges_clause}",
        '            OPTIONS {bfs: true, uniqueVertices: "global"}',
        "            RETURN v",
        ")",
        "LET subgraph_ids = UNIQUE(FOR doc IN subgraph RETURN doc._id)",
        "LET orphan_ids = (",
        "    FOR candidate IN subgraph",
        "        LET external_inbound = (",
        f"            FOR parent IN 1..1 INBOUND candidate._id {all_edges_clause}",
        "                FILTER parent._id NOT IN @starts AND parent._id NOT IN subgraph_ids",
        "                LIMIT 1",
        "                RETURN 1",
        "        )",
        "        FILTER LENGTH(external_inbound) == 0",
        "        RETURN candidate._id",
        ")",
    ]
    for idx, edge_name in enumerate(cascade_edge_names):
        var = f"edge_keys_{idx}"
        lines.extend(
            [
                f"LET {var} = (",
                f"    FOR e IN {edge_name}",
                "        FILTER e._from IN @starts OR e._from IN orphan_ids OR e._to IN orphan_ids OR e._to IN @starts",
                "        RETURN e._key",
                ")",
            ]
        )
    for idx, target_name in enumerate(target_names):
        var = f"orphan_id_{idx}"
        lines.extend(
            [
                f'FOR {var} IN orphan_ids FILTER STARTS_WITH({var}, "{target_name}/")',
                f"    REMOVE PARSE_IDENTIFIER({var}).key IN {target_name}",
            ]
        )
    for idx, edge_name in enumerate(cascade_edge_names):
        var = f"edge_keys_{idx}"
        lines.extend(
            [
                f"FOR key_{idx} IN {var}",
                f"    REMOVE key_{idx} IN {edge_name}",
            ]
        )
    lines.extend(
        [
            "FOR start_id IN @starts",
            f"    REMOVE PARSE_IDENTIFIER(start_id).key IN {collection_name}",
            "RETURN 1",
        ]
    )
    return "\n".join(lines)
