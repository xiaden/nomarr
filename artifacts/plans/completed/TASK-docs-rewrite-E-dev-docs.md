# Task: Docs Rewrite Part E — Developer Documentation Rewrite

## Problem Statement

The `docs/dev/` folder contains 17 files and a `skills/` subdirectory totaling ~8,500 lines. Nearly every file references removed features (QueueService, StateBroker/SSE, SQL schema, TensorFlow, multi-type workers) or obsolete module layouts. Two files document systems that no longer exist and should be deleted. Four files are frontend or code-intel documentation that is out of scope. The remaining files need rewrites of varying depth to match the architecture established by Plan C's LAYER.md files.

## Phases

### Phase 1: Triage and Cleanup
- [x] Read all 17 files plus 3 `skills/` files against the current codebase; classify each as full-rewrite, delete, freshen, or out-of-scope; record classifications as a triage table in a scratch note for reference during subsequent phases
    **Triage:** | # | File | Classification | Rationale |
|---|------|---------------|-----------|
| 1 | architecture.md | full-rewrite | References QueueService, ProcessingService, queue_service, ml/backend_essentia.py, events/, queue/ components, SQL-style persistence patterns |
| 2 | calibration-troubleshooting.md | freshen | Core per-label calibration content accurate; verify cross-refs and stale terms |
| 3 | domains.md | full-rewrite | Stale domain catalog (lists events/, queue/ as components), references entity_keys_comp, outdated examples |
| 4 | health.md | full-rewrite | Describes SQL-table health system with worker:processing:* IDs; actual system uses pipe/FD HealthMonitorService with worker:discovery:* IDs and ComponentStatus enum |
| 5 | mcp-config-defaults.md | out-of-scope | MCP/code-intel documentation |
| 6 | mcp-config-examples.md | out-of-scope | MCP/code-intel documentation |
| 7 | migrations.md | freshen | Already describes current baseline+delta system accurately; verify cross-refs after Phase 1 deletions |
| 8 | mui-integration.md | out-of-scope | Frontend documentation |
| 9 | naming.md | full-rewrite | Examples use QueueService, ProcessingService, WorkersCoordinator, StateBroker as exemplars |
| 10 | qc.md | full-rewrite | References obsolete scripts (check_naming.py, discover_import_chains.py), doesn't mention lint_project_backend as primary QC tool |
| 11 | server-file-picker.md | out-of-scope | Frontend component documentation |
| 12 | services.md | delete | Duplicates SERVICES.md layer doc, documents nonexistent QueueService/ProcessingService |
| 13 | statebroker.md | delete | Documents StateBroker/SSE system entirely removed from codebase |
| 14 | vector-stores.md | freshen | Hot/cold architecture doc is current; verify cross-refs |
| 15 | versioning.md | freshen | General versioning strategy accurate; verify migration cross-refs |
| 16 | workers.md | full-rewrite | Still references health table DB writes alongside pipe/FD; needs sharper focus on single DiscoveryWorker type with claim-based processing |
| 17 | skills/README.md | full-rewrite | Lists deleted layer-* skills in directory tree example |
| 18 | skills/nomarr-skills.md | full-rewrite | Lists 10 skills including 6 deleted layer-* skills; actual count is 12 different skills |
| 19 | skills/specification.md | freshen | Agent Skills format spec is reference material; verify against current format |
Summary: 2 delete, 7 full-rewrite, 4 freshen, 4 out-of-scope, 2 deleted in this phase
- [x] Delete `services.md` (duplicates `SERVICES.md` layer doc, references nonexistent `QueueService`/`ProcessingService`) and `statebroker.md` (documents StateBroker/SSE system entirely removed from codebase); mark `mui-integration.md`, `server-file-picker.md`, `mcp-config-defaults.md`, and `mcp-config-examples.md` as out-of-scope with no changes
    **Done:** Deleted services.md and statebroker.md. Removed both from mkdocs.yml nav. Out-of-scope files (mui-integration.md, server-file-picker.md, mcp-config-defaults.md, mcp-config-examples.md) left unchanged.

### Phase 2: Core Architecture Rewrites
- [x] Rewrite `architecture.md` — document current layer structure (interfaces → services → workflows → components → persistence/helpers), DI via constructor injection and FastAPI `Depends`, ONNX inference backend, discovery-based workers, persistence-only-via-components rule; remove all references to queues, TensorFlow, Essentia-as-ML-backend, and `ml/backend_essentia.py`
    **Done:** Rewrote architecture.md: 1015 lines → 466 lines. Documented current 5-layer structure, DI via constructor injection + FastAPI Depends, ONNX inference backend, discovery-based workers, persistence-only-via-components rule. Added full Database facade collection table. Removed all stale references (queues, TensorFlow, Essentia-as-ML, StateBroker, SSE).
