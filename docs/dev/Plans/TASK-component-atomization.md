# Task: Component Atomization (One Export Per File)

## Problem Statement

Components are currently grouped by apparent domain but the tools themselves are multi-domain. This makes future domain hardening difficult because you can't easily re-sort when tools are bundled together in "cohesive" files.

**The goal:** Atomize components to one-export-per-file, then re-group correctly during domain hardening refactor.

**Secondary rule:** No private helpers in components. The presence of a private helper indicates that workflow logic has leaked into the component. Each component should be a single pure computational tool.

## Current State Analysis

### Summary by Violation Type

| Category | Count | Files |
|----------|-------|-------|
| Multi-export (2+ public exports) | 18 | See Phase 2 |
| Has private helpers/classes | 2 | `tagging_writer_comp.py`, `gpu_monitor_comp.py` |
| Classes that should be functions | 5 | See Phase 3 |
| Already compliant (1 export) | 11 | No action needed |

### Multi-Export Components (Need Splitting)

1. **analytics_comp.py** - 5 exports: `compute_artist_tag_profile`, `compute_mood_distribution`, `compute_tag_co_occurrence`, `compute_tag_correlation_matrix`, `compute_tag_frequencies`

2. **path_comp.py** - 3 exports: `build_library_path_from_db`, `build_library_path_from_input`, `get_library_root`

3. **library_admin_comp.py** - 4 exports: `clear_library_data`, `create_library`, `delete_library`, `update_library_root`

4. **library_root_comp.py** - 4 exports: `ensure_no_overlapping_library_root`, `get_base_library_root`, `normalize_library_root`, `resolve_path_within_library`

5. **metadata_extraction_comp.py** - 3 exports: `compute_chromaprint_for_file`, `extract_metadata`, `resolve_artists`

6. **search_files_comp.py** - 3 exports: `get_unique_tag_keys`, `get_unique_tag_values`, `search_library_files`

7. **tag_cleanup_comp.py** - 2 exports: `cleanup_orphaned_tags`, `get_orphaned_tag_count`

8. **entity_cleanup_comp.py** - 2 exports: `cleanup_orphaned_tags`, `get_orphaned_tag_count` (duplicate of above?)

9. **metadata_cache_comp.py** - 2 exports: `rebuild_all_song_metadata_caches`, `rebuild_song_metadata_cache`

10. **ml_audio_comp.py** - 2 exports: `load_audio_mono`, `should_skip_short`

11. **ml_backend_essentia_comp.py** - 3 exports: `get_version`, `is_available`, `require`

12. **ml_cache_comp.py** - 13 exports: `backbone_cache_key`, `cache_backbone_predictor`, `cache_key`, `check_and_evict_idle_cache`, `clear_predictor_cache`, `get_backbone_cache_size`, `get_cache_idle_time`, `get_cache_size`, `get_cached_backbone_predictor`, `is_initialized`, `touch_cache`, `warmup_predictor_cache`

13. **ml_calibration_comp.py** - 10 exports: Various calibration functions

14. **ml_discovery_comp.py** - 4 exports + 2 classes: `compute_model_suite_hash`, `discover_heads`, `get_embedding_output_node`, `get_head_output_node`, `HeadInfo`, `Sidecar`

15. **ml_embed_comp.py** - 3 exports + 1 class: `pool_scores`, `score_segments`, `segment_waveform`, `Segments`

16. **ml_heads_comp.py** - 6 exports + 3 classes: Decision functions and specs

17. **ml_inference_comp.py** - 3 exports: `compute_embeddings_for_backbone`, `make_head_only_predictor_batched`, `make_predictor_uncached`

18. **ml_tier_selection_comp.py** - 2 exports + 3 classes: `get_tier_description`, `select_execution_tier`

19. **arango_first_run_comp.py** - 4 exports: `get_root_password_from_env`, `is_first_run`, `provision_database_and_user`, `write_db_config`

20. **resource_monitor_comp.py** - 7 exports + 1 class: Various resource monitoring functions

21. **tag_normalization_comp.py** - 3 exports: `normalize_id3_tags`, `normalize_mp4_tags`, `normalize_vorbis_tags`

22. **tagging_aggregation_comp.py** - 6 exports: Various aggregation functions

23. **tagging_reader_comp.py** - 3 exports: `infer_write_mode_from_tags`, `read_nomarr_namespace`, `read_tags_from_file`

24. **worker_crash_comp.py** - 2 exports + 1 class: `calculate_backoff`, `should_restart_worker`

25. **worker_discovery_comp.py** - 6 exports: `claim_file`, `cleanup_stale_claims`, `discover_and_claim_file`, `discover_next_file`, `get_active_claim_count`, `release_claim`

26. **templates_comp.py** - 7 exports: Various template getters

### Components with Private Helpers (Workflow Logic Leakage)

1. **tagging_writer_comp.py** - Contains `_MP3Writer`, `_MP4Writer`, `_VorbisWriter` private classes with `_clear_ns`, `_ff_key`, `_vorbis_key` helpers. These are format-specific implementations - may need refactoring to individual format components.

2. **gpu_monitor_comp.py** - Contains `_send_heartbeat` helper method in class. This is a process class, may be exempt.

### Classes That Should Potentially Be Functions

Some components export classes where functions might be cleaner:
- `HealthComp` - has `__init__` + `get_all_workers`, `get_component`
- `ListLibrariesComp` - has `__init__` + `list`
- `UpdateLibraryMetadataComp` - has `__init__` + `update`
- `TagWriter` - has state (`overwrite`, `namespace`)
- `GPUHealthMonitor` - stateful process (may be exempt)

### Already Compliant (1 Export)

