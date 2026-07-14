# PostgreSQL + pgvector Migration: Hard-Cut Replacement of ArangoDB — Design Document

**Status:** Draft  
**Author:** rnd-dd-author, rnd-refiner (adversarial refinement)  
**Created:** 2026-07-13  
**Companion:** [Adversarial Refinement Details](DD-postgresql-pgvector-migration/adversarial-refinement.md)

---

## 1. Scope, Problem, Goals & Constraints

### Scope

Complete replacement of ArangoDB 3.12 with PostgreSQL 17 + pgvector 0.8.x in Nomarr's persistence layer. In scope: schema design for all 37 collections (23 document + 14 edge), edge-to-relational mapping, vector storage strategy, cascade deletion, query equivalence, technology choices, and risk analysis.

**Out of scope**: Data migration scripts (hard cut — zero data preservation), frontend changes (API contracts preserved), service/workflow layer changes (intent facades unchanged), performance benchmarking, backup/restore procedures.

### Problem Statement

Nomarr's persistence layer uses ArangoDB 3.12 — a multi-model database. However, Nomarr's data is fundamentally relational (files, tags, libraries with FK relationships) with exactly one vector search surface (music embeddings for similarity). The graph model adds operational complexity without proportional benefit:

1. **Dynamic collection proliferation**: Per-backbone-per-library vector collections require runtime DDL, namespace management, and ~200 lines of registration code.
2. **AQL lock-in**: ~5,500 lines of Tier 2 AQL operations across 11 packages are ArangoDB-specific. AQL is less expressive than SQL for relational queries.
3. **Cascade deletion complexity**: `remove_library()` is 147 lines of batched AQL manually handling FK-like relationships.
4. **Query limitations**: Crossing-point queries require multiple graph traversals or application-level post-processing.
5. **Graph overhead**: 14 edge collections materialize relationships that are simple FK columns. 10 of 14 are 1:N (→ FK column), only 4 are M:N (→ junction table).
6. **Operational cost**: No maintained migration library, weak Python native support, and no offline AQL validation.

**Proposed solution**: Hard-cut migration to PostgreSQL 17 + pgvector 0.8.x. Replace document-graph model with relational schema. Use pgvector HNSW for vector search. Eliminate all AQL. Preserve intent facade API.

**Industry validation**: Cross-referenced 6 comparable music-library/audio-search projects (agnostic-audio-engine, lainbow, simil, mycelium, nendo, render-examples). Zero use ArangoDB. All use PostgreSQL+pgvector, ChromaDB, Qdrant, FAISS, or numpy arrays on disk.

### Design Goals

1. **Simplification**: Eliminate ~59% of persistence layer code (~5,500 of ~8,600 lines)
2. **Query capability**: Enable SQL joins, subqueries, window functions, and filtered ANN search
3. **Operational simplicity**: Single database engine, standard SQL, no dynamic DDL
4. **Vector performance**: pgvector HNSW with cosine distance — same algorithm, cleaner API
5. **Type safety**: SQLAlchemy ORM provides compile-time column validation
6. **Preserve intent facades**: `db.library`, `db.ml`, `db.app` API surface unchanged
7. **Hard cut**: No data migration, no shims, no dual-write, V1 schema with zero Alembic history

### Constraints

1. Hard cut — no backwards compatibility, no deprecation period, no coexistence
2. V1 schema — one baseline Alembic migration creates all tables; normal migrations from V2 onward
3. Intent facades preserved — callers see no API change
4. No AQL survives — all AQL code deleted
5. Docker — `pgvector/pgvector:pg17` replaces `arangodb:3.12`
6. Engine-agnostic exceptions — `PersistenceError`, `DuplicateKeyError` preserved
7. Layer conventions unchanged — no business logic in persistence, no upward imports

---

## 2. Architecture & Key Decisions

### Before → After

