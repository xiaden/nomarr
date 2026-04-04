# Task: Navidrome Integration Audit Fixes

## Problem Statement

An audit of the completed Navidrome integration plans (A, B, C) revealed two runtime
bugs, one misleading validation gap, and three overcomplexities. The WASM plugin
(Plan B) and overall architecture are sound, but the Python backend has issues that
will cause silent failures at runtime.

**Bug 1 — `trigger_rescan` never fires.** In `navidrome_svc.py`, `trigger_rescan()`
checks `if self._client is None: return False`, but `_client` is only populated by
`_get_client()`. Since `trigger_rescan` never calls `_get_client()`, the check always
passes on a fresh service instance. The `reconcile_library_tags` endpoint in
`library_if.py` (line 604) calls `navidrome_service.trigger_rescan()` after tag writes,
but the rescan is silently skipped every time.

**Bug 2 — `now_ms()` stored as wrapper object.** In `navidrome_song_map_aql.py`,
`upsert_batch()` stores `ts = now_ms()` directly as `synced_at`. But `now_ms()` returns
a `Milliseconds` dataclass (not a raw `int`). The python-arango driver will fail or
serialize this incorrectly when building AQL bind variables.

**Overcomplexity — `rescan_trigger_comp.py` is pointless indirection.** The file wraps a
single `client.start_scan()` call in a try/except with logging. Components are for heavy
domain logic; this has none. It should be inlined into the service.

**Minor issues:** `ping()` doesn't check `api_password` in its early-return guard;
`SubsonicClient` never closes its `httpx.Client`; `SyncResponse` in `navidrome_v1_if.py`
duplicates `SyncSongsResponse` from `navidrome_types.py`.

## Phases

### Phase 1: Fix Runtime Bugs

- [x] Fix `now_ms()` usage in `navidrome_song_map_aql.py:upsert_batch` — change `ts = now_ms()` to `ts = now_ms().value` so `synced_at` stores an integer, not a `Milliseconds` wrapper
    **Notes:** Changed `ts = now_ms()` to `ts = now_ms().value` on line 47 of navidrome_song_map_aql.py. Confirmed Milliseconds is a frozen dataclass with `value: int`, not an int subclass. lint_project_backend: 0 new errors (5 pre-existing mypy cursor typing).
- [x] Fix `trigger_rescan` in `navidrome_svc.py` — replace `if self._client is None: return False` with a try/except around `_get_client()` that returns False on `ValueError` (not configured), so rescan works when credentials are configured but client not yet lazily constructed
    **Notes:** Replaced `if self._client is None: return False` + `_do_rescan(self._client, ...)` with try/except around `_get_client()` (lines 264-268). Now catches ValueError when not configured, and uses the client from _get_client() which handles lazy construction. lint_project_backend: 0 new errors.
- [x] Add `api_password` to `ping()` early-return guard in `navidrome_svc.py` — check `not self.cfg.api_password` alongside url/user, update error message to include password
    **Notes:** Added `not self.cfg.api_password` to ping() guard (line 276) and updated error message to include password. lint_project_backend: 0 new errors.

### Phase 2: Remove Overcomplexity

- [x] Delete `nomarr/components/navidrome/rescan_trigger_comp.py` and inline its logic into `NavidromeService.trigger_rescan()` — replace the `_do_rescan(self._client, ...)` call with a direct `client.start_scan()` call plus try/except logging, remove the import from `navidrome_svc.py`
    **Notes:** Deleted nomarr/components/navidrome/rescan_trigger_comp.py. Removed import on old line 13 of navidrome_svc.py. Inlined try/except logging from the component directly into trigger_rescan() (lines 263-274). No remaining references to the deleted file (locate_module_symbol returns 0 matches). lint_project_backend: 0 new errors.
- [x] Add `close()` method to `SubsonicClient` in `subsonic_client_comp.py` that calls `self._http.close()`, for clean shutdown; no callers needed yet but prevents resource leak warnings
    **Notes:** Added close() method to SubsonicClient (lines 36-38) that calls self._http.close(). lint_project_backend: 0 new errors.
- [x] Consolidate duplicate sync response models — remove inline `SyncResponse` from `navidrome_v1_if.py` and import `SyncSongsResponse` from `navidrome_types.py`, aliasing if needed for API clarity
    **Notes:** Removed inline SyncResponse class from navidrome_v1_if.py (was lines 54-61). Imported SyncSongsResponse from nomarr.interfaces.api.types.navidrome_types (line 17). Updated navidrome_sync_songs return type and constructor (lines 95, 102). lint_project_backend: 0 new errors.
- [x] Run `lint_project_backend` on all modified files and verify zero errors
    **Notes:** Ran lint_project_backend on all 4 modified files: navidrome_song_map_aql.py, navidrome_svc.py, subsonic_client_comp.py, navidrome_v1_if.py. 0 new errors across all files. Only 5 pre-existing mypy cursor typing errors in navidrome_song_map_aql.py (python-arango Cursor union type). Also verified nomarr/services/domain directory (6 files checked) — clean.

## Completion Criteria

- `trigger_rescan` correctly constructs the Subsonic client when credentials are configured, even if called before any other client-using method
- `synced_at` in `navidrome_song_map` stores an integer timestamp, not a serialized dataclass
- `rescan_trigger_comp.py` is deleted; its logic lives in the service
- `SubsonicClient` has a `close()` method
- No duplicate response models between web and v1 navidrome endpoints
- `lint_project_backend` passes with zero errors

## References

- `navidrome_svc.py` trigger_rescan: `nomarr/services/domain/navidrome_svc.py` line 254
- `navidrome_song_map_aql.py` upsert_batch: `nomarr/persistence/database/navidrome_song_map_aql.py` line 48
- `rescan_trigger_comp.py`: `nomarr/components/navidrome/rescan_trigger_comp.py`
- `library_if.py` reconcile_library_tags: `nomarr/interfaces/api/web/library_if.py` line 604
- Completed plans: `plans/completed/TASK-navidrome-integration-A-similarity-api.md`, `B-wasm-plugin.md`, `C-playlist-push.md`
