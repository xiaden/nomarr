# Task: Personal Playlist — Graph Collections + Migration

## Problem Statement

Nomarr's Navidrome integration currently uses a flat `navidrome_song_map` document collection that stores simple nd_id ↔ file_id mappings. The personal playlist feature requires a graph-native data model to represent tracks, users, play counts, and file resolution paths. This plan creates four new collections (`navidrome_tracks`, `has_nd_id`, `navidrome_playcounts`, `has_plays`), writes persistence Operations classes for CRUD + graph traversal, writes a V019 migration to convert existing data, and updates bootstrap for fresh installs.

**Key data model (from contracts ledger):**
- `navidrome_tracks` — vertex, `_key = nd_id`, no timestamps
- `has_nd_id` — edge, `_from: navidrome_tracks/{nd_id}` → `_to: library_files/{file_key}`
- `navidrome_playcounts` — vertex, `_key = user_id`, one document per Navidrome user
- `has_plays` — edge, `_from: navidrome_playcounts/{user_id}` → `_to: navidrome_tracks/{nd_id}`, carries `playcount: int` and `last_played_ms: int`

**Graph traversal path** (top plays → file resolution):
`navidrome_playcounts/{user}` →[has_plays]→ `navidrome_tracks/{nd_id}` →[has_nd_id]→ `library_files/{file_key}`

**Prerequisite:** None (foundation plan)

## Phases

### Phase 1: Persistence Layer
- [x] Create `TrackPlayData` TypedDict in `nomarr/helpers/dto/navidrome_dto.py` with fields `nd_id: str`, `file_id: str | None`, `playcount: int`, `last_played_ms: int | None` — returned by top-plays graph traversal; `file_id` is None when `has_nd_id` edge is absent
- [x] Create `nomarr/persistence/database/navidrome_tracks_aql.py` with `NavidromeTracksOperations(db: DatabaseLike)` managing `navidrome_tracks` vertices + `has_nd_id` edges. Methods: `upsert_track(nd_id)`, `bulk_upsert_tracks(nd_ids)`, `ensure_file_link(nd_id, file_id)`, `bulk_ensure_file_links(mappings)`, `resolve_nd_to_file(nd_id) -> str | None`, `resolve_file_to_nd(file_id) -> str | None`, `bulk_resolve_nd_to_files(nd_ids) -> dict[str, str]`. Follow `NavidromeSongMapOperations` pattern.
- [x] Create `nomarr/persistence/database/navidrome_playcounts_aql.py` with `NavidromePlaycountsOperations(db: DatabaseLike)` managing `navidrome_playcounts` vertices + `has_plays` edges. Methods: `ensure_user(user_id)`, `upsert_play_edge(user_id, nd_id, playcount, last_played_ms)` (UPSERT on _from+_to), `increment_play(user_id, nd_id, timestamp_ms)` (atomic increment + update last_played_ms), `get_top_plays(user_id, top_n) -> list[TrackPlayData]` (2-hop traversal sorted by playcount DESC), `bulk_upsert_play_edges(plays)`.
- [x] Register new Operations in `nomarr/persistence/db.py` — add `self.navidrome_tracks = NavidromeTracksOperations(self.db)` and `self.navidrome_playcounts = NavidromePlaycountsOperations(self.db)` in `Database.__init__`. Keep existing `navidrome_song_map` registration (deprecated, removed by Part C).
- [x] Update bootstrap in `nomarr/components/platform/arango_bootstrap_comp.py` — add `navidrome_tracks`, `navidrome_playcounts` to document collections; add `has_nd_id`, `has_plays` to edge collections; add indexes (unique `(_from,_to)` on both edge collections, persistent `(_to)` on `has_nd_id`, persistent `(_from)` on `has_plays`); create named graph `navidrome_graph` with edge definitions.
- [x] Verify `lint_project_backend` passes on `nomarr/persistence`, `nomarr/helpers/dto`, and `nomarr/components/platform` with zero errors.

### Phase 2: Migration + Deprecation
- [x] Create `nomarr/migrations/V019_navidrome_graph_model.py` with `SCHEMA_VERSION_BEFORE=18`, `SCHEMA_VERSION_AFTER=19`. The `upgrade(db)` function creates all 4 collections idempotently, creates indexes, migrates `navidrome_song_map` docs into `navidrome_tracks` vertices + `has_nd_id` edges (file_id is already a full doc ID), leaves `navidrome_playcounts`/`has_plays` empty, and drops `navidrome_song_map`. Follow V018 pattern for idempotency and logging.
- [x] Add deprecation notice to `NavidromeSongMapOperations` class docstring in `nomarr/persistence/database/navidrome_song_map_aql.py` noting the underlying collection is dropped by V019 and the class is retained until Part C removes callers.
- [x] Verify `lint_project_backend` (full workspace) passes with zero errors.

## Completion Criteria
- All four collections (`navidrome_tracks`, `has_nd_id`, `navidrome_playcounts`, `has_plays`) have Operations classes with full method signatures
- `Database` class registers both new Operations classes
- Bootstrap creates collections and indexes on fresh install
- V019 migration converts existing `navidrome_song_map` data and drops the old collection
- `TrackPlayData` TypedDict available for downstream graph traversal queries
- `lint_project_backend` passes with zero errors across all modified layers
- Old `NavidromeSongMapOperations` deprecated but still functional (for Part C transition)

## References
- Design doc: `plans/dev/design-personal-playlist.md` (graph architecture section)
- Contracts ledger: `plans/dev/personal-playlist-parts/CONTRACTS.md`
- Existing pattern: `nomarr/persistence/database/navidrome_song_map_aql.py`
- Migration pattern: `nomarr/migrations/V018_split_vectors_per_library.py`