```
BEFORE (ArangoDB):                          AFTER (PostgreSQL):
┌─────────────────────────────┐             ┌─────────────────────────────┐
│ Tier 3: Intent Facades      │             │ Tier 3: Intent Facades      │
│ LibraryDb, MlDb, AppDb      │             │ LibraryDb, MlDb, AppDb      │
│ (api/*.py)                  │             │ (api/*.py — SAME API)       │
├─────────────────────────────┤             ├─────────────────────────────┤
│ Tier 2: Domain AQL Ops      │             │ Tier 2: SQLAlchemy Repos    │
│ LibrariesAqlOperations,     │             │ LibraryRepo, VectorRepo,    │
│ VectorsAqlOperations, etc.  │             │ TagRepo, FileRepo, etc.     │
│ (database/*_aql.py)         │             │ (database/*_repo.py)        │
├─────────────────────────────┤             ├─────────────────────────────┤
│ Tier 1: AQL Primitives      │             │ Tier 1: SQLAlchemy Core     │
│ get_many_by_keys,           │             │ select(), insert(),         │
│ upsert_by_field, etc.       │             │ update(), delete()          │
│ (aql/primitives.py)         │             │ (sql/primitives.py)         │
├─────────────────────────────┤             ├─────────────────────────────┤
│ ArangoDB Client             │             │ PostgreSQL Engine           │
│ SafeDatabase, _jsonify      │             │ create_async_engine(),      │
│ (arango_client.py)          │             │ async_sessionmaker()        │
├─────────────────────────────┤             ├─────────────────────────────┤
│ Schema DDL (ArangoDB)       │             │ Schema (SQLAlchemy Models)  │
│ CollectionDef, IndexDef     │             │ SQLAlchemy Base models      │
│ (schema/ddl.py)             │             │ (models/*.py + alembic/)    │
└─────────────────────────────┘             └─────────────────────────────┘
```

### Layer Mapping

| ArangoDB Layer | PostgreSQL Layer | Change |
|---|---|---|
| `aql/primitives.py` (420 lines) | `sql/primitives.py` (~200 lines) | SQLAlchemy Core expressions replace AQL primitives |
| `database/*_aql.py` (11 packages, ~5,500 lines) | `database/*_repo.py` (~1,500 lines) | SQLAlchemy sessions replace raw AQL |
| `api/library.py` (594 lines) | `api/library.py` (similar) | Internal delegation changes; public API unchanged |
| `api/ml.py` (408 lines) | `api/ml.py` (similar) | Same — internal delegation changes |
| `api/application.py` (398 lines) | `api/application.py` (similar) | Same — internal delegation changes |
| `arango_client.py` (188 lines) | `pg_engine.py` (~50 lines) | `create_async_engine()` one-liner |
| `schema/ddl.py` + `schema/names.py` (370 lines) | `models/*.py` (~300 lines) | SQLAlchemy declarative models |
| `schema_types.py` (437 lines) | `models/embedding.py` (~80 lines) | Single Embedding model |
| `models/` (ArangoDocument, etc., ~80 lines) | SQLAlchemy ORM models | Pydantic models deleted |

### Key Architectural Decisions

1. **Single `embeddings` table** with `(backbone_id, tier)` columns replaces N×M dynamic vector collections
2. **halfvec type** — 50% storage savings; pgvector 0.7.0 benchmarks show identical recall (0.987) vs vector at ef_search=200
3. **Partial HNSW index** on `WHERE tier = 'cold'` — hot vectors use sequential scan; cold gets indexed
4. **FK ON DELETE CASCADE** — `remove_library()` goes from 147-line AQL cascade to `await db.delete(library)`
5. **Recursive CTEs** for tree traversal (folder hierarchy, tag ancestry)
6. **SQLAlchemy 2.x async + asyncpg** — connection pooling, type safety, query composition
7. **maintenance_work_mem = 2-4 GB** for HNSW build sessions — PostgreSQL's 64MB default silently causes 10-50× slower disk-fallback builds
8. **pg_trgm** extension for fuzzy text search — trigram GIN indexes on path and tag name
9. **Strict vector ordering** — `hnsw.iterative_scan = strict_order` for all queries. Ensures returned ANN candidates are ordered exactly by computed distance. Recall remains approximate, governed by ef_search, scan limits, and filter selectivity.
10. **Sync psycopg2 + async asyncpg** — dual-driver: sync for Alembic, async for application

### Technology Choices

| Technology | Version | Rationale |
|---|---|---|
| PostgreSQL | 17 | JSONB, recursive CTEs, partial indexes, mature ecosystem |
| asyncpg | latest | Fastest async PG driver for Python |
| psycopg2 | latest | Sync driver for Alembic migrations (needed for `CREATE INDEX CONCURRENTLY` autocommit) |
| SQLAlchemy | 2.x async | ORM + Core, async session, type-safe queries, Alembic integration |
| pgvector | 0.8.x | HNSW index, cosine distance, halfvec, iterative scans |
| pgvector-python | 0.5.0 | SQLAlchemy VECTOR type registration |
| pg_trgm | bundled (contrib) | Trigram fuzzy text search, typo tolerance |
| Alembic | latest | Schema migrations (V2+; V1 is initial schema) |
| Docker | pgvector/pgvector:pg17 | Drop-in replacement for arangodb:3.12 |

---

## 3. Schema & Relationship Mapping

### Core Tables (SQLAlchemy 2.x Async Models)

