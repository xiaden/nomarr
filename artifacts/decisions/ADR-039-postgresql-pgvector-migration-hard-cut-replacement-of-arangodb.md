# ADR-039: PostgreSQL + pgvector Migration — Hard-Cut Replacement of ArangoDB

**Status:** Accepted  
**Date:** 2026-07-19  
**Tags:** persistence, architecture, postgresql, pgvector, migration, database  
**Supersedes:** ADR-030-adopt-descriptor-based-database-facade-for-persistence-access, ADR-031-aql-primitives-and-intent-sub-facades-as-canonical-persistence-architecture, ADR-036-vector-stores-are-per-backbone-not-per-backbone-per-library  

## Context

Nomarr's persistence layer used ArangoDB 3.12 — a multi-model (document + graph) database — with ~8,600 lines of persistence code across three tiers (AQL primitives, domain capability bindings, intent sub-facades). The data is fundamentally relational (files, tags, libraries with FK relationships) with exactly one vector search surface (music embeddings for similarity). The graph model added operational complexity without proportional benefit:

1. **Dynamic collection proliferation**: Per-backbone-per-library vector collections required runtime DDL, namespace management, and ~200 lines of registration code.
2. **AQL lock-in**: ~5,500 lines of Tier 2 AQL operations across 11 packages were ArangoDB-specific. AQL is less expressive than SQL for relational queries.
3. **Cascade deletion complexity**: `remove_library()` was 147 lines of batched AQL manually handling FK-like relationships.
4. **Query limitations**: Crossing-point queries required multiple graph traversals or application-level post-processing.
5. **Graph overhead**: 14 edge collections materialized relationships that are simple FK columns. 10 of 14 were 1:N (→ FK column), only 4 were M:N (→ junction table).
6. **Operational cost**: No maintained migration library (python-arango), weak Python native support, and no offline AQL validation.

Cross-referencing 6 comparable music-library/audio-search projects confirmed zero use ArangoDB — all use PostgreSQL+pgvector, ChromaDB, Qdrant, FAISS, or numpy arrays on disk.

A design document (DD-postgresql-pgvector-migration) was created and adversarially refined. Implementation proceeded in two passes (Plans A-G → Plans A-H) plus a sync-first refinement. However, no Architecture Decision Record was created to formally document the migration decision or supersede the AQL-specific ADRs (030, 031, 036). This ADR corrects that gap.

## Decision

### 1. Replace ArangoDB with PostgreSQL 17 + pgvector 0.8.x

Hard-cut migration — no data preservation, no backwards compatibility, no deprecation period, no coexistence. V1 schema with zero Alembic history; normal migrations from V2 onward.

### 2. Preserve the Three-Tier Intent Facade Architecture (ADR-031 concept, ArangoDB-free)

The proven three-tier model is preserved but reimplemented on PostgreSQL:

| Tier | Before (ArangoDB) | After (PostgreSQL) |
|------|-------------------|-------------------|
| Tier 1 — Primitives | `aql/primitives.py` (~420 lines AQL) | `sql/primitives.py` (~200 lines SQLAlchemy Core) |
| Tier 2 — Domain Bindings | `database/*_aql.py` (11 packages, ~5,500 lines) | `database/*_repo.py` (15 repos, ~1,500 lines) |
| Tier 3 — Intent Facades | `api/{library,ml,application}.py` | `api/{library,ml,application}.py` — **unchanged API** |

Public API surface (`db.library.*`, `db.ml.*`, `db.app.*`) is preserved. Callers see no change.

### 3. Relational Schema Replaces Document-Graph Model

- 23 document collections + 14 edge collections → 18 relational tables
- 10 of 14 edge collections were 1:N (→ FK column with `ON DELETE CASCADE`)
- 4 M:N edges → junction tables (e.g., `file_tags`, `file_state_assignments`)
- `remove_library()`: 147-line cascade → `ON DELETE CASCADE` handles everything
- Folder hierarchy → recursive CTE queries
- Tag ancestry → self-referencing FK with recursive CTE

### 4. Single `embeddings` Table Replaces N×M Dynamic Vector Collections

- One table with `(backbone_id, tier)` discriminator replaces per-backbone-per-library hot/cold collections
- `halfvec` type for 50% storage savings (identical recall at 0.987 vs vector)
- Partial HNSW index on `WHERE tier = 'cold'` — hot vectors use sequential scan
- `hnsw.iterative_scan = strict_order` for correct distance ordering
- Achieves the same simplification goal as ADR-036 (per-backbone consolidation) but goes further

### 5. Technology Stack

| Technology | Role |
|---|---|
| PostgreSQL 17 | Relational engine, JSONB, recursive CTEs, partial indexes |
| pgvector 0.8.x | HNSW ANN search, halfvec, iterative scans |
| SQLAlchemy 2.x | ORM + Core, type-safe queries, Alembic integration |
| psycopg2 | Sync driver for application + Alembic migrations |
| Alembic | Schema migrations (V1 baseline, V2+ incremental) |
| pg_trgm | Trigram fuzzy text search with GIN indexes |

### 6. Sync-First Persistence Strategy

