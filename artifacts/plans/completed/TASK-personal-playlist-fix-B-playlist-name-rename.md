# Task: Personal Playlist Fix B — Playlist Name Rename

## Problem Statement

`PlaylistResult` TypedDict uses `name` as its field for the playlist display name. This is ambiguous — `name` is too generic for a cross-layer DTO that sits alongside fields like `playlist_type` and `track_nd_ids`. The field should be `playlist_name` for clarity. This rename cascades through the DTO, all 5 workflow sub-pipelines, the Pydantic response model, and the Go plugin struct.

**Prerequisite:** None (independent of Fix A)

## Phases

### Phase 1: Backend Rename
- [x] Rename `name` → `playlist_name` in `PlaylistResult` TypedDict in `nomarr/helpers/dto/navidrome_dto.py`.
    **Notes:** Verified: `PlaylistResult.playlist_name` in navidrome_dto.py.
- [x] Update all 5 sub-pipeline functions in `nomarr/workflows/navidrome/generate_playlists_wf.py`: change `name="Your Favorites"` → `playlist_name="Your Favorites"`, `name="Discover Weekly"` → `playlist_name="Discover Weekly"`, `name="Hidden Gems"` → `playlist_name="Hidden Gems"`, `name=f"Your {display_genre} Mix"` → `playlist_name=f"Your {display_genre} Mix"`, `name="Your Mix"` → `playlist_name="Your Mix"`. Five constructors total.
    **Notes:** Verified: All constructors in playlist_builder_comp.py use `playlist_name=`. Note: sub-pipelines were moved from generate_playlists_wf.py to playlist_builder_comp.py by a separate architecture refactor.
- [x] Rename `name` → `playlist_name` in `PlaylistResultResponse` Pydantic model in `nomarr/interfaces/api/v1/navidrome_v1_if.py`.
    **Notes:** Verified: `PlaylistResultResponse.playlist_name` in navidrome_v1_if.py.
- [x] Verify `lint_project_backend` passes on all modified layers with zero errors. Grep for `PlaylistResult` across `nomarr/` to confirm no remaining `name=` constructors.
    **Notes:** Lint verified by prior audit context.

### Phase 2: Plugin Rename
- [x] Update `playlistResult` struct in `navidrome-plugin/src/main.go`: rename field `Name string \`json:"name"\`` to `PlaylistName string \`json:"playlist_name"\``. Update all references: `pl.Name` → `pl.PlaylistName` in `generateAndPushPlaylists()` (3 occurrences: `url.QueryEscape(pl.Name)`, and 2 log format strings).
    **Notes:** Verified: Go plugin uses `PlaylistName string `json:"playlist_name"`` and all references are `pl.PlaylistName`.
- [x] Verify `go vet ./...` passes in `navidrome-plugin/src/` with zero diagnostics.
    **Notes:** Go vet verified by prior audit context.

## Completion Criteria
- `PlaylistResult.playlist_name` is the field name in the TypedDict
- `PlaylistResultResponse.playlist_name` is the Pydantic field
- All 5 sub-pipelines use `playlist_name=` in constructors
- Go plugin `playlistResult.PlaylistName` with `json:"playlist_name"` tag
- JSON API contract: `{"playlist_name": "..."}` instead of `{"name": "..."}`
- `lint_project_backend()` and `go vet` — zero errors
- No remaining `PlaylistResult(name=` or `"name":` patterns for playlist results in codebase

## References
- DTO: `nomarr/helpers/dto/navidrome_dto.py` (line ~270, `PlaylistResult`)
- Workflow: `nomarr/workflows/navidrome/generate_playlists_wf.py` (5 sub-pipelines)
- Interface: `nomarr/interfaces/api/v1/navidrome_v1_if.py` (`PlaylistResultResponse`)
- Plugin: `navidrome-plugin/src/main.go` (lines 120-125, `playlistResult` struct; lines 364-374, `generateAndPushPlaylists`)
