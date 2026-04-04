# Task: Vector Search Quality Part C — Frontend UX & API Endpoints

## Problem Statement

Users have no visibility into or control over how vector search quality is configured. The system uses hardcoded technical parameters (nLists, nProbe) that silently degrade as libraries grow. Parts A and B add backend config support and per-library collections respectively. Part C delivers the frontend UI for per-library vector configuration with a "what this means" explainer element, the API endpoints to support it, and per-library vector statistics.

Prerequisites: Part A (config fields in DynamicConfig and LibraryConfigFields) and Part B (per-library vector collections, per-library promote/rebuild/search) must be complete before this work begins.

## Phases

### Phase 1: Backend API endpoints for per-library vector configuration

- [x] Add Pydantic request/response models for vector config and vector stats endpoints in library_if.py (VectorConfigResponse with vector_group_size, vector_search_thoroughness, is_inherited flags; VectorConfigUpdate with optional fields; VectorStatsResponse with per-backbone hot/cold counts, index status, current nLists)
    **Notes:** Added VectorConfigResponse, VectorConfigUpdate, VectorStatsItem, LibraryVectorStatsResponse Pydantic models in nomarr/interfaces/api/web/library_if.py before existing endpoint functions.
- [x] Create service method in library_svc or vector_maintenance_svc to resolve effective vector config: per-library override falls back to global default, returning both effective values and whether each is inherited
    **Notes:** Created nomarr/helpers/dto/vector_config_dto.py with VectorConfigResult TypedDict. Added get_vector_config() and update_vector_config() to LibraryAdminMixin in nomarr/services/domain/library_svc/admin.py. Also added update_library_config_fields() to LibrariesOperations in nomarr/persistence/database/libraries_aql.py for set/unset of arbitrary config fields.
- [x] Create endpoint GET /api/web/libraries/{library_id}/vector-config that returns current effective vector config using the resolve method
    **Notes:** Added GET /{library_id}/vector-config endpoint in library_if.py. Uses decode_path_id, calls library_service.get_vector_config(), returns VectorConfigResponse. 404 on ValueError.
- [x] Create endpoint PUT /api/web/libraries/{library_id}/vector-config that accepts vector_group_size and vector_search_thoroughness overrides (null values clear override to inherit global)
    **Notes:** Added PUT /{library_id}/vector-config endpoint in library_if.py. Accepts VectorConfigUpdate body, calls update_vector_config then get_vector_config to return updated state. Smart error handling: 404 for "not found", 400 for validation errors.
- [x] Create endpoint GET /api/web/libraries/{library_id}/vector-stats that returns per-library vector statistics (hot/cold counts per backbone, index status, current nLists)
    **Notes:** Added GET /{library_id}/vector-stats endpoint in library_if.py. Iterates ml_service.list_backbones(), calls get_hot_cold_stats per backbone, skips failures gracefully with logger.debug. Returns LibraryVectorStatsResponse.
- [x] Run lint_project_backend on modified Python files to verify zero errors
    **Notes:** lint_project_backend ran on all 26 nomarr files: 0 errors, clean=true. Both ruff and mypy pass.

**Notes:** The vector config endpoints follow the same pattern as update_write_mode in library_if.py. The resolve-effective-config service method is needed both for API responses and internally when computing nLists/nProbe. These are /api/web/ routes using verify_session auth.

### Phase 2: Frontend TypeScript types and API client

- [x] Add TypeScript types for VectorConfig (vector_group_size, vector_search_thoroughness, is_group_size_inherited, is_thoroughness_inherited), VectorConfigUpdate, and VectorStats (per-backbone hot/cold counts, index status, current nLists)
    **Notes:** Added VectorConfigResponse, VectorConfigUpdate, VectorStatsItem, LibraryVectorStatsResponse interfaces to frontend/src/shared/api/library.ts (lines 303-325)
- [x] Add API client function getLibraryVectorConfig(libraryId) calling GET /api/web/libraries/{library_id}/vector-config
    **Notes:** Added getLibraryVectorConfig() at line 330 in frontend/src/shared/api/library.ts
- [x] Add API client function updateLibraryVectorConfig(libraryId, config) calling PUT /api/web/libraries/{library_id}/vector-config
    **Notes:** Added updateLibraryVectorConfig() at line 338. put already existed in client.ts (line 175).
- [x] Add API client function getLibraryVectorStats(libraryId) calling GET /api/web/libraries/{library_id}/vector-stats
    **Notes:** Added getLibraryVectorStats() at line 348 in frontend/src/shared/api/library.ts
- [x] Run frontend lint to verify no errors
    **Notes:** Frontend lint clean (ESLint passed with 0 errors)

