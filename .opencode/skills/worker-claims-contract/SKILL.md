---
name: worker-claims-contract
description: Worker claim key contract, lifecycle (claim→steal→release→cleanup), and known mismatches for Nomarr worker claims (tag extraction, ML discovery, reconciliation). Also covers scan progress/reconcile and ML replace_song_inference_results persistence contract quirks discovered during correctness review.
---

# Worker Claims Contract & Related Persistence Quirks

## Mental Model
Nomarr workers reserve files by inserting a row into `worker_claims` (key unique, JSONB value, claimed_at). The claim **key encodes the claim type**: `claim_{song_id}` (untyped), `claim_{claim_type}_{song_id}` (typed, e.g. `claim_reconcile_{song_id}`). All claim mutation goes through `AppDb` (`nomarr/persistence/api/application.py`) → `AppRepository` (`nomarr/persistence/database/app_repo.py`). Cleanup of stale claims is a periodic pass that removes claims for (a) workers with stale heartbeats, (b) songs that are already tagged, (c) songs that no longer exist.

## Coverage
**Documented:** claim key construction, worker release mismatch (bug), steal path, cleanup semantics, scan reconcile pagination quirk, scan-progress ValueError risk, ML replace contract.
**Not yet documented:** whether the claim mismatch has been fixed in later commits; calibration repo set_state select-then-insert race (no unique constraint on model_id, documented in code).
**Last extended:** 2026-08-18

## Key Findings

### Claim key mismatch — worker releases are no-ops (HIGH severity, live bug)
- **Location:** `nomarr/components/workers/worker_discovery_comp.py:70` (claim) vs `:84` (release); `nomarr/persistence/api/application.py:176-177`; `nomarr/persistence/database/app_repo.py:316-326`
- **What:** `claim_file` calls `db.app.claim_song(int(file_id), worker_id, claimed_at=...)` with **no claim_type** → key `claim_{id}`. `release_claim` (worker_discovery_comp) calls `db.app.remove_claim(worker_id, file_id)` → facade **default `claim_type="process"`** → `app_repo.release_claim` builds prefix `claim_process_` → targets `claim_process_{id}`. The delete targets a key that was never created.
- **Affected release call sites (untyped claim mismatch):** `tag_extraction_worker.py:179`, `discovery_worker.py:170/383/413/434/440/455/468/539` (all via `worker_discovery_comp.release_claim`). NOT affected: `tagging_svc/write.py:132/140` and `file_write_comp.py` — they import `reconciliation_comp.release_claim` ("reconcile" type, consistent).
- **Why it matters:** Processed-song claims are never released by workers; they persist until `cleanup_stale_claims` runs. **Errored songs that are retried via `retry_errored_songs` (`services/domain/library_svc/songs.py:179-206`) are permanently re-blocked**: the retry transitions ERRORED→NOT_ERRORED and PROCESSED→NOT_PROCESSED, but `discover_next_untagged_file` / `discover_next_file_needing_tags` (`components/library/library_song_state_comp.py:183-241`) subtract `claimed_ids` — and the errored song's stale claim (worker is alive, song not tagged, song exists) is never removed by `cleanup_stale_claims`. Liveness bug: errored songs can get stuck forever.
- **Consistent path:** reconciliation claims use `claim_type="reconcile"` end-to-end (`reconciliation_comp.py:68,85,94`; `try_insert_or_steal_claim` `worker_discovery_comp.py:113,132`) — these release correctly.

### Steal path mismatch for untyped claims
- **Location:** `worker_discovery_comp.py:132` `db.app.remove_claim_by_song(int(file_id), str(claim_type or "process"))`
- **What:** When stealing, it removes `claim_process_{id}` (or `claim_{type}_{id}`), but the actual stale claim created by `claim_file` is `claim_{id}`. The steal deletes nothing, then re-claim raises DuplicateEntityError and returns False.

