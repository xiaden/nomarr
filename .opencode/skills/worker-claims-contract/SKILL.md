---
name: worker-claims-contract
description: Worker claim intent-facade contract for Nomarr — the canonical add_claim/remove_claim/remove_claims/list_claims/count_claims surface, exact-key atomic acquisition, single-active-claim-per-song invariant (incl. cross-type replacement), errored/retry-eligible liveness, and persistence-internal key encoding (claim_{song_id} / claim_{claim_type}_{song_id}). Also covers scan progress/reconcile and ML replace_song_inference_results persistence contract quirks discovered during correctness review.
---

# Worker Claims Contract & Related Persistence Quirks

## Mental Model
All worker-claim mutation goes through the **canonical claims intent facade** (`AppDb` in `nomarr/persistence/api/application.py`): `add_claim(WorkerClaim, *, now_ms=None, lease_ms=None) -> bool`, `remove_claim(WorkerClaimIdentity) -> bool`, `remove_claims(ClaimRemovalRequest) -> int`, `list_claims() -> list[WorkerClaim]`, `count_claims() -> int`, plus the all-claims reset under `db.app.maintenance.delete_all_worker_claims()`. The facade delegates to `AppRepository` (`nomarr/persistence/database/app_repo.py`).

Callers know nothing of the underlying storage: the claim **key encoding** (`claim_{song_id}` untyped, `claim_{claim_type}_{song_id}` typed, e.g. `claim_reconcile_{song_id}`), the JSONB payload, and row→domain mapping are **persistence-internal** to `app_repo.py`. Domain values are frozen/slotted in `nomarr/helpers/dataclasses/worker_claim_dataclass.py`. Legacy insert/release/steal method names are gone (CONTRACTS.md); component-level thin helpers such as `release_claim(db, ...)` may wrap the facade but never touch storage shapes.

Cleanup of stale claims is `remove_claims(ClaimRemovalRequest)`: it removes claims for (a) given worker ids, (b) given songs, (c) stale workers (missing/expired health heartbeat), (d) missing/completed/errored songs — while **preserving active reconcile claims** and skipping `claim_type == 'reconcile'` in song-cleanup.

## Coverage
**Documented:** exact-key atomicity (authoritative), cross-type expiry replacement (single active claim), errored/retry-eligible liveness, reconcile-preservation during cleanup, scan reconcile pagination quirk, scan-progress ValueError risk (+ residual live chains), ML replace contract, embedding-stream unique constraint status.
**Not yet documented:** calibration repo set_state select-then-insert race (no unique constraint on model_id, documented in code).
**Last extended:** 2026-08-31 (rewritten for the intent-facade surface, Phase 3 of TASK-worker-claims-intent-facade-A-correction)

## Key Findings

### Claim acquisition is exactly-key atomic — authoritative contract
- **Location:** `nomarr/persistence/database/app_repo.py` `_acquire_claim` (`:594`), wired as `db.app.add_claim` in `application.py`.
- **Contract:** acquisition begins a nested transaction that serializes on the song's existing claim rows (`SELECT ... FOR UPDATE` over `claim_{song_id}` and the `claim\_%\_\{song_id\}` LIKE set). If no row exists → INSERT, returns `True`. If `lease_ms is None` → insert-only, never replaces (returns `False` on any existing claim). If a lease is given and an existing row is expired (`claimed_at < now_ms - lease_ms`) → replaced via an **exact-key, expiry-filtered UPDATE** (targets only the specific old key and only if still expired), returns `True`. Any active (non-expired) conflict → `False`.
- **Why exact-key matters:** replacement never deletes or overwrites another row. A cross-type stealer can only claim a slot by re-using the exact old key; the single-active-claim invariant holds across typed and untyped claims because the UPDATE re-points the one conflicting row.
- **Missing song** → `False` (no row created).

### Cross-type expiry replacement leaves exactly one claim
- **Location:** `_acquire_claim` same-key UPDATE path; regression `test_acquire_claim_cross_type_replaces_expired_claim`.
- **Contract:** when an expired untyped `claim_{song_id}` exists and a typed claim (e.g. `claim_reconcile_{song_id}`) acquires with a lease, the exact-key UPDATE rewrites that one row to the new key/worker/type. After acquisition exactly one claim row remains for the song. The old cross-type *steal* path (`try_insert_or_steal_claim` + `remove_claim_by_song`) was removed; both claims could previously coexist until cleanup.

