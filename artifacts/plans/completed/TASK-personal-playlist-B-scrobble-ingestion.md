# Task: Personal Playlist — Scrobble Ingestion

## Problem Statement

The personal playlist feature needs real-time play data to build taste profiles. Currently, play counts are only captured during bulk Navidrome sync (Part C). This plan creates a real-time scrobble data path: a thin `POST /api/v1/navidrome/scrobble` endpoint (API-key auth) that delegates to `ingest_scrobble_wf`. The workflow upserts the track vertex, ensures the user vertex, atomically increments the `has_plays` edge playcount, and applies 30-second dedup. File resolution is attempted but never blocks on failure.

All persistence calls use concrete Plan A contracts (`db.navidrome_tracks.*`, `db.navidrome_playcounts.*`).

**Prerequisite:** TASK-personal-playlist-A-graph-collections

## Phases

### Phase 1: Workflow

- [x] Create `nomarr/workflows/navidrome/ingest_scrobble_wf.py` with public function `ingest_scrobble(db: Database, user_id: str, nd_id: str, timestamp_ms: int) -> None`. Sequence: dedup check → `db.navidrome_tracks.upsert_track(nd_id)` → `db.navidrome_playcounts.ensure_user(user_id)` → `db.navidrome_playcounts.increment_play(user_id, nd_id, timestamp_ms)` → `db.navidrome_tracks.resolve_nd_to_file(nd_id)` (log result, don’t block on None).
- [x] Implement dedup as module-level `_dedup_cache: dict[tuple[str, str], int]` guarded by `threading.Lock`. Before incrementing, check if `(user_id, nd_id)` was seen within `_DEDUP_WINDOW_MS = 30_000`; if so, log DEBUG and return early. Update cache entry on every non-duplicate scrobble.
- [x] Verify `lint_project_backend` passes on `nomarr/workflows/navidrome` with zero errors.

### Phase 2: Interface + Service Wiring

- [x] Add Pydantic models to `nomarr/interfaces/api/v1/navidrome_v1_if.py`: `ScrobbleTrack(BaseModel)` with `id: str`, optional `title: str = ""`, `duration: float = 0.0`; `ScrobbleRequest(BaseModel)` with `username: str`, `track: ScrobbleTrack`, `timestamp: int` (epoch seconds from Navidrome Scrobbler).
- [x] Add `POST /scrobble` endpoint to same file with `dependencies=[Depends(verify_key)]`, `status_code=204`. Convert `body.timestamp * 1000` to millis, call `svc.ingest_scrobble(user_id=body.username, nd_id=body.track.id, timestamp_ms=...)` via `asyncio.to_thread`, return `Response(status_code=204)`. Follow `navidrome_similar_tracks` pattern for service injection.
- [x] Add thin `ingest_scrobble(self, user_id: str, nd_id: str, timestamp_ms: int) -> None` method to `nomarr/services/domain/navidrome_svc.py`. Body: import and call `ingest_scrobble` from `nomarr.workflows.navidrome.ingest_scrobble_wf` with `db=self._db`.
- [x] Verify `lint_project_backend` (full workspace) passes with zero errors.

## Completion Criteria

- `POST /api/v1/navidrome/scrobble` endpoint exists with API-key auth (`verify_key`)
- Scrobble request body validated via Pydantic (`ScrobbleRequest` with `ScrobbleTrack`)
- Workflow atomically increments play count on `has_plays` edge via `increment_play`
- 30-second dedup prevents duplicate increments for same user+track
- Unresolved tracks (no `has_nd_id` edge) still succeed — play data captured, file resolution deferred
- `lint_project_backend` passes with zero errors

## References

- Design doc: `plans/dev/design-personal-playlist.md` (scrobble ingestion section)
- Contracts ledger: `plans/dev/personal-playlist-parts/CONTRACTS.md`
- Existing patterns: `nomarr/interfaces/api/v1/navidrome_v1_if.py`, `nomarr/services/domain/navidrome_svc.py`
- Prerequisite: `plans/TASK-personal-playlist-A-graph-collections.md`
