# ADR-032: Domain-Model Boundary: Persistence Returns Only Domain Objects, Never Storage Shapes

**Status:** Accepted  
**Date:** 2026-06-16  
**Tags:** persistence, layering, architecture, domain-model  
**Supersedes:** persistence-storage-shapes-must-not-leak-beyond-the-persistence-layer  

## Context

The Nomarr codebase speaks ArangoDB across every layer. Functions return raw dicts with `_id`, `_key`, and `_rev` fields. Components construct document IDs like `"library_files/abc123"`. Workflows describe data flow in terms of edge collections (`song_has_tags`). This means renaming a collection requires touching ~200 files across every layer, and domain code is tightly coupled to a specific database implementation. The root cause is that there is no domain-model boundary between persistence and the rest of the application.

## Decision

Establish a hard boundary at the persistence facade: 1) Persistence methods accept and return only domain model objects (Track, Tag, Library, etc.) — no raw dicts, no `_id` strings. 2) Domain models have no persistence fields — no `_id`, `_key`, `_rev`, no collection names, no edge references. 3) Domain models use natural keys — a Track is identified by `(library_key, path)`, a Tag by `(name, values)`. 4) Operations expressed in domain language — `get_tracks_from_tag(tag)` not `list_file_ids_for_tag_id(tag_id)`. 5) The persistence layer alone owns the model-storage mapping.

## Consequences

Positive: Collection renames become single-place changes. New developers learn domain concepts, not ArangoDB internals. The persistence implementation can theoretically be swapped.

Negative: Major migration effort — every method, component, and test fixture referencing `_id`/`_key` must change. Performance: tag resolution by (name, values) adds one indexed lookup per operation, negligible for typical workloads. Transition period requires compatibility shims.

## References

v2/nomarr/helpers/dataclasses/tags_dataclass.py (Tag/Tags reference implementation), nomarr/persistence/schema/names.py (CollectionNames enum), nomarr/persistence/schema/ddl.py (DDL definitions)