- [x] Rewrite `domains.md` — update domain inventory to match current `components/` subfolders (library, metadata, tagging, analytics, ml, workers, navidrome, platform, playlist_import, processing, infrastructure), fix data ownership examples with actual ArangoDB collections, remove references to deleted modules (`events/`, `queue/`, `entity_keys_comp.py`)
    **Done:** Rewrote domains.md: 1162 lines → 371 lines. Updated domain inventory to match all 11 current components/ subfolders. Mapped each domain to actual ArangoDB collections from Database facade. Removed events/, queue/, entity_keys_comp.py, tag_queue references. Added navidrome, workers, platform, playlist_import, processing, infrastructure domains.
- [x] Rewrite `health.md` — replace SQL-table schema with pipe/FD-based `HealthMonitorService` contract from `health_monitor_svc.py`; document `ComponentStatus` enum (pending/healthy/unhealthy/recovering/dead/failed), `ComponentPolicy` dataclass, per-component registration model, and status transitions from `health_dto.py`; remove all `worker:processing:*` component IDs (now `worker:discovery:*`)
    **Done:** Rewrote health.md: 659 lines → 319 lines. Replaced SQL-table schema with pipe/FD HealthMonitorService contract. Documented ComponentStatus Literal (pending/healthy/unhealthy/recovering/dead/failed), ComponentPolicy dataclass with defaults, ComponentLifecycleHandler protocol, registration model, health frame format, state machine with all transitions. Removed worker:processing:* IDs, SQL references, queue references.
- [x] Rewrite `workers.md` — focus on single `DiscoveryWorker` type in `services/infrastructure/workers/discovery_worker.py`, claim-based work discovery via `worker_claims_aql`, `WorkerSystemService` lifecycle management, crash recovery via `HealthMonitorService` callbacks; cross-reference `health.md` for monitoring details; remove any remaining multi-worker-type or queue-based references
    **Done:** Rewrote workers.md: 400 lines → 279 lines. Focused on single DiscoveryWorker type with claim-based work discovery via worker_claims_aql. Documented WorkerSystemService lifecycle (admission control, spawn, pause/resume, graceful stop), crash recovery flow (HealthMonitorService callback → claim release → VRAM release → restart policy → backoff). Cross-references health.md for monitoring details. Removed all multi-worker-type, queue-based, and services.md references.

### Phase 3: Remaining Doc Updates
- [x] Rewrite `naming.md` and `qc.md` — in `naming.md`, replace stale examples (`QueueService`, `ProcessingService`, `WorkersCoordinator`) with actual service names from `services/domain/` and `services/infrastructure/`; in `qc.md`, update tooling section to reference `lint_project_backend` as primary Python QC tool, remove references to obsolete scripts, align architecture checks with current layer rules
    **Done:** **naming.md:** 554→370 lines. Replaced QueueService/ProcessingService/WorkersCoordinator/StateBroker with actual services (domain: AnalyticsService, CalibrationService, LibraryService, MetadataService, NavidromeService, TaggingService, VectorSearchService, VectorMaintenanceService; infra: ConfigService, HealthMonitorService, InfoService, KeyManagementService, MLService, WorkerSystemService). Updated module naming to _svc/_wf/_comp suffixes. Replaced check_naming.py with lint_project_backend. Removed services.md cross-ref.
**qc.md:** 649→300 lines. lint_project_backend is now primary QC tool. Removed all obsolete scripts (check_naming.py, discover_import_chains.py, discover_api.py, qc_quick.sh, qc_full.sh). Replaced TensorFlow/essentia-tensorflow with ONNX. Updated SQL examples to AQL. Updated priority modules to actual paths. Added MCP tools table. Removed services.md cross-ref.
- [x] Rewrite `skills/` directory — update `README.md` and `nomarr-skills.md` to reflect the actual 12 skills in `.github/skills/` (code-discovery, code-generation, code-migration, doc-coauthoring, feature-execution, feature-planning, mcp-builder, playwright-cli, quality-analysis, skill-creator, skill-maintenance); remove references to deleted layer-* skills; verify `specification.md` against current Agent Skills format and update if needed
    **Done:** **README.md:** Updated directory tree to show actual 11 active skills (removed layer-helpers, layer-components, layer-workflows, layer-services, layer-interfaces, layer-persistence). Added all current skills: code-discovery, code-generation, code-migration, doc-coauthoring, feature-execution, feature-planning, mcp-builder, playwright-cli, quality-analysis, skill-creator, skill-maintenance.
