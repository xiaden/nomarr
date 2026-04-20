# Task: Personal Playlist DTO Formalization

## Problem Statement

The personal playlist pipeline (`generate_playlists_wf` → `playlist_builder_comp`) passes raw positional args with inconsistent signatures across 5 builder functions. This caused architectural drift: `build_familiar_playlist` evolved into a playcount-only ranker instead of using the same vector-based approach as the other 4 builders. There is no shared contract between the workflow and its component functions.

The fix: introduce `NavidromePersonalPlaylistContext` (input) and `NavidromePersonalPlaylistEntry` (output) DTOs. Every builder becomes `(db, ctx) -> list[entry]`. The workflow constructs the context once, passes it uniformly. The V1 interface handles nd_id resolution (external concern) — components only work with `library_files/_id`.

This also retires the existing `PlaylistResult` TypedDict and `TrackPlayData` import from the component layer, and removes `PlaylistConfig` (replaced by the new context DTO + service-level config that stays in the service).

## Phases

### Phase 1: Define new DTOs in navidrome_dto.py

- [x] Add `NavidromePersonalPlaylistContext` TypedDict with fields: `backbone_id: str`, `library_key: str`, `centroid: list[float]`, `max_songs: int`, `played_file_ids: list[str]`
    **Notes:** Added `NavidromePersonalPlaylistContext(TypedDict)` after `PlaylistResult` in `navidrome_dto.py` with fields: `backbone_id`, `library_key`, `centroid`, `max_songs`, `played_file_ids`. Lint clean.
- [x] Add `NavidromePersonalPlaylistEntry` TypedDict with fields: `playlist_type: str`, `playlist_name: str`, `file_ids: list[str]`
    **Notes:** Added `NavidromePersonalPlaylistEntry(TypedDict)` after `NavidromePersonalPlaylistContext` in `navidrome_dto.py` with fields: `playlist_type`, `playlist_name`, `file_ids`. Lint clean.
- [x] Export both from `nomarr/helpers/dto/__init__.py`
    **Notes:** Added `NavidromePersonalPlaylistContext` and `NavidromePersonalPlaylistEntry` to both the import block (lines 60-61) and `__all__` (lines 100-101) in `dto/__init__.py`. Lint clean.

### Phase 2: Rewrite component builders to use new DTOs

- [x] Rewrite all 5 functions in `playlist_builder_comp.py` to signature `(db: Database, ctx: NavidromePersonalPlaylistContext) -> list[NavidromePersonalPlaylistEntry]` — remove nd_id resolution, return `file_ids` instead of `track_nd_ids`, hardcode `min_songs` as component constant for genre builder
    **Notes:** Rewrote all 5 builders to `(db, ctx: NavidromePersonalPlaylistContext) -> list[NavidromePersonalPlaylistEntry]`. Removed all `bulk_resolve_files_to_nd` calls — builders now return `file_ids` (library_files/_id). Removed `TrackPlayData` and `PlaylistResult` imports. Hardcoded `_GENRE_MIN_SONGS = 5` as module constant. Lint clean.
- [x] Fix `build_familiar_playlist` to use centroid + ANN search like the other builders instead of playcount ranking
    **Notes:** Already done in P2-S1. `build_familiar_playlist` now uses `cold_ops.search_similar(ctx["centroid"], ...)` with over-fetch (5x), then filters to `played` set. No playcount ranking, no `TrackPlayData`, no `plays` param. Same ANN pattern as other builders.
- [x] Update exports in `nomarr/components/navidrome/__init__.py` if signatures changed
    **Notes:** No changes needed. Function names are unchanged (only signatures changed); `__init__.py` exports by name. Lint clean.

### Phase 3: Update workflow to construct context and use new result type

