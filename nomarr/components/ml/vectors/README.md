# ML Vectors

Embedding vector storage with hot/cold tiered collections for similarity search.

## Responsibilities

- Pool segment-level embeddings into track-level vectors for storage
- Persist vectors to hot collections during ML processing
- Promote vectors from hot to cold collections (drain + UPSERT)
- Build and maintain pgvector indexes on cold collections
- Retrieve promoted vectors for similarity queries
- Backfill genre metadata on cold vectors

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `ml_vector_pool_comp` | Pool segment embeddings into single track-level vector (trimmed mean) for JSON serialization |
 | `ml_vector_persist_comp` | Write pooled vectors to per-backbone hot collections during ML processing |
 | `ml_vector_retrieve_comp` | Fetch promoted vectors from cold collections for similarity search |
 | `ml_vector_maintenance_comp` | Hot→cold drain (convergent UPSERT + truncate), vector index build/rebuild, genre backfill, embed_dim probing |
 | `ml_vector_idle_promotion_comp` | Discover hot collections with pending vectors, compute optimal nlists for index parameters |

## Patterns

- **Hot/cold tiering:** Hot collections are write-only accumulation targets during ML processing. Cold collections hold promoted, indexed vectors for search. Hot is never searched.
- **Convergent drain:** `drain_hot_to_cold` uses ON CONFLICT UPSERT (idempotent by primary key) then truncates hot — safe to run multiple times. It is a pure hot→cold promotion and performs no genre enrichment.
- **Genre enrichment:** `backfill_genres` (not `drain_hot_to_cold`) enriches existing cold vector documents with genre tags derived from the song's tags (via the `MlDb` facade, `name="genre"`); run it via `backfill_vector_genres_workflow`.
- **Per-backbone collections:** Each backbone (effnet, musicnn, etc.) has its own hot and cold vector collection, selected by backbone name.

## Dependencies

- **Upstream:** Called by `workflows/` (vector promotion, similarity search)
- **Downstream:** Calls `persistence/` for vector collection access, `onnx/` for embed_dim probing