**nomarr-skills.md:** Full rewrite. Replaced 10-skill list (6 deleted layer-* + 4 tooling) with actual 11 active skills. Each skill has trigger conditions and description from actual SKILL.md frontmatter. Removed all layer-specific skill sections. Updated dependency direction to match current rules (services may skip workflows, lateral imports allowed). Removed references to obsolete scripts (check_naming.py, discover_import_chains.py, etc.) and ml_backend_essentia_comp.py.
**specification.md:** Verified against current Agent Skills format — no changes needed. Content is a reference spec with no Nomarr-specific stale terms.
- [x] Freshen `migrations.md`, `versioning.md`, `vector-stores.md`, and `calibration-troubleshooting.md` — verify each against codebase, fix any stale terms from the contracts ledger, ensure cross-references to other docs/dev/ files point to files that still exist after Phase 1 deletions
    **Done:** **migrations.md:** Verified — no stale terms, no broken cross-references. Content accurately describes baseline+delta system. No changes needed.
**versioning.md:** Fixed 11 stale references. Replaced "database tables" → "database collections", "table or column" → "collection or field", "queue job format" → "worker claim format". Updated all example version entries from queue-based to vector architecture examples (0.3.0 "Hot/cold vector architecture", 0.3.1 "Vector promotion fix"). Fixed changelog example similarly.
**vector-stores.md:** Verified — no stale terms, no broken cross-references. Hot/cold architecture content is accurate and current. No changes needed.
**calibration-troubleshooting.md:** Fixed 4 instances of incorrect "22" → "23" calibration document count (table correctly totals 23: 10 binary heads × 2 + 3 regression heads × 1). Verified cross-references to existing files (calibration_state_aql.py, generate_calibration_wf.py, calibration_if.py, CalibrationDisplay.tsx) are valid.

### Phase 4: Validation
- [x] Grep all `docs/dev/` files for every banned stale term from the contracts ledger (TensorFlow, QueueService, sql_helper, queue_svc, base.py worker, scan_library_direct_wf, start_scan_wf, entity_keys_comp, events/ components, pages/ directory, ml_backend_essentia_comp as ML entry, StateBroker) — zero matches required
    **Results:** Grepped all docs/dev/ files (14 files + skills/) for all 12 banned stale terms. Initial scan found 1 match: "TensorFlow" in architecture.md line 106 as a negation ("There is no TensorFlow dependency"). Fixed by rephrasing to "All ML inference runs exclusively through ONNX Runtime." Confirmation sweep: 0 matches for all 12 terms (TensorFlow, QueueService, sql_helper, queue_svc, base.py worker, scan_library_direct_wf, start_scan_wf, entity_keys_comp, events/ components, pages/ directory, ml_backend_essentia_comp, StateBroker). Also verified zero matches for services.md, statebroker.md, calibration.md, queues.md links. Note: WorkersCoordinator appears once in naming.md as an anti-pattern example (❌) — not on the banned list and valid documentation use.
- [x] Cross-reference each surviving `docs/dev/` file against the 6 LAYER.md files and `copilot-instructions.md` — verify no contradictions in dependency direction, persistence access rules, worker/health architecture, or ML backend identity; verify all internal cross-links between docs/dev/ files resolve to files that exist
    **Results:** Cross-referenced all 14 surviving docs/dev/ files (+ 3 skills/) against the 6 LAYER.md files, import-linter config, and copilot-instructions.md.
CONTRADICTION FOUND AND FIXED: architecture.md line 81 said "Only components may import from the persistence layer" — contradicted by its own "Can Import" table (services can import persistence) and SERVICES.md ("Services may hold a Database reference for DI wiring"). Fixed to: "Only components may call persistence methods (db.*) directly. Services and workflows may hold a Database reference for DI wiring and pass-through, but never invoke persistence operations themselves."
CORE FACTS VERIFIED CONSISTENT: (1) Dependency direction `interfaces → services → workflows → components → persistence/helpers` matches across all docs. (2) Persistence access rule (components-only calling) consistent after fix. (3) ONNX Runtime as exclusive ML backend — consistent. (4) Single DiscoveryWorker with claim-based processing — consistent. (5) ArangoDB/AQL — consistent. (6) Pipe/FD health monitoring via HealthMonitorService — consistent.
CROSS-LINKS: All 41 internal markdown links between docs/dev/ files resolve to existing files. Zero links to deleted files (services.md, statebroker.md, calibration.md, queues.md). One link in skills/specification.md to `references/REFERENCE.md` is inside a code block example (not an actual link). External links to docs/user/deployment.md and docs/user/getting_started.md both resolve.

## Completion Criteria
- `services.md` and `statebroker.md` deleted; no docs/dev/ file references a removed system as if it exists
- `architecture.md` and `domains.md` accurately describe current layers, domains, and module hierarchy
- `health.md` documents pipe/FD-based HealthMonitorService, not SQL health table
- `workers.md` describes single DiscoveryWorker type with claim-based processing
- Zero grep matches for any stale term in the contracts ledger across all docs/dev/ files
- No contradictions between docs/dev/ files and the LAYER.md files produced by Plan C
- Out-of-scope files (mui-integration.md, server-file-picker.md, mcp-config-*.md) unchanged