```python
# ── libraries ──────────────────────────────────────────────────────────
class Library(Base):
    __tablename__ = "libraries"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    library_type: Mapped[str] = mapped_column(String(50), nullable=False)
    auto_tag: Mapped[int] = mapped_column(Integer, default=0)
    auto_curate: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)

# ── library_files ──────────────────────────────────────────────────────
class LibraryFile(Base):
    __tablename__ = "library_files"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("library_folders.id", ondelete="SET NULL"), index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger)
    modified_time: Mapped[int] = mapped_column(BigInteger)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    chromaprint: Mapped[str | None] = mapped_column(String(255), index=True)
    needs_tagging: Mapped[int] = mapped_column(Integer, default=0)
    is_valid: Mapped[int] = mapped_column(Integer, default=0)
    tagged: Mapped[int] = mapped_column(Integer, default=0)
    calibration_hash: Mapped[str | None] = mapped_column(String(255), index=True)
    write_claimed_by: Mapped[str | None] = mapped_column(String(255), index=True)
    last_tagged_at: Mapped[int | None] = mapped_column(BigInteger)
    scanned_at: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        UniqueConstraint("library_id", "path"),
        UniqueConstraint("library_id", "normalized_path"),
        Index("ix_lf_needs_tagging_valid", "needs_tagging", "is_valid"),
        Index("ix_lf_library_tagged", "library_id", "tagged"),
    )

# ── library_folders ────────────────────────────────────────────────────
class LibraryFolder(Base):
    __tablename__ = "library_folders"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("library_folders.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(255))

# ── tags ───────────────────────────────────────────────────────────────
class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_tag_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id", ondelete="SET NULL"), index=True)
    source: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)
    tier: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        UniqueConstraint("name", "value", "namespace"),
        Index("ix_tags_parent", "parent_tag_id"),
    )

# ── file_tags (junction: song_has_tags) ────────────────────────────────
class FileTag(Base):
    __tablename__ = "file_tags"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("file_id", "tag_id"),)

# ── file_states (junction: file_has_state) ─────────────────────────────
class FileStateAssignment(Base):
    __tablename__ = "file_state_assignments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    state_id: Mapped[int] = mapped_column(ForeignKey("file_states.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("file_id", "state_id"),)

class FileState(Base):
    __tablename__ = "file_states"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

# ── library_scans ──────────────────────────────────────────────────────
class LibraryScan(Base):
    __tablename__ = "library_scans"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[int] = mapped_column(BigInteger)
    finished_at: Mapped[int | None] = mapped_column(BigInteger)
    files_found: Mapped[int] = mapped_column(Integer, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

# ── embeddings (replaces dynamic vector collections) ───────────────────
class Embedding(Base):
    __tablename__ = "embeddings"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    backbone_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(10), nullable=False, default="hot")
    embedding: Mapped[Any] = mapped_column(HalfVector(1280))
    embed_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    model_suite_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    num_segments: Mapped[int] = mapped_column(Integer)
    segmentation_hash: Mapped[str | None] = mapped_column(String(255))
    genres: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        UniqueConstraint("file_id", "backbone_id"),
        Index("ix_embeddings_backbone_tier", "backbone_id", "tier"),
        Index("ix_embeddings_cold_hnsw", "embedding",
              postgresql_using="hnsw",
              postgresql_with={"m": "16", "ef_construction": "200"},
              postgresql_ops={"embedding": "halfvec_cosine_ops"},
              postgresql_where=text("tier = 'cold'")),
    )

# ── ml_* tables ────────────────────────────────────────────────────────
class MlOutputStream(Base):       # ml_output_streams
    __tablename__ = "ml_output_streams"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[int] = mapped_column(BigInteger)

class MlEmbeddingStream(Base):    # ml_embedding_streams
    __tablename__ = "ml_embedding_streams"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    backbone_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    patches_emb: Mapped[bytes] = mapped_column(LargeBinary)  # int8 via BYTEA
    created_at: Mapped[int] = mapped_column(BigInteger)

class MlModel(Base):              # ml_models
    __tablename__ = "ml_models"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # model name as natural key
    model_type: Mapped[str] = mapped_column(String(100))
    backbone_id: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger, index=True)

class MlModelOutput(Base):        # ml_model_outputs
    __tablename__ = "ml_model_outputs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False, index=True)
    output_data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[int] = mapped_column(BigInteger)

# ── pipeline_states ──────────────────────────────────────────────────────
class PipelineState(Base):
    __tablename__ = "pipeline_states"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    state_key: Mapped[str] = mapped_column(String(100), nullable=False)
    state_data: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("library_id", "state_key"),)

# ── calibration ────────────────────────────────────────────────────────
class CalibrationState(Base):     # calibration_state
    __tablename__ = "calibration_state"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False, index=True)
    state_data: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[int] = mapped_column(BigInteger, index=True)

class CalibrationHistory(Base):   # calibration_history
    __tablename__ = "calibration_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[int] = mapped_column(BigInteger)

# ── app-level config/key-value tables ──────────────────────────────────
# meta(key, value JSONB), sessions(id, data JSONB, expires_at),
# health(worker_id, status, last_seen), worker_claims(worker_id, key, value),
# locks(key TEXT PK, value JSONB), worker_restart_policy, applied_migrations,
# vram_promises — straightforward key-value/config tables, not detailed here.

# ── Navidrome integration tables ───────────────────────────────────────
class NavidromeTrack(Base):       # navidrome_tracks
    __tablename__ = "navidrome_tracks"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # Navidrome ID
    title: Mapped[str] = mapped_column(Text)
    artist: Mapped[str] = mapped_column(Text)
    album: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)

class NavidromeTrackMap(Base):    # navidrome_track_maps (junction)
    __tablename__ = "navidrome_track_maps"
    navidrome_track_id: Mapped[str] = mapped_column(
        ForeignKey("navidrome_tracks.id", ondelete="CASCADE"), primary_key=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)

class NavidromePlay(Base):        # navidrome_plays
    __tablename__ = "navidrome_plays"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    navidrome_track_id: Mapped[str] = mapped_column(
        ForeignKey("navidrome_tracks.id", ondelete="CASCADE"), index=True)
    played_at: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[str | None] = mapped_column(String(255))

class NavidromePlayMap(Base):     # navidrome_play_maps (junction)
    __tablename__ = "navidrome_play_maps"
    play_id: Mapped[int] = mapped_column(
        ForeignKey("navidrome_plays.id", ondelete="CASCADE"), primary_key=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
```

