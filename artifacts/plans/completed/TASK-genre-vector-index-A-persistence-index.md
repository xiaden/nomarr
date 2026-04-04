# Task: Genre Enrichment on Vector Documents (Part A)

## Problem Statement

Cold vector doc collection (`vectors_track_cold__{backbone}__{lib}`) currently stores only
embedding vectors and file metadata. Genre-aware playlists (Part B) require each cold doc to
carry its file's genre tags so the ANN index can evaluate genre filters without extra doc reads.

Three changes are needed:

1. **Drain-time enrichment** — modify `drain_hot_to_cold` AQL to JOIN `song_has_tags` + `tags`
   (where `tag.rel == "genre"`) for each doc's `file_id`, writing `genres: list[str]` on both
   the INSERT and UPDATE branches of the UPSERT.
2. **Index `storedValues`** — add `"storedValues": [{"fields": ["genres"]}]` to
   `build_cold_vector_index` so ArangoDB stores genre data inside the ANN index structure,
   enabling FILTER evaluation without a full doc fetch.
3. **Genre-filtered ANN search** — add `search_similar_by_genre(vector, genre, limit, nprobe)`
   to `VectorsTrackColdOperations`; AQL uses `FILTER @genre IN doc.genres` after
   `APPROX_NEAR_COSINE`.
4. **Backfill function** — add `backfill_genres(db, backbone_id, library_key) -> int` in
   `ml_vector_maintenance_comp.py` to UPDATE existing cold docs that predate this feature.

Files touched:

- `nomarr/persistence/database/vectors_track_aql.py`
- `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py`

Out of scope: frontend UI, API endpoints, playlist wiring (Part B).

## Phases

### Phase 1: Genre enrichment in drain_hot_to_cold AQL

- [x] In `ml_vector_maintenance_comp.py`, replace the UPSERT AQL inside `drain_hot_to_cold` with a version that first collects genres via a subquery (`FOR edge IN song_has_tags FILTER edge._from == doc.file_id FOR tag IN tags FILTER tag._id == edge._to AND tag.rel == "genre" RETURN tag.value`) and stores the result as `genres` in both INSERT and UPDATE branches of the convergent UPSERT
    **Note:** Added LET genres subquery before UPSERT in the f-string AQL. Both INSERT and UPDATE branches use MERGE(doc, {genres: genres}). Collection names song_has_tags and tags are fixed identifiers embedded directly (not bind vars, consistent with existing hot_name/cold_name pattern). The subquery joins edge._from == doc.file_id then filters tag.rel == "genre".
- [x] Verify the updated function is fully type-annotated and the docstring mentions the new `genres` field populated from tag joins
    **Note:** Signature (db: DatabaseLike, backbone_id: str, library_key: str) -> int unchanged. Docstring updated with a paragraph describing the genres field: "Each drained document is enriched with a genres field (list[str]) populated by joining song_has_tags edges and tags documents where tag.rel == 'genre' for the document's file_id."
- [x] Run `lint_project_backend(path="nomarr/components/ml/vectors")` — zero errors required
    **Result:** lint_project_backend(path="nomarr/components/ml/vectors") reported total_errors=0, clean=true, files_checked=1.

### Phase 2: storedValues on build_cold_vector_index

- [x] In `ml_vector_maintenance_comp.py`, update `build_cold_vector_index` to add `"storedValues": [{"fields": ["genres"]}]` as a sibling key to `"params"` in the dict passed to `cold_coll.add_index` (not nested inside `params`)
- [x] Confirm by re-reading the modified `add_index` call that its shape is `{"type": "vector", "fields": [...], "params": {...}, "storedValues": [...]}`
- [x] Run `lint_project_backend(path="nomarr/components/ml/vectors")` — zero errors required

### Phase 3: backfill_genres function in maintenance comp

- [x] Add `backfill_genres(db: DatabaseLike, backbone_id: str, library_key: str) -> int` to `ml_vector_maintenance_comp.py`; verify cold collection exists (raise `ValueError` if not); execute an AQL UPDATE joining each cold doc's `file_id` to `song_has_tags` + `tags` (where `tag.rel == "genre"`) and write the genre list into `doc.genres`; return the count of updated documents
- [x] Add a docstring describing args, return value, and raises; include that this is a one-time backfill for cold docs that predate genre enrichment
- [x] Run `lint_project_backend(path="nomarr/components/ml/vectors")` — zero errors required

### Phase 4: search_similar_by_genre on VectorsTrackColdOperations

- [x] Add `search_similar_by_genre(self, vector: list[float], genre: str, limit: int, nprobe: int = 20) -> list[dict[str, Any]]` in the Search section of `VectorsTrackColdOperations` in `vectors_track_aql.py`; AQL must call `APPROX_NEAR_COSINE(doc.vector_n, @query_vector, {nProbe: {nprobe}})`, add `FILTER @genre IN doc.genres` before the SORT, bind `query_vector`, `limit`, and `genre` as bind vars, and return `MERGE(doc, {score: score})`
- [x] Add a docstring that matches the style of `search_similar`, noting the `genre` filter and the requirement that the vector index must have `storedValues` for `genres`
- [x] Run `lint_project_backend(path="nomarr/persistence")` — zero errors required

## Completion Criteria

- `drain_hot_to_cold` AQL includes a genre subquery; newly drained docs carry `genres: list[str]`
- `build_cold_vector_index` index body includes `"storedValues": [{"fields": ["genres"]}]` at the top level alongside `"params"`
- `backfill_genres(db, backbone_id, library_key)` exists in `ml_vector_maintenance_comp.py`, updates cold docs' `genres` field via AQL join, and returns the updated doc count
- `VectorsTrackColdOperations.search_similar_by_genre` exists in `vectors_track_aql.py` with correct AQL using `FILTER @genre IN doc.genres`
- `lint_project_backend` passes with zero errors on both changed files after all phases complete

## References

- Design doc: `plans/dev/genre-vector-index-parts/README.md`
- Contracts ledger: see task request (genre vector index contracts)
- Prerequisite: none (Part A is the root of the dependency graph)
- Part B depends on this plan: `TASK-genre-vector-index-B-playlist-builder.md` (not yet created)