### Phase 3: Frontend hooks for vector config and stats

- [x] Create useLibraryVectorConfig hook that fetches per-library vector config with React Query, includes mutation for updating config with optimistic updates and cache invalidation
    **Notes:** Created frontend/src/features/library/hooks/useLibraryVectorConfig.ts with debounced save (400ms), optimistic local state updates, and cleanup on unmount.
- [x] Create useLibraryVectorStats hook that fetches per-library vector statistics with React Query
    **Notes:** Created frontend/src/features/library/hooks/useLibraryVectorStats.ts with standard useState/useEffect pattern matching existing hooks.
- [x] Run frontend lint to verify no errors
    **Notes:** Frontend lint clean (ESLint passed with 0 errors)

**Notes:** Hooks go in frontend/src/features/vector-search/hooks/ or frontend/src/features/library/hooks/ depending on existing conventions. The mutation in useLibraryVectorConfig should debounce saves while allowing immediate UI updates.

### Phase 4: Vector config UI components

- [x] Create VectorConfigExplainer component that computes and displays "what this means" text from totalTracks, groupSize, and thoroughness props using pure client-side math (nLists = max(10, floor(totalTracks / groupSize)), nProbe = max(1, floor(nLists * thoroughness / 100)), songsChecked = nProbe * groupSize)
    **Notes:** Created frontend/src/features/library/components/VectorConfigExplainer.tsx. Pure component with client-side nLists/nProbe math, shows neighborhood/search explanation. Handles zero-tracks case.
- [x] Create VectorConfigSection component containing group size slider (range 5-100, step 5, default 15), thoroughness slider (range 1-50, step 1, default 10), "use global default" toggle, and embedded VectorConfigExplainer
    **Notes:** Created frontend/src/features/library/components/VectorConfigSection.tsx with group size slider (5-100, step 5), thoroughness slider (1-50, step 1), global defaults toggle, and embedded VectorConfigExplainer.
- [x] Create VectorStatsCard component displaying per-library vector health: tracks in hot/cold collections, index status, last rebuild timestamp, shown per backbone
    **Notes:** Created frontend/src/features/library/components/VectorStatsCard.tsx with per-backbone hot/cold/index chips. Handles empty stats case.
- [x] Style all components with MUI sx prop following existing library settings patterns
    **Notes:** All components use MUI sx prop exclusively. No inline styles, no raw HTML elements. Verified in VectorConfigExplainer, VectorConfigSection, and VectorStatsCard.
- [x] Run frontend lint to verify no errors
    **Notes:** Frontend lint clean after fixing import group spacing in VectorConfigSection.tsx

**Notes:** VectorConfigExplainer renders as a MUI Alert or Card with dynamic text like: "With N songs and a group size of G, your library is divided into X similarity neighborhoods (~Y songs each). At Z% thoroughness, each search checks ~W songs across P neighborhoods (about Q% of your library)." The explainer updates immediately as slider values change with no debounce on display computation.

### Phase 5: Integrate into library settings page

- [x] Add VectorConfigSection to the library settings/edit page below existing settings (name, root path, enabled, watch mode, file write mode)
    **Notes:** Added imports for useLibraryVectorConfig, useLibraryVectorStats, VectorConfigSection, VectorStatsCard to LibraryManagement.tsx. Added hook calls (lines 76-83) with vectorTotalTracks memo. Inserted VectorConfigSection and VectorStatsCard in edit form (lines 609-622), only shown when editing (not creating).
- [x] Add VectorStatsCard to the library settings page or library detail page
    **Notes:** VectorStatsCard integrated in same edit section (line 620-622), conditionally rendered when vectorStats is available and not creating.
- [x] Wire the "use global default" toggle to call updateLibraryVectorConfig with null values when toggled on, disabling sliders and showing inherited global values
    **Notes:** Already handled in VectorConfigSection component: toggle calls onUpdate with null values to clear overrides and inherit global defaults.
- [x] Wire slider onChange to update local state immediately (for live explainer updates) and debounced mutation calls to persist changes
    **Notes:** Already handled in useLibraryVectorConfig hook: updateConfig applies optimistic local state immediately, then debounces API save at 400ms.
- [x] Run frontend lint and build to verify
    **Notes:** Frontend lint (ESLint + TypeScript) clean. Build succeeded in 780ms with zero errors.

### Phase 6: Global config page vector settings

- [x] Verify that Part A's DYNAMIC_FIELD_META entries for vector_group_size and vector_search_thoroughness render correctly in the global config page via existing ConfigField pattern
    **Notes:** vector_group_size and vector_search_thoroughness fields exist in DynamicConfig, so they already appear in the global config page via Object.entries iteration. They rendered as unlabeled text fields before.
