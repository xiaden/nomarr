# ADR-036: Vector Stores Are Per-Backbone, Not Per-Backbone-Per-Library

**Status:** Superseded by ADR-040  
**Date:** 2026-06-19  
**Tags:** vectors, persistence, architecture, simplification  

## Context

Vector collections have been organized per-backbone-per-library since the initial ML pipeline implementation: `vectors_track_hot__{backbone}__{library_key}` and `vectors_track_cold__{backbone}__{library_key}`. This means N libraries × M backbones = N×M hot collections and N×M cold collections, each with its own HNSW ANN index.

This design appears to be a holdover from a period of confusion about Nomarr's architecture — a misconception that different libraries might correspond to different users or tenants, requiring vector isolation. Nomarr is and has always been a single-user application. Libraries are organizational boundaries within one user's music collection (e.g., "lossless archive" vs. "portable collection"), not multi-tenant isolation boundaries.

The per-library boundary creates unnecessary complexity:
- Cross-library vector search requires fan-out iteration across every library's cold collection, merging and deduplicating results after the fact
- Each library maintains its own HNSW index, wasting DB resources when all vectors should be in one index
- Library deletion requires discovering per-library vector collections by suffix and dropping them individually
- Promotion/idle-indexing must enumerate (backbone, library) pairs
- Playlist generation and similar-track search carry `library_key` through the entire call chain unnecessarily

There are no ADRs or design documents that discuss or justify the per-library vector store decision. It appears to have been implemented without explicit architectural discussion.

## Decision

Vector stores will be organized per-backbone only, with no library boundary:

**Collection naming:** `vectors_track_hot__{backbone}` and `vectors_track_cold__{backbone}`

**Changes from current architecture:**

1. **Resolution** — `get_hot_namespace(db, backbone, library_key)` → `get_hot_namespace(db, backbone)`. The `library_key` parameter is dropped. Same for `get_cold_namespace`.

2. **Search** — `search_similar_tracks` no longer needs `library_scope`. All ANN searches run against the single per-backbone cold index. Cross-library discovery is the default (all vectors in one index). Library-scoped results, if needed, use post-ANN filtering by extracting the library from `file_id` (`library_files/{key}`).

3. **Fan-out eliminated** — `_search_fan_out` is removed entirely. A single ANN query replaces the iterate-and-merge pattern.

4. **Promotion and indexing** — `promote_and_rebuild(db, backbone, library_key)` → `promote_and_rebuild(db, backbone)`. The entire backbone's hot vectors are drained to cold and indexed in one operation. Per-backbone-per-library promotion had no practical value in a single-user system — idle promotion already enumerated and promoted all pairs sequentially.

5. **Stats and maintenance** — `get_embedding_stats(backbone, library_key)` → `get_embedding_stats(backbone)`. Per-library breakdowns, if needed, are derived from queries that filter by `file_id` prefix. `has_embedding_index`, `rebuild_library_embedding_index`, and `index_library_embeddings` are simplified to backbone-scoped operations.

6. **Library deletion** — The per-library vector collection cleanup in `LibrariesAqlOperations.remove_library()` (the Python loop discovering `vectors_track*__{lib_key}` collections) is removed. Vector documents are deleted via `file_has_vectors` edges, which are already global and point into the shared hot/cold collections. No per-library collections exist to drop.

7. **`file_has_vectors` edges** — No change needed. These edges are already global (not per-library) and point from `library_files/{id}` to vector documents. They continue to work unchanged because vector documents are still in the hot/cold collections.

8. **Library-scoped filtering** — When a caller genuinely needs to limit results to one library, post-ANN filtering on `file_id` is used. The `file_id` field in vector documents encodes the owning library (`library_files/{key}`). Over-fetching (e.g., `limit * 3`) ensures the filter step still yields sufficient results.

**Migration approach:** Forward-only migration. All per-backbone-per-library hot/cold collections are merged into per-backbone collections. Existing vector documents are copied; `file_has_vectors` edges are preserved. Per-library collections are dropped after migration. Cold HNSW indexes are rebuilt once per backbone on the merged collection.

## Consequences

**Positive:**

