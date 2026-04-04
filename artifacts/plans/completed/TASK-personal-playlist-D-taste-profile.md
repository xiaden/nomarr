# Task: Personal Playlist — Taste Profile + Genre Indexes

## Problem Statement

The personal playlist feature needs to compute per-user taste profiles from play history and perform genre-scoped similarity searches. This plan implements two capabilities: (1) a stateless taste profile component that queries top-N tracks by play count via graph traversal, fetches embeddings from cold vectors, and computes a recency-weighted centroid using $w_i = \log(1 + \text{playcount}_i) \cdot e^{-\lambda \cdot d_i}$; (2) genre-partitioned ANN index creation during cold promotion so Part E can do per-genre similarity search.

The taste profile component follows existing patterns in `nomarr/components/navidrome/tag_query_comp.py`. Genre index creation extends `ml_vector_maintenance_comp.py` and hooks into the cold promotion workflow.

**Prerequisite:** TASK-personal-playlist-A-graph-collections

## Phases

### Phase 1: DTOs + Taste Profile Component
- [x] Add `TasteProfile` and `TasteCluster` TypedDicts to `nomarr/helpers/dto/navidrome_dto.py`. `TasteProfile`: `user_id: str`, `centroid: list[float]`, `backbone_id: str`, `library_key: str`, `track_count: int`, `generated_at_ms: int`. `TasteCluster`: `label: str`, `centroid: list[float]`, `track_count: int`. Export both from `nomarr/helpers/dto/__init__.py`.
- [x] Create `nomarr/components/navidrome/taste_profile_comp.py` with public function `compute_taste_profile(db: Database, user_id: str, backbone_id: str, library_key: str, half_life_days: float = 30.0, top_n: int = 200) -> TasteProfile | None`. Calls `db.navidrome_playcounts.get_top_plays(user_id, top_n)`, filters to tracks with `file_id is not None`, batch-fetches cold vectors, computes recency weights, computes weighted centroid, returns `TasteProfile` with `generated_at_ms=now_ms().value`. Returns `None` if no valid tracks with embeddings.
- [x] Implement `_compute_recency_weights(plays, now_ms_val, half_life_days) -> list[float]` private helper in same file. Formula: λ = ln(2)/half_life_days, d_i = (now_ms - last_played_ms)/86400000 or half_life_days*2 fallback if None. Weight: w_i = log(1+playcount_i) * e^(-λ*d_i). Uses `math.log`/`math.exp`.
- [x] Implement `_compute_weighted_centroid(vectors, weights) -> list[float]` private helper. Uses numpy: `np.average(vectors, axis=0, weights=weights)` then L2-normalize via `centroid / np.linalg.norm(centroid)`. Handle zero-norm edge case. Return as `list[float]`.
- [x] Verify `lint_project_backend` passes on `nomarr/components/navidrome` and `nomarr/helpers/dto` with zero errors.

### Phase 2: Genre-Partitioned ANN Indexes
- [x] Add genre-index helper functions to `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py`: `_query_genre_file_groups(db, cold_collection_name) -> dict[str, list[str]]` (AQL join cold vectors with song_has_tags where rel=="genre", group by genre) and `_sanitize_genre_name(genre) -> str` (lowercase, replace non-alphanumeric with underscore, truncate to 64 chars).
- [x] Implement `build_genre_partitioned_indexes(db, backbone_id, library_key, embed_dim, nlists, min_genre_tracks=100) -> int` in same file. For each genre with 100+ files: create collection, AQL-copy vectors, add vector index. Returns count. Also implement `drop_genre_indexes(db, backbone_id, library_key) -> int` to drop all genre sub-collections matching the naming pattern.
- [x] Hook into `nomarr/workflows/platform/promote_and_rebuild_vectors_wf.py`: after existing `build_cold_vector_index()` call, add `drop_genre_indexes()` then `build_genre_partitioned_indexes()` with same embed_dim and nlists. Import both from `ml_vector_maintenance_comp`.
- [x] Verify `lint_project_backend` passes on `nomarr/components/ml/vectors`, `nomarr/workflows/platform`, and full workspace with zero errors.

## Completion Criteria
- `compute_taste_profile()` returns a `TasteProfile` TypedDict with recency-weighted centroid
- Recency weight formula matches $w_i = \log(1 + \text{playcount}_i) \cdot e^{-\lambda \cdot d_i}$
- Unknown recency (last_played_ms=None) uses half_life_days * 2 fallback
- Final centroid is L2-normalized
- Genre-partitioned ANN indexes created during cold promotion for genres with 100+ tracks
- `TasteProfile` and `TasteCluster` TypedDicts available in `helpers/dto/`
- `lint_project_backend` passes with zero errors

## References
- Design doc: `plans/dev/design-personal-playlist.md` (taste profile + genre index sections)
- Contracts ledger: `plans/dev/personal-playlist-parts/CONTRACTS.md`
- Existing patterns: `nomarr/components/navidrome/tag_query_comp.py`, `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py`
- Cold promotion: `nomarr/workflows/platform/promote_and_rebuild_vectors_wf.py`
- Prerequisite: `plans/TASK-personal-playlist-A-graph-collections.md`
