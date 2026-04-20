# Task: Navidrome Integration A — Similarity API Infrastructure

## Problem Statement

Nomarr has ML-derived vector embeddings for audio tracks stored in ArangoDB, powering a
visual similarity search feature in the Nomarr UI. Navidrome v0.60.0+ supports WASM
plugins that implement `SimilarSongsByTrackProvider`, which powers the "Instant Mix"
feature — when a user clicks Instant Mix on a track, Navidrome calls the plugin with
the track's ID, name, artist, and MBID, and the plugin returns similar songs.

This plan builds the Nomarr-side API infrastructure that the WASM plugin (Plan B) will
call. Specifically:

1. A Subsonic API client to communicate with Navidrome's library inventory
2. A persisted bidirectional ID mapping between Navidrome song IDs and Nomarr file IDs
3. An API endpoint (`POST /api/v1/navidrome/similar-tracks`) that accepts a Navidrome
   song ID and returns similar tracks identified by their Navidrome IDs, powered by
   vector ANN search

Currently, `NavidromeConfig` has only a `namespace: str` field (hardcoded constant),
`config.yaml` has zero navidrome API fields, and `ConfigService` has no navidrome
awareness. All of this must be built.

### Design Decisions

**Sync HTTP client.** The existing services, workflows, and components are synchronous.
Using `httpx.Client` (sync) avoids event-loop bridging complexity. FastAPI endpoints
already wrap sync service calls with `asyncio.to_thread`, so this fits naturally.

**Path-to-ID resolution via album walk.** The Subsonic `search3` endpoint searches by
artist/title/album text — it cannot look up by file path. Instead, we paginate through
all albums via `getAlbumList2` (ID3-based, `type=alphabeticalByName`, `size=500`,
incrementing `offset`) and call `getAlbum(id)` for each to collect every song's `path`
and `id` attributes. The `path` attribute is part of the Subsonic XSD `child` element
(confirmed in official API examples, e.g. `path="ACDC/High voltage/ACDC - The Jack.mp3"`).
These Navidrome-relative paths are remapped to Nomarr's `normalized_path` format using
configurable prefix mappings, then matched via `db.library_files.get_files_by_paths_bulk()`.

**Persisted ArangoDB collection (`navidrome_song_map`).** The album walk is expensive
— O(albums/500 + albums) Subsonic API calls. For a 5,000-album library that's ~5,010
HTTP requests. This must survive process restarts, not be rebuilt from scratch on every
launch. A new `navidrome_song_map` collection stores
`{_key: navidrome_id, file_id: "library_files/...", nd_path: "..."}` with a unique
index on `file_id` for reverse lookups. Created by migration V015. The sync workflow
upserts in batches, so re-syncs are incremental (unchanged mappings are no-ops).
A full re-sync is only needed when the path prefix map changes or the Navidrome library
is replaced.

**Persistence module for the map.** A new `navidrome_song_map_aql.py` persistence
module exposes `lookup_by_nd_id(nd_id) -> file_id | None`,
`lookup_by_file_id(file_id) -> nd_id | None`, and
`bulk_lookup_by_file_ids(file_ids) -> dict[str, str]` for the similarity workflow.
Accessed via `db.navidrome_song_map` like other persistence modules.

**API key auth for the plugin endpoint.** The WASM plugin calls Nomarr via HTTP from
within Navidrome's Extism sandbox. The endpoint lives at `/api/v1/navidrome/` and uses
existing API key auth — no session tokens available in plugin context.

**SongRef ID strategy.** The WASM plugin will return `SongRef` with the `ID` field
populated with Navidrome mediafile IDs. This gives Navidrome direct ID resolution
without fuzzy title/artist matching. AudioMuse-AI uses this same reliable pattern.

**Workflow-level similarity logic.** The similarity workflow
(`find_similar_tracks_wf`) uses `VectorsTrackColdOperations` directly (persistence
layer) for vector retrieval and ANN search, `db.navidrome_song_map` for ID resolution,
and `db.library_files` for metadata enrichment. The service (`NavidromeService`) owns
the lazy client construction and the public `get_similar_tracks()` method.

**Sync trigger.** The song map sync is exposed as `POST /api/web/navidrome/sync-songs`
for manual trigger from the frontend, and can also be called programmatically after
library scans complete.

## Phases

### Phase 1: Config & Subsonic Client Infrastructure

