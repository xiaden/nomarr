# ADR-041: Domain Dataclasses as the Persistence-Component Contract

**Status:** Accepted  
**Date:** 2026-07-25  
**Tags:** persistence, domain-facade, dataclasses, architecture  
**Source Log:** nyx#L1  

## Context

Domain dataclasses currently carry persistence-owned fields: `_id` (ArangoDB document ID like `"library_files/12345"`), `_key` (ArangoDB shard key), collection names, and `from_db_doc()` factories that know how to map database documents. These fields leaked into components and workflows — anywhere a `Song` or `Library` is used, callers see and sometimes depend on persistence internals.

This is the problem ADR-032 tried to solve with its domain-model boundary, but the boundary was aspirational. The dataclasses still carry the persistence shape. When we migrated from ArangoDB to PostgreSQL (ADR-040), every file that touched these dataclasses potentially needed changes because the persistence-owned fields changed meaning.

The adversarial review (ADVERSARIAL-persistence-intent-facade-rebuild.md) refined Approach 2 as the architecture: the facade mediates between persistence and components, domain dataclasses are the shared contract, and components never touch persistence. But Approach 2 only works if the domain dataclasses are actually domain-shaped — not persistence-shaped with a domain label.

The concrete problem: `_id` is an ArangoDB document ID, `_key` is an ArangoDB shard key, `from_db_doc()` couples the domain class to the persistence format, and components that accept `Song` sometimes check `_id` or `_key` — taking a dependency on persistence internals.

## Decision

Domain dataclasses use natural keys as primary identity. Persistence-owned fields are removed.

1. Natural keys replace database PKs. Songs are identified by `path` (absolute file path — guaranteed unique, meaningful, database-independent). Libraries by `(name, root_path)`. Tags by `(source, value)`. OutputStreams by `(stream_type, library_key)`. EmbeddingStreams by `(backbone, model_version)`.

2. Persistence-owned fields removed from domain dataclasses. `_id`, `_key`, `from_db_doc()`, `_DOC_FIELD_MAP` are all removed. The class doesn't know or care how it's stored.

3. `from_db_doc()` moves to persistence layer. Repos or persistence mapper modules own the DB row → domain dataclass mapping. The domain class has no knowledge of database shapes.

4. Persistence internal PKs are persistence-internal. PostgreSQL integer PKs exist for efficient joins but stay inside the persistence layer. Never exposed to the domain.

5. Components work with natural keys, not database IDs. Components that need to reference a song use `path`. Components that need to reference a library use `(name, root_path)`. They never see `_id`, `_key`, or integer PKs.

6. Behavioral methods on dataclasses. Self-contained domain rules live on the dataclass (`Song.needs_retagging()`, `Song.is_empty()`). Cross-entity coordination stays in Components.

## Consequences

Positive: Domain dataclasses are actually domain-shaped. Components never see persistence internals. Changing database technology doesn't ripple into components. Test fixtures are trivial — no fake `_id` or `_key`.

Negative: Natural keys can be longer than integer PKs (storage/index tradeoff). `from_db_doc()` must be rewritten as persistence-layer mappers (mechanical but touches every repo).

Risks: Natural key collision if two files share an absolute path across libraries — mitigate with composite `(path, library_key)`. Migration cost for components reading `_id`/`_key` — grep-and-fix, mechanical.

## References

artifacts/designs/process/ADVERSARIAL-persistence-intent-facade-rebuild.md, artifacts/decisions/ADR-040-postgresql-pgvector-migration-hard-cut-replacement-of-arangodb.md, artifacts/decisions/ADR-032-domain-model-boundary-persistence-returns-only-domain-objects-never-storage-shapes.md
