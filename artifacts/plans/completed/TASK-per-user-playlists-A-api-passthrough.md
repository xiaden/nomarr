# Task: Wire Playlist Param Overrides Through API

## Problem Statement

The endpoint `POST /api/v1/navidrome/generate-playlists` already accepts `max_songs` and `enabled_types` in `GeneratePlaylistsRequest` but ignores them — the endpoint only passes `user_id` to `NavidromeService.generate_playlists()`, which reads all values from `ConfigService`. This blocks per-user playlist configuration from the Navidrome plugin because there is no way for the caller to override user-facing preferences.

This plan adds `min_songs` to the request model, wires all three user-facing overrides through the endpoint, and updates the service method to accept them as optional kwargs that fall back to `ConfigService` when `None`. Technical params (`half_life_days`, `top_n`, `min_play_count`) remain unconditionally server-side. The workflow signature is already correct — no changes needed there.

**Files:** `nomarr/interfaces/api/v1/navidrome_v1_if.py`, `nomarr/services/domain/navidrome_svc.py`

## Phases

### Phase 1: Interface layer — expand request model and wire through endpoint

- [x] Add `min_songs: int | None = None` field to `GeneratePlaylistsRequest` after the existing `enabled_types` field in `nomarr/interfaces/api/v1/navidrome_v1_if.py`
    **Notes:** Added `min_songs: int | None = None` after `enabled_types` in `GeneratePlaylistsRequest`.
- [x] Update the `navidrome_generate_playlists` endpoint's `asyncio.to_thread` call to pass `enabled_types=body.enabled_types`, `max_songs=body.max_songs`, `min_songs=body.min_songs` as kwargs to `svc.generate_playlists`
    **Notes:** Wired `enabled_types`, `max_songs`, `min_songs` as kwargs in the `asyncio.to_thread` call.
- [x] Verify `lint_project_backend(path="nomarr/interfaces")` passes with zero errors
    **Warning:** 3 mypy `call-arg` errors as expected: `generate_playlists` signature hasn't been updated yet. The endpoint passes `enabled_types`, `max_songs`, `min_songs` kwargs that the service method doesn't accept until Phase 2 updates the signature. These errors will resolve when Phase 2 is implemented.

### Phase 2: Service layer — accept overrides with ConfigService fallback

- [x] Update `NavidromeService.generate_playlists` signature from `(self, user_id: str)` to `(self, user_id: str, *, enabled_types: list[str] | None = None, max_songs: int | None = None, min_songs: int | None = None)`
    **Notes:** Signature updated with keyword-only `enabled_types`, `max_songs`, `min_songs` — all `| None = None`.
- [x] Replace the three user-facing `self._config_service.get(...)` calls with override-or-fallback: use provided value if not `None`, else read from `ConfigService`. Technical params (`half_life_days`, `top_n`, `min_play_count`) remain unconditional `ConfigService` reads.
    **Notes:** Used `is not None` guard for all three user-facing params. Technical params (`half_life_days`, `top_n`, `min_play_count`) remain unconditional ConfigService reads.
- [x] Verify `lint_project_backend(path="nomarr/services")` passes with zero errors
    **Notes:** Zero errors on both `nomarr/services` and `nomarr/interfaces`. Phase 1 mypy `call-arg` errors resolved.

## Completion Criteria

- `GeneratePlaylistsRequest` has three optional override fields: `enabled_types`, `max_songs`, `min_songs`
- Endpoint passes all three to the service method as kwargs
- Service uses provided values when not `None`, falls back to `ConfigService` when `None`
- Technical params (`half_life_days`, `top_n`, `min_play_count`) always read from `ConfigService`
- `lint_project_backend()` passes with zero errors on both files
- Existing API callers sending only `{"user_id": "..."}` still work (backward compatible)

## References

- Design doc: `plans/dev/design-per-user-playlists.md`
- Parts README: `plans/dev/per-user-playlists-parts/README.md`
- Contracts ledger: `plans/dev/per-user-playlists-parts/CONTRACTS.md`