1. **Cross-library vector search is the default** — ANN queries on one index inherently return results from any library. No fan-out, no merge, no deduplication overhead.
2. **Fewer ArangoDB collections** — One hot and one cold collection per backbone instead of N hot and N cold. Cleaner database, simpler operations.
3. **Fewer HNSW indexes** — One index per backbone instead of N indexes. Lower memory usage in ArangoDB.
4. **Simpler code** — `get_hot_namespace` / `get_cold_namespace` drop `library_key`. `_search_fan_out` is deleted. `remove_library` loses the per-collection cleanup loop. `list_hot_vector_targets` returns backbone IDs instead of (backbone, library) pairs. Playlist context drops `library_key`. The `library_scope` parameter disappears from `search_similar_tracks` and the API.
5. **Simpler maintenance** — Promote and rebuild is backbone-scoped. Idle promotion checks each backbone's hot count once instead of N times.
6. **Library deletion is simpler** — No dynamic collection discovery needed. Vector cleanup uses existing `file_has_vectors` edges.
7. **Library creation is simpler** — Bootstrap no longer needs to pre-create per-library vector collections.

**Negative:**

1. **Library-scoped searches require post-filtering** — Minor performance cost for the "own library" use case. Over-fetching mitigates this. In practice, most searches are already cross-library (playlist generation uses the full index).
2. **Promotion and reindexing are all-or-nothing per backbone** — If a user has 10 libraries and wants to promote/reindex only one, they can't. In a single-user system, the distinction between "promote library A" and "promote all libraries" is academic — promoting incrementally still eventually promotes everything. The idle promoter already enumerates and promotes all pairs.
3. **Per-library stats require queries, not simple collection counts** — Moving from `collection.count()` to `FOR doc IN @@col FILTER doc.file_id LIKE @prefix RETURN 1` is a minor cost. Stats queries are infrequent and non-blocking.
4. **Multi-instance needed for boundary isolation** — If a future multi-user deployment needed true vector isolation between libraries, multiple Nomarr instances would be required instead of per-library collections within one instance. This is acceptable because Nomarr is single-user by design and has no plans for multi-tenancy.
5. **Migration cost** — Merging per-library collections into per-backbone collections is a one-time cost. Cold indexes must be rebuilt after the merge.

**Files affected (non-exhaustive):**
- `nomarr/components/ml/vectors/ml_vector_registry_comp.py` — drop `library_key` from `get_hot_namespace`, `get_cold_namespace`
- `nomarr/components/ml/vectors/ml_vector_persist_comp.py` — drop `library_key` from `upsert_hot_track_vector`, `persist_backbone_vector`
- `nomarr/components/ml/vectors/ml_vector_retrieve_comp.py` — drop `library_key` from retrievers
- `nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py` — simplify `list_hot_vector_targets`
- `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py` — drop `library_key`
- `nomarr/components/navidrome/playlist_builder_comp.py` — drop `library_key` from all builders
- `nomarr/components/navidrome/taste_profile_comp.py` — drop `library_key`
- `nomarr/services/domain/vector_search_svc.py` — remove `_search_fan_out`, `library_scope`, simplify `search_similar_tracks`
- `nomarr/services/domain/vector_maintenance_svc.py` — drop `library_key` from `promote_and_rebuild`, `get_hot_cold_stats`, etc.
- `nomarr/persistence/database/vectors_aql.py` — drop `library_key` from `_hot_name`, `_cold_name`, `get_embedding_stats`, `has_embedding_index`, `index_library_embeddings`
- `nomarr/persistence/database/libraries_aql.py` — remove per-library vector collection cleanup from `remove_library`
- `nomarr/persistence/schema_types.py` — update `NAME_PATTERN` for `VectorsTrackHot` and `VectorsTrackCold`
- `nomarr/components/platform/arango_bootstrap_comp.py` — simplify bootstrap to create per-backbone collections only
- `nomarr/interfaces/api/web/vectors_if.py` — remove `library_scope` from API
- `nomarr/interfaces/api/types/vector_types.py` — remove `library_scope` field
- `nomarr/helpers/dto/navidrome_dto.py` — remove `library_key` from `NavidromePersonalPlaylistContext`
- `nomarr/workflows/navidrome/generate_playlists_wf.py` — drop `library_key` parameter
- `nomarr/workflows/navidrome/find_similar_tracks_wf.py` — drop `library_key` parameter
- Various library DTOs with per-library vector config fields

## References

- `nomarr/components/ml/vectors/ml_vector_registry_comp.py` — current per-backbone-per-library namespace resolution
- `nomarr/services/domain/vector_search_svc.py` — fan-out search iterating per-library collections
- `nomarr/persistence/database/vectors_aql.py` — `_hot_name`, `_cold_name` with `library_key`
- `nomarr/persistence/database/libraries_aql.py:126-275` — `remove_library` per-collection vector cleanup
- `nomarr/components/platform/arango_bootstrap_comp.py:325` — per-library vector collection bootstrap
- `nomarr/components/navidrome/playlist_builder_comp.py` — all builders pass `library_key` to `get_cold_namespace`
- `nomarr/workflows/navidrome/generate_playlists_wf.py` — `library_key` in workflow signature and context
