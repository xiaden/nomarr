---
name: worker-claims-contract
description: Worker claim key contract, lifecycle (claim→steal→release→cleanup), and known mismatches for Nomarr worker claims (tag extraction, ML discovery, reconciliation). Also covers scan progress/reconcile and ML replace_song_inference_results persistence contract quirks discovered during correctness review.
---

# Worker Claims Contract & Related Persistence Quirks

## Mental Model
Nomarr workers reserve files by inserting a row into `worker_claims` (key unique, JSONB value, claimed_at). The claim **key encodes the claim type**: `claim_{song_id}` (untyped), `claim_{claim_type}_{song_id}` (typed, e.g. `claim_reconcile_{song_id}`). All claim mutation goes through `AppDb` (`nomarr/persistence/api/application.py`) → `AppRepository` (`nomarr/persistence/database/app_repo.py`). Cleanup of stale claims is a periodic pass that removes claims for (a) workers with stale heartbeats, (b) songs that are already tagged, (c) songs that no longer exist.

## Coverage
**Documented:** claim key construction, worker release mismatch (bug) + fix status, steal path, cleanup semantics, scan reconcile pagination quirk, scan-progress ValueError risk (+ residual live chains), ML replace contract, embedding-stream unique constraint status.
**Not yet documented:** calibration repo set_state select-then-insert race (no unique constraint on model_id, documented in code).
**Last extended:** 2026-08-18 (re-validated post-fix, see L102)

## Key Findings

### Claim key mismatch — worker releases are no-ops (HIGH severity, live bug) — **FIXED by dba00542**
- **Location:** `nomarr/components/workers/worker_discovery_comp.py:70` (claim) vs `:84` (release); `nomarr/persistence/api/application.py:176-177`; `nomarr/persistence/database/app_repo.py:317-345`
- **What (original bug):** `claim_file` calls `db.app.claim_song(int(file_id), worker_id, claimed_at=...)` with **no claim_type** → key `claim_{id}`. `release_claim` called `db.app.remove_claim(worker_id, file_id)` with facade default `claim_type="process"` → prefix `claim_process_` → targeted `claim_process_{id}`, a key never created.
- **Fix status (verified L102):** facade defaults changed to `str | None = None` (`application.py:161,176-181`); `app_repo.release_claim`/`release_claim_by_song` build prefix `claim_` when claim_type is falsy (`app_repo.py:329,342`); steal path coerces `str | None` (`worker_discovery_comp.py:110-113,132`). All untyped release sites (tag_extraction_worker:179, discovery_worker:170/383/413/434/440/455/468/539, worker_tag_comp:40) now match `claim_{id}`. Reconciliation claims remain 'reconcile'-typed end-to-end. `cleanup_stale_claims` keys (`claim_{sid}`, `claim_reconcile_{sid}`) match. Test `test_release_claim_removes_untyped_claim` added.
- **Residual (LOW, pre-existing):** `try_insert_or_steal_claim` cross-type steal — an expired UNTYPED claim is not removed by a 'reconcile' stealer (`remove_claim_by_song(file_id, "reconcile")` deletes only `claim_reconcile_{id}`), so both claims coexist until cleanup. Only caller is `reconciliation_comp`.
- **Affected release call sites (untyped claim mismatch):** `tag_extraction_worker.py:179`, `discovery_worker.py:170/383/413/434/440/455/468/539` (all via `worker_discovery_comp.release_claim`). NOT affected: `tagging_svc/write.py:132/140` and `file_write_comp.py` — they import `reconciliation_comp.release_claim` ("reconcile" type, consistent).
- **Why it matters:** Processed-song claims are never released by workers; they persist until `cleanup_stale_claims` runs. **Errored songs that are retried via `retry_errored_songs` (`services/domain/library_svc/songs.py:179-206`) are permanently re-blocked**: the retry transitions ERRORED→NOT_ERRORED and PROCESSED→NOT_PROCESSED, but `discover_next_untagged_file` / `discover_next_file_needing_tags` (`components/library/library_song_state_comp.py:183-241`) subtract `claimed_ids` — and the errored song's stale claim (worker is alive, song not tagged, song exists) is never removed by `cleanup_stale_claims`. Liveness bug: errored songs can get stuck forever.
- **Consistent path:** reconciliation claims use `claim_type="reconcile"` end-to-end (`reconciliation_comp.py:68,85,94`; `try_insert_or_steal_claim` `worker_discovery_comp.py:113,132`) — these release correctly.

### Steal path mismatch for untyped claims — **FIXED by dba00542**
- **Location:** `worker_discovery_comp.py:110-113,132`
- **What (original):** `db.app.remove_claim_by_song(int(file_id), str(claim_type or "process"))` removed `claim_process_{id}` instead of the stale `claim_{id}`.
- **Fix:** `claim_type` coerced to `str | None`; `None` → `claim_` prefix. See cross-type residual above.

### `reconcile_library_paths` offset pagination skips rows when delete policy deletes mid-iteration (MEDIUM) — **FIXED by aa1096cb**
- **Location:** `nomarr/components/library/reconcile_paths_comp.py:63-95` (loop; `deleted_before_batch`/`deleted_in_batch` delta at :68,:91-95), `:117-143` (`_handle_invalid_path` → `db.library.remove_song_by_path`)
- **What (original):** Paginated `list_songs(db, library_id=..., limit=batch_size, offset=offset)` and incremented `offset += len(files)`; deleting rows mid-loop skipped shifted rows.
- **Fix:** after each batch, `offset += len(files) - deleted_in_batch`, where `deleted_in_batch` is the delta of `result["deleted_files"]`. Sound because `list_songs` re-fetches the full current library list per page (`library_song_query_comp.py:341-364` — limit=None fetch, in-memory sort+paginate). Test `test_delete_policy_validates_rows_shifted_by_deletions` asserts offsets [0,0,1].
- **Also (unchanged, cosmetic):** `get_library_stats(db)` `total_count` is global, not per-library.

