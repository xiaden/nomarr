---
name: song-hydration-flow
description: Song hydration in Nomarr — the write path that turns audio metadata into persisted tags, entity tags, metadata cache fields, duration, and the not_hydrated→hydrated state transition (tag_extraction_worker Pass 2). Also covers the read path (hydrate_songs_with_metadata) that derives canonical metadata from tags for library queries. Use when working on hydrate_song intent facades, tag extraction workers, metadata cache updates, duration updates, or hydration state transitions.
---

# Song Hydration Flow

## Mental Model
"Hydration" in Nomarr means two different things:

1. **WRITE path (hydration producer):** `tag_extraction_worker._process_file` extracts audio metadata from a file via mutagen, persists it as `nom:`-prefixed tags + entity tags (artist/artists/album/label/genre/year), writes metadata-cache fields, fills `duration_seconds` if missing, then transitions the song `not_hydrated → hydrated`. Runs one song at a time under a worker claim, driven by `discover_next_file_needing_tags`.
2. **READ path (hydration consumer):** `tag_hydration_comp.hydrate_songs_with_metadata` derives canonical artist/album/title/artists/labels/genres/year from the song's stored tags in one batch query (`db.library.list_song_tags_for_songs`), merging into song docs for library query/list endpoints (8 call sites in `library_song_query_comp.py`).

## Coverage
**Documented:** Write-path step order, read-path batch contract, tag_id contract gap, AR-SDR-4 atomicity constraint, N+1 pitfalls, claim lifecycle, state-transition semantics.
**Not yet documented:** Whether the `{name,value}` → `tag_id` mismatch actually crashes in production (integration test needed), batch sizes/chunking.
**Last extended:** 2026-08-18

## Key Findings

### Write path step order (tag_extraction_worker.py:42-99)
1. `db.library.get_song(song_id)` + `build_library_path_from_input` validity check
2. `extract_metadata(path, namespace)` — mutagen, format-specific (metadata_extraction_comp.py:187-253)
3. `save_song_tags` for `nom:`-prefixed parsed tags (song_sync_comp.py:48-65 → tag_write_comp.set_song_tags_batch)
4. `seed_entities_for_scan_batch` — entity tags + metadata cache (entity_seeding_comp.py:101-158)
5. `update_library_song_duration` only if `duration_seconds` not already set (one-shot fill)
6. `transition_song_state([song_id], not_hydrated → hydrated)` — LAST = commit point

### CRITICAL: tag_id contract gap
- `song_tag_repo.replace_song_tags` (song_tag_repo.py:119-137) requires each payload dict to have `tag_id` (KeyError if absent).
- ALL component callers pass `{"name": ..., "value": ...}`: tag_write_comp.py:32-50, entity_seeding_comp.py:37-98, sync_file_to_library_wf.py:77-80, move_detection_comp.py:254-257.
- Unit tests mock the DB so the mismatch is never exercised; repo test passes tag_id payloads.
- **No name/value → tag_id resolution exists in the write path.** Any hydrate_song facade must own batch tag resolution (find_or_create_tag, tag_repo.py:77-99 — itself SELECT+INSERT+commit per call).

### AR-SDR-4: no facade-level transactions
- docs/dev/architecture.md:105-139: facades expose NO `transaction()` context; repos own short internal txns (`begin_nested` + `commit` per method); callers must not open their own transactions.
- Consequence: a hydrate_song facade composed of existing facade calls is NOT atomic. Per-song atomicity requires a new repo-level method (e.g. delete edges + insert + state swap in one txn), which is a design decision needing an ADR.
- pg_engine.py: statement_timeout=30000 (30s cap on statements — batch sizes must chunk), expire_on_commit=False.