### Edge-To-Relational Mapping

14 ArangoDB edge collections map as follows:

| ArangoDB Edge | PostgreSQL | Pattern |
|---|---|---|
| library_has_folder | folders.library_id | FK column (1:N) |
| folder_has_folder | folders.parent_id | Self-ref FK (tree) |
| library_has_file | library_files.library_id | FK column (1:N) |
| file_in_folder | library_files.folder_id | FK column (1:N) |
| file_has_tag | file_tags(file_id, tag_id) | Junction table (M:N) |
| tag_has_tag | tags.parent_tag_id | Self-ref FK (tree) |
| file_has_state | file_state_assignments | Junction table (M:N) |
| file_has_vectors | embeddings.file_id | FK column (1:N) |
| file_streams_output | ml_output_streams.file_id | FK column (1:N) |
| file_has_output | ml_model_outputs.file_id | FK column (1:N) |
| navidrome_track_maps_file | navidrome_track_maps | Junction table (M:N) |
| navidrome_plays_maps_file | navidrome_play_maps | Junction table (M:N) |
| library_has_scan | library_scans.library_id | FK column (1:N) |
| library_has_pipeline_state | pipeline_states.library_id | FK column (1:N) |

10 of 14 are FK columns (1:N), 4 are junction tables (M:N). This is not a graph database problem — it's a relational modeling problem that ArangoDB misrepresented.

---

## 4. Vector Design

### Storage Strategy

Single `embeddings` table replaces all dynamic per-backbone-per-library collections. `tier` column (`hot`|`cold`) acts as a lifecycle discriminator:

```
embeddings table
├── hot tier (unindexed, fast writes)
│   └── Workers INSERT new embeddings during ML processing
│   └── Searched via sequential scan (small — recently processed files only)
│
└── cold tier (HNSW-indexed, slow writes, fast search)
    └── Drain job: UPDATE SET tier = 'cold' WHERE backbone_id = $1 AND tier = 'hot'
    └── Partial HNSW index: WHERE tier = 'cold'
```

**Why partial index**: HNSW index maintenance on INSERT is expensive. Hot vectors are transient. The cold tier is the search surface — only cold vectors get the index. Hot vectors use sequential scan (acceptable for small sets). The drain operation is a single UPDATE — no document copying, no multi-collection AQL.

### ANN Search

```sql
-- Cosine similarity search with backbone + tier filter
SET hnsw.ef_search = 200;
SELECT e.file_id, e.embedding <=> :query_vector AS distance
FROM embeddings e
WHERE e.backbone_id = :backbone_id
  AND e.tier = 'cold'
ORDER BY e.embedding <=> :query_vector
LIMIT 10;
```

### Cascade Deletion

`ON DELETE CASCADE` on all foreign keys. `remove_library()` becomes:

```python
async def remove_library(self, library: Library) -> None:
    await self.session.delete(library)
    await self.session.commit()
```

