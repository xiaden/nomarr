# Task: Streaming Scan Pipeline A — Per-Folder Pipeline

## Problem Statement

Library scans currently block for 60-90 seconds before any files are processed. Two operations cause this:

1. **Folder discovery** walks the entire library filesystem synchronously before processing starts
2. **DB snapshot** (`snapshot_existing_files`) loads ALL library files (~29K) into memory via a single `limit=1_000_000` query before any folder is processed

This defeats the purpose of having a database and creates poor UX ("scanning" with no visible progress).

**Goal:** Eliminate the pre-scan file snapshot. Replace it with per-folder DB queries, a lightweight folder-set diff for vanished folders, and incremental move detection during the scan loop so `deferred_new_entries` stays small.

**Scan flow after this plan:**

1. `discover_library_folders` runs as before (fast — stat calls only) returning `all_discovered_folders`
2. Pre-scan DB calls: `get_folder_rel_paths` (vanished folder diff), `library_has_tagged_files`, `count_library_files` (progress total), `get_cached_folders` (quick scan only)
3. Compute `vanished = db_folder_paths - discovered_folder_paths`; fetch their file docs via `get_files_for_folders` (imported as `get_files_for_missing_folders`) → seed initial `missing_docs` list
4. Per-folder loop: `get_files_for_folder` → `scan_folder_files` → append per-folder missing docs to `missing_docs` → if `has_tagged_files` and new files found, run `detect_file_moves(new_files, missing_docs)` → matched moves recorded and removed from both sides; unmatched new files appended to `unmatched_new`
5. Post-loop: `detect_file_moves(unmatched_new, remaining_missing_docs)` → apply all moves, upsert remaining unmatched new files, remove remaining missing

**Key constraint:** Each new file gets exactly one move-detection attempt during the loop. Unmatched files go to `unmatched_new` and are not re-checked until the final pass.

## Phases

### Phase 1: Persistence methods

- [x] Add `get_folder_rel_paths(library_id)` to `nomarr/persistence/database/library_files_aql/queries.py` — returns `set[str]` of folder rel_path strings known to DB for a library
- [x] Add `get_files_for_folder(library_id, folder_rel_path)` to `library_files_aql` — returns `dict[str, dict]` of `path → file_doc` for one folder
- [x] Add `get_files_for_folders(library_id, folder_rel_paths)` to `library_files_aql` — batch fetch file docs for a list of folder rel_paths; imported as `get_files_for_missing_folders` at workflow call sites
- [x] Add `count_library_files(library_id)` to `library_files_aql` — returns total file count for a library (used for progress total at scan start)
- [x] Run `lint_project_backend` on `nomarr/persistence`

### Phase 2: Workflow rewrite

- [x] Update `scan_library_full_workflow`: run pre-scan DB calls (`get_folder_rel_paths`, `library_has_tagged_files`, `count_library_files`); compute vanished folders and seed `missing_docs` via `get_files_for_missing_folders`; replace snapshot call with `get_files_for_folder` per folder in loop; implement incremental `detect_file_moves` + `unmatched_new` accumulator in loop; replace final `detect_missing_files` call with post-loop `detect_file_moves(unmatched_new, missing_docs)` pass
- [x] Update `scan_library_quick_workflow` with the same pattern; add `get_cached_folders` to pre-scan DB calls (one call, result passed into loop for cache-check per folder — not queried per folder)
- [x] Wrap each folder's `get_files_for_folder` + `scan_folder_files` block in per-folder try/except; on exception retry once; if retry also fails log the folder as failed and continue scan (do not abort)
- [x] Remove `snapshot_existing_files` call from both workflows
- [x] Remove `detect_missing_files` call from both workflows (replaced by per-folder accumulation + vanished-folder diff); leave the function in place for now
- [x] Remove `plan_full_scan` and `plan_incremental_scan` from both workflows (logic inlined); `discover_library_folders` stays unchanged — no generator conversion
- [x] Run `lint_project_backend` on `nomarr/workflows/library` and `nomarr/components/library`

### Phase 3: Validation

- [ ] Run full scan on test library; verify move detection, short file healing, and missing file removal all work correctly
- [ ] Rename a folder on disk and run quick scan; verify files appear as moved (not deleted + re-added)
- [ ] Rename every folder in a two-level subtree (simulating full library restructure) and run full scan; verify all files detected as moved, not deleted
- [ ] Delete a folder on disk and run quick scan; verify files are removed
- [ ] Run quick scan immediately after full scan; verify unchanged folders are all skipped
- [ ] Confirm first folder is processed within 10 seconds of scan start
- [x] Run `lint_project_backend` on full workspace

## Completion Criteria

- No pre-scan global file snapshot — file lookups are per-folder or seeded from vanished-folder fetch
- `has_tagged_files`, progress total, and cached folders all fetched as explicit pre-scan calls (not bundled in snapshot)
- Vanished folders detected via folder-set diff before scan loop starts
- Incremental move detection during loop; each new file checked once; unmatched deferred to final pass
- Per-folder errors retry once then continue (scan does not abort on single folder failure)
- Quick scan cache-check uses one upfront `get_cached_folders` call, not per-folder queries
- Both quick and full scans pass functional tests (moves detected, missing removed, unchanged skipped)
- All lint checks pass

## References

- `nomarr/components/library/folder_analysis_comp.py` — folder discovery
- `nomarr/components/library/scan_lifecycle_comp.py` — `snapshot_existing_files` (to be removed)
- `nomarr/components/library/missing_file_detection_comp.py` — `detect_missing_files` call to be removed
- `nomarr/persistence/database/library_files_aql/queries.py` — new persistence methods go here
- `nomarr/workflows/library/scan_library_full_wf.py`
- `nomarr/workflows/library/scan_library_quick_wf.py`