### Errored/retry-eligible claims are released (liveness contract)
- **Location:** `_remove_claims` with `remove_errored_songs=True` (songs in `STATE_ERRORED`); `_resolve_stale_workers` (missing or expired health heartbeat). Caller: `cleanup_stale_claims` / worker-death cleanup.
- **Contract:** errored songs that are retried (`retry_errored_songs` transitions ERRORED→NOT_ERRORED, PROCESSED→NOT_PROCESSED) must not remain blocked by a stale claim. `remove_claims(remove_errored_songs=True)` releases errored-song claims so the retried song can be rediscovered. Previously (pre-intent-facade) errored songs could get stuck forever because a live worker's stale claim was never removed.
- **Note:** `_remove_claims` returns the number of rows removed; it preserves active `reconcile` claims and skips `claim_type == 'reconcile'` during song-cleanup.

### Active pending reconcile claims survive cleanup
- **Location:** `_remove_claims`; regression `test_remove_claims_preserves_active_reconcile_claims`.
- **Contract:** reconciliation claims (`claim_type == 'reconcile'`) are excluded from song-state cleanup; a pending reconcile claim is not released by `remove_completed_songs`/`remove_errored_songs`. Worker/song-filtered removals still apply.

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

### Embedding-stream race — baseline constraint, ORM/repo NOT updated (PARTIAL)
- **Location:** `alembic/versions/001_current_schema_baseline.py` (creates `uq_ml_embedding_streams_song_backbone` on (song_id, backbone_id)); `nomarr/persistence/models/ml_embedding_stream.py` (NO constraint declared); `nomarr/persistence/database/embedding_stream_repo.py:55-93` (`upsert_stream` select-then-insert-or-update; docstring at :63-65 still claims no constraint)
- **What:** Alembic-managed prod DBs enforce the unique constraint, but test DBs built via `Base.metadata.create_all` do not (schema divergence). A concurrent race in prod now surfaces as `IntegrityError` (23505 → `DuplicateEntityError`) instead of duplicate rows. `replace_embedding_stream_for_song` has zero production callers (only `test_ml_db.py:488`).
- `add_songs_to_library` state bootstrap semantics (existing_paths from DB before upsert; bootstrap only for paths not in existing_paths) are correct.

### `fetch_output_streams` silently drops rows with NULL output_index (LOW/MEDIUM latent)
- **Location:** `nomarr/components/ml/inference/ml_output_stream_store_comp.py:86-99`
- **What:** `if not isinstance(output_index, int): continue` — rows written with `output_index=None` are silently dropped, which could flip `load_output_streams_for_song` to "no streams → reprocess" (`:164-169`).

## Critical Invariants
- All claim mutation flows through the canonical intent facade (`db.app.add_claim / remove_claim / remove_claims / list_claims / count_claims`); never call repository methods, raw rows, or encoded keys from above persistence.
- Single active claim per logical song, across typed and untyped. Acquisition is insert-only when `lease_ms is None`; with a lease, expired replacement is exact-key atomic (never deletes/overwrites another row). Cross-type replacement leaves exactly one claim.
- `remove_claims` preserves active `reconcile` claims and skips `claim_type == 'reconcile'` during song-cleanup; errored/retry-eligible claims are released so retried songs are not re-blocked.
- Claim key encoding (`claim_{song_id}` / `claim_{claim_type}_{song_id}`) is persistence-internal — built/parsed only in `app_repo.py`.
- `record_scan_progress` / `complete_scan` assume a scan row exists — recovery paths guard the crash-divergence case, while normal scan setup creates the row first.
- `replace_song_inference_results` owns a full atomic replacement for (streams × (song_id, backbone)); do not pair it with separate direct stream/vector writes.

## Sources
- Files: application.py, app_repo.py, worker_claim_dataclass.py, library_scans.py, library_songs.py, song_state_repo.py, pipeline_repo.py, scan_repo.py, reconcile_paths_comp.py, ml_inference_repo.py, output_repo.py, ml_output_stream_store_comp.py, discovery_worker.py, tag_extraction_worker.py, pipeline_svc.py, library_song_state_comp.py, library_song_query_comp.py, file_batch_scanner_comp.py, library_scan_file_ops_comp.py, scan_lifecycle_comp.py, worker_discovery_comp.py, worker_tag_comp.py, reconciliation_comp.py
- Log entries: L93, L95, L97, L99, L101