Cascades chain down: library → library_files → (embeddings, file_tags, ml_output_streams, ...). Tags referenced by deleted `file_tags` rows are preserved (no CASCADE from file_tags to tags). All FKs have supporting indexes — CI enforces this.

### Graph Query Equivalence

Recursive CTEs replace AQL graph traversals:

```sql
-- Tag hierarchy (max 5 levels): replaces FOR v,e IN 1..5 OUTBOUND
WITH RECURSIVE tag_tree AS (
    SELECT id, name, parent_tag_id, 0 AS depth FROM tags WHERE id = $1
    UNION ALL
    SELECT t.id, t.name, t.parent_tag_id, tt.depth + 1
    FROM tags t JOIN tag_tree tt ON t.parent_tag_id = tt.id
    WHERE tt.depth < 5
) SELECT * FROM tag_tree;

-- Folder tree: replaces folder_has_folder edges
WITH RECURSIVE folder_tree AS (
    SELECT id, name, parent_id, 0 AS depth FROM library_folders WHERE id = $1
    UNION ALL
    SELECT f.id, f.name, f.parent_id, ft.depth + 1
    FROM library_folders f JOIN folder_tree ft ON f.parent_id = ft.id
) SELECT * FROM folder_tree;
```

---

## 5. Persistence & Repository Architecture

### Tier Architecture

The existing 3-tier architecture is preserved with different implementations:

| Tier | ArangoDB | PostgreSQL |
|---|---|---|
| **Tier 3: Intent Facades** | `api/library.py`, `api/ml.py`, `api/application.py` | Same files, same API. Internal delegation changes (AQL ops → repos). |
| **Tier 2: Domain Repositories** | `database/*_aql.py` (11 packages, ~5,500 lines) | `database/*_repo.py` (~1,500 lines). One repo per domain (LibraryRepo, TagRepo, EmbeddingRepo, etc.). |
| **Tier 1: Query Primitives** | `aql/primitives.py` (420 lines) | `sql/primitives.py` (~200 lines). SQLAlchemy Core select/insert/update/delete wrappers. |

### Repository Pattern

Each domain repository uses SQLAlchemy async session for CRUD. Pattern:

```python
class EmbeddingRepo:
    """Cold embed storage and similarity search."""
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_similar(self, query: list[float], backbone_id: str,
                           limit: int = 10) -> list[SimilarResult]:
        stmt = select(Embedding).where(
            Embedding.backbone_id == backbone_id,
            Embedding.tier == "cold"
        ).order_by(Embedding.embedding.cosine_distance(query)).limit(limit)
        result = await self._session.execute(stmt)
        return [SimilarResult(...) for (e,) in result]

    async def insert_batch(self, embeddings: list[Embedding]) -> None:
        self._session.add_all(embeddings)
        await self._session.flush()

    async def drain_hot_to_cold(self, backbone_id: str) -> int:
        stmt = update(Embedding).where(
            Embedding.backbone_id == backbone_id,
            Embedding.tier == "hot"
        ).values(tier="cold", updated_at=int(time.time()))
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount
```

### Database Wiring

```python
# pg_engine.py (~50 lines, replaces arango_client.py)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(
    "postgresql+asyncpg://user:pass@postgres:5432/nomarr",
    pool_size=5, max_overflow=10, pool_pre_ping=True
)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with SessionFactory() as session:
        yield session

# db.py — Database class wires facades to repos
class Database:
    def __init__(self) -> None:
        self._session_factory = SessionFactory
    def library_db(self, session: AsyncSession) -> LibraryDb:
        return LibraryDb(LibraryRepo(session), TagRepo(session), ...)
```

### Key Query Patterns

| Pattern | SQLAlchemy |
|---|---|
| UPSERT | `insert(Embedding).on_conflict_do_update(index_elements=['file_id','backbone_id'], set_=dict(embedding=excluded.embedding))` |
| Bulk insert | `session.add_all(embeddings)` |
| Filtered ANN | `select(Embedding).where(tier='cold', backbone_id=X).order_by(cosine_distance).limit(k)` |
| Tag intersection | `EXISTS(subquery_tag_a) AND EXISTS(subquery_tag_b)` |
| Cascade delete | `await session.delete(library); await session.commit()` |
| Counting | `select(func.count()).where(...)` |

---

## 6. Migration & Implementation Strategy

### Phase 1: Infrastructure Setup

1. Replace `arangodb:3.12` with `pgvector/pgvector:pg17` in docker-compose
2. Add PostgreSQL health check and volume mounts
3. Create `pg_engine.py` with `create_async_engine()` — test connectivity
4. Add dependencies to pyproject.toml: `sqlalchemy[asyncio]`, `asyncpg`, `pgvector`, `alembic`

