"""Immutable data model for representing ArangoDB schema shapes.

All dataclasses are frozen for hashability (needed for frozenset membership
and order-independent equality comparison in later pipeline stages).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Collection:
    """A document or edge collection."""

    name: str
    edge: bool


@dataclass(frozen=True)
class Index:
    """A collection index."""

    collection: str
    index_type: str
    fields: tuple[str, ...]
    unique: bool
    sparse: bool
    expire_after: int | None


@dataclass(frozen=True)
class EdgeDefinition:
    """A single edge definition within a named graph."""

    edge_collection: str
    from_vertex_collections: tuple[str, ...]
    to_vertex_collections: tuple[str, ...]


@dataclass(frozen=True)
class Graph:
    """A named graph with edge definitions."""

    name: str
    edge_definitions: tuple[EdgeDefinition, ...]


@dataclass(frozen=True)
class SeedDocument:
    """A seed document inserted during schema bootstrap."""

    collection: str
    key: str


@dataclass(frozen=True)
class SchemaShape:
    """Complete database schema shape — order-independent via frozensets."""

    collections: frozenset[Collection]
    indexes: frozenset[Index]
    graphs: frozenset[Graph]
    seed_documents: frozenset[SeedDocument]
