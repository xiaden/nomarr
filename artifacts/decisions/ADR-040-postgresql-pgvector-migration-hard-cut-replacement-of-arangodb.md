# ADR-040: PostgreSQL + pgvector Migration — Hard-Cut Replacement of ArangoDB

**Status:** Accepted  
**Date:** 2026-07-19  
**Tags:** persistence, architecture, postgresql, pgvector, migration, database  
**Source Log:** nyx#L3  
**Supersedes:** ADR-030-adopt-descriptor-based-database-facade-for-persistence-access, ADR-031-aql-primitives-and-intent-sub-facades-as-canonical-persistence-architecture, ADR-036-vector-stores-are-per-backbone-not-per-backbone-per-library, ADR-004-schema-refactor-v1-graph-normalization, ADR-010-bulk-edit-commit-strategy-optimistic-batch-via-set-song-tags-batch, ADR-016-skip-ensure-schema-on-existing-databases, ADR-024-aql-subpackage-naming-convention-and-collection-origination-principle, ADR-025-schema-driven-persistence-constructor-supersedes-hand-written-aql-conventions  

## Context

Nomarr's persistence layer used ArangoDB 3.12 — a multi-model (document + graph) database — with ~8,600 lines of persistence code across three tiers (AQL primitives, domain capability bindings, intent sub-facades). The data is fundamentally relational (files, tags, libraries with FK relationships) with exactly one vector search surface (music embeddings for similarity). The graph model added operational complexity without proportional benefit:

1. Dynamic collection proliferation (per-backbone-per-library vector collections, ~200 lines registration code)
2. AQL lock-in (~5,500 lines across 11 packages)
3. Cascade deletion complexity (remove_library() = 147 lines of batched AQL)
4. 14 edge collections where 10 were 1:N (→ FK column) and only 4 were M:N (→ junction table)
5. No maintained migration library, weak Python native support, no offline AQL validation

Cross-referencing 6 comparable music-library projects confirmed zero use ArangoDB. Implementation was completed across two passes (Plans A-G → Plans A-H) plus a sync-first refinement. No ADR was created — this corrects that gap.

## Decision

1. Replace ArangoDB 3.12 with PostgreSQL 17 + pgvector 0.8.x — hard cut, no data preservation, no coexistence.

2. Preserve the three-tier intent facade architecture (ADR-031 concept, ArangoDB-free): Tier 1 AQL primitives → SQLAlchemy Core primitives, Tier 2 domain AQL ops → SQLAlchemy repos, Tier 3 intent facades → unchanged API.

3. Relational schema replaces document-graph model: 23 doc + 14 edge collections → 18 tables; FK ON DELETE CASCADE replaces 147-line cascade; recursive CTEs for hierarchies; pg_trgm for fuzzy search.

4. Single embeddings table with (backbone_id, tier) replaces N×M dynamic vector collections; halfvec type for 50% storage savings; partial HNSW index on cold tier.

5. Sync-first persistence: psycopg2 + scoped_session replacing asyncpg; eliminated 33 asyncio.run() calls; all components/workflows/services use plain def; FastAPI bridges via asyncio.to_thread().

6. Tech stack: PostgreSQL 17, pgvector 0.8.x, SQLAlchemy 2.x, psycopg2, Alembic, pg_trgm.

## Consequences

Positive: 59% code reduction (~8,600→~3,500 lines), standard SQL, FK cascade integrity, type safety, single database engine, no AQL knowledge required, sync predictability.

Negative: Hard cut (zero data preservation), recursive CTEs more verbose than graph traversals, HNSW builds need 2-4 GB maintenance_work_mem, 92 grandfathered _id/_key violations remain (.arango-field-allowlist.yaml, 90-day auto-expiry).

Preserves: ADR-032 (domain-model boundary, strengthened by int IDs), ADR-038 (int8 streams, pgvector replaces ArangoDB ANN), ADR-008/016/037 (database-agnostic decisions).

## References

DD-postgresql-pgvector-migration (first-pass), DD-postgresql-migration-second-pass (cleanup), DD-sync-first-persistence-strategy (sync-first refinement), .arango-field-allowlist.yaml (92 violations)
