"""MutableSchemaShape class and all ``_apply_*`` mutation functions.

This module owns the mutable working copy of the schema during replay.
``MutableSchemaShape`` wraps the frozen ``SchemaShape`` fields in mutable
Python containers (``dict``, ``set``) to allow O(1) create/delete/rename
operations.

All ``_apply_*`` functions accept a ``MutableSchemaShape`` and mutate it
in place, implementing the semantics of the corresponding migration operations
including phantom creation when target objects don't exist.
"""

from __future__ import annotations

import logging

from scripts.consolidate_migrations.blacklist import is_blacklisted
from scripts.consolidate_migrations.schema_model import (
    Collection,
    Graph,
    Index,
    SchemaShape,
    SeedDocument,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MutableSchemaShape
# ---------------------------------------------------------------------------


class MutableSchemaShape:
    """Mutable working copy of a ``SchemaShape`` for in-place mutation during replay.

    Fields are keyed by name (for collections and graphs) to allow O(1) lookup
    during rename/delete operations.  Indexes and seed documents remain sets
    because their operations are add/remove by value.
    """

    __slots__ = ("collections", "graphs", "indexes", "seed_documents")

    def __init__(
        self,
        *,
        collections: dict[str, Collection],
        indexes: set[Index],
        graphs: dict[str, Graph],
        seed_documents: set[SeedDocument],
    ) -> None:
        self.collections = collections
        self.indexes = indexes
        self.graphs = graphs
        self.seed_documents = seed_documents

    @classmethod
    def from_shape(cls, shape: SchemaShape) -> MutableSchemaShape:
        """Deep-copy a frozen ``SchemaShape`` into a mutable form."""
        return cls(
            collections={c.name: c for c in shape.collections},
            indexes=set(shape.indexes),
            graphs={g.name: g for g in shape.graphs},
            seed_documents=set(shape.seed_documents),
        )

    def freeze(self) -> SchemaShape:
        """Convert back to a frozen ``SchemaShape`` with ``frozenset`` fields."""
        return SchemaShape(
            collections=frozenset(self.collections.values()),
            indexes=frozenset(self.indexes),
            graphs=frozenset(self.graphs.values()),
            seed_documents=frozenset(self.seed_documents),
        )


# ---------------------------------------------------------------------------
# Collection mutators
# ---------------------------------------------------------------------------


def _apply_create_collection(
    shape: MutableSchemaShape,
    name: str,
    edge: bool,
    warnings: list[str],
    migration_name: str,
) -> None:
    """Add a ``Collection`` to the mutable shape.

    Skips with a debug log if a collection with the same name already exists
    (idempotent behaviour matching real migration guards).  Also skips
    blacklisted dynamic collections that cannot be resolved statically.
    """
    if is_blacklisted(name):
        warnings.append(f"{migration_name}: Skipped blacklisted collection '{name}'")
        return
    if name in shape.collections:
        logger.debug("%s: Collection '%s' already exists -- skipping create", migration_name, name)
        return
    shape.collections[name] = Collection(name=name, edge=edge)


def _apply_delete_collection(
    shape: MutableSchemaShape,
    name: str,
    warnings: list[str],
    migration_name: str,
) -> None:
    """Remove a collection and all its indexes from the mutable shape.

    If the collection doesn't exist, creates a phantom first (phantom creation
    rule) so that the delete can proceed without error.
    """
    if name not in shape.collections:
        warnings.append(f"{migration_name}: Phantom created for delete_collection('{name}')")
        shape.collections[name] = Collection(name=name, edge=False)
    del shape.collections[name]
    # Remove all indexes belonging to the deleted collection
    shape.indexes = {idx for idx in shape.indexes if idx.collection != name}


def _apply_rename_collection(
    shape: MutableSchemaShape,
    old_name: str,
    new_name: str,
    warnings: list[str],
    migration_name: str,
) -> None:
    """Rename a collection from *old_name* to *new_name*.

    Handles three cases:

    - Normal rename: old exists, new doesn't -- rename + update index refs.
    - Phantom rename: old doesn't exist -- create phantom, then rename.
    - Merge rename: old exists, new also exists -- remove old, keep new.
    """
    if old_name not in shape.collections:
        warnings.append(f"{migration_name}: Phantom created for rename('{old_name}' -> '{new_name}')")
        shape.collections[old_name] = Collection(name=old_name, edge=False)

    if new_name in shape.collections:
        # Merge: remove old, keep existing new
        warnings.append(f"{migration_name}: Merge rename '{old_name}' -> '{new_name}' (target exists)")
        del shape.collections[old_name]
    else:
        old_coll = shape.collections.pop(old_name)
        shape.collections[new_name] = Collection(name=new_name, edge=old_coll.edge)

    # Update all indexes that reference the old collection name
    updated: set[Index] = set()
    for idx in shape.indexes:
        if idx.collection == old_name:
            updated.add(
                Index(
                    collection=new_name,
                    index_type=idx.index_type,
                    fields=idx.fields,
                    unique=idx.unique,
                    sparse=idx.sparse,
                    expire_after=idx.expire_after,
                )
            )
        else:
            updated.add(idx)
    shape.indexes = updated


# ---------------------------------------------------------------------------
# Index mutators
# ---------------------------------------------------------------------------


def _apply_add_index(
    shape: MutableSchemaShape,
    index: Index,
    warnings: list[str],
    migration_name: str,
) -> None:
    """Add an ``Index`` to the shape.

    If the index's collection doesn't exist, creates a phantom collection
    first, then adds the index.
    """
    if index.collection not in shape.collections:
        warnings.append(f"{migration_name}: Phantom collection '{index.collection}' created for add_index")
        shape.collections[index.collection] = Collection(name=index.collection, edge=False)
    shape.indexes.add(index)


def _apply_delete_index(
    shape: MutableSchemaShape,
    collection: str,
    index_type: str,
    fields: tuple[str, ...],
    warnings: list[str],
    migration_name: str,
) -> None:
    """Remove an index matching collection, type, and fields.

    If no matching index is found, logs a warning (phantom skip).
    """
    matching = {
        idx
        for idx in shape.indexes
        if idx.collection == collection and idx.index_type == index_type and idx.fields == fields
    }
    if not matching:
        warnings.append(
            f"{migration_name}: Index not found for delete_index("
            f"'{collection}', '{index_type}', {fields}) -- phantom skip"
        )
        return
    shape.indexes -= matching


# ---------------------------------------------------------------------------
# Graph mutators
# ---------------------------------------------------------------------------


def _apply_create_graph(
    shape: MutableSchemaShape,
    graph: Graph,
    warnings: list[str],
    migration_name: str,
) -> None:
    """Add a ``Graph`` to the shape, skipping if one with the same name exists."""
    if graph.name in shape.graphs:
        logger.debug("%s: Graph '%s' already exists -- skipping create", migration_name, graph.name)
        return
    shape.graphs[graph.name] = graph


# ---------------------------------------------------------------------------
# Seed document mutators
# ---------------------------------------------------------------------------


def _apply_insert(
    shape: MutableSchemaShape,
    seed: SeedDocument,
    warnings: list[str],
    migration_name: str,
) -> None:
    """Add a ``SeedDocument`` to the shape."""
    shape.seed_documents.add(seed)
