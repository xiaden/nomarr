# Task: Docs Rewrite Part D — Subdomain README Files

## Problem Statement

Only the 6 top-level layer folders in `nomarr/` have documentation (LAYER.md files, rewritten in Plan C). The ~35 subfolders beneath them — where developers and agents actually land when navigating code — have zero orientation. A developer opening `components/ml/onnx/` or `persistence/database/tags_aql/` today finds only Python files with no explanation of the folder's purpose, boundaries, key modules, or relationships. This plan creates a README.md in every code-containing subfolder, following a consistent template that complements the LAYER.md files above them.

**Prerequisite:** TASK-docs-rewrite-C-layer-docs (layer docs must be accurate before subdomain docs reference them)

## Phases

### Phase 1: Components ML Subdomain (7 READMEs)

- [x] Create READMEs for `components/ml/` and its 6 subfolders (`audio/`, `calibration/`, `inference/`, `onnx/`, `resources/`, `vectors/`): the ML root README must describe the subsystem architecture (audio loading → preprocessing → ONNX inference → vector storage), Essentia isolation rule (only `ml_audio_comp.py` and `ml_preprocess_comp.py`), and ONNX-as-backend rule; each subfolder README covers its modules, key patterns (e.g., session caching in `onnx/`, VRAM coordination in `resources/`, hot/cold tiers in `vectors/`), and upstream/downstream relationships within the ML pipeline
    **Notes:** Created 7 READMEs: ml/ (root, 46 lines), audio/ (31), calibration/ (31), inference/ (34), onnx/ (38), resources/ (35), vectors/ (35). Pipeline architecture diagram in root README. Essentia isolation rule documented in root and audio/ READMEs.
- [x] Create READMEs for `components/library/` (18 modules — scanning lifecycle, file sync, move detection, batch scanning, metadata extraction, search, tag cleanup), `components/tagging/` (9 modules — parsing, normalization, reconstruction, writing, removal, mood labels, aggregation), and `components/workers/` (discovery-based claim logic, crash recovery): each README lists all modules with purpose, documents domain-specific patterns, and notes that these components call persistence directly
    **Notes:** Created 3 READMEs: library/ (50 lines, 18 modules listed), tagging/ (41 lines, 9 modules listed), workers/ (30 lines, 2 modules listed). All note "calls persistence directly" in dependencies. Library has 18 modules (plan said 18), tagging has 9 (plan said 9), workers has 2 (discovery + crash).

### Phase 2: Remaining Components (7 READMEs)

- [x] Create READMEs for `components/analytics/` (3 modules — collection stats, mood analysis, overview), `components/infrastructure/` (health checks, path resolution), `components/metadata/` (entity cleanup, seeding, cache), `components/navidrome/` (7 modules — Subsonic client, playlist builder, M3U, tag queries, taste profiles, crawling, templates), `components/platform/` (ArangoDB bootstrap, GPU monitoring, migration runner, resource monitor), `components/playlist_import/` (Spotify/Deezer fetching, track matching, URL parsing, metadata normalization), and `components/processing/` (file write operations)
    **Notes:** Created 7 READMEs: analytics/ (31 lines), infrastructure/ (29 lines), metadata/ (31 lines), navidrome/ (38 lines), platform/ (35 lines), playlist_import/ (33 lines), processing/ (29 lines). All follow Phase 1 template. Each notes "calls persistence directly" in dependencies. No stale references. Navidrome covers 7 modules; platform covers 6 including arango_first_run_comp and gpu_probe_comp discovered in the subdirectory.

### Phase 3: Services and Workflows (12 READMEs)

