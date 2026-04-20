# ADR-004: Schema Refactor V1 — Graph Normalization and Collection Decomposition

**Status:** Accepted  
**Date:** 2026-04-03  
**Tags:** persistence, arangodb, schema, migration, architecture  
**Source Log:** exec-executor#L1  

## Context

The ArangoDB schema had grown organically with several structural problems: relationships between documents were implicit (tracked via embedded fields or convention rather than edges), lock operations were split across two separate collections with identical logic (`ml_capacity_probe_locks`, `vector_promotion_locks`), scan state was embedded inside library documents rather than normalized, and there was no type-safe boundary between raw ArangoDB documents and application code. ADR-003 addressed part of this (file processing state), but the broader schema needed normalization.

## Decision

Migration V021 implements a comprehensive schema normalization:

1. **Edge-based relationships replace implicit references.** New edge collections (`library_contains_file`, `library_contains_folder`, `library_has_scan`, `file_has_vectors`, `file_has_segment_stats`, `model_has_output`, `model_has_calibration`) make containment and association explicit. Each gets a unique `(_from, _to)` index plus separate `_from` and `_to` indexes for bidirectional traversal. A named graph `library_graph` aggregates these for ArangoDB's query optimizer.

2. **Lock consolidation.** Two lock collections merge into one `locks` collection. Lock type is a field (`lock_type`) rather than a collection-per-type. Single TTL index for automatic expiry. Callers migrate from `db.vector_promotion_locks.*` / `db.ml_capacity_probe_locks.*` to `db.locks.acquire(lock_type=..., ...)`.

3. **Scan state decomposition.** Scan tracking is extracted from `libraries` documents into a dedicated `library_scans` collection, linked via `library_has_scan` edges. One scan document per library. Access via `db.library_scans.*` instead of embedded fields.

4. **Pydantic model layer.** `ArangoDocument` and `ArangoEdge` base classes in `nomarr/persistence/models/` provide type-safe serialization boundaries. `ArangoEdge` handles `_from`/`_to` via `from_id`/`to_id` fields. Models use `from_attributes=True` for Pydantic v2 compatibility.

## Consequences

**Positive:**

- Relationships are queryable via graph traversal, not just key lookups
- Lock logic is DRY — one implementation, discriminated by type
- Scan state can evolve independently of library documents
- Pydantic models catch schema drift at the persistence boundary instead of at runtime deep in business logic

**Negative:**

- Breaking changes to `db.*` facade — all callers of old lock and scan APIs must update
- Migration V021 is large (creates 7 edge collections, 2 document collections, 1 named graph, multiple indexes)
- Edge-based queries are slightly more complex than embedded field access
- Alpha policy: forward-only, no rollback

**Deferred:**

- Migrating all existing AQL operations to use Pydantic models (incremental adoption)
- Domain relationship edges (genre_of, artist_of) — separate concern

## References

- ADR-003: Pure Boolean State Graph (companion decision for file state specifically)
- Migration: nomarr/migrations/V021_schema_refactor_v1.py
- Migration: nomarr/migrations/V022_file_state_graph_completion.py
