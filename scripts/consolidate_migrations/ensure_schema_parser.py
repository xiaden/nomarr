"""Schema shape extraction from Nomarr's DDL definitions.

Reads the authoritative ``DOCUMENT_COLLECTIONS``, ``EDGE_COLLECTIONS``
and ``ALL_STATE_VERTICES`` definitions directly — no AST parsing needed.
Graphs are intentionally excluded (they were dropped in V030).

This replaces the older AST-based parser that could not resolve imported
DDL constants.  The bootstrap source path is still accepted for interface
compatibility but is no longer read.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nomarr.helpers.constants.file_states import ALL_STATE_VERTICES
from nomarr.persistence.schema.ddl import (
    CollectionDef,
    DOCUMENT_COLLECTIONS,
    EDGE_COLLECTIONS,
)

from .schema_model import Collection, Index, SchemaShape, SeedDocument

if TYPE_CHECKING:
    pass  # no additional imports needed


def parse_ensure_schema(source_path: Path) -> SchemaShape:
    """Build a SchemaShape from Nomarr's DDL definitions.

    Reads ``DOCUMENT_COLLECTIONS`` and ``EDGE_COLLECTIONS`` from the
    canonical DDL module, plus ``ALL_STATE_VERTICES`` for seed documents.
    Graphs are excluded — they were dropped in V030.

    The *source_path* parameter is accepted for CLI compatibility but is
    not used (all schema data comes from imports).

    Returns:
        A frozen ``SchemaShape`` representing the current schema baseline.

    """
    collections: list[Collection] = []
    indexes: list[Index] = []

    for coll_def in DOCUMENT_COLLECTIONS:
        _ingest_collection(coll_def, edge=False, collections=collections, indexes=indexes)

    for coll_def in EDGE_COLLECTIONS:
        _ingest_collection(coll_def, edge=True, collections=collections, indexes=indexes)

    seed_docs = _build_seed_documents()

    return SchemaShape(
        collections=frozenset(collections),
        indexes=frozenset(indexes),
        graphs=frozenset(),  # graphs dropped in V030
        seed_documents=frozenset(seed_docs),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ingest_collection(
    coll_def: CollectionDef,
    *,
    edge: bool,
    collections: list[Collection],
    indexes: list[Index],
) -> None:
    """Record a collection and its indexes."""
    name = coll_def.name.value
    collections.append(Collection(name=name, edge=edge))

    for idx_def in coll_def.indexes:
        indexes.append(
            Index(
                collection=name,
                index_type=idx_def.index_type,
                fields=tuple(idx_def.fields),
                unique=idx_def.unique,
                sparse=idx_def.sparse,
                expire_after=idx_def.expire_after,
            )
        )


def _build_seed_documents() -> list[SeedDocument]:
    """Build seed documents from the known set of file_states vertices."""
    return [
        SeedDocument(collection="file_states", key=vertex.split("/")[1])
        for vertex in ALL_STATE_VERTICES
    ]


if __name__ == "__main__":
    from pathlib import Path

    # Accept the argument for CLI compatibility but don't actually use it
    shape = parse_ensure_schema(Path("nomarr/components/platform/arango_bootstrap_comp.py"))

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
    print("  (none — graphs dropped in V030)")

    print("\n--- Seed Documents ---")
    for sd in sorted(shape.seed_documents, key=lambda s: s.key):
        print(f"  {sd.collection}/{sd.key}")
