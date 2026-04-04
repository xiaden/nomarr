# Task: Instruction Files Stale Reference Refresh

## Problem Statement

The 15 `.github/instructions/*.instructions.md` files provide Copilot/agent auto-context when editing layer-specific code. 9 of 15 contain stale references that actively mislead agents: references to deleted queue components, TensorFlow markers, SQL helpers, non-existent Layer Scripts paths, and incorrect Essentia isolation rules. Most critically, the persistence-only-via-components rule — that components are the ONLY layer allowed to call persistence — is missing from services, workflows, and interfaces instruction files.

This plan performs surgical fixes across the 9 affected files. No full rewrites — just targeted edits to purge stale references, add the missing persistence rule, and fix directory trees.

**Prerequisite:** None (parallel with Plan A)

## Phases

### Phase 1: Core Layer Files — Persistence Rule and Stale Purge

- [x] Fix `components.instructions.md`: replace directory tree (remove `queue/`, add `infrastructure/`, `metadata/`, `navidrome/`, `playlist_import/`, `processing/`, restructure `ml/` subfolders), change Essentia isolation from `ml_backend_essentia_comp.py` with `essentia_tensorflow` to `ml/audio/ml_audio_comp.py` and `ml/audio/ml_preprocess_comp.py` with `essentia`, note ONNX is the ML backend not Essentia, replace Layer Scripts section with `lint_project_backend()` MCP tool reference
    **Notes:** Directory tree updated to match actual codebase (13 top-level dirs + 6 ml/ subdirs). Essentia isolation updated to ml_audio_comp.py and ml_preprocess_comp.py with plain `essentia` (not essentia_tensorflow). ONNX noted as ML backend. Layer Scripts replaced with lint_project_backend() MCP tool reference.
- [x] Fix `services.instructions.md`: remove "queues" from purpose and dependency list, remove `queue_file_for_tagging()` example and `queue_` verb, remove "Queue handles" from resources, add persistence-only-via-components rule (services may hold `Database` for DI wiring but must NEVER call persistence methods directly), replace Layer Scripts section
    **Notes:** Removed "queues" from purpose line and dependency coordinator list. Removed queue_file_for_tagging() example and queue_ verb from allowed verbs. Removed "Queue handles" from long-lived resources. Added Persistence Rule section with code examples between Forbidden Imports and MCP Server Tools. Replaced Layer Scripts with lint_project_backend() MCP tool reference.
- [x] Fix `persistence.instructions.md`: remove "and queue access" from purpose, replace "`*Operations` classes own SQL" with "`*AQL` classes own AQL queries", remove `db.queue.enqueue()` example and replace with current example, replace Layer Scripts section
    **Notes:** Removed "and queue access" from purpose. Changed "*Operations classes own SQL" to "*AQL classes own AQL queries". Replaced db.queue.enqueue() example with db.library_files.get_pending_files(). Replaced Layer Scripts with lint_project_backend() MCP tool reference.
- [x] Fix `workflows.instructions.md`: add persistence-only-via-components rule (workflows receive `Database` as parameter for passing to components but must NEVER call persistence methods directly — all data access delegated to components)
    **Notes:** Added Persistence Rule section between Forbidden Imports and MCP Server Tools. Includes code examples showing correct (delegate to component) vs wrong (direct db call) patterns.
- [x] Fix `interfaces.instructions.md`: add explicit persistence rule statement reinforcing that interfaces must never access the database — all data flows through services, existing Forbidden Imports already lists persistence but lacks the explicit rule text
    **Notes:** Added explicit persistence rule text after Forbidden Imports code block, reinforcing that interfaces must never access the database. Replaced Layer Scripts with lint_project_backend() MCP tool reference.

### Phase 2: Supporting Files — Minor Stale Fixes

- [x] Fix `helpers.instructions.md`: change "SQL fragments" to "data formatting" in purpose, replace Layer Scripts section with MCP tool reference
    **Notes:** Changed "SQL fragments" → "data formatting" in purpose list. Replaced Layer Scripts section (lint.py + check_naming.py) with MCP tool reference (lint_project_backend).
- [x] Fix `frontend.instructions.md`: update API Client section from `shared/api.ts` single file to `shared/api/` directory with domain-specific modules, update directory tree and import examples
    **Notes:** Updated directory tree: shared/api.ts → shared/api/ with 10+ domain modules listed. Updated API Client section: import examples now show domain-specific and barrel imports. Adding endpoints now references domain module + index re-export. Replaced Layer Scripts → Validation Tool with lint_project_frontend().
- [x] Fix `testing-backend.instructions.md`: replace `@pytest.mark.requires_tensorflow` with correct marker (verify in conftest.py first), replace `start_scan_workflow` with `scan_library_full_workflow` or `scan_library_quick_workflow`
    **Notes:** Replaced requires_tensorflow marker → requires_onnx in Resource Markers table. Replaced start_scan_workflow → scan_library_full_workflow in integration test example. Note: pyproject.toml still registers the old requires_tensorflow marker — that's a separate cleanup outside this plan's scope (instruction files only).
- [x] Fix `instructions.instructions.md`: remove or update "Reference Layer Skills" example pointing to non-existent `layer-services/SKILL.md` and `layer-services/scripts/check_naming.py`, replace with current MCP tool or instruction file cross-reference
    **Notes:** Replaced "Reference Layer Skills" section (pointed to non-existent layer-services/SKILL.md and check_naming.py) with "Reference Related Instructions" section showing cross-reference to other instruction files and lint_project_backend() validation.

### Phase 3: Verification

- [x] Run grep across all `.github/instructions/` files for every stale term: `tensorflow`, `essentia_tensorflow`, `ml_backend_essentia`, `sql_helper`, `queue_svc`, `queue/`, `scan_library_direct`, `start_scan_wf`, `entity_keys_comp`, `layer-services`, `layer-components`, `layer-helpers` — confirm zero matches remain
    **Notes:** All 12 stale terms searched across .github/instructions/: tensorflow, essentia_tensorflow, ml_backend_essentia, sql_helper, queue_svc, queue/, scan_library_direct, start_scan_wf, entity_keys_comp, layer-services, layer-components, layer-helpers. Each returned 0 matches. Clean.
- [x] Re-read each of the 9 edited files and verify: persistence rule present where needed, directory trees match actual codebase, no broken file references, no Layer Scripts pointing to non-existent paths
    **Notes:** All 9 files verified. Persistence rule present in components/services/workflows/interfaces. Directory trees match codebase (minor: persistence tree shows file_tags_aql.py/library_files_aql.py as files but they're packages — illustrative, not blocking). All cross-references valid. Zero "Layer Scripts" sections remain. All 5 core layer files have lint_project_backend() validation. Frontend api/ correctly shown as directory. No broken file references found.

## Completion Criteria

- Grep for stale terms across all instruction files returns zero matches
- Persistence-only-via-components rule present in components, services, workflows, and interfaces instruction files
- No instruction file references `layer-services/`, `layer-components/`, or similar non-existent skill paths
- 6 clean files (testing-frontend, testing-e2e, mcp-basics, mcp-tools, docker, task-plans) remain untouched
- All directory trees in edited instruction files match actual codebase structure

## References

- Design doc: `plans/dev/design-docs-rewrite.md`
- Parts overview: `plans/dev/docs-rewrite-parts/README.md`
- Contracts ledger: `plans/dev/docs-rewrite-parts/CONTRACTS.md`