### N+1 pitfalls in the write path
- `AppDb.add_song_states` (application.py:96-98) loops `assign_state` per song — each does SELECT state-id + INSERT + COMMIT. Batch transitions (scan_library_full_wf.py:150-161, scan_library_quick_wf.py:148-159) pay N commits + N state-name lookups.
- `update_metadata_cache_batch` (metadata_cache_comp.py:65-85) is misnamed — loops `update_library_song_metadata_cache` → `song_repo.update_song` per song (per-commit).
- `set_song_tags_batch` (tag_write_comp.py:60-81): 1 batch read, but per-song `replace_song_tags` txn (delete + re-insert).
- `get_or_create_tag`: commits per tag.
- Existing single-txn batch primitives: `batch_upsert` (primitives.py:136-159), `upsert_songs_for_library` (song_repo.py:126-148), `replace_state_for_songs` (song_state_repo.py:129-160 — but REPLACES ALL AXES, edge-loss bug, NOT for per-axis transitions).

### State transitions
- `transition_song_state` (library_song_state_comp.py:49-73): per-axis, additive — `remove_song_state` (1 txn) + `add_song_states` (N txns). Already fixed from the snapshot-based remove-all bug (log L93).
- Scan workflows run unguarded transitions (not_scanned→scanned, errored→not_errored, hydrated→not_hydrated) on rows that may lack the from-edge — tolerant by design (remove-all no longer used).
- `ensure_song_state` bug: `db.library.add_songs_to_library` facade default `initial_state="tagged"` (library.py:198) vs sub-facade default STATE_NOT_PROCESSED (library_songs.py:135); "tagged" is NOT a song_states vertex → ValueError for every new song through the facade default. Scan path hits this (library_scan_file_ops_comp.py:90).

### Claims
- Hydration is worker-exclusive: `discover_and_claim_file_for_tags` (worker_tag_comp.py:25-42) → `claim_file` (worker_discovery_comp.py:47-73) → canonical `db.app.add_claim(WorkerClaim, *, now_ms=None, lease_ms=None)` (backed by `app_repo._acquire_claim`, which owns the `claim_{song_id}` / `claim_{claim_type}_{song_id}` key encoding as a persistence-internal detail). Released in `finally` (tag_extraction_worker.py) via `release_claim` (which wraps `db.app.remove_claim`).
- Facade must NOT be called with storage rows/keys — the claim key encoding is persistence-internal; claims stay in worker components and go through the canonical intent facade.

## Critical Invariants
- State transition to `hydrated` must be the LAST write in the hydration sequence (commit point).
- `replace_song_tags` is full-replace — idempotent on retry; re-hydration churns edges (scan resets hydrated→not_hydrated when mtime changes, scan_library_full_wf.py:160-161).
- Duration is one-shot: never overwrite an existing `duration_seconds`.
- Metadata cache fields (artist, artists, album, labels, genres, year, _cache_updated_at) are sorted-array strings; `update_library_song_metadata_cache` validates allowed fields (library_songs.py:252-259).
- Error marking (not_errored→errored) happens at worker level, never in the facade.

## Sources
- nomarr/services/infrastructure/workers/tag_extraction_worker.py:42-99, 102-167
- nomarr/components/library/tag_hydration_comp.py:20-165
- nomarr/components/metadata/{metadata_cache_comp,metadata_extraction_comp,entity_seeding_comp}.py
- nomarr/components/tagging/tag_write_comp.py:17-81
- nomarr/components/library/{library_song_state_comp,library_song_query_comp,song_sync_comp}.py
- nomarr/persistence/database/{song_tag_repo,song_state_repo,song_repo,tag_repo,app_repo}.py
- nomarr/persistence/api/{library,library_songs,library_tags,application}.py
- nomarr/workflows/library/{scan_library_full_wf,scan_library_quick_wf,sync_file_to_library_wf}.py
- nomarr/services/infrastructure/workers/{discovery_worker,worker_tag_comp? (nomarr/components/workers/)}.py
- docs/dev/architecture.md:95-164 (AR-SDR-4)
- tests/unit/test_transaction_guard.py, tests/unit/components/tagging/test_tag_write_comp.py, tests/unit/persistence/database/test_tag_repo.py:181-198
- deadcode_allowlist.py:698 (hydrate_song_with_tags)