### Phase 2: Schema Definition

5. Write SQLAlchemy models in `nomarr/persistence/models/` (one file per domain)
6. Define all FK constraints with `ON DELETE CASCADE`
7. Ensure every FK column has a supporting index
8. Define partial HNSW index on `embeddings WHERE tier = 'cold'`
9. Define GIN trigram indexes on `library_files.path` and `tags.name`
10. Generate baseline Alembic migration to create all tables (V1). Normal Alembic migrations from V2 onward.

### Phase 3: Repository Layer

11. Create `sql/primitives.py` — minimal SQLAlchemy Core wrappers
12. Create `database/*_repo.py` — domain repositories (one per domain)
13. Implement all CRUD operations: scan, tag, embed, calibrate, navidrome sync
14. Implement `EmbeddingRepo.drain_hot_to_cold()` as async drain job
15. Run all existing tests against new repos — verify behavioral equivalence

### Phase 4: Intent Facade Re-wire

16. Update `db.py` Database class — wire repos into facades (same public API)
17. Update `api/library.py`, `api/ml.py`, `api/application.py` — internal delegation changes only
18. Update maintenance companions — maintenance methods map to repos

### Phase 5: Service Layer Re-wire

19. Update DI container — inject PostgreSQL sessions instead of ArangoDB clients
20. Update all services that construct Database class

### Phase 6: Deletion (Hard Cut)

21. Delete `aql/` directory (primitives + all 11 domain packages)
22. Delete `arango_client.py`
23. Delete `schema/ddl.py`, `schema/names.py`, `schema_types.py`
24. Delete ArangoDB-specific Pydantic models in `models/`
25. Remove `python-arango` from pyproject.toml
26. Remove `arangodb` service from docker-compose

### Phase 7: Testing & Verification

27. Run full backend test suite — zero failures
28. Run `test_static_aql_validation.py` (removed, verify no AQL references remain)
29. Verify `remove_library()` cascade with 50K+ files (integration test)
30. Recall benchmark: compare pgvector HNSW results against brute-force cosine baseline
31. Lint: `ruff check`, `mypy`, `import-linter` — zero errors

### Hard Cut Rationale

No data migration. No dual-write. No backwards compatibility. Nomarr is in alpha — the application is offline right now. A hard cut eliminates the enormous complexity of a dual-write transitional architecture. The cost of doing it this way is zero (no users, no data) and the benefit is enormous (no migration code ever written, no compatibility shims ever maintained).

---

## 7. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Partial HNSW planner bypass — index silently not used | HIGH | Use `EXPLAIN (ANALYZE, BUFFERS)` during performance validation with representative data volumes. CI assertions verify HNSW index is used for ANN queries on cold-tier data. Monitor query latency — regressions indicate planner drift. For small datasets where a sequential scan is legitimately cheaper, the planner's choice is correct. Brute-force fallback only when ANN recall or result count is insufficient, not because an index node was absent.
| HNSW build memory starvation from 64MB default | HIGH | Set `maintenance_work_mem = 2GB` for build sessions. Use formula: 60% of Docker RAM / (1 + workers). `CREATE INDEX CONCURRENTLY`. Re-provision at 300K cold-tier vectors. |
| HNSW index size (1.8-2.5× raw data) | MEDIUM | halfvec halves raw storage (1M 512-dim: raw ~1 GB, index ~2-2.5 GB). Track index:table ratio. REINDEX when >2.5×. |
| halfvec SIMD regression with GCC < 9 (2.8× slower) | MEDIUM | Verify `pgvector/pgvector:pg17` Docker image compiler version. Ubuntu-based image ships GCC ≥ 9 — LOW risk for Docker deployment. |
| Index bloat from UPDATE-heavy drain workload | MEDIUM | `VACUUM ANALYZE` weekly. Monitor `pg_stat_user_indexes`. `REINDEX CONCURRENTLY` monthly or when ratio >2.5×. |
| FK CASCADE deadlock — missing supporting indexes | MEDIUM | CI check: every FK column must have a supporting index. Documented in migration checklist. |
| SQLAlchemy async connection leaks under `CancelledError` | MEDIUM | Pin SA ≥ 2.0.37. `asyncio.shield()` on `session.close()`. `pool_pre_ping=True`. |
| Cascade deletion correctness | MEDIUM | `ON DELETE CASCADE` is atomic within a transaction. Integration test with 50K+ files. |
| Stored values (genres) — no direct pgvector equivalent | LOW | Covering index: `CREATE INDEX ON embeddings (id) INCLUDE (genres) WHERE tier = 'cold'`. Adds ~0.1ms per result. |
| halfvec overflow for unnormalized embeddings (>±65504) | LOW | All music embeddings (VGGish, CLAP, MERT) are L2-normalized. Document "always normalize before insert" as hard requirement. |
| pg_trgm short-string fallback for queries < 8 chars | LOW | Document the threshold. Short artist names ("Muse", "Bass") may use sequential scan — acceptable. |
| Graph query equivalence | LOW | Folder hierarchy is flat in V1. Recursive CTEs available if tree structure added. |
| Migration complexity | HIGH | Hard cut means no rollback. Test thoroughly in dev. Fix all issues before merging. |
| halfvec precision loss | LOW | Official pgvector 0.7.0 benchmarks: identical recall (0.987) for both types at ef_search=200. |

