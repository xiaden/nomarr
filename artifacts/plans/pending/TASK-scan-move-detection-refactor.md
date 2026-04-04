# Task: Refactor Scan Move Detection into a Stateful Accumulator

## Problem Statement

The per-folder scan loop in both `scan_library_full_wf.py` and `scan_library_quick_wf.py` is ~100 lines of tangled state management because move detection spans two passes:

1. **Per-folder (incremental pass):** after each folder is scanned, new entries are fed to `detect_file_moves` against all missing docs seen so far. Unmatched new entries accumulate in `unmatched_new`.
2. **Final pass:** after all folders, `unmatched_new` is re-checked against any remaining `missing_docs_map` entries. Only then are truly-new files inserted.

Three raw dicts/lists accumulate across the loop:

- `missing_docs_map` — files that vanished from disk (candidates for the "old path" side of a move)
- `unmatched_new` — new file entries not yet matched as a move destination
- `unmatched_new_metadata` — metadata map for those unmatched entries

This logic is **duplicated verbatim** between the two workflow files. Any bug fix or optimization must be applied twice. The workflow function bodies are hard to read as distinct phases.

The O(n) constraint (no global DB file snapshot; per-folder DB fetch + incremental matching) must be preserved. Algorithm correctness must not change.

## Phases

### Phase 1: Introduce `ScanMoveAccumulator` in `move_detection_comp.py`

- [ ] Add a `ScanMoveAccumulator` dataclass (or class with `__init__`) to `nomarr/components/library/move_detection_comp.py` that owns the three mutable state collections: `missing_docs_map`, `unmatched_new`, `unmatched_new_metadata`
- [ ] Give `ScanMoveAccumulator.__init__` two parameters: `initial_missing: dict[str, dict]` (pre-seeded from vanished folders) and `has_tagged_files: bool`
- [ ] Add `ScanMoveAccumulator.ingest_folder_result(existing_for_folder, discovered_paths, new_entries, metadata_map, db)` — this method absorbs the per-folder incremental move detection block: it updates `missing_docs_map`, runs `detect_file_moves` + `apply_detected_moves` when `has_tagged_files`, accumulates unmatched entries, and returns a `FolderIngestResult(moves_applied: int, stats: dict)` so the workflow can add to its stats
- [ ] Add `ScanMoveAccumulator.finalize(all_metadata, db, library_root)` — runs the final move pass over `unmatched_new` vs remaining `missing_docs_map`, applies moves, and returns a `FinalizeResult(truly_new: list, unmatched_new_metadata: dict, moves_applied: int, remaining_missing: dict)`. The returned `remaining_missing` replaces `missing_docs_map` in the workflow for the deletion step
- [ ] Keep `detect_file_moves`, `apply_detected_moves`, `FileMove`, and `MoveDetectionResult` unchanged — `ScanMoveAccumulator` is an orchestration layer on top of them, not a replacement

### Phase 2: Refactor `scan_library_full_wf.py` to use `ScanMoveAccumulator`

- [ ] Replace the three raw state collections (`missing_docs_map` seeding at step 4, `unmatched_new`, `unmatched_new_metadata`) with a single `accumulator = ScanMoveAccumulator(initial_missing=..., has_tagged_files=...)` constructed after step 4
- [ ] In the per-folder loop body (step 5), replace the `missing_docs_map.update(...)` + incremental `detect_file_moves` block + `elif new_entries` upsert block with a single call to `accumulator.ingest_folder_result(...)` and add its returned stats to the workflow's `stats` dict
- [ ] Replace step 6 (final move detection pass) with `finalize_result = accumulator.finalize(all_metadata, db, library_root)` and derive `truly_new`, `files_moved` delta, and the new `missing_docs_map` from the `FinalizeResult`
- [ ] Verify the upsert + seed call for `truly_new` and step 7 deletion still use the same inputs (just sourced from the accumulator result now)
- [ ] The workflow should now read as clear, labelled phases with minimal inlined logic

### Phase 3: Refactor `scan_library_quick_wf.py` to use `ScanMoveAccumulator`

- [ ] Apply an identical substitution in `scan_library_quick_wf.py` (the inner loop body and step 6 are verbatim copies of the full scan)
- [ ] Confirm the only remaining difference between the two workflow files in the per-folder section is the cache-check skip logic (`cached_folders` lookup) that belongs to the quick scan — all move-detection accumulation must be handled by the shared accumulator

### Phase 4: Verify correctness and style

- [ ] Run `lint_project_backend` on `nomarr/workflows/library/` and `nomarr/components/library/move_detection_comp.py` — zero errors required
- [ ] Confirm `ScanMoveAccumulator` and `FolderIngestResult` / `FinalizeResult` are fully type-annotated
- [ ] Confirm no logic was changed: same calls to `detect_file_moves`, `apply_detected_moves`, `upsert_scanned_files`, `seed_entities_for_scan_batch` in the same order with the same arguments — only the intermediate state management is encapsulated

## Completion Criteria

- `ScanMoveAccumulator` lives in `nomarr/components/library/move_detection_comp.py` and is the single owner of `missing_docs_map`, `unmatched_new`, and `unmatched_new_metadata` state
- Both workflow files import and use `ScanMoveAccumulator`; neither file contains inline incremental move detection logic
- The per-folder loop bodies in both workflows are 30–40 lines shorter and read as: scan folder → upsert updated entries → ingest new entries into accumulator → save folder record
- Step 6 in both workflows is a single `accumulator.finalize(...)` call
- `lint_project_backend` passes with zero errors
- Algorithm behaviour is identical: same two-pass move detection approach, same O(n) DB access pattern, no correctness change

## References

- `nomarr/workflows/library/scan_library_full_wf.py` — primary target (steps 5–6, lines ~95–230)
- `nomarr/workflows/library/scan_library_quick_wf.py` — duplication target (identical steps 5–6)
- `nomarr/components/library/move_detection_comp.py` — home for `ScanMoveAccumulator`
- `nomarr/components/library/scan_lifecycle_comp.py` — no changes needed; provides upsert/save helpers