- [x] Rewrite `generate_playlists_wf.py` to construct `NavidromePersonalPlaylistContext` from taste profile + play history, pass uniformly to all builders, return `list[NavidromePersonalPlaylistEntry]`
    **Notes:** Rewrote workflow to construct `NavidromePersonalPlaylistContext` and pass uniformly to all builders via `_BUILDERS` dispatch dict. Workflow signature now takes keyword-only params instead of `PlaylistConfig`. Returns `list[NavidromePersonalPlaylistEntry]`. Uses `len(p["file_ids"])` for min_songs filter. Lint clean.
- [x] Remove `PlaylistConfig` usage — the workflow receives the individual params it needs from the service, builds the context DTO itself
    **Notes:** Already done in P3-S1. `PlaylistConfig` import removed from workflow. Workflow now takes individual keyword params (`half_life_days`, `top_n`, `max_songs`, `min_play_count`, `min_songs`, `enabled_types`) and constructs `NavidromePersonalPlaylistContext` itself.

### Phase 4: Update service and interface layers

- [x] Update `NavidromeService.generate_playlists` return type to `list[NavidromePersonalPlaylistEntry]`, adjust how it passes config to the workflow
    **Notes:** Return type changed to `list[NavidromePersonalPlaylistEntry]`. Removed `PlaylistConfig` dict construction — now passes individual keyword args directly to workflow. Added `resolve_files_to_nd` helper for interface to use. Lint clean.
- [x] Update V1 interface `navidrome_generate_playlists` endpoint to do `bulk_resolve_files_to_nd` on the `file_ids` from results, then build the `PlaylistResultResponse` with `track_nd_ids` for the external API
    **Notes:** Interface now collects all unique file_ids from results, calls `svc.resolve_files_to_nd(all_file_ids)` to get nd_map, then builds `PlaylistResultResponse` with resolved `track_nd_ids` and counts. External API contract preserved. Lint clean.

### Phase 5: Clean up old DTOs and exports

- [x] Remove `PlaylistResult` TypedDict from `navidrome_dto.py` if no other consumers remain
    **Notes:** Removed `PlaylistResult` TypedDict from `navidrome_dto.py`. No consumers remained after service and workflow rewrites.
- [x] Remove `PlaylistResult` from `nomarr/helpers/dto/__init__.py` exports
    **Notes:** Removed `PlaylistResult` from import and `__all__` in `dto/__init__.py`. Lint clean.
- [x] Update or remove `PlaylistConfig` if fully replaced by workflow params + context DTO
    **Notes:** Removed `PlaylistConfig` from `navidrome_dto.py` (class deleted alongside PlaylistResult), and from both import and `__all__` in `dto/__init__.py`. All 4 removals verified. Lint clean.

### Phase 6: Validation

- [x] Run `lint-imports` — zero contract violations from this change
    **Notes:** No new import contract violations. Pre-existing `ml_vector_idle_promotion_comp` → `workflows` violation is unrelated to this change.
- [x] Run `ruff check` on all touched paths — zero errors
    **Notes:** All 6 touched files pass ruff check + mypy (via lint_project_backend) with zero errors.
- [x] Run `mypy` on all touched paths — zero errors
    **Notes:** mypy reports "Success: no issues found in 6 source files" across all touched files. All validation complete.

## Completion Criteria

- Every builder function has signature `(db: Database, ctx: NavidromePersonalPlaylistContext) -> list[NavidromePersonalPlaylistEntry]`
- No `track_nd_ids` or nd_id resolution in any component or workflow — only in the interface layer
- `build_familiar_playlist` uses centroid + ANN search, not playcount ranking
- `PlaylistResult` TypedDict removed (replaced by `NavidromePersonalPlaylistEntry`)
- `min_songs` for genre is a component constant, not a config parameter
- All linters pass with zero errors

## References

- Prior plan: `plans/completed/TASK-generate-playlists-wf-architecture-fix.md` (extracted domain logic from workflow to component)
- Design discussion: `PlaylistConfig` fields `half_life_days`, `top_n`, `min_play_count`, `overwrite_playlists`, `enabled_types` are service/workflow concerns, not component concerns — they stay in the service layer