### Operational Cadence

Rely on autovacuum for normal maintenance. Monitor the following metrics and intervene only when thresholds are crossed:

| Metric | Threshold | Action |
|---|---|---|
| Dead tuple ratio | > 20% in `pg_stat_user_tables` | `VACUUM ANALYZE` on affected table |
| Index-to-table size ratio | > 2.5× in `pg_stat_user_indexes` | `REINDEX CONCURRENTLY` on affected index |
| ANN recall | Drops > 5% vs brute-force baseline on held-out queries | Investigate: index bloat, incomplete drain, ef_search too low |
| Query latency (p95) | > 2× baseline | Check for missing `EXPLAIN` plans, planner drift, stale statistics |
| pgvector releases | New stable release | Plan upgrade within 1-2 months in dev; test recall before production roll

---

## 8. Testing & Acceptance Criteria

### Unit Tests

- **Query-construction tests**: SQLAlchemy Core expression tests verify correct SQL generation without a database. No dialect needed.
- **DTO/serialization tests**: Verify Pydantic DTOs serialize/deserialize correctly. Database-free.
- **Repository tests**: Run against an ephemeral PostgreSQL container (testcontainers-python or Docker fixture). The repository layer depends on PostgreSQL-specific types (ARRAY, JSONB, halfvec), operators (<=>), and index behavior (partial HNSW) that SQLite cannot approximate. Treating SQLite as a substitute would either require enough dialect substitution to become a second persistence implementation or silently fail to test the important behavior.

### Integration Tests

- **HNSW build + search**: PostgreSQL Docker required. Create synthetic embeddings (10K vectors), build HNSW index, verify recall ≥ 0.95 vs brute-force. Marked `@pytest.mark.hnsw_build` — optional for local dev, required in CI.
- **Cascade deletion**: Create library with 50K files, 100 tags, embeddings, streams. Delete library. Verify zero orphaned rows across all child tables. Verify FK constraint error if child has no CASCADE.
- **Hot/cold drain**: Insert 1K hot embeddings, run drain, verify tier = 'cold', verify HNSW index includes them.
- **Concurrency**: Multiple workers insert embeddings simultaneously. Verify no deadlocks, no duplicate key errors.
- **pg_trgm search**: Insert known paths, search with typos, verify correct matches with similarity scores.

### Acceptance Criteria

1. All existing service tests pass without modification (intent facade API unchanged)
2. `remove_library()` cascade test: 50K files deleted in single transaction, no orphaned rows
3. HNSW recall ≥ 0.95 at ef_search=200 on 10K synthetic embeddings vs brute-force baseline
4. drain operation: 1K hot → cold in < 5 seconds
5. pg_trgm: "Abby Road" matches "Abbey Road" with similarity ≥ 0.60
6. `ruff check`, `mypy`, `import-linter` — zero errors across entire codebase
7. Zero references to ArangoDB, python-arango, or AQL anywhere in nomarr/
8. Lint: no new lint errors introduced

### CI Requirements

- Full integration test suite: 6 GB Docker RAM (transient `maintenance_work_mem` for HNSW builds)
- Local dev without HNSW tests: 2-3 GB Docker RAM
- `pytest -m "not hnsw_build"` for rapid local iteration; CI always runs full suite

---

## 9. Resolved Decisions

All open questions from the adversarial refinement resolved:

| # | Question | Decision |
|---|---|---|
| Q1 | Sync psycopg2 for migrations? | **Accepted**. Dual-driver: sync for Alembic, async for app. |
| Q2 | Relaxed vs strict vector ordering? | **Strict everywhere**. Pay ~20% cost for exact ordering. |
| Q3 | Migration hard cut outage? | **Irrelevant**. Alpha app, offline, no users. |
| Q4 | halfvec for ML training? | **Accepted**. Training not a concern. Regenerate from raw audio if needed. |
| Q5 | Read-after-write inconsistency? | **Accepted**. ~100ms window acceptable for async music ingestion. |
| Q6 | HNSW vs DiskANN switch? | **Ignored**. HNSW sufficient for Nomarr's scale. |
| Q7 | CI RAM provisioning? | **Resolved**. 6 GB CI, 2-3 GB local dev without HNSW tests. |

