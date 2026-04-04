# Task: Fix Pre-existing Import-Linter Contract Violations

## Problem Statement

`lint-imports` reports 3 broken contracts that predate the ML reorganization:

1. **Interfaces → workflows violation:** `nomarr.interfaces.api.web.playlist_import_if` imports `PlaylistConversionError` from `nomarr.workflows.playlist_import.convert_playlist_wf`. The "Interfaces should be thin" contract forbids interfaces from importing workflows.

2. **Helpers purity violation (components):** `nomarr.helpers.tag_key_mapping` imports `get_nomarr_tag_rels` from `nomarr.components.navidrome.tag_query_comp` at runtime (line 156, inside `get_short_to_versioned_mapping`).

3. **Helpers purity violation (persistence):** `nomarr.helpers.tag_key_mapping` imports `Database` from `nomarr.persistence.db` (line 27, under `TYPE_CHECKING`), and transitively reaches persistence through the component import.

### Root causes

- `PlaylistConversionError` is a plain exception class defined in a workflow module. It belongs in `nomarr.helpers.exceptions` where all other cross-layer exceptions live.
- `get_short_to_versioned_mapping` and `resolve_short_to_versioned_keys` in `tag_key_mapping` require database access. They are component-level logic (DB query + pure-helper composition) incorrectly placed in the helpers layer. They should move to `nomarr.components.navidrome.tag_query_comp`, which already owns the underlying `get_nomarr_tag_rels` function they depend on.

## Phases

### Phase 1: Move PlaylistConversionError to helpers

- [x] Add `PlaylistConversionError` class to `nomarr/helpers/exceptions.py` (after existing exception classes)
    **Notes:** Added PlaylistConversionError class at line 26 of nomarr/helpers/exceptions.py, before SubsonicApiError.
- [x] Update import in `nomarr/workflows/playlist_import/convert_playlist_wf.py`: remove class definition, import from `nomarr.helpers.exceptions`
    **Notes:** Removed class definition (old lines 44-45). Added `from nomarr.helpers.exceptions import PlaylistConversionError` at line 40.
- [x] Update import in `nomarr/services/domain/playlist_import_svc.py`: import `PlaylistConversionError` from `nomarr.helpers.exceptions` (keep workflow function import)
    **Notes:** Split import: PlaylistConversionError now from nomarr.helpers.exceptions (line 15), convert_playlist_workflow still from workflow (line 16-18).
- [x] Update import in `nomarr/interfaces/api/web/playlist_import_if.py`: import `PlaylistConversionError` from `nomarr.helpers.exceptions` instead of the workflow
    **Notes:** Replaced workflow import with `from nomarr.helpers.exceptions import PlaylistConversionError` at line 12. Removed the 3-line workflow import block.
- [x] Run `lint_project_backend(path="nomarr/interfaces/api/web")` and `lint_project_backend(path="nomarr/workflows/playlist_import")` — zero errors required
    **Notes:** lint_project_backend on interfaces/api/web and workflows/playlist_import: 0 errors in target files. 5 pre-existing mypy errors in navidrome_song_map_aql.py (unrelated, not touched). helpers/exceptions.py: 0 errors.

### Phase 2: Move DB-dependent functions out of tag_key_mapping

- [x] Add `get_short_to_versioned_mapping` and `resolve_short_to_versioned_keys` to `nomarr/components/navidrome/tag_query_comp.py`, importing the pure helpers (`is_versioned_ml_key`, `make_short_tag_name`) from `nomarr.helpers.tag_key_mapping`
    **Notes:** Added get_short_to_versioned_mapping (lines 95-130) and resolve_short_to_versioned_keys (lines 133-151) to tag_query_comp.py. Both use lazy import of is_versioned_ml_key and make_short_tag_name from helpers.tag_key_mapping.
- [x] Remove `get_short_to_versioned_mapping`, `resolve_short_to_versioned_keys`, and the `TYPE_CHECKING` import of `Database` from `nomarr/helpers/tag_key_mapping.py`
    **Notes:** Removed TYPE_CHECKING block (Database import) and both functions (get_short_to_versioned_mapping, resolve_short_to_versioned_keys). File now 131 lines, pure helpers only with no component/persistence imports.
- [x] Update import in `nomarr/workflows/navidrome/filter_engine_wf.py`: import `resolve_short_to_versioned_keys` from `nomarr.components.navidrome.tag_query_comp`
    **Notes:** Changed import source from nomarr.helpers.tag_key_mapping to nomarr.components.navidrome.tag_query_comp. Consolidated with existing find_files_matching_tag import into single import block (lines 18-21).
- [x] Run `lint_project_backend(path="nomarr/helpers")` and `lint_project_backend(path="nomarr/components/navidrome")` — zero errors required
    **Notes:** nomarr/helpers: 0 errors, 2 files. nomarr/components/navidrome: 0 errors in target files. 5 pre-existing mypy errors in navidrome_song_map_aql.py (unrelated).

### Phase 3: Full validation

- [x] Run `lint_project_backend()` (full workspace) — zero errors required
    **Notes:** Full workspace lint: 6 errors, all pre-existing (5 in navidrome_song_map_aql.py, 1 in scripts/tools/test_musicnn_patch.py). Zero errors in files modified by this plan.
- [x] Run `lint-imports` — all 9 contracts must show KEPT
    **Notes:** lint-imports: 9 kept, 0 broken. All contracts pass.
- [x] Run `pytest -m "not container_only and not requires_database and not requires_models and not requires_audio and not requires_essentia" -x -q` — all tests pass
    **Notes:** pytest: 391 passed, 0 failed in 7.29s. All tests pass including test_filter_engine_wf (which uses resolve_short_to_versioned_keys) and test_exceptions.

## Completion Criteria

- `lint-imports` reports 9/9 contracts KEPT, 0 broken
- `lint_project_backend()` full workspace returns zero errors
- All unit tests pass
- `PlaylistConversionError` lives in `nomarr.helpers.exceptions`
- `tag_key_mapping` has zero imports from components or persistence (including TYPE_CHECKING)
- `get_short_to_versioned_mapping` and `resolve_short_to_versioned_keys` live in `nomarr.components.navidrome.tag_query_comp`

## References

- Discovered during audit of `TASK-ml-reorganize-B-wiring.md`
