# Genre Vector Index — Implementation Parts

## Context

Genre-aware playlist generation was previously implemented via per-genre vector sub-collections
(`vectors_track_cold__{backbone}__{lib}__genre__{sanitized}`). This was removed because ArangoDB
supports `storedValues` on ANN indexes — a single collection with genre data stored in the index
is the correct approach. Songs can have **multiple genres** (array field).

This feature:

1. Populates a `genres: list[str]` array field on cold vector documents at drain time (via tag join)
2. Adds `storedValues` for `genres` to the ANN index definition
3. Adds a genre-filtered ANN search method to `VectorsTrackColdOperations`
4. Restores `build_genre_playlists` in the playlist component using the indexed filter

## Parts

 | Part | Title | Depends On | Layers |
 | --- | --- | --- | --- |
 | A | Genre Enrichment on Vector Documents | None | persistence, maintenance_comp |
 | B | Genre Playlist via Indexed Filter | A | component, workflow |

## Dependency Graph

```
A (drain+index+search method) → B (genre playlist builder)
```

## Execution Rounds

Round 1: A
Round 2: B (depends on A — needs search_similar_by_genre)

## Per-Part Scope

### Part A: Genre Enrichment on Vector Documents

Modifies `drain_hot_to_cold` AQL in `ml_vector_maintenance_comp.py` to JOIN `song_has_tags` and
`tags` (where `rel == "genre"`) for each doc's `file_id`, collecting genre values into a
`genres: list[str]` array. Updates the INSERT and UPDATE branches. Also modifies
`build_cold_vector_index` to include `storedValues: [{"fields": ["genres"]}]` so the index can
evaluate genre filters without doc reads. Adds `search_similar_by_genre(vector, genre, limit,
nprobe)` to `VectorsTrackColdOperations` in `vectors_track_aql.py` using
`FILTER @genre IN doc.genres` after `APPROX_NEAR_COSINE`. Adds a `backfill_genres` AQL utility
function in the maintenance comp to populate `genres` on existing cold docs (one-time use;
runtime invoked via the promote_and_rebuild trigger or manually). Touches:
`nomarr/persistence/database/vectors_track_aql.py`,
`nomarr/components/ml/vectors/ml_vector_maintenance_comp.py`.

### Part B: Genre Playlist via Indexed Filter

Restores `build_genre_playlists` in `nomarr/components/navidrome/playlist_builder_comp.py`.
Function gets user's genre affinities via `db.tags.get_distinct_tag_values_for_files(file_ids,
"genre")`, then for each genre calls `cold_ops.search_similar_by_genre(centroid, genre, limit,
nprobe)` on the single cold collection. No sub-collections, no collection_suffix. Multi-genre
coverage is natural — each genre produces one `Your {Genre} Mix` playlist. Re-wires
`build_genre_playlists` into `generate_playlists_wf.py` (`_BUILDERS` dict) and
`nomarr/components/navidrome/__init__.py`. Touches:
`nomarr/components/navidrome/playlist_builder_comp.py`,
`nomarr/workflows/navidrome/generate_playlists_wf.py`,
`nomarr/components/navidrome/__init__.py`.