- [x] Extend `NavidromeConfig` dataclass in `navidrome_svc.py` to add `api_url: str | None`, `api_user: str | None`, `api_password: str | None` (all default `None`), and `path_prefix_map: list[tuple[str, str]]` for mount prefix remapping (Navidrome-relative path prefix → Nomarr normalized_path prefix)
    **Notes:** Extended NavidromeConfig in navidrome_svc.py with api_url, api_user, api_password (all str | None = None) and path_prefix_map (list[tuple[str, str]] with field(default_factory=list)). Added field import from dataclasses. lint_project_backend — 0 errors.
- [x] Add `navidrome_api_url`, `navidrome_api_user`, `navidrome_api_password`, `navidrome_path_prefix_map` to `ConfigService._default_config()` and `_ALLOWED_CONFIG_KEYS`, wire into `NavidromeConfig` construction in `Application.start()` in `app.py`, add fields to `build_resources/config/config.yaml` with a new Navidrome API section, and ensure `config_types.py` includes them
    **Notes:** Added navidrome_api_url, navidrome_api_user, navidrome_api_password, navidrome_path_prefix_map to_ALLOWED_CONFIG_KEYS (lines 79-83) and _default_config() (lines 316-320) in config_svc.py. Wired into NavidromeConfig construction in app.py (lines 270-276) with_parse_path_prefix_map() static method (lines 433-452). Added Navidrome API section to config.yaml (lines 74-84). config_types.py is already dict-flexible, no changes needed. lint_project_backend — 0 errors on both config_svc.py and app.py.
- [x] Create `nomarr/components/navidrome/subsonic_client_comp.py` — synchronous HTTP client using `httpx.Client` with `f=json` for JSON responses. Constructor: `SubsonicClient(base_url: str, user: str, password: str)`. Auth: Subsonic token scheme — each request sends `u=user`, `t=md5(password+salt)`, `s=salt` (random 12-char hex), `v=1.16.1`, `c=nomarr`. Methods: `ping() -> bool`, `get_album_list2(type: str, size: int, offset: int) -> list[dict]`, `get_album(album_id: str) -> dict`, `get_playlists() -> list[dict]`, `create_or_replace_playlist(name: str, song_ids: list[str], playlist_id: str | None = None) -> dict`, `start_scan(full_scan: bool = False) -> dict`. All methods raise `SubsonicApiError` (new helper exception) on non-ok Subsonic responses
    **Notes:** Created nomarr/components/navidrome/subsonic_client_comp.py (204 lines) with SubsonicClient class. Added SubsonicApiError(code, message) to nomarr/helpers/exceptions.py. Used httpx.QueryParams for type-safe param construction. The type parameter in get_album_list2 uses noqa: A002 to shadow the builtin. lint_project_backend — 0 errors on both files.
- [x] Write unit tests in `tests/unit/components/navidrome/test_subsonic_client_comp.py` covering auth token generation (md5 of password+salt), URL construction (all common params present), JSON response parsing, repeated `songId` parameter encoding for `createPlaylist`, and Subsonic error code handling; run `lint_project_backend`
    **Notes:** Created tests/unit/components/navidrome/test_subsonic_client_comp.py (296 lines, 19 tests across 5 test classes). All 19 tests pass. lint_project_backend — 0 errors.

### Phase 2: Persisted Song Map & Sync

- [x] Create migration `nomarr/migrations/V015_add_navidrome_song_map.py` — creates `navidrome_song_map` vertex collection with persistent index on `file_id` (unique) for reverse lookups. `_key` is the Navidrome mediafile ID. Document schema: `{_key: str, file_id: str, nd_path: str, synced_at: int}` where `synced_at` is `now_ms()` timestamp. Register in `nomarr/migrations/__init__.py`
    **Notes:** Created nomarr/migrations/V015_add_navidrome_song_map.py (79 lines). Creates navidrome_song_map vertex collection with unique persistent index on file_id._key = Navidrome mediafile ID. Schema: {_key, file_id, nd_path, synced_at}. Idempotent (contextlib.suppress + http_code 409 handling). Migrations are auto-discovered by migration_runner_comp.py scanning V*.py files, no **init**.py registration needed. lint_project_backend -- 0 errors.
- [x] Create `nomarr/persistence/database/navidrome_song_map_aql.py` with class `NavidromeSongMapOperations` exposing: `upsert_batch(mappings: list[dict]) -> int` (AQL UPSERT batch with `_key`, `file_id`, `nd_path`, `synced_at`), `lookup_by_nd_id(nd_id: str) -> str | None` (returns `file_id`), `lookup_by_file_id(file_id: str) -> str | None` (returns Navidrome `_key`), `bulk_lookup_by_file_ids(file_ids: list[str]) -> dict[str, str]` (maps `file_id -> nd_id`), `count() -> int`, `truncate() -> None`. Wire into `Database` class so it's accessible as `db.navidrome_song_map`
    **Notes:** Created nomarr/persistence/database/navidrome_song_map_aql.py (164 lines) with NavidromeSongMapOperations class. Methods: upsert_batch (AQL UPSERT with now_ms timestamp), lookup_by_nd_id, lookup_by_file_id, bulk_lookup_by_file_ids, count, truncate. Wired into Database class in db.py as self.navidrome_song_map. lint_project_backend -- 0 errors on both files.
