---
name: song-state-transitions
description: Song-level state machine in Nomarr — the song_state_assignments junction (16 vertices, 8 axes), transition_song_state's remove-all/re-add snapshot rewrite semantics (and its data-loss/race/duplicate bugs), hydration worker flow, error-marking recovery paths, and discovery exclusions. Use when working on hydration, errored marking, scan state bootstrap, retry_errored_songs, or any song-state transition.
---

# Song State Transitions

## Mental Model

Song processing state lives in rows of the `song_state_assignments` junction table linking `songs` → `song_states` (16 named vertices = 8 axis pairs from `ALL_STATE_VERTICES`/`AXIS_PAIRS` in `nomarr/helpers/constants/file_states.py`). A song should hold exactly one edge per axis (one pole of each pair). "Rows lacking the expected state edge" is a real, supported condition: the hydration axis was introduced after initial scans, and new-song state bootstrap only assigns a single state (and even that can fail — `ensure_song_state` is called with `"tagged"`, which is NOT one of the 16 vertices, raising `ValueError: Unknown song state: 'tagged'`).

## Coverage

**Documented:** `transition_song_state` semantics and failure modes, hydration worker flow (`tag_extraction_worker.py`), ML worker concurrent processing, error-marking paths, discovery exclusions, scan-batch post-transitions, retry flow, `ensure_song_state` "tagged" bug.
**Not yet documented:** calibration/write-state transitions in detail, Navidrome sync interplay.
**Last extended:** 2026-08-17

## Key Findings

### 1. `transition_song_state` is a snapshot remove-all/re-add rewrite
- **Location:** `nomarr/components/library/library_song_state_comp.py:49-81`
- Reads full membership (`db.app.get_song_states_for_songs`), then `db.app.remove_song_states` (DELETE all assignments for the song ids), then re-adds `snapshot − from_state + to_state`.
- Validates only the axis pair via `_VALID_TRANSITIONS` (same-axis pole swap; `errored` pairs with `not_errored` only — `mark_song_errored` at :274 cannot ever succeed for a positive pole on another axis).
- Missing `from_state` edge does NOT raise — the rewrite silently proceeds, and the resulting edge set can only reflect the (possibly stale/partial) snapshot. Concurrent transitions lose each other's re-adds; duplicate re-adds of the same `(song_id, state_id)` violate `uq_song_state_assign_song_state` (`nomarr/persistence/models/song_state_assignment.py:19`) → `IntegrityError 23505` → `DuplicateEntityError` mid-transition.
- Callers: `bulk_set_not_hydrated`, `bulk_set_not_calibrated`, `bulk_set_not_vectors_extracted`, `bulk_set_tags_not_fresh` (same file), `mark_song_errored` (0 callers, always raises), `retry_errored_songs` (`nomarr/services/domain/library_svc/songs.py:203-204`), scan batches (`scan_library_full_wf.py:150-161`, `scan_library_quick_wf.py`), `bootstrap_file_state_edges` (`library_scan_file_ops_comp.py:168`), `mark_song_processed` (`song_sync_comp.py:39`), hydration worker (`tag_extraction_worker.py:97`), ML worker (`discovery_worker.py:379,406`).

### 2. Hydration flow (Pass 2 of scan)
- **Location:** `nomarr/services/infrastructure/workers/tag_extraction_worker.py`
- `run()` loop: `discover_next_file_needing_tags` (songs in `not_hydrated` MINUS `errored` MINUS claimed) → `_process_file` (extract audio tags/metadata, seed entities) → final step `transition_song_state(db, [song_id], NOT_HYDRATED, HYDRATED)` at :97.
- On any exception: except-block at :145-151 runs `transition_song_state(db, [song_id], NOT_ERRORED, ERRORED)` — **the recovery that marks errored**.