- [x] Create READMEs for `services/domain/` (8 service files + `_library_mapping.py` — domain service index listing each service's responsibility), `services/domain/library_svc/` (6 modules — admin, config, entities, files, query, scan split), `services/infrastructure/` (10 modules — config, workers system, health, ML service, file watcher, background tasks, bootstrap, keys, info, calibration download), and `services/infrastructure/workers/` (single `discovery_worker.py`): each README must include the "services MUST NOT call persistence directly" rule
    **Notes:** Created 4 READMEs: domain/ (42 lines, 8 services + _library_mapping + library_svc/ subfolder), domain/library_svc/ (40 lines, 6 modules), infrastructure/ (49 lines, 10 modules + workers/ subfolder), infrastructure/workers/ (37 lines, 1 module). All include "MUST NOT call persistence directly" rule.
- [x] Create READMEs for all 8 workflow subfolders: `workflows/calibration/`, `workflows/library/`, `workflows/metadata/`, `workflows/navidrome/`, `workflows/platform/`, `workflows/playlist_import/`, `workflows/processing/`, `workflows/vectors/` — each listing workflow files with purpose, orchestration patterns, which components they call, and the "workflows MUST NOT call persistence directly" rule
    **Notes:** Created 8 READMEs: calibration/ (40 lines, 6 modules), library/ (42 lines, 8 modules), metadata/ (31 lines, 2 modules), navidrome/ (52 lines, 12 modules), platform/ (39 lines, 5 modules), playlist_import/ (33 lines, 1 module), processing/ (33 lines, 2 modules), vectors/ (29 lines, 1 module). All include "MUST NOT call persistence directly" rule. All note component dependencies.

### Phase 4: Interfaces, Persistence, Helpers, Migrations (12 READMEs)

- [x] Create READMEs for `interfaces/api/` (app setup, auth, id encoding), `interfaces/api/types/` (13 Pydantic request/response type files), `interfaces/api/v1/` (3 versioned public routes — admin, navidrome, public), `interfaces/api/web/` (18 endpoint files + router + dependencies), `interfaces/cli/` (CLI entry point, UI helpers), and `interfaces/cli/commands/` (2 command files — cleanup, manage_password)
    **Notes:** Created 6 READMEs: api/ (40 lines), api/types/ (39 lines), api/v1/ (31 lines), api/web/ (45 lines), cli/ (35 lines), cli/commands/ (28 lines). All include "MUST NOT import or access persistence directly" rule. Types README lists all 13 type files. Web README lists all 16 endpoint files + router + dependencies.
- [x] Create READMEs for `persistence/database/` (20+ AQL query modules — the query layer root), `persistence/database/library_files_aql/` (8 modules — calibration, chromaprint, CRUD, queries, reconciliation, stats, status, tracks), and `persistence/database/tags_aql/` (6 modules — analytics, cleanup, CRUD, mood, queries, stats): each README must note "only components may import these modules"
    **Notes:** Created 3 READMEs: database/ (55 lines, 21 root-level modules listed), library_files_aql/ (33 lines, 8 mixins listed), tags_aql/ (32 lines, 6 mixins listed). All include "only components may import these modules" access rule.
- [x] Create READMEs for `helpers/dto/` (19 DTO files covering every domain — list all with purpose) and `migrations/` (forward-only migration system, current migration files, how to add new migrations per `docs/dev/migrations.md`)
    **Notes:** Created 2 READMEs: helpers/dto/ (46 lines, all 18 DTO files listed with exports), migrations/ (48 lines, 2 current migrations listed, links to docs/dev/migrations.md). DTO README lists all 18 modules with key types. Migrations README covers architecture, crash recovery, and how-to-add guide.

### Phase 5: Validation

- [x] Verify all 35 README.md files exist in the correct locations, each follows the template (heading, responsibilities, key modules table, patterns, dependencies), contains no stale references from the contracts ledger stale-terms list, and accurately reflects the actual files in each directory
    **Notes:** 40 README.md files verified (plan said 35, actual matches phase annotations: P1=10, P2=7, P3=12, P4=11). All follow template structure (heading, responsibilities, modules/subfolders table, patterns/rules, dependencies). Stale terms grep found zero real violations — one "TensorFlow" mention in ml/README.md is contextual ("No TensorFlow" exclusion rule). All 39 directories' module tables match actual .py files (100% accuracy). Persistence access rule correctly stated in all component READMEs (either explicit "calls persistence directly" or "Calls persistence/" in downstream deps). audio/ and inference/ correctly omit persistence (verified: zero persistence imports). helpers/dto/ says "No nomarr.* imports" (stronger than persistence prohibition, correct).
- [x] Cross-check consistency: every folder mentioned in LAYER.md directory trees has a corresponding README, dependency relationships described in READMEs are bidirectionally consistent (if A says "called by B", B says "calls A"), persistence access rule appears correctly in all component READMEs (as owner) and all non-component READMEs (as prohibition), and update the contracts ledger Plan D section to record all files created
    **Notes:** Cross-check complete. Every subfolder in all 6 LAYER.md directory trees has a README (17 components, 1 helpers, 6 interfaces, 3 persistence, 4 services, 8 workflows + 1 standalone migrations = 40 total). Bidirectional dependencies verified: workflows reference their component dependencies, components reference workflow callers; services reference workflows they call, workflows reference calling services. Persistence rule verified: all 3 persistence READMEs say "only components may import"; all 18 non-component READMEs include prohibition; all 17 component READMEs document persistence access. Contracts ledger Plan D section updated with actuals and PASS verdict.

## Completion Criteria

- 35 README.md files created across all code-containing subfolders under `nomarr/`
- Every README follows the consistent template: title, 1-2 sentence summary, responsibilities list, key modules table, patterns section, dependencies section
- Each README is 30-60 lines — orientation aids, not exhaustive documentation
- Zero stale references (TensorFlow, SQL, queues, deleted files) in any README
- Persistence access rule correctly stated: components READMEs say "calls persistence directly", all others say "MUST NOT import persistence"
- Essentia isolation rule present in `components/ml/` and `components/ml/audio/` READMEs
- ONNX-as-backend rule present in `components/ml/` and `components/ml/onnx/` READMEs
- Cross-references between READMEs and parent LAYER.md files are consistent
- Contracts ledger updated with Plan D completion record