- [x] Create `nomarr/workflows/navidrome/sync_song_map_wf.py` — workflow `sync_song_map(client: SubsonicClient, path_prefix_map: list[tuple[str, str]], db: Database) -> SyncResult` that: (1) paginates `client.get_album_list2('alphabeticalByName', 500, offset)` until empty, (2) calls `client.get_album(id)` per album to collect `(song_id, song_path)` pairs, (3) applies prefix remapping to convert Navidrome paths to Nomarr normalized_paths, (4) batch-resolves via `db.library_files.get_files_by_paths_bulk()` to get Nomarr file_ids, (5) upserts resolved mappings via `db.navidrome_song_map.upsert_batch()` in chunks, (6) returns `SyncResult` TypedDict with `total_songs`, `resolved`, `unresolved`, `duration_ms`. Logs progress every 100 albums and warns on unresolvable paths
    **Notes:** Created nomarr/workflows/navidrome/sync_song_map_wf.py (147 lines). sync_song_map() paginates getAlbumList2, fetches each album's songs via getAlbum, applies_remap_path prefix mapping, bulk-resolves via db.library_files.get_files_by_paths_bulk(), upserts in 500-doc batches via db.navidrome_song_map.upsert_batch(). Returns SyncResult TypedDict. Logs progress every 100 albums. lint_project_backend -- 0 errors.
- [x] Add `NavidromeService.sync_song_map() -> SyncResult` method that calls `sync_song_map` workflow with the lazy client, raising ValueError if client is not configured
    **Notes:** Added _client lazy attribute,_get_client() method (validates api_url/user/password, constructs SubsonicClient on first call), and sync_song_map() public method that delegates to the sync_song_map workflow. lint_project_backend -- 0 errors.
- [x] Write unit tests for `NavidromeSongMapOperations` (mock ArangoDB cursor responses for lookups and upserts) and `sync_song_map` workflow (mock client and db, verify batched upserts and path remapping); run `lint_project_backend`

### Phase 3: Similarity API Endpoint

- [x] Create `nomarr/workflows/navidrome/find_similar_tracks_wf.py` — workflow `find_similar_tracks(seed_nd_id: str, count: int, backbone_id: str, db: Database) -> list[SimilarTrackResult]` that: (1) resolves `seed_nd_id` to Nomarr file_id via `db.navidrome_song_map.lookup_by_nd_id()`, raising ValueError if unmapped, (2) constructs `VectorsTrackColdOperations(db, backbone_id)` and calls `get_vector(file_id)` for the seed vector, (3) calls `cold_ops.search_similar(vector, count * 2)` for ANN search (over-fetch to compensate for unmapped results), (4) resolves result file_ids to Navidrome IDs via `db.navidrome_song_map.bulk_lookup_by_file_ids()`, (5) enriches mapped results with metadata via `db.library_files.get_files_by_ids_with_tags()`, (6) returns up to `count` results as `list[SimilarTrackResult]` with fields: `nd_id`, `name`, `artist`, `album`, `score`
    **Notes:** Created nomarr/workflows/navidrome/find_similar_tracks_wf.py (146 lines). Pipeline: resolve ND ID via db.navidrome_song_map.lookup_by_nd_id, get vector from cold (+ hot fallback via db.register_vectors_track_backbone), ANN search via cold_ops.search_similar with 2x over-fetch, bulk resolve to ND IDs, enrich via db.library_files.get_files_by_ids_with_tags, return up to count SimilarTrackResult. Excludes seed track from results. lint_project_backend: 0 new errors (5 pre-existing mypy in navidrome_song_map_aql.py cursor typing).
- [x] Add `NavidromeService.get_similar_tracks(nd_song_id: str, count: int, backbone_id: str = 'effnet-discogs') -> list[SimilarTrackResult]` that calls `find_similar_tracks` workflow, raising ValueError if client is not configured
    **Notes:** Added get_similar_tracks(nd_song_id, count, backbone_id='effnet-discogs') to NavidromeService (lines 241-268). Delegates to find_similar_tracks workflow. Added SimilarTrackResult to TYPE_CHECKING imports. No client required -- similarity search only needs db. lint_project_backend -- 0 errors.