### 3. ML worker races the same song rows
- **Location:** `nomarr/services/infrastructure/workers/discovery_worker.py:339-412`, `nomarr/components/workers/worker_discovery_comp.py:33-51`
- ML worker claims from `not_processed` (`discover_next_untagged_file`), tag worker from `not_hydrated`. A fresh song holds both edges → both workers concurrently call `transition_song_state` on the same row → remove-all/re-add interleaving → lost updates and/or `DuplicateEntityError`.
- `_handle_process_error` (discovery_worker.py:399-412) also marks `(not_errored → errored)` on any processing exception.

### 4. Scan batch post-processing assumes edges exist
- **Location:** `nomarr/workflows/library/scan_library_full_wf.py:145-161`
- After upsert: `transition_song_state(file_ids, NOT_SCANNED → SCANNED)`, `(ERRORED → NOT_ERRORED)`, and for modified files `(HYDRATED → NOT_HYDRATED)` at :161 — unconditionally, with no membership-requirement check. Comment at :154 claims "New files already get not_hydrated from state bootstrap" — FALSE: `_upsert_batch` only re-initializes existing files with NO assignments (`library_scan_file_ops_comp.py:92-101`); new files never get negative edges via that path.

### 5. `ensure_song_state` bootstrap uses an invalid vertex name
- **Location:** `nomarr/persistence/api/library_songs.py:134,144,171` (`initial_state="tagged"`), `nomarr/components/workers/worker_discovery_comp.py:20` (`_TAGGED_STATE_ID = "tagged"`)
- `song_states` is seeded by `bootstrap_states` (`nomarr/persistence/database/song_state_repo.py:130-181`) with only the 16 `ALL_STATE_VERTICES` names — "tagged" is not among them → `assign_state` raises `ValueError: Unknown song state: 'tagged'` for every brand-new song → `_upsert_batch` aborts → folder skipped after retry (`scan_library_full_wf.py:183-194`). New rows end up with no edges at all.

### 6. Errored marking is permanent until manual retry
- `discover_next_untagged_file` (`library_song_state_comp.py:192-215`) and `discover_next_file_needing_tags` (:227-250) both subtract `errored` membership unconditionally.
- Only clearing path: `retry_errored_songs` (`library_svc/songs.py:179-206`), which performs two more snapshot rewrites `(errored→not_errored)`, `(processed→not_processed)`. On a partial-edge row the result can be e.g. `{not_errored, not_processed}` — still missing `not_hydrated`, so the row can never be re-discovered for hydration again.

## Critical Invariants

1. **A transition must never drop edges of other axes.** `transition_song_state`'s remove-all/re-add violates this under stale/partial membership reads and concurrent workers — the bug. Prefer touch-only-pole semantics (remove `from_state`, add `to_state`).
2. **Discovery must NOT permanently exclude errored rows that merely had a transient failure.** An errored song should remain recoverable without manual retry (or retry must restore the full negative-pole set).
3. **State vertex names are exactly `ALL_STATE_VERTICES`.** "tagged" is not a vertex; any code using it (`ensure_song_state` default, `_TAGGED_STATE_ID`) is broken.
4. **New rows must be seeded with the full negative-pole set** (like `initialize_song_states_batch`) before any scan-batch transition runs, or transitions must tolerate missing edges.

## Sources
- `nomarr/components/library/library_song_state_comp.py`
- `nomarr/services/infrastructure/workers/tag_extraction_worker.py`
- `nomarr/services/infrastructure/workers/discovery_worker.py`
- `nomarr/components/workers/worker_discovery_comp.py`
- `nomarr/workflows/library/scan_library_full_wf.py`, `scan_library_quick_wf.py`
- `nomarr/components/library/library_scan_file_ops_comp.py`
- `nomarr/persistence/api/library_songs.py`, `nomarr/persistence/api/application.py`
- `nomarr/persistence/database/song_state_repo.py`, `pipeline_repo.py`
- `nomarr/persistence/models/song_state_assignment.py`
- `nomarr/persistence/sql/exceptions.py`, `nomarr/persistence/sql/primitives.py`
- `nomarr/services/domain/library_svc/songs.py`, `scan.py`
- `tests/unit/components/library/test_library_song_state_comp.py`
- Research log entry L93 (support-researcher, 2026-08-17)