### `reconcile_library_paths` offset pagination skips rows when delete policy deletes mid-iteration (MEDIUM)
- **Location:** `nomarr/components/library/reconcile_paths_comp.py:63-90` (loop), `:133` (delete_invalid → `db.library.remove_song_by_path`)
- **What:** Paginates `list_songs(db, library_id=..., limit=batch_size, offset=offset)` and increments `offset += len(files)`. With `policy="delete_invalid"`, rows are deleted inside the loop → subsequent offsets miss shifted rows → some invalid paths never checked.
- **Also:** `get_library_stats(db)` `total_count` is global, not per-library (cosmetic/logging only).

### `record_scan_progress` raises ValueError when no scan row exists (MEDIUM)
- **Location:** `nomarr/persistence/api/library_scans.py:58-81`
- **What:** Raises `ValueError("no scan exists")` when `get_scan_record` returns None. `pipeline_svc.recover_stale_states` (`services/infrastructure/pipeline_svc.py:113-119`) and `recover_stale_heartbeats` (`:163`) call `update_scan_progress(scan_error=...)` at startup — if library axis is SCAN_IN_PROGRESS but the scan row was removed, the ValueError propagates → app startup crash (`app.py:361`). `complete_scan` (`library_scans.py:83-88`) has the same pattern.

### ML `replace_song_inference_results` — contract (verified FIXED vs L97 findings)
- **Location:** `nomarr/persistence/database/ml_inference_repo.py:28-119`; called from `discovery_worker._execute_deferred_writes` (:143-158)
- **What:** Atomic single-txn, backbone-scoped vector replace; `ml_output_streams` now has real `output_id`/`values` columns (migration 003). Per-backbone loop re-inserts the full stream set each iteration (idempotent). Empty `stream_payloads` while vectors exist **deliberately deletes** the song's streams (documented replace contract).
- **Known latent risk:** `_insert_vector` requires `payload["model_id"]` (KeyError if missing) and `EmbeddingStreamRepository.upsert_stream` select-then-insert without unique `(song_id, backbone_id)`.

### `update_songs` (library_songs.py:158-210) — full-library diff with `remove_missing=True`
- **What:** `remove_missing=True` diffs against `list_library_song_ids` (all songs in library). Currently no production callers (deadcode allowlist); a partial payload would delete songs not in the payload. Latent footgun, not live.
- `add_songs_to_library` state bootstrap semantics (existing_paths from DB before upsert; bootstrap only for paths not in existing_paths) are correct.

### `steal_claim` (app_repo.py:360-370) — no row filter
- **What:** `UPDATE worker_claims SET ... WHERE claimed_at + lease_ms < now` updates ALL expired claims with the same payload — latent data-corruption bug, but only exercised by tests (test_app_repo.py:394) and allowlisted as dead code.

### `fetch_output_streams` silently drops rows with NULL output_index (LOW/MEDIUM latent)
- **Location:** `nomarr/components/ml/inference/ml_output_stream_store_comp.py:86-99`
- **What:** `if not isinstance(output_index, int): continue` — rows written with `output_index=None` are silently dropped, which could flip `load_output_streams_for_song` to "no streams → reprocess" (`:164-169`).

## Critical Invariants
- Claim key must be built and consumed with the SAME `claim_type`; never mix default `"process"` release with untyped `claim_{id}` creation.
- `record_scan_progress` / `complete_scan` assume a scan row exists — recovery paths must tolerate missing rows (they don't currently).
- `replace_song_inference_results` owns a full atomic replacement for (streams × (song_id, backbone)); do not pair it with separate direct stream/vector writes.

## Sources
- Files: worker_discovery_comp.py, worker_tag_comp.py, reconciliation_comp.py, app_repo.py, application.py, library_scans.py, library_songs.py, song_state_repo.py, pipeline_repo.py, scan_repo.py, reconcile_paths_comp.py, ml_inference_repo.py, output_repo.py, ml_output_stream_store_comp.py, discovery_worker.py, tag_extraction_worker.py, pipeline_svc.py, library_song_state_comp.py, library_song_query_comp.py, file_batch_scanner_comp.py, library_scan_file_ops_comp.py, scan_lifecycle_comp.py
- Log entries: L93, L95, L97, L99, L101