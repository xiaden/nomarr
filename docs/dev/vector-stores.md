# Vector Stores

Nomarr stores all track embeddings in a single PostgreSQL `embeddings` table,
addressed by a `backbone_id` column. There is no hot/cold table split:

- **Single table** receives fresh writes and serves ANN search
- The former hot/cold collection pair was removed with the ArangoDB → PostgreSQL migration

The live persistence API is intent-facade based. The former `nomarr/persistence/collections.py` templates, `Builder` wiring, and runtime `db.register(resolved_name, template_name)` registration were removed with the ArangoDB → PostgreSQL migration: all embeddings now live in a single PostgreSQL `embeddings` table, addressed by `backbone_id` through the `db.ml` facade (see `nomarr/persistence/PERSISTENCE.md` §8).

---

## Migration Path (Alembic)

Schema is versioned via Alembic migrations in `alembic/versions/` (e.g.
`001_current_schema_baseline.py`).

All embeddings live in a single `embeddings` table, addressed by a
`backbone_id` column. There is no hot/cold split — no per-backbone
`vectors_track_hot__*` / `vectors_track_cold__*` tables. The former
`nomarr/migrations/V007_split_vectors_hot_cold.py` does not exist.

The single table carries the ANN index: the partial HNSW index
(`ix_embeddings_cold_hnsw`) is created once by the baseline schema migration
and maintained automatically by PostgreSQL (updated on VACUUM). There is no
per-backbone index creation or teardown, so `rebuild_backbone_embedding_index` /
`build_vector_index` are no-ops kept for API compatibility.
`index_backbone_embeddings` is not a no-op: it drains hot embeddings to the cold
tier for the backbone and returns the number of rows drained.

---

## Key Components

| Layer | Responsibilities |
| --- | --- |
| Components / Persistence | Single `embeddings` table (addressed by `backbone_id`) via the `db.ml` intent facade |
| Workflows | `promote_and_rebuild_workflow` orchestrates drain, rebuild, and convergence checks |
| Services | `VectorSearchService` (cold-only search + fallback reads), `VectorMaintenanceService` (promote + stats) |
| Interfaces | `/api/web/vector/*` exposes search and maintenance endpoints |

Subsequent sections describe operational guidance, search semantics, and upgrade
paths for existing deployments.

```text
[ ML Workers ] --upsert--> [ embeddings (single table, by backbone_id) ] --search--> [ API Clients ]
```

---

## Runtime registration

Runtime vector collection registration was removed with the ArangoDB → PostgreSQL migration. There are no `collections.py` templates, no `Builder` wiring, and no `db.register(...)`. All embeddings live in a single PostgreSQL `embeddings` table, addressed by a `backbone_id` column (e.g. `discogs_effnet`).

Vector access goes through the `db.ml` intent facade (`search_vectors`, `list_song_vectors`, `clear_vector_collection`, `list_vector_collection_names`, ...) over that single table.