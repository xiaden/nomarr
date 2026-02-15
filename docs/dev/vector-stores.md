# Vector Stores (Hot/Cold Architecture)

## Overview

Nomarr's embedding pipeline now stores vectors in two physically separate
collections per backbone:

- **Hot collections (`vectors_track_hot__{backbone}`)** capture fresh vectors as
  soon as ML processing finishes. They are write-optimized and **never** host a
  vector index, which keeps inference throughput predictable.
- **Cold collections (`vectors_track_cold__{backbone}`)** hold promoted vectors
  that are ready for similarity search. These collections own the vector
  indexes and remain query-optimized.

This split avoids the OOM regressions we saw when the ANN index was maintained
inline with ingest. Workers can upsert freely in hot, and operators decide when
search freshness should be updated by draining to cold.

## Lifecycle Summary

1. ML workers upsert embeddings into the hot collection via
   `VectorsTrackHotOperations`.
2. Operators run the synchronous promote & rebuild workflow, which drains the
   hot collection, inserts documents into cold, and rebuilds the ANN index.
3. Search APIs query the cold collection only, guaranteeing predictable query
   latency and "as of last promote" semantics.
4. Direct get-by-id operations check cold first for promoted vectors and then
   fall back to hot for "not yet promoted" files.

## When to Run Promote & Rebuild

- Trigger the workflow **after a batch of ML processing completes** so that all
  recent vectors are captured in the subsequent cold collection snapshot.
- Use `VectorMaintenanceService.get_hot_cold_stats()` (exposed via the admin API)
  to inspect `hot_count` versus `cold_count`. When hot grows beyond a batch's
  worth of files, schedule a promote to keep search freshness bounded.
- Run promote & rebuild during operational quiet periods. The workflow is
  synchronous and rebuilds the ANN index; keeping it off the ingest critical path
  prevents worker stalls.
- Skip automatic interval-based scheduling for now. Operators can manually
  trigger the `/api/v1/admin/vectors/promote` endpoint once the ML pipeline has
  drained its queue.

## Calculating `nlists`

`VectorMaintenanceService.calculate_optimal_nlists()` computes
`nlists = clamp(10, 100, floor(sqrt(total_docs)))`, where `total_docs` is the
future cold size (`hot_count + cold_count`). Operators generally do not need to
provide a value; the admin endpoint accepts `null` and defers to this
calculation. Override it only when benchmarking a specific backbone that needs a
higher/lower recall-performance tradeoff.

## Search Semantics

- `/api/v1/vectors/search` and `VectorSearchService` query **cold collections only**.
- Responses represent the state **as of the last promote & rebuild**. Newly
  ingested vectors will show up after the next maintenance cycle.
- Hot collections are never searched; this guarantees predictable ANN latency
  and keeps write-path data isolated from query-path data.
- If clients require "draft" visibility, they can call
  `VectorSearchService.get_track_vector()` for a single file, which falls back
  to hot storage when cold misses.

## Get-by-ID Retrieval

`VectorSearchService.get_track_vector()` implements the documented fallback:

1. Query cold collection — return immediately if the vector exists.
2. If cold misses, query the hot collection for the same file ID.
3. Return `None` only when both storage tiers lack the vector.

Use this endpoint for editor previews or debugging when a specific file has been
processed but not yet promoted. The behavior is intentionally read-mostly and
should not be used to emulate bulk search.

## Migration Path (m007)

Existing deployments (schema version 6) move to the hot/cold model via
`nomarr/migrations/V007_split_vectors_hot_cold.py`:

1. For each backbone, rename `vectors_track__{backbone}` to
   `vectors_track_cold__{backbone}` so that all existing vectors remain readable
   and keep their ANN index.
2. Create a fresh empty `vectors_track_hot__{backbone}` collection with the
   required `_key` and `file_id` persistent indexes.
3. Recreate persistent indexes on the cold collection (excluding vector indexes)
   to guarantee convergence and cascade-delete performance.
4. Operators must run promote & rebuild after the migration to rebuild the ANN
   index under the new naming scheme.

Schema version increments to 7, and bootstrap now provisions hot collections
only. The migration is idempotent; re-running it skips already-converted
backbones.

## Key Components

| Layer | Responsibilities |
| --- | --- |
| Components / Persistence | Low-level ArangoDB operations for hot/cold collections |
| Workflows | `promote_and_rebuild_workflow` orchestrates drain, rebuild, and convergence checks |
| Services | `VectorSearchService` (cold-only search + fallback reads), `VectorMaintenanceService` (promote + stats) |
| Interfaces | `/api/v1/vectors/search`, `/api/v1/admin/vectors/*` expose search + maintenance endpoints |

Subsequent sections describe operational guidance, search semantics, and upgrade
paths for existing deployments.


```
[ ML Workers ] --upsert--> [ vectors_track_hot__* ] --promote & rebuild--> [ vectors_track_cold__* ] --search--> [ API Clients ]
```