No unresolved human decisions remain. All blocking issues (U1: `updated_at` column, U2: memory formula) are fixed in schema and risk sections above.

---

## 10. Compact Appendix

### Persistence Layer Impact

| Metric | Before | After |
|---|---|---|
| Total lines | ~8,600 | ~3,500 |
| Reduction | — | ~59% |
| `aql/` directory | 11 files, 420 lines | **Deleted** |
| `database/*_aql.py` | 11 packages, ~5,500 lines | `database/*_repo.py`, ~1,500 lines |
| `arango_client.py` | 188 lines | `pg_engine.py`, ~50 lines |
| `schema/ddl.py` + `schema/names.py` | 370 lines | SQLAlchemy models |
| `schema_types.py` | 437 lines | `models/embedding.py`, ~80 lines |
| Cascade deletion AQL | 147 lines | `await db.delete(library)` |

### ArangoDB → PostgreSQL Collection Mapping

37 CollectionNames entries:

| Domain | ArangoDB Collection | PostgreSQL Table |
|---|---|---|
| Libraries | libraries, library_files, folders | libraries, library_files, library_folders |
| Tags | tags, song_has_tags | tags, file_tags |
| ML | ml_models, ml_streams, ml_outputs | ml_models, ml_output_streams, ml_embedding_streams, ml_model_outputs |
| Calibration | calibration_state, calibration_history | calibration_state, calibration_history |
| Vectors | vectors_*__* (dynamic, per-backbone-per-library) | embeddings (single table, backbone_id column) |
| App | app_config, app_sessions, worker_health | app_config, app_sessions, worker_health |
| Navidrome | navidrome_tracks, navidrome_plays | navidrome_tracks, navidrome_plays, navidrome_track_maps, navidrome_play_maps |
| Edges | 14 edge collections | 10 → FK columns, 4 → junction tables |

### Fuzzy Search Strategy (pg_trgm)

Hybrid approach from rendiment.io's 2026 "Finding Abbey Road" article:

1. **pg_trgm fuzzy match first** — sub-ms, GIN-indexed, typo-tolerant
2. **Score ≥ 0.65** → return immediately (excellent match)
3. **Score < 0.65** → fall back to pgvector semantic search (embedding similarity)
4. **Combine results** — return best of both

Extensions: `CREATE EXTENSION pg_trgm;`. GIN indexes on `library_files.path gin_trgm_ops` and `tags.name gin_trgm_ops`. Phonetic fallback (`fuzzystrmatch`) deferred to V1+.

### Docker Configuration

```yaml
postgres:
  image: pgvector/pgvector:pg17
  environment:
    POSTGRES_USER: nomarr
    POSTGRES_PASSWORD: nomarr
    POSTGRES_DB: nomarr
  ports:
    - "5432:5432"
  volumes:
    - pg_data:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U nomarr"]
    interval: 5s
    timeout: 5s
    retries: 5
```

### Companion Documents

- [Adversarial Refinement Details](DD-postgresql-pgvector-migration/adversarial-refinement.md) — Full 8-turn adversarial pipeline (4,488 lines): rejected approaches (per-backbone partitioned, zero-ORM asyncpg, hybrid PostgreSQL+Qdrant, pgvectorscale DiskANN), critique with production evidence, resolution logs, and all unresolved risks.

### Pre-existing Bug: Disappears with ArangoDB

`LIBRARY_HAS_SCAN` and `LIBRARY_HAS_PIPELINE_STATE` are listed in `CollectionNames` enum but have **no DDL definition** in `ddl.py`. They are managed through raw AQL edge operations and would never be created by `ensure_schema()`. This bug disappears when `ddl.py` and `CollectionNames` are deleted.

### Sizing Reference

| Library Size | Files | Embeddings (1 per file) | Raw halfvec Storage | HNSW Index | Total |
|---|---|---|---|---|---|
| Small | 10K | 10K 512-dim | ~10 MB | ~22 MB | ~32 MB |
| Medium | 100K | 100K 512-dim | ~100 MB | ~220 MB | ~320 MB |
| Large | 500K | 500K 512-dim | ~500 MB | ~1.1 GB | ~1.6 GB |
| Huge | 1M | 1M 512-dim | ~1 GB | ~2.2 GB | ~3.2 GB |

All well within local-machine storage budgets. PostgreSQL shared_buffers should be the smaller of 25% of RAM or 1 GB.