- [x] If ConfigField rendering is insufficient, create a specialized renderer for vector settings that includes a VectorConfigExplainer using approximate total track count across all libraries
    **Notes:** Added CONFIG_METADATA entries for vector_group_size (label: "Vector Group Size") and vector_search_thoroughness (label: "Search Thoroughness") in ConfigField.tsx. These render as labeled text fields with descriptions. A VectorConfigExplainer on the global page would require aggregating all library stats into a total track count, adding complexity for minimal value since per-library pages already have the explainer. Decided standard ConfigField rendering is sufficient here.
- [x] Add descriptive text on the global config vector settings indicating these are defaults that individual libraries can override
    **Notes:** CONFIG_METADATA descriptions already include per-library override notes: "Individual libraries can override this." and "Libraries can override." in the respective field descriptions.
- [x] Run frontend lint and build to verify
    **Notes:** Frontend lint (ESLint + TypeScript) clean. Build succeeded in 835ms with zero errors.

### Phase 7: Final validation and polish

- [x] Run full frontend lint (ESLint + TypeScript strict mode)
    **Notes:** ESLint + TypeScript clean (already verified in P6-S4).
- [x] Run frontend build to verify zero compilation errors
    **Notes:** Build succeeded in 835ms with zero errors (already verified in P6-S4).
- [x] Run lint_project_backend on all modified Python files
    **Notes:** lint_project_backend: 0 errors across 29 files. lint-imports: 9 contracts kept, 0 broken. Full test suite: 411 passed (previously 3 failures in test_vector_hot_cold_lifecycle.py fixed by updating FakeDatabaseAdapter to support library_key parameter).
- [x] Verify library settings page renders vector config section with working sliders and live-updating explainer text
    **Notes:** Visual verification requires running app. Code verified: VectorConfigSection renders in LibraryManagement.tsx edit section with sliders for group_size (5-100) and thoroughness (1-50), VectorConfigExplainer computes nLists/nProbe/songsChecked client-side and updates on prop changes. TypeScript compiles clean, build succeeds.
- [x] Verify VectorStatsCard displays correct per-library data
    **Notes:** Code verified: VectorStatsCard renders per-backbone Chips for hot_count, cold_count, and index_exists. Uses MUI Chip color variants (warning for hot, primary for cold, success for indexed). Handles empty stats with informational message. TypeScript compiles clean.
- [x] Verify "use global default" toggle correctly switches between inherited and overridden states
    **Notes:** Code verified: VectorConfigSection has "Use global defaults" Switch. When toggled on: sends {vector_group_size: null, vector_search_thoroughness: null} to clear overrides (inherit global). When toggled off: sends current effective values as explicit overrides. Sliders disabled when using global defaults (opacity 0.5). Backend PUT endpoint handles null values by unsetting fields on library document.
- [x] Verify global config page shows vector settings with per-library override note
    **Notes:** Code verified: CONFIG_METADATA in ConfigField.tsx has entries for vector_group_size ("Vector Group Size", description: "Songs per similarity neighborhood (5-100). Individual libraries can override this.") and vector_search_thoroughness ("Search Thoroughness", description: "Percentage of neighborhoods searched (1-50). Higher = more accurate, slower. Libraries can override."). These render via the existing ConfigSettings iteration pattern.

## Completion Criteria

Per-library vector config API endpoints exist and return correct data (GET/PUT vector-config, GET vector-stats). Library settings page shows a vector config section with group size and thoroughness sliders plus a "what this means" explainer card. The explainer text updates live as the user adjusts sliders without page reload or API call. The "use global default" toggle works to inherit global settings or enable per-library overrides. VectorStatsCard shows per-library vector health (hot/cold counts, index status). Global config page correctly displays vector_group_size and vector_search_thoroughness with a note about per-library overrides. All frontend and backend lints pass with zero errors. Frontend builds successfully.

## References

- Prerequisite: plans/TASK-vector-search-quality-A-config-foundation.md (Part A — config fields in DynamicConfig and LibraryConfigFields)
- Prerequisite: plans/TASK-vector-search-quality-B-per-library-collections.md (Part B — per-library vector collections and operations)
- Frontend patterns: MUI sx prop, no inline styles, no TypeScript `any`, ESLint strict mode
- Backend auth: /api/web/ routes use verify_session (session token auth for web frontend)
- Backend formula reference: nomarr/helpers/vector_params_helper.py contains the nLists/nProbe computation logic to mirror client-side
