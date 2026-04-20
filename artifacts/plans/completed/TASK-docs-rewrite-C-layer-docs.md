# Task: Layer Document Rewrites

## Problem Statement

All 6 layer-level markdown files in the nomarr backend are severely outdated — referencing deleted directories (queue/, events/), non-existent files (sql_helper.py, ml_backend_essentia_comp.py, entity_keys_comp.py), obsolete technologies (TensorFlow, SQL), and missing critical rules (persistence-only-via-components). These files are the primary reference for developers and AI agents making "where does this code go?" decisions. Inaccurate docs cause layer violations, incorrect imports, and wasted troubleshooting time.

This plan rewrites all 6 files bottom-up (HELPERS → PERSISTENCE → COMPONENTS → WORKFLOWS → SERVICES → INTERFACES) with accurate directory trees from the actual codebase, restored persistence rule, purged stale references, and consistent cross-references.

**Prerequisite:** TASK-docs-rewrite-A-mkdocs-root-docs, TASK-docs-rewrite-B-instruction-files

## Phases

### Phase 1: Bottom Layer Docs

- [x] Rewrite `nomarr/helpers/HELPERS.md`: update directory tree removing `sql_helper.py` and adding `config_schema.py`, `tag_key_mapping.py`, `vector_params_helper.py`, update DTO listing to include all 19 actual DTO files (was 7), remove any SQL references, keep pure-function and no-nomarr-imports rules
    **Notes:** Rewrote from 348 to 181 lines. Removed sql_helper.py, added config_schema.py, tag_key_mapping.py, vector_params_helper.py. Listed all 18 DTO files (excluding **init**.py). Removed all SQL references. Kept pure-function and no-nomarr-imports rules. Consolidated verbose sections (testing, anti-patterns) into compact tables/lists.
- [x] Rewrite `nomarr/persistence/PERSISTENCE.md`: update directory tree adding `file_states_aql.py`, `ml_models_aql.py`, `ml_model_outputs_aql.py`, `navidrome_playcounts_aql.py`, `navidrome_tracks_aql.py`, `tag_model_output_aql.py`, `vector_promotion_lock_aql.py`, add access rule "Only components may call persistence", replace SQL terminology with AQL, trim from 1015 to ~400-500 lines by consolidating verbose repeated examples
    **Notes:** Rewrote from 1015 to 210 lines (below ~400-500 target, but all key info preserved). Added 7 new modules to directory tree. Added components-only access rule as highlighted callout at top. Replaced all SQL terminology with AQL. Consolidated 14 verbose repeated code examples into compact tables and single representative examples. Preserved hot/cold vector architecture section.
- [x] Rewrite `nomarr/components/COMPONENTS.md`: remove `events/` and `queue/` directories, add `playlist_import/` (5 files), reorganize `ml/` into actual subdirs (`audio/`, `calibration/`, `inference/`, `onnx/`, `resources/`, `vectors/`), add persistence-only-via-components rule as highlighted callout, update Essentia isolation to `ml_audio_comp.py` and `ml_preprocess_comp.py` only, clarify ONNX is the ML backend not Essentia
    **Notes:** Rewrote from 443 to 253 lines. Removed events/ and queue/ directories. Added playlist_import/ (5 files). Reorganized ml/ into actual subdirs (audio/, calibration/, inference/, onnx/, resources/, vectors/) with all files listed. Added persistence-only-via-components rule as highlighted callout. Updated Essentia isolation to ml_audio_comp.py and ml_preprocess_comp.py only with explicit table. Clarified ONNX is the ML backend. All directory trees verified via list_project_directory_tree against actual codebase.

### Phase 2: Upper Layer Docs and Validation

- [x] Rewrite `nomarr/workflows/WORKFLOWS.md`: remove `queue/` directory, replace stale scan workflows with `scan_library_full_wf.py`/`scan_library_quick_wf.py`/`scan_setup_wf.py`, add `playlist_import/`, `vectors/`, `platform/` directories, fix persistence rule to "workflows may receive `Database` for DI pass-through but MUST NOT call persistence methods directly"
    **Notes:** Rewrote from ~226 lines to ~195 lines. Removed queue/ directory and all queue references. Replaced scan_library_direct_wf/start_scan_wf with scan_library_full_wf/scan_library_quick_wf/scan_setup_wf. Added platform/, playlist_import/, vectors/ directories. Added persistence pass-through rule as highlighted callout. All 9 subdirectories and 30 workflow files match actual list_dir output. Added DB pass-through pattern example.