The original migration used dual-driver (async `asyncpg` for app, sync `psycopg2` for Alembic). This created 33 `asyncio.run()` calls across 6 layers and real bugs (discarded coroutines, fragile `asyncio.run()` in constructors). The refinement (`DD-sync-first-persistence-strategy`) replaced the async facade with a sync-first architecture:

- `psycopg2` + `scoped_session` (thread-local, per-request)
- All persistence, components, workflows, and services use plain `def`
- FastAPI interface layer bridges async→sync via `await asyncio.to_thread(svc.method())`
- Eliminated all `asyncio.run()` calls, coroutine-discard bugs, and async constructor patterns

### 7. Implementation Phases

**First Pass** (Plans A-G): Infrastructure (Docker, Alembic), SQL primitives, core repos (library, file, tag, folder), ML + Navidrome repos, intent facades, upstream cleanup (delete all AQL, ArangoDB client, legacy framework), test suite conversion.

**Second Pass** (Plans A-H): Seal persistence boundary (components → intent facades only), enforce domain-model boundary (eliminate `_id`/`_key`/`_rev` from non-persistence code), fix async boundaries (ONNXModelCache factory pattern), exception mapping (pgcode-based translation), import enforcement (ripgrep pre-commit + CI), edge-case extraction from xfailed tests.

**Sync-First Refinement**: asyncpg → psycopg2, `AsyncSession` → `scoped_session`, 33 `asyncio.run()` → 0, 58 `async def` components → `def`.

## Consequences

**Positive:**

- **59% code reduction** in persistence layer (~8,600 → ~3,500 lines)
- **Standard SQL** — joins, subqueries, window functions, filtered ANN search
- **Single database engine** — no dynamic DDL, no runtime collection registration
- **FK ON DELETE CASCADE** — referential integrity handled by the database, not application code
- **Type safety** — SQLAlchemy ORM provides compile-time column validation
- **Operational simplicity** — Alembic for migrations, pg_trgm for fuzzy search, standard tooling
- **Eliminates all AQL** — no ArangoDB-specific knowledge required for contributions
- **Sync predictability** — no async/await bugs, no coroutine-discard traps, deterministic execution

**Negative:**

- Hard cut means zero data preservation across the migration boundary — fresh start required
- Loss of graph-native features — recursive CTEs replace graph traversals (more verbose for deep hierarchies)
- HNSW index builds require `maintenance_work_mem = 2-4 GB` to avoid 10-50× slower disk-fallback builds
- 92 grandfathered `_id`/`_key` field references remain in non-persistence code (`.arango-field-allowlist.yaml`, 90-day auto-expiry), violating ADR-032 domain-model boundary until cleaned up

**Migration Artifacts:**

- 563-line `.arango-field-allowlist.yaml` tracking remaining ArangoDB field name violations
- Three empty `*_aql/` directories under `persistence/database/` (source deleted, `__pycache__` remains)
- `arango-field-allowlist.yaml` and empty AQL directories are cleanup candidates for a future maintenance pass

## Relationship to Superseded ADRs

**ADR-030 (Descriptor-based Database Facade):** The descriptor-based collection accessor pattern (`db.library_files.path.get()`) is replaced by repo-based access through intent facades (`db.library.get_file_by_path()`). The core rule — higher layers access persistence only through the `Database` facade — is preserved and strengthened.

**ADR-031 (AQL Primitives and Intent Sub-Facades):** The three-tier architecture is conceptually preserved but reimplemented: Tier 1 AQL primitives → SQLAlchemy Core primitives, Tier 2 domain AQL operations → SQLAlchemy repos, Tier 3 intent facades → unchanged. "AQL" is removed from the architecture vocabulary but the structural pattern endures.

**ADR-036 (Vector Stores Per-Backbone):** The goal of consolidating N×M per-library vector collections into per-backbone stores is achieved and extended by the single `embeddings` table. Per-backbone-per-library dynamic collection creation is eliminated. Per-backbone isolation is maintained via the `backbone_id` column.

## Relationship to Preserved ADRs

**ADR-032 (Domain-Model Boundary):** The domain-model boundary is strengthened — PostgreSQL integer `id` replaces ArangoDB string `_id`/`_key`. The second-pass migration explicitly targets remaining `_id`/`_key`/`_rev` violations. The principle (persistence returns domain objects, never storage shapes) is unchanged.

**ADR-038 (Int8 Embedding Streams):** The int8 quantization strategy is preserved. pgvector's HNSW index replaces ArangoDB's APPROX_NEAR_COSINE for ANN search. The stream-as-canonical-artifact pattern is unchanged.

**ADR-008, 016, 037:** These ADRs mention ArangoDB in implementation context but their architectural decisions are database-agnostic. No changes needed.

## References

- DD-postgresql-pgvector-migration (first-pass design, 2026-07-13)
- DD-postgresql-migration-second-pass (second-pass cleanup design, 2026-07-17)
- DD-sync-first-persistence-strategy (sync-first refinement, 2026-07-18)
- Implementation plans: TASK-postgresql-pgvector-migration-{A..G} (first pass), TASK-postgresql-migration-second-pass-{A..H} (second pass)
- .arango-field-allowlist.yaml (92 grandfathered ArangoDB field name violations)