- `file_tags_comp.py` - 1 function
- `reconcile_paths_comp.py` - 1 function
- `scan_target_validator_comp.py` - 1 function
- `entity_seeding_comp.py` - 1 function
- `chromaprint_comp.py` - 1 function
- `arango_bootstrap_comp.py` - 1 function
- `gpu_probe_comp.py` - 1 function
- `tag_parsing_comp.py` - 1 function
- `tagging_remove_comp.py` - 1 function
- `safe_write_comp.py` - 1 function + result class (acceptable - result is DTO)
- `folder_analysis_comp.py` - 1 function + 2 result classes (acceptable - results are DTOs)
- `file_batch_scanner_comp.py` - 1 function + 1 result class (acceptable - result is DTO)
- `move_detection_comp.py` - 1 function + 2 result classes (acceptable - results are DTOs)

## Phases

### Phase 1: Update Instructions and Linting

- [ ] Update `components.instructions.md` to enforce one-export-per-file rule
- [ ] Update `components.instructions.md` to prohibit private helpers
- [ ] Create/update `check_naming.py` for components to validate single public export
- [ ] Add lint check for private helper detection

**Notes:**

### Phase 2: Split Multi-Export Components

For each multi-export component, create subdirectory and split:

**Pattern:** `analytics_comp.py` → `analytics/compute_tag_frequencies_comp.py`, etc.

- [ ] Split `analytics_comp.py` (5 → 5 files)
- [ ] Split `path_comp.py` (3 → 3 files)
- [ ] Split `library_admin_comp.py` (4 → 4 files)
- [ ] Split `library_root_comp.py` (4 → 4 files)
- [ ] Split `metadata_extraction_comp.py` (3 → 3 files)
- [ ] Split `search_files_comp.py` (3 → 3 files)
- [ ] Split `tag_cleanup_comp.py` (2 → 2 files)
- [ ] Resolve duplicate: `entity_cleanup_comp.py` vs `tag_cleanup_comp.py`
- [ ] Split `metadata_cache_comp.py` (2 → 2 files)
- [ ] Split `ml_audio_comp.py` (2 → 2 files)
- [ ] Split `ml_backend_essentia_comp.py` (3 → 3 files)
- [ ] Split `ml_cache_comp.py` (13 → individual files OR reconsider as stateful cache class)
- [ ] Split `ml_calibration_comp.py` (10 → individual files)
- [ ] Split `ml_discovery_comp.py` (4 functions + 2 classes → individual files)
- [ ] Split `ml_embed_comp.py` (3 functions + 1 class → individual files)
- [ ] Split `ml_heads_comp.py` (6 functions + 3 classes → individual files)
- [ ] Split `ml_inference_comp.py` (3 → 3 files)
- [ ] Split `ml_tier_selection_comp.py` (2 functions + 3 classes → individual files)
- [ ] Split `arango_first_run_comp.py` (4 → 4 files)
- [ ] Split `resource_monitor_comp.py` (7 functions + 1 class → individual files)
- [ ] Split `tag_normalization_comp.py` (3 → 3 files)
- [ ] Split `tagging_aggregation_comp.py` (6 → 6 files)
- [ ] Split `tagging_reader_comp.py` (3 → 3 files)
- [ ] Split `worker_crash_comp.py` (2 functions + 1 class → individual files)
- [ ] Split `worker_discovery_comp.py` (6 → 6 files)
- [ ] Split `templates_comp.py` (7 → 7 files OR keep as single template registry)

**Notes:**

### Phase 3: Refactor Private Helpers to Separate Components

- [ ] Refactor `tagging_writer_comp.py` - extract `_MP3Writer`, `_MP4Writer`, `_VorbisWriter` to separate format-specific components
- [ ] Review `gpu_monitor_comp.py` - `_send_heartbeat` may be acceptable for process class

**Notes:**

### Phase 4: Convert Class Components to Functions (Where Appropriate)

- [ ] `HealthComp` → `get_all_workers()`, `get_component()` functions
- [ ] `ListLibrariesComp` → `list_libraries()` function
- [ ] `UpdateLibraryMetadataComp` → `update_library_metadata()` function
- [ ] Evaluate `TagWriter` - stateful, may need to remain class

**Notes:**

### Phase 5: Update All Imports

After splitting, all callers need import updates:

- [ ] Update workflow imports
- [ ] Update service imports
- [ ] Update `__init__.py` re-exports for backward compatibility (temporary)
- [ ] Run `lint_backend(check_all=True)` to verify no breakage

**Notes:**

### Phase 6: Validation

- [ ] `lint_backend(path="nomarr/components")` passes
- [ ] `lint_backend(check_all=True)` passes (full codebase)
- [ ] All component files have exactly one public export
- [ ] No private helpers exist in components

## Completion Criteria

1. Every `*_comp.py` file exports exactly one public function/class
2. No `def _*` or `class _*` patterns exist in components (except `__init__`, `__post_init__`)
3. All linting passes
4. All imports updated across codebase
5. Instructions file updated with new rules

## Decision Log

- **DTOs bundled with function are OK:** A component like `safe_write_comp.py` that exports `safe_write_tags()` + `SafeWriteResult` is compliant because the result class is a DTO for that specific function.

- **ml_cache consideration:** The 13-export `ml_cache_comp.py` might be better as a stateful class with these as methods. To be decided during Phase 2.

- **templates_comp consideration:** May be better as a template registry class rather than 7 individual files. To be decided during Phase 2.

## Estimated Scope

- **~40 files to create** (splitting multi-export components)
- **~25 existing files to modify** (removing multi-exports)
- **~50+ import updates** in workflows/services
- **2-3 instruction file updates**