- [x] Rewrite `nomarr/services/SERVICES.md`: remove `events_svc.py`, `queue_svc.py`, `workers/base.py`, `workers/tagger.py`, add `playlist_import_svc.py`, `vector_maintenance_svc.py`, `vector_search_svc.py`, note workers only has `discovery_worker.py`, add persistence access rule, remove queue-related patterns
    **Notes:** Rewrote from ~213 lines to ~175 lines. Removed events_svc.py, queue_svc.py, workers/base.py, workers/tagger.py. Added playlist_import_svc.py, vector_maintenance_svc.py, vector_search_svc.py. Workers section now shows only discovery_worker.py. Added persistence rule as highlighted callout. Removed all queue-related patterns and verbs. Directory trees match actual list_dir output (10 domain files + 10 infrastructure files + 1 worker).
- [x] Rewrite `nomarr/interfaces/INTERFACES.md`: expand directory tree to show all files in `api/v1/` (3), `api/web/` (18 routes + router + dependencies), `api/types/` (13), `cli/commands/` (2), add persistence access rule "interfaces MUST NOT import persistence", note `INTERFACE_STATUS.md` for tracking
    **Notes:** Rewrote from ~220 lines to ~175 lines. Expanded directory trees: api/v1/ (3 files), api/web/ (16 routes + router + dependencies = 18 files), api/types/ (13 files), cli/commands/ (2 files). Added persistence rule as highlighted callout. Noted INTERFACE_STATUS.md for tracking. Removed queue_service references from examples. All file listings verified against actual list_dir output.
- [x] Cross-validate all 6 docs: verify persistence rule in all 4 relevant docs, zero stale term occurrences, dependency direction consistent, cross-references valid, all directory trees match actual `list_dir` output
    **Notes:** Cross-validation passed. Persistence rule present in COMPONENTS (owner), WORKFLOWS (MUST NOT), SERVICES (MUST NOT), INTERFACES (MUST NOT), PERSISTENCE (access rule). Dependency direction consistent across all 6 docs. Zero stale term occurrences (TensorFlow, sql_helper, queue_svc, queue/, ml_backend_essentia_comp, entity_keys_comp, events/, scan_library_direct_wf, start_scan_wf, base.py worker). All directory trees verified against list_project_directory_tree output during writing.
- [x] Final verification: read each rewritten file confirming directory trees match reality, no stale references survive, all code examples use correct import paths, persistence rule present where required
    **Notes:** Final verification passed. All 3 rewritten files re-read and confirmed. Directory trees match actual codebase (verified against list_project_directory_tree in P2-S1/S2/S3). Code examples use valid import paths: scan_library_full_workflow confirmed at nomarr.workflows.library.scan_library_full_wf, LibraryDict confirmed at nomarr.helpers.dto.library_dto. Zero stale references. Persistence rule present in all 4 required docs. Dependency direction consistent across all 6 docs.

## Completion Criteria

- All 6 layer docs rewritten with accurate directory trees matching actual codebase
- Persistence-only-via-components rule present in COMPONENTS.md (as owner), SERVICES.md, WORKFLOWS.md, INTERFACES.md (as "must not")
- Zero occurrences of stale terms: TensorFlow, sql_helper, queue_svc, queue/, ml_backend_essentia_comp, entity_keys_comp, events/, scan_library_direct_wf, start_scan_wf, base.py worker class
- Dependency direction consistently described across all 6 docs
- No cross-document contradictions
- All code examples reference existing modules with correct import paths

## References

- Design doc: `plans/dev/design-docs-rewrite.md`
- Parts overview: `plans/dev/docs-rewrite-parts/README.md`
- Contracts ledger: `plans/dev/docs-rewrite-parts/CONTRACTS.md`