- [x] Create `nomarr/interfaces/api/v1/navidrome_v1_if.py` with two endpoints using API key auth (`verify_key`): (a) `POST /api/v1/navidrome/similar-tracks` — request body `SimilarTracksRequest(song_id: str, count: int = 50, backbone_id: str = 'effnet-discogs')`, response `SimilarTracksResponse(songs: list[SongResult])` where `SongResult` has `id`, `name`, `artist`, `album`, `score`; (b) `POST /api/v1/navidrome/sync-songs` — triggers `sync_song_map`, returns `SyncResponse(total_songs, resolved, unresolved, duration_ms)`. Inject `NavidromeService` via `Depends`. Register router in `nomarr/interfaces/api/v1/__init__.py`
    **Notes:** Created nomarr/interfaces/api/v1/navidrome_v1_if.py (115 lines) with POST /similar-tracks and POST /sync-songs endpoints using verify_key auth. Pydantic models: SimilarTracksRequest(song_id, count=50, backbone_id), SongResult(id, name, artist, album, score), SimilarTracksResponse(songs), SyncResponse(total_songs, resolved, unresolved, duration_ms). Registered router in api_app.py line 24 (import) and line 59 (include_router). lint_project_backend -- 0 new errors.
- [x] Add `POST /api/web/navidrome/sync-songs` endpoint to `navidrome_if.py` (web auth) for frontend-triggered sync with progress response
    **Notes:** Added SyncSongsResponse Pydantic model to navidrome_types.py (lines 251-257). Added POST /sync-songs endpoint to navidrome_if.py (lines 137-155) with verify_session auth and asyncio.to_thread wrapping. ValueError → 400, generic Exception → 500 with sanitized message. lint_project_backend -- 0 new errors on both files.
- [x] Write unit tests for `find_similar_tracks` workflow (mock persistence layer, verify seed lookup → vector fetch → ANN search → ID resolution → metadata enrichment flow); run `lint_project_backend`
    **Notes:** Created tests/unit/workflows/navidrome/test_find_similar_tracks_wf.py (233 lines, 11 tests across 3 classes). TestFindSimilarTracksHappyPath (4 tests): full pipeline, seed exclusion, count limit, over-fetch verification. TestFindSimilarTracksErrors (2 tests): unmapped seed ValueError, missing vector ValueError. TestFindSimilarTracksEdgeCases (5 tests): empty ANN, partial mapping, all unmapped, missing metadata defaults, backbone_id forwarding. All 11 tests pass. lint_project_backend -- 0 new errors.

## Completion Criteria

- `NavidromeConfig` carries optional API credentials and path prefix map; `ConfigService` populates them from `config.yaml`; `Application.start()` passes them through
- `SubsonicClient` authenticates with Subsonic token scheme (`md5(password+salt)`), sends `f=json` and all required common params, and is unit tested with mock responses
- Migration V015 creates `navidrome_song_map` collection with unique index on `file_id`
- `sync_song_map` workflow walks Navidrome's album inventory, resolves paths to Nomarr file_ids, and upserts the mapping into `navidrome_song_map` — persisted across restarts
- `POST /api/v1/navidrome/similar-tracks` accepts a Navidrome song ID and returns similar tracks with their Navidrome IDs, via vector ANN search against cold collection with persisted ID resolution
- `POST /api/web/navidrome/sync-songs` and `POST /api/v1/navidrome/sync-songs` trigger a full song map sync
- `NavidromeService` manages lazy client construction and delegates to workflows
- `lint_project_backend` passes with zero errors

## References

- Research doc: `docs/upstream/navidrome_integration.md`
- Existing service: `nomarr/services/domain/navidrome_svc.py`
- Vector search service: `nomarr/services/domain/vector_search_svc.py`
- Vector persistence: `nomarr/persistence/database/vectors_track_aql.py`
- Library files queries: `nomarr/persistence/database/library_files_aql/queries.py` (`get_files_by_paths_bulk`, `get_files_by_ids_with_tags`)
- Config service: `nomarr/services/infrastructure/config_svc.py`
- App composition root: `nomarr/app.py`
- Migration pattern: `nomarr/migrations/V014_add_ml_model_graph.py`
- Existing persistence pattern: `nomarr/persistence/database/vectors_track_aql.py`
- AudioMuse-AI plugin (reference): <https://github.com/NeptuneHub/AudioMuse-AI-NV-plugin>
- Subsonic API spec: <http://www.subsonic.org/pages/api.jsp>
- Part B (WASM plugin): `plans/TASK-navidrome-integration-B-wasm-plugin.md`
- Part C (playlist push): `plans/TASK-navidrome-integration-C-playlist-push.md`
