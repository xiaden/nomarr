# Task: Personal Playlist E — Playlist Generation Pipeline

## Problem Statement

The playlist generation pipeline is the core use case: given a user's play history (graph model from Plan A), compute a taste profile (Plan D), run ANN searches with type-specific filters, and return track lists as Navidrome IDs. Five playlist types — Familiar, Discovery, Hidden Gems, Genre, Universal — each use the same weighted centroid but different search strategies and filter logic. This creates the workflow, service method, and API endpoint consumed by the Navidrome plugin (Plan G).

**Prerequisites:** Plan A (graph collections + persistence), Plan D (taste profile computation + genre indexes)

## Phases

### Phase 1: DTOs + Workflow

- [x] Add `PlaylistConfig` TypedDict to `nomarr/helpers/dto/navidrome_dto.py` with fields: `half_life_days: float`, `top_n: int`, `max_songs: int`, `min_songs: int`, `min_play_count: int`, `enabled_types: list[str]`, `overwrite_playlists: bool`. Add `PlaylistResult` TypedDict with fields: `playlist_type: str`, `name: str`, `track_nd_ids: list[str]`, `track_count: int`. Export both from `helpers/dto/__init__.py`.
- [x] Create `nomarr/workflows/navidrome/generate_playlists_wf.py` with public function `generate_playlists(db: Database, user_id: str, backbone_id: str, library_key: str, config: PlaylistConfig) -> list[PlaylistResult]`. Structure: (1) call `compute_taste_profile` from Plan D, return empty if None; (2) get user's played file_ids + nd_ids via `db.navidrome_playcounts.get_top_plays`; (3) filter out tracks with `playcount < config["min_play_count"]`; (4) dispatch each enabled type to its sub-pipeline; (5) filter out playlists below `min_songs`.
- [x] Implement Familiar sub-pipeline: no ANN search. Rank `played_file_ids` by playcount descending, take top `max_songs`. Resolve to nd_ids via `db.navidrome_tracks.bulk_resolve_files_to_nd`. Design doc confirms Familiar uses "None (direct query)" for ANN index.
- [x] Implement Discovery + Universal sub-pipelines: ANN search on global cold collection via `db.get_vectors_track_cold(backbone_id, library_key).search_similar(centroid, limit)`. Discovery excludes played file_ids from results. Universal takes diversified sampling (no exclusion, spread across result set). Both resolve file_ids to nd_ids via `bulk_resolve_files_to_nd`.
- [x] Implement Hidden Gems sub-pipeline: (a) collect known artist tag values via AQL traversal of `song_has_tags` edges for user's played file_ids where `rel == "artist"` (returns `DISTINCT tag.value`); (b) ANN search on global cold collection; (c) for each candidate, batch-query artist tags via AQL; (d) exclude candidates whose artists overlap with known set. Resolve to nd_ids. AQL queries use `db.db.aql.execute()` following existing workflow pattern in `find_similar_tracks_wf.py`.
- [x] Implement Genre sub-pipeline: for each genre the user has affinity for (genres from their played tracks via `song_has_tags` traversal), construct genre collection name `vectors_track_cold__{backbone}__{lib}__genre__{sanitized}`, instantiate `VectorsTrackColdOperations(db.db, backbone_id, library_key)` with genre-suffixed naming (details at implementation time — may need a helper on Database or direct construction). ANN search with centroid, exclude played tracks, resolve to nd_ids. One `PlaylistResult` per genre (name: "Your {Genre} Mix"). Skip genres whose collection doesn't exist (try/except) or whose results are below `min_songs`.
- [x] Verify `lint_project_backend` passes on `nomarr/workflows/navidrome` and `nomarr/helpers/dto` with zero errors.

### Phase 2: Service + Interface

- [x] Add `generate_playlists(self, user_id: str) -> list[PlaylistResult]` method to `NavidromeService` in `nomarr/services/domain/navidrome_svc.py`. Thin method: reads `backbone_id` and `library_key` from `ConfigService` settings, builds `PlaylistConfig` from config values, calls `generate_playlists_wf.generate_playlists(db=self._db, ...)`. Returns the result directly.
- [x] Add Pydantic models to `nomarr/interfaces/api/v1/navidrome_v1_if.py`: `GeneratePlaylistsRequest` with `user_id: str` + optional overrides (`max_songs: int | None = None`, `enabled_types: list[str] | None = None`); `PlaylistResultResponse` with `playlist_type: str`, `name: str`, `track_nd_ids: list[str]`, `track_count: int`; `GeneratePlaylistsResponse` with `playlists: list[PlaylistResultResponse]`.
- [x] Add `POST /api/v1/navidrome/generate-playlists` endpoint with `dependencies=[Depends(verify_key)]`. Call `svc.generate_playlists(user_id=body.user_id)` via `asyncio.to_thread`. Map `list[PlaylistResult]` to `GeneratePlaylistsResponse`. Return 200 with playlist data.
- [x] Verify `lint_project_backend` passes on all modified layers (`nomarr/interfaces`, `nomarr/services`, `nomarr/workflows`, `nomarr/helpers`) with zero errors.

## Completion Criteria

- `POST /api/v1/navidrome/generate-playlists` accepts `user_id`, returns playlist results for all enabled types
- Five playlist types implemented with correct filter logic per design doc taxonomy
- Hidden Gems artist exclusion uses tag traversal AQL, not denormalized data
- Genre playlists query per-genre cold collections created by Plan D
- All playlist track IDs are Navidrome IDs (resolved via `bulk_resolve_files_to_nd`)
- Familiar uses playcount ranking only (no ANN search — design doc: "None (direct query)")
- `lint_project_backend()` — zero errors