### `record_scan_progress` requires a scan row (MEDIUM) — **startup crash fixed; setup ordering is current**
- **Location:** `nomarr/persistence/api/library_scans.py:58-81` (raise), `:83-88` (complete_scan same guard)
- **Startup fix (verified L102):** both `pipeline_svc.recover_stale_states` (`:115-127`) and `recover_stale_heartbeats` (`:171-182`) wrap `update_scan_progress(scan_error=...)` in try/except ValueError with logger.warning. `recover_stale_heartbeats` is now WIRED at `app.py:363` (its `deadcode_allowlist.py:799` entry is now stale). Tests added for both.
- **Current contract:** `scan_setup_wf.py` synchronously calls `mark_scan_started`/`start_scan` before the background full/quick workflows issue progress updates. A missing row remains a state divergence and must not be silently ignored. There is no library-creation `ensure_scan_state` placeholder-row path.

### ML `replace_song_inference_results` — contract (verified FIXED vs L97 findings; re-verified L102)
- **Location:** `nomarr/persistence/database/ml_inference_repo.py:28-119`; called from `discovery_worker._execute_deferred_writes` (:143-158)
- **What:** Atomic single-txn (one `begin_nested` SAVEPOINT + single commit), backbone-scoped vector replace; `ml_output_streams` has canonical `output_id`/`output_index`/`values` columns (migration 003 + ORM `ml_output_stream.py:23-25`). Per-backbone loop re-inserts the full stream set each iteration (idempotent). Empty `stream_payloads` while vectors exist **deliberately deletes** the song's streams (documented replace contract).
- **Known latent risk:** `_insert_vector` requires `payload["model_id"]` (KeyError if missing). `fetch_output_streams` (`ml_output_stream_store_comp.py:79-102`) still silently drops rows with NULL `output_index` — live writes carry ints (`ml_head_pipeline_comp.py:148`, `process_file_wf.py:226`) so drop is defensive-only.

### `update_songs` (library_songs.py:158-210) — full-library diff with `remove_missing=True` (UNCHANGED, latent)
- **What:** `remove_missing=True` diffs against `list_library_song_ids` (all songs in library). No production callers (facade `library.py:211` + test only; `deadcode_allowlist.py:917`); a partial payload would delete songs not in the payload. Latent footgun, not live.

### Embedding-stream race — unique constraint ADDED in migration 003, ORM/repo NOT updated (PARTIAL)
- **Location:** `alembic/versions/003_canonical_ml_output_streams.py` (adds `uq_ml_embedding_streams_song_backbone` on (song_id, backbone_id)); `nomarr/persistence/models/ml_embedding_stream.py` (NO constraint declared); `nomarr/persistence/database/embedding_stream_repo.py:55-93` (`upsert_stream` select-then-insert-or-update; docstring at :63-65 still claims no constraint)
- **What:** Alembic-managed prod DBs now enforce the unique constraint, but test DBs built via `Base.metadata.create_all` do not (schema divergence). A concurrent race in prod now surfaces as `IntegrityError` (23505 → `DuplicateEntityError`) instead of duplicate rows. `replace_embedding_stream_for_song` has zero production callers (only `test_ml_db.py:488`).
- `add_songs_to_library` state bootstrap semantics (existing_paths from DB before upsert; bootstrap only for paths not in existing_paths) are correct.

### `steal_claim` (app_repo.py:370-380) — no row filter (UNCHANGED, latent)
- **What:** `UPDATE worker_claims SET ... WHERE claimed_at + lease_ms < now` updates ALL expired claims with the same payload — latent data-corruption bug, but only exercised by tests (test_app_repo.py:402-414) and allowlisted as dead code. The production steal path (`try_insert_or_steal_claim`) does NOT use it — it does remove+re-insert.

### `fetch_output_streams` silently drops rows with NULL output_index (LOW/MEDIUM latent)
- **Location:** `nomarr/components/ml/inference/ml_output_stream_store_comp.py:86-99`
- **What:** `if not isinstance(output_index, int): continue` — rows written with `output_index=None` are silently dropped, which could flip `load_output_streams_for_song` to "no streams → reprocess" (`:164-169`).

## Critical Invariants
- Claim key must be built and consumed with the SAME `claim_type`; never mix default `"process"` release with untyped `claim_{id}` creation.
- `record_scan_progress` / `complete_scan` assume a scan row exists — recovery paths guard the crash-divergence case, while normal scan setup creates the row first.
- `replace_song_inference_results` owns a full atomic replacement for (streams × (song_id, backbone)); do not pair it with separate direct stream/vector writes.

## Sources
- Files: worker_discovery_comp.py, worker_tag_comp.py, reconciliation_comp.py, app_repo.py, application.py, library_scans.py, library_songs.py, song_state_repo.py, pipeline_repo.py, scan_repo.py, reconcile_paths_comp.py, ml_inference_repo.py, output_repo.py, ml_output_stream_store_comp.py, discovery_worker.py, tag_extraction_worker.py, pipeline_svc.py, library_song_state_comp.py, library_song_query_comp.py, file_batch_scanner_comp.py, library_scan_file_ops_comp.py, scan_lifecycle_comp.py
- Log entries: L93, L95, L97, L99, L101
