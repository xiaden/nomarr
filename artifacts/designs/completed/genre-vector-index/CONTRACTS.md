# Genre Vector Index — Contracts Ledger

**Design doc:** `plans/dev/genre-vector-index-parts/README.md`
**Last updated:** 2026-03-22 (Plan A + Plan B implemented + reviewed — FEATURE COMPLETE)

---

## Architectural Rules

- Workflows take `db: Database`, never services
- Persistence uses `DatabaseLike` from `nomarr.persistence.arango_client`
- No upward imports: persistence → components → workflows → services → interfaces
- Helpers never import `nomarr.*` modules
- `now_ms().value` for int epoch millis
- ArangoDB `_id`/`_key` never renamed
- `build_cold_vector_index` is in `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py`
- `drain_hot_to_cold` is in `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py`
- `VectorsTrackColdOperations` is in `nomarr/persistence/database/vectors_track_aql.py`
- Cold collection naming: `vectors_track_cold__{backbone_id}__{library_key}` (no suffix needed)
- `song_has_tags` edges: `_from = library_files/_id`, `_to = tags/_id`; tags have `{name, value}`
- `db.tags.get_distinct_tag_values_for_files(file_ids, "genre")` → `list[str]` (genre values)
- Genre playlists builder signature pattern: `(db: Database, ctx: NavidromePersonalPlaylistContext) -> list[NavidromePersonalPlaylistEntry]`
- `NavidromePersonalPlaylistContext` is in `nomarr/helpers/dto/navidrome_dto.py`; fields include `backbone_id`, `library_key`, `centroid`, `max_songs`, `played_file_ids`
- `_BUILDERS` dict in `generate_playlists_wf.py` maps playlist type string → builder function

---

## Collections & Methods

### vectors_track_cold__{backbone}__{lib} (Plan A)

**Document schema (cold doc fields):**
`{_key, file_id, model_suite_hash, embed_dim, vector, vector_n, num_segments, created_at, genres}`

**`genres` field:** `list[str]` — genre tag values from `song_has_tags` + `tags` join (e.g. `["rock", "electronic"]`); populated at drain time and via `backfill_genres`

**Operations class:** `VectorsTrackColdOperations` in `nomarr/persistence/database/vectors_track_aql.py`

 | Method | Signature |
 | --- | --- |
 | search_similar | `(self, vector: list[float], limit: int, nprobe: int = 20) -> list[dict[str, Any]]` |
 | search_similar_by_genre | `(self, vector: list[float], genre: str, limit: int, nprobe: int = 20) -> list[dict[str, Any]]` |

### ml_vector_maintenance_comp — new functions (Plan A)

 | Function | Signature |
 | --- | --- |
 | drain_hot_to_cold | `(db: DatabaseLike, backbone_id: str, library_key: str) -> int` — now includes `genres` field via AQL join in UPSERT; row count via `COLLECT WITH COUNT INTO n RETURN n` (not `RETURN NEW`; efficient for large libraries) |
 | build_cold_vector_index | `(db: DatabaseLike, backbone_id: str, library_key: str, embed_dim: int, nlists: int) -> None` — now includes `storedValues: [{"fields": ["genres"]}]` alongside `params` |
 | backfill_genres | `(db: DatabaseLike, backbone_id: str, library_key: str) -> int` — AQL UPDATE on cold collection, joins file_id → song_has_tags → tags (rel=="genre"), populates `genres`; returns updated count |

---

## API Contracts

*(No new endpoints in this feature)*

---

## DTOs Created

*(None expected — existing DTOs sufficient)*

---

## Functions Added: playlist_builder_comp (Plan B)

 | Function | Signature |
 | --- | --- |
 | build_genre_playlists | `(db: Database, ctx: NavidromePersonalPlaylistContext) -> list[NavidromePersonalPlaylistEntry]` |

**`playlist_type` detail:** `f"genre_{genre.lower()}"` (unique per genre, e.g. `"genre_rock"`) — not a shared `"genre"` string. Enables per-genre deduplication when Navidrome updates existing playlists.

**`_GENRE_MIN_SONGS`:** `100` — genres with fewer than 100 ANN results are skipped.

**Wired in:**

- `_BUILDERS["genre"]` in `generate_playlists_wf.py`
- Exported from `nomarr/components/navidrome/__init__.py`

---

## Decisions Made

 | Decision | Rationale | Plan |
 | --- | --- | --- |
 | Genre stored on cold docs as `genres: list[str]` array | Songs have multiple genres; ANN index `storedValues` supports array containment filter | init |
 | Genre populated at drain time via AQL join | Hot docs have the file_id; join to song_has_tags+tags at drain is atomic and avoids a separate backfill pipeline | init |
 | Backfill function needed for existing cold docs | Docs already in cold predate this feature; must add genres retroactively before genre playlists can work | init |
 | No sub-collection suffix on VectorsTrackColdOperations | Feature uses single collection with index filter; `collection_suffix` constructor param stays but genre routing doesn't use it | init |
