# Task: Streaming Scan Pipeline B — Parallel Folder Processing

## Problem Statement

After Plan A converts the scan pipeline to per-folder DB queries and incremental move detection, folder processing is still sequential: each folder's filesystem walk, metadata extraction, and `get_files_for_folder` DB query runs one at a time. For a library with ~1000 folders this is an I/O bottleneck.

**Prerequisite:** `TASK-streaming-scan-pipeline-A-per-folder-pipeline.md` must be complete. This plan builds directly on the `ScanFolderResult` structure, per-folder DB queries, and incremental move detection introduced there.

**Goal:** Use a `ThreadPoolExecutor` to process multiple folders concurrently. Workers handle per-folder I/O (disk reads + DB query). The main thread accumulates `ScanFolderResult` objects as futures complete, appending missing docs and running incremental move detection in arrival order. All post-loop operations remain sequential and unchanged from Plan A.

**Incremental move detection in parallel context:**
Workers return `new_entries` and `missing_file_docs` in `ScanFolderResult`. The main thread — not workers — performs all accumulation and move detection as futures complete via `as_completed`. No locks needed: only the main thread writes to `missing_docs`, `unmatched_new`, and move results.

## Phases

### Phase 1: Parallel folder execution

- [ ] Add `ScanFolderResult` dataclass to `nomarr/components/library/folder_analysis_comp.py` — fields: `folder` (FolderMetadata), `batch` (FolderScanBatch), `missing_file_docs` (list[dict]); returned by the worker task
- [ ] Add `scan_single_folder_task(db, folder, library_root, library_id, existing_files, tagger_version, min_duration_s)` to `nomarr/components/library/file_batch_scanner_comp.py` — calls `scan_folder_files` with provided `existing_files`; queries `get_files_for_folder` to populate `missing_file_docs` (DB files for this folder not in `batch.discovered_paths`); retries once on any exception before marking folder failed; returns `ScanFolderResult`
- [ ] Replace sequential folder loop in `scan_library_full_workflow` with `ThreadPoolExecutor(max_workers=4)`; submit `scan_single_folder_task` per folder (passing per-folder `existing_files` from `get_files_for_folder`); collect via `concurrent.futures.as_completed`
- [ ] Replace sequential folder loop in `scan_library_quick_workflow` with the same pattern; cache-check (skip unchanged folders) happens on the main thread before submitting each folder to the pool
- [ ] Add `threading.BoundedSemaphore(32)` submission guard in both workflows: acquire before `executor.submit`, release via `future.add_done_callback`; prevents more than 32 in-flight futures regardless of library size
- [ ] On the main thread as each future completes: call `future.result()` to get `ScanFolderResult`; append `result.missing_file_docs` to `missing_docs`; if `has_tagged_files` and `result.batch.new_entries` is non-empty, run `detect_file_moves(result.batch.new_entries, missing_docs)`; matched moves recorded; unmatched appended to `unmatched_new`
- [ ] Move `save_folder_record` out of the parallel loop; after executor exits collect `(rel_path, mtime, file_count)` from all results and call `save_folder_record` sequentially
- [ ] Confirm all post-loop operations remain strictly sequential: vanished-folder diff, `detect_file_moves(unmatched_new, missing_docs)` final pass, `apply_detected_moves`, deferred upserts, `cleanup_stale_folders`, entity cleanup, tag validation
- [ ] Call `update_scan_progress` on the main thread after each future completes, passing running `len(discovered_paths)` from accumulated results
- [ ] Run `lint_project_backend` on `nomarr/components/library` and `nomarr/workflows/library`

### Phase 2: Validation

- [ ] Run full scan; confirm first folder processed within 10 seconds and wall-clock total faster than Plan A baseline
- [ ] Run quick scan on unchanged library; confirm all folders skipped, scan completes in under 5 seconds
- [ ] Rename a folder and run quick scan; verify files detected as moved (not deleted + re-added)
- [ ] Rename every folder in a two-level subtree and run full scan; verify all files detected as moved via combined incremental + final pass
- [ ] Confirm no stale folder records or orphaned entities after parallel scan
- [ ] Run `lint_project_backend` on full workspace

## Completion Criteria

- Folder I/O (disk + DB reads) runs up to 4 folders concurrently
- Backpressure caps in-flight futures at 32
- All accumulation and move detection on main thread only — no shared mutable state inside workers
- Incremental move detection fires per arrived result on main thread; each new file checked once during loop; unmatched deferred to final pass
- Post-loop operations identical to Plan A (sequential, correct)
- All lint checks pass

## References

- Prerequisite plan: `TASK-streaming-scan-pipeline-A-per-folder-pipeline.md`
- `nomarr/components/library/file_batch_scanner_comp.py` — `scan_single_folder_task` goes here
- `nomarr/components/library/folder_analysis_comp.py` — `ScanFolderResult` dataclass goes here
- `nomarr/workflows/library/scan_library_full_wf.py`
- `nomarr/workflows/library/scan_library_quick_wf.py`
