# Test Coverage Analysis

**Generated:** 2025-01-XX  
**Status:** Pre-Alpha - Architecture Stabilization Phase

---

## Executive Summary

This document analyzes test coverage gaps in the Nomarr codebase by comparing existing tests against actual source modules. The analysis is organized by architectural layer (interfaces → services → workflows → components → persistence → helpers).

**Current Test Coverage:**
- **Unit Tests:** 9 files (data, services, ml, workflows)
- **Integration Tests:** 4 files (API, CLI, navidrome, services)
- **Root Tests:** 4 files (application lifecycle, architecture QC, calibration, processing)

**Critical Findings:**
1. ✅ **Strong Coverage:** Services layer, database operations, architecture validation
2. ⚠️ **Partial Coverage:** ML components (cache only), workflows (single test), interfaces (integration only)
3. ❌ **No Coverage:** Tagging components, analytics components, queue components, library components, event broker, workers, most workflows, most interfaces

---

## 1. Test Inventory (What We Have)

### 1.1 Unit Tests (`tests/unit/`)

#### Data Layer (`tests/unit/data/`)
- `test_database.py` - Database class schema and queries ✅
- `test_joined_queries_security.py` - Security checks for joined queries ✅
- `test_processing_queue.py.legacy` - Legacy file (inactive)

#### Services Layer (`tests/unit/services/`)
- `test_health_monitor.py` - HealthMonitor tracking ✅
- `test_library_service.py` - LibraryService scan operations ✅
- `test_queue_service.py` - QueueService business operations ✅
- `test_worker_service.py` - WorkerService state management ✅
- `test_worker_system_service.py` - WorkerSystemService enable/disable ✅

#### ML Layer (`tests/unit/ml/`)
- `test_cache.py` - ModelCache loading/eviction ✅

#### Workflows Layer (`tests/unit/workflows/`)
- `test_parse_smart_playlist_query.py` - Navidrome smart playlist parsing ✅

#### Tagging Layer (`tests/unit/tagging/`)
- **EMPTY** ❌

#### Models Layer (`tests/unit/models/`)
- **DOES NOT EXIST** ❌

#### Interfaces Layer (`tests/unit/interfaces/`)
- **DOES NOT EXIST** ❌

### 1.2 Integration Tests (`tests/integration/`)

- `test_api_integration.py` - HTTP API endpoints ✅
- `test_cli_integration.py` - CLI command execution ✅
- `integration/navidrome/` - Navidrome integration tests (directory exists) ⚠️
- `integration/services/` - Service coordination tests (directory exists) ⚠️

### 1.3 Root Tests (`tests/`)

- `test_application.py` - Application lifecycle ✅
- `test_architecture_qc.py` - Architecture validation (import rules, layer boundaries) ✅
- `test_calibration.py` - Calibration workflows ✅
- `test_refactored_processor.py` - Processing workflows ✅

---

## 2. Coverage Gaps by Layer

### 2.1 Interfaces Layer

**Source Modules:** `nomarr/interfaces/`

#### API Endpoints (`interfaces/api/web/`)
- `analytics_if.py` - Analytics endpoints ❌ NO UNIT TESTS
- `auth_if.py` - Authentication endpoints ⚠️ INTEGRATION ONLY
- `calibration_if.py` - Calibration endpoints ❌ NO UNIT TESTS
- `config_if.py` - Config endpoints ❌ NO UNIT TESTS
- `fs_if.py` - Filesystem endpoints ❌ NO UNIT TESTS
- `info_if.py` - Info endpoints ❌ NO UNIT TESTS
- `library_if.py` - Library endpoints (including NEW tag cleanup) ❌ NO UNIT TESTS
- `navidrome_if.py` - Navidrome endpoints ❌ NO UNIT TESTS
- `processing_if.py` - Processing endpoints ❌ NO UNIT TESTS
- `queue_if.py` - Queue endpoints ❌ NO UNIT TESTS
- `sse_if.py` - Server-Sent Events ❌ NO UNIT TESTS
- `tags_if.py` - Tags endpoints ❌ NO UNIT TESTS
- `worker_if.py` - Worker endpoints ❌ NO UNIT TESTS

#### CLI Commands (`interfaces/cli/commands/`)
- `admin_reset_cli.py` - Admin reset command ⚠️ INTEGRATION ONLY
- `cache_refresh_cli.py` - Cache refresh command ⚠️ INTEGRATION ONLY
- `cleanup_cli.py` - Cleanup command ❌ NO TESTS
- `manage_password_cli.py` - Password management ❌ NO TESTS
- `remove_cli.py` - Remove command ⚠️ INTEGRATION ONLY

**Gap Analysis:**
- **Integration tests exist** for HTTP and CLI, but they're coarse-grained
- **No unit tests** for endpoint input validation, DTO serialization, error handling
- **New endpoints** (tag cleanup, file tags retrieval) added in latest commit have NO tests

**Priority:** HIGH - Interfaces are user-facing and need comprehensive validation

---

### 2.2 Services Layer

**Source Modules:** `nomarr/services/`

#### Domain Services (`services/domain/`)
- `analytics_svc.py` - AnalyticsService ❌ NO TESTS
- `calibration_svc.py` - CalibrationService ❌ NO TESTS
- `library_svc.py` - LibraryService ✅ TESTED (`test_library_service.py`)
- `navidrome_svc.py` - NavidromeService ❌ NO TESTS
- `recalibration_svc.py` - RecalibrationService ❌ NO TESTS

#### Infrastructure Services (`services/infrastructure/`)
- `calibration_download_svc.py` - CalibrationDownloadService ❌ NO TESTS
- `cli_bootstrap_svc.py` - CliBootstrapService ❌ NO TESTS
- `config_svc.py` - ConfigService ❌ NO TESTS
- `health_monitor_svc.py` - HealthMonitor ✅ TESTED (`test_health_monitor.py`)
- `info_svc.py` - InfoService ❌ NO TESTS
- `keys_svc.py` - KeyManagementService ❌ NO TESTS
- `ml_svc.py` - MLService ❌ NO TESTS
- `queue_svc.py` - QueueService ✅ TESTED (`test_queue_service.py`)
- `worker_system_svc.py` - WorkerSystemService ✅ TESTED (`test_worker_system_service.py`)
- `workers/base.py` - BaseWorker ❌ NO TESTS
- `workers/scanner.py` - ScannerWorker ❌ NO TESTS
- `workers/tagger.py` - TaggerWorker ❌ NO TESTS
- `workers/recalibration.py` - RecalibrationWorker ❌ NO TESTS

**Gap Analysis:**
- **5/14 services tested** (35% coverage)
- **Critical services untested:** AnalyticsService, CalibrationService, NavidromeService, MLService
- **NEW service methods untested:** `LibraryService.cleanup_orphaned_tags()`, `LibraryService.get_file_tags()`
- **Worker implementations untested** - workers are long-running processes with complex lifecycle management

**Priority:** HIGH - Services own orchestration and wiring, need robust tests

---

### 2.3 Workflows Layer

**Source Modules:** `nomarr/workflows/`

#### Processing Workflows (`workflows/processing/`)
- `process_file_wf.py` - Process file workflow ✅ TESTED (`test_refactored_processor.py`)

#### Library Workflows (`workflows/library/`)
- `cleanup_orphaned_tags_wf.py` - Tag cleanup workflow (NEW) ❌ NO TESTS
- `scan_library_wf.py` - Library scan workflow ⚠️ PARTIAL (tested via `test_library_service.py`)
- `scan_single_file_wf.py` - Single file scan ❌ NO TESTS
- `start_library_scan_wf.py` - Start scan workflow ❌ NO TESTS

#### Calibration Workflows (`workflows/calibration/`)
- `generate_calibration_wf.py` - Generate calibration ✅ TESTED (`test_calibration.py`)
- `recalibrate_file_wf.py` - Recalibrate file ✅ TESTED (`test_calibration.py`)

#### Navidrome Workflows (`workflows/navidrome/`)
- `filter_engine_wf.py` - Filter engine ❌ NO TESTS
- `generate_navidrome_config_wf.py` - Generate config ❌ NO TESTS
- `generate_smart_playlist_wf.py` - Generate playlist ❌ NO TESTS
- `parse_smart_playlist_query_wf.py` - Parse query ✅ TESTED (`test_parse_smart_playlist_query.py`)
- `preview_smart_playlist_wf.py` - Preview playlist ❌ NO TESTS
- `preview_tag_stats_wf.py` - Preview tag stats ❌ NO TESTS

#### Queue Workflows (`workflows/queue/`)
- `clear_queue_wf.py` - Clear queue ❌ NO TESTS
- `enqueue_files_wf.py` - Enqueue files ⚠️ PARTIAL (tested via `test_queue_service.py`)
- `remove_jobs_wf.py` - Remove jobs ❌ NO TESTS
- `reset_jobs_wf.py` - Reset jobs ❌ NO TESTS

**Gap Analysis:**
- **4/18 workflows tested** (22% coverage)
- **NEW workflow untested:** `cleanup_orphaned_tags_wf.py` (added this session)
- **Navidrome workflows mostly untested** (5/6 missing)
- **Queue workflows mostly untested** (3/4 missing)
- **Library workflows mostly untested** (3/4 missing)

**Priority:** CRITICAL - Workflows implement core business logic and need comprehensive tests

---

### 2.4 Components Layer

**Source Modules:** `nomarr/components/`

#### Analytics Components (`components/analytics/`)
- `analytics_comp.py` - Analytics computations ❌ NO TESTS

#### Tagging Components (`components/tagging/`)
- `tagging_aggregation_comp.py` - Mood tier aggregation ❌ NO TESTS
- `tagging_reader_comp.py` - Tag reading ❌ NO TESTS
- `tagging_remove_comp.py` - Tag removal ❌ NO TESTS
- `tagging_writer_comp.py` - Tag writing ❌ NO TESTS
- `tag_normalization_comp.py` - Tag normalization ❌ NO TESTS

#### ML Components (`components/ml/`)
- `ml_audio_comp.py` - Audio loading ❌ NO TESTS
- `ml_backend_essentia_comp.py` - Essentia backend ❌ NO TESTS
- `ml_cache_comp.py` - Model cache ✅ TESTED (`test_cache.py`)
- `ml_calibration_comp.py` - Calibration computation ❌ NO TESTS
- `ml_discovery_comp.py` - Model discovery ❌ NO TESTS
- `ml_embed_comp.py` - Embedding computation ❌ NO TESTS
- `ml_heads_comp.py` - Classification heads ❌ NO TESTS
- `ml_inference_comp.py` - ML inference ❌ NO TESTS

#### Library Components (`components/library/`)
- `file_tags_comp.py` - File tags retrieval (NEW) ❌ NO TESTS
- `metadata_extraction_comp.py` - Metadata extraction ❌ NO TESTS
- `search_files_comp.py` - File search ❌ NO TESTS
- `tag_cleanup_comp.py` - Tag cleanup (NEW) ❌ NO TESTS

#### Queue Components (`components/queue/`)
- `queue_cleanup_comp.py` - Queue cleanup ❌ NO TESTS
- `queue_dequeue_comp.py` - Dequeue operations ❌ NO TESTS
- `queue_enqueue_comp.py` - Enqueue operations ❌ NO TESTS
- `queue_status_comp.py` - Queue status ❌ NO TESTS

#### Event Components (`components/events/`)
- `event_broker_comp.py` - StateBroker (SSE) ❌ NO TESTS

#### Worker Components (`components/workers/`)
- `job_recovery_comp.py` - Job recovery logic ❌ NO TESTS
- `worker_crash_comp.py` - Worker crash handling ❌ NO TESTS

**Gap Analysis:**
- **1/29 components tested** (3% coverage)
- **ZERO tagging tests** - tagging is core domain logic
- **ZERO analytics tests** - analytics drive the UI
- **ZERO queue component tests** - queue operations are critical for reliability
- **ZERO event broker tests** - SSE is user-facing real-time feature
- **NEW components untested:** `file_tags_comp.py`, `tag_cleanup_comp.py` (added this session)
- **ML mostly untested** (7/8 modules missing) - ML is the core value proposition

**Priority:** CRITICAL - Components contain heavy domain logic and are the workhorses of the system

---

### 2.5 Persistence Layer

**Source Modules:** `nomarr/persistence/`

#### Database Operations (`persistence/database/`)
- `calibration_queue_sql.py` - CalibrationQueueOperations ⚠️ PARTIAL (tested via higher layers)
- `calibration_runs_sql.py` - CalibrationRunsOperations ⚠️ PARTIAL (tested via `test_calibration.py`)
- `file_tags_sql.py` - FileTagOperations (REWRITTEN) ⚠️ PARTIAL (tested via `test_database.py`)
- `health_sql.py` - HealthOperations ✅ TESTED (`test_health_monitor.py`)
- `joined_queries_sql.py` - JoinedQueryOperations ✅ TESTED (`test_joined_queries_security.py`)
- `libraries_sql.py` - LibraryOperations ⚠️ PARTIAL (tested via `test_library_service.py`)
- `library_files_sql.py` - LibraryFileOperations ⚠️ PARTIAL (tested via `test_database.py`)
- `library_queue_sql.py` - LibraryQueueOperations ⚠️ PARTIAL (tested via higher layers)
- `library_tags_sql.py` - LibraryTagOperations (NEW) ❌ NO DIRECT TESTS
- `meta_sql.py` - MetaOperations ❌ NO TESTS
- `sessions_sql.py` - SessionOperations ⚠️ PARTIAL (tested via auth integration)
- `shared_sql.py` - SharedOperations ❌ NO TESTS
- `tag_queue_sql.py` - TagQueueOperations ⚠️ PARTIAL (tested via `test_queue_service.py`)

#### Analytics Queries (`persistence/`)
- `analytics_queries.py` - Analytics SQL queries ❌ NO DIRECT TESTS

**Gap Analysis:**
- **2/14 operations tested directly** (14% coverage)
- **Most operations tested indirectly** via services/workflows (integration-style)
- **NEW operations untested:** `LibraryTagOperations` (added this session)
- **No direct tests for SQL logic** - relying on integration tests means SQL bugs are harder to isolate
- **Analytics queries untested** - these drive the analytics UI

**Priority:** MEDIUM - Persistence is tested indirectly, but direct tests would improve debuggability

---

### 2.6 Helpers Layer

**Source Modules:** `nomarr/helpers/`

- `dataclasses.py` - Shared dataclasses ❌ NO TESTS
- `exceptions.py` - Custom exceptions ❌ NO TESTS
- `file_validation_helper.py` - File validation ❌ NO TESTS
- `files_helper.py` - File utilities ❌ NO TESTS
- `logging_helper.py` - Logging utilities ❌ NO TESTS
- `navidrome_templates_helper.py` - Template rendering ❌ NO TESTS
- `sql_helper.py` - SQL utilities ❌ NO TESTS

#### DTOs (`helpers/dto/`)
- `admin_dto.py` - Admin DTOs ❌ NO TESTS
- `analytics_dto.py` - Analytics DTOs ❌ NO TESTS
- `calibration_dto.py` - Calibration DTOs ❌ NO TESTS
- `config_dto.py` - Config DTOs ❌ NO TESTS
- `events_state_dto.py` - Events/State DTOs ❌ NO TESTS
- `info_dto.py` - Info DTOs ❌ NO TESTS
- `library_dto.py` - Library DTOs ❌ NO TESTS
- `ml_dto.py` - ML DTOs ❌ NO TESTS
- `navidrome_dto.py` - Navidrome DTOs ❌ NO TESTS
- `processing_dto.py` - Processing DTOs ❌ NO TESTS
- `queue_dto.py` - Queue DTOs ❌ NO TESTS
- `recalibration_dto.py` - Recalibration DTOs ❌ NO TESTS
- `tagging_dto.py` - Tagging DTOs ❌ NO TESTS

**Gap Analysis:**
- **0/20 helpers/DTOs tested** (0% coverage)
- **File validation untested** - critical for preventing bad data
- **SQL helpers untested** - query building utilities need validation
- **DTOs untested** - DTOs are contracts between layers, serialization issues hard to catch

**Priority:** LOW-MEDIUM - Helpers are simpler, but file validation and SQL helpers should be tested

---

## 3. Testing Issues and Anti-Patterns

### 3.1 Architecture Violations

✅ **GOOD:** Test architecture respects layer boundaries
- Tests don't import upward (persistence tests don't import workflows)
- Integration tests properly use real services instead of mocking

⚠️ **CONCERN:** Some tests may be testing too much at once
- Service tests use real databases (good) but also test workflows implicitly
- Hard to isolate failures to specific layers

### 3.2 Test Marker Usage

✅ **GOOD:** All unit tests now marked with `pytestmark = pytest.mark.unit` (fixed this session)

⚠️ **INCOMPLETE:** Other markers underutilized
- `@pytest.mark.requires_ml` - Only used in `test_cache.py`
- `@pytest.mark.slow` - Not consistently applied
- `@pytest.mark.integration` - Not applied to integration tests (should be)
- `@pytest.mark.code_smell` - Only used in `test_architecture_qc.py`

❌ **MISSING:** New markers not used yet
- `@pytest.mark.requires_models` - Should mark tests needing real models
- `@pytest.mark.requires_audio` - Should mark tests needing audio files
- `@pytest.mark.real_db` - Should mark tests using real databases (all current unit tests)

### 3.3 Fixture Usage

✅ **GOOD:** Fixtures follow consistent patterns
- `test_db` provides real Database instances
- `temp_dir` provides temporary directories
- `mock_*` fixtures for optional dependencies

⚠️ **MISSING:** Some fixtures documented in TEST_STRUCTURE.md don't exist
- `temp_audio_file` - Documented but not implemented
- `temp_music_library` - Documented but not implemented
- `essentia_available` - Documented but not implemented
- `skip_if_no_essentia` - Documented but not implemented

❌ **INCONSISTENT:** Service fixtures not consistently named
- `real_queue_service` vs `mock_job_queue` - naming is confusing
- Should be `queue_service_fixture` or similar

### 3.4 Test Organization

✅ **GOOD:** Tests follow clear directory structure mirroring source
- `tests/unit/services/` mirrors `nomarr/services/`
- `tests/unit/data/` mirrors persistence layer

⚠️ **INCONSISTENT:** Some tests in wrong locations
- `test_refactored_processor.py` - Root test, should be in `tests/unit/workflows/processing/`
- `test_calibration.py` - Root test, should be in `tests/unit/workflows/calibration/`

❌ **MISSING:** Many layer directories don't exist
- `tests/unit/components/` - MISSING
- `tests/unit/interfaces/` - MISSING
- `tests/unit/helpers/` - MISSING

### 3.5 Edge Case Testing

⚠️ **INCOMPLETE:** Most tests focus on happy paths
- Error handling not consistently tested
- Invalid inputs not systematically validated
- Edge cases (empty files, null values, etc.) not covered

**Example gaps:**
- What happens if audio file is corrupted?
- What happens if database connection fails mid-transaction?
- What happens if ML model file is missing?
- What happens if Essentia is not installed?

### 3.6 Integration vs Unit Test Balance

⚠️ **IMBALANCED:** Heavy reliance on integration tests
- API/CLI tested at integration level only
- Services tested with real databases (good) but workflows tested implicitly (not ideal)
- Components barely tested at all

**Recommended balance:**
- Unit: 70% (fast, isolated, many edge cases)
- Integration: 25% (realistic, multi-layer, happy paths)
- E2E: 5% (full system, critical workflows)

**Current balance (estimated):**
- Unit: 40%
- Integration: 55%
- E2E: 5%

---

## 4. Critical Missing Tests (Prioritized)

### Priority 1: CRITICAL (Implement First)

**Components:**
1. **Tagging Components** (ALL 5 modules untested)
   - `tagging_aggregation_comp.py` - Mood tier logic is complex
   - `tagging_writer_comp.py` - File I/O, easy to break
   - `tagging_reader_comp.py` - Reading existing tags
   - `tag_normalization_comp.py` - Data transformation logic

2. **ML Components** (7/8 modules untested)
   - `ml_inference_comp.py` - Core ML execution
   - `ml_embed_comp.py` - Embedding computation
   - `ml_heads_comp.py` - Classification logic
   - `ml_audio_comp.py` - Audio loading (file I/O)

3. **Library Components** (NEW components added this session)
   - `tag_cleanup_comp.py` - NEW, untested
   - `file_tags_comp.py` - NEW, untested
   - `metadata_extraction_comp.py` - Critical for library scanning

4. **Library Workflows** (NEW workflow added this session)
   - `cleanup_orphaned_tags_wf.py` - NEW, untested

**Why Critical:**
- Components are the workhorses - they do the real work
- Tagging and ML are core value propositions
- NEW code added this session has ZERO tests
- These are complex, error-prone modules with many edge cases

---

### Priority 2: HIGH (Implement Soon)

**Services:**
1. `AnalyticsService` - Drives analytics UI
2. `CalibrationService` - Manages calibration runs
3. `NavidromeService` - Navidrome integration
4. `MLService` - ML backend management
5. NEW methods in `LibraryService`:
   - `cleanup_orphaned_tags()`
   - `get_file_tags()`

**Workflows:**
1. **Navidrome workflows** (5/6 untested):
   - `filter_engine_wf.py`
   - `generate_navidrome_config_wf.py`
   - `generate_smart_playlist_wf.py`
   - `preview_smart_playlist_wf.py`
   - `preview_tag_stats_wf.py`

2. **Queue workflows** (3/4 untested):
   - `clear_queue_wf.py`
   - `remove_jobs_wf.py`
   - `reset_jobs_wf.py`

3. **Library workflows**:
   - `scan_single_file_wf.py`
   - `start_library_scan_wf.py`

**Persistence:**
1. `LibraryTagOperations` - NEW, critical for normalized schema
2. `analytics_queries.py` - Drives analytics UI
3. Direct tests for FileTagOperations (currently tested indirectly)

**Why High:**
- Services orchestrate critical workflows
- Navidrome is a key integration point
- Queue operations affect reliability
- NEW persistence operations need validation

---

### Priority 3: MEDIUM (Implement Later)

**Interfaces:**
1. **API Endpoints** (unit tests for input validation, DTO serialization):
   - `library_if.py` - NEW endpoints added
   - `analytics_if.py` - Analytics endpoints
   - `calibration_if.py` - Calibration endpoints
   - `queue_if.py` - Queue endpoints
   - `processing_if.py` - Processing endpoints

2. **CLI Commands** (unit tests beyond integration):
   - `cleanup_cli.py`
   - `manage_password_cli.py`

**Components:**
1. **Queue Components** (4/4 untested):
   - `queue_enqueue_comp.py`
   - `queue_dequeue_comp.py`
   - `queue_status_comp.py`
   - `queue_cleanup_comp.py`

2. **Event Components**:
   - `event_broker_comp.py` - StateBroker (SSE)

3. **Worker Components**:
   - `job_recovery_comp.py`
   - `worker_crash_comp.py`

**Workers:**
1. `ScannerWorker` - Long-running scanner
2. `TaggerWorker` - Long-running tagger
3. `RecalibrationWorker` - Long-running recalibration

**Why Medium:**
- Interfaces tested at integration level (coarse but functional)
- Queue/event/worker components are complex but have integration coverage
- Workers are hard to test (long-running processes)

---

### Priority 4: LOW (Nice to Have)

**Helpers:**
1. `file_validation_helper.py` - File validation logic
2. `sql_helper.py` - SQL query building
3. `files_helper.py` - File utilities

**Infrastructure Services:**
1. `ConfigService` - Config loading/validation
2. `InfoService` - System info
3. `KeyManagementService` - API key management

**DTOs:**
1. DTO serialization tests (ensure Pydantic schemas match)

**Why Low:**
- Helpers are simpler, less error-prone
- Infrastructure services are thin wrappers
- DTOs are validated at integration level

---

## 5. Recommendations

### 5.1 Immediate Actions (This Week)

1. **Test NEW code first:**
   - `tag_cleanup_comp.py` ← NEW component
   - `file_tags_comp.py` ← NEW component
   - `cleanup_orphaned_tags_wf.py` ← NEW workflow
   - `LibraryService.cleanup_orphaned_tags()` ← NEW method
   - `LibraryService.get_file_tags()` ← NEW method
   - `library_if.py` cleanup/file-tags endpoints ← NEW endpoints

2. **Create missing test directories:**
   ```
   tests/unit/components/
   tests/unit/components/tagging/
   tests/unit/components/ml/
   tests/unit/components/library/
   tests/unit/components/queue/
   tests/unit/components/analytics/
   tests/unit/helpers/
   tests/unit/interfaces/
   ```

3. **Apply test markers consistently:**
   - Add `pytestmark = pytest.mark.integration` to all integration tests
   - Add `@pytest.mark.requires_ml` to ML tests
   - Add `@pytest.mark.slow` to slow tests (calibration, full scans)

4. **Implement missing fixtures:**
   - `temp_audio_file` - Real audio file fixture
   - `essentia_available` - Check if Essentia installed
   - `skip_if_no_essentia` - Skip ML tests if unavailable

### 5.2 Short-Term Strategy (This Month)

1. **Focus on Priority 1 (CRITICAL):**
   - Test all tagging components (5 modules)
   - Test core ML components (4 modules: inference, embed, heads, audio)
   - Test all library components (4 modules)
   - Test NEW library workflow

2. **Improve test isolation:**
   - Add unit tests for components (currently tested indirectly via workflows)
   - Add unit tests for workflows (currently tested indirectly via services)
   - Keep integration tests but don't rely on them exclusively

3. **Expand edge case coverage:**
   - Invalid inputs (null, empty, malformed)
   - Missing files, corrupted data
   - Missing dependencies (Essentia, models)
   - Database errors (connection failures, constraint violations)

### 5.3 Medium-Term Strategy (Next Quarter)

1. **Balance test pyramid:**
   - Increase unit test coverage to 70%
   - Reduce reliance on integration tests for basic functionality
   - Maintain E2E tests for critical workflows

2. **Test all Priority 2 (HIGH) items:**
   - All services (especially AnalyticsService, NavidromeService)
   - All Navidrome workflows
   - All queue workflows
   - NEW persistence operations

3. **Improve test documentation:**
   - Update TEST_STRUCTURE.md to match reality
   - Document testing conventions (when to mock, when to use real deps)
   - Add examples of good test patterns

4. **Measure coverage:**
   - Use `pytest --cov=nomarr --cov-report=html` to generate coverage reports
   - Set coverage targets: 80% overall, 90% for critical paths

### 5.4 Long-Term Strategy (Ongoing)

1. **Test-driven development for new features:**
   - Write tests BEFORE implementing new features
   - Never commit new code without tests
   - Use `scripts/generate_tests.py` to scaffold test files

2. **Continuous coverage monitoring:**
   - Run coverage reports in CI
   - Block PRs that reduce coverage
   - Require tests for all new code

3. **Refactor tests as architecture evolves:**
   - Keep tests in sync with layer refactoring
   - Remove obsolete tests (e.g., `test_processing_queue.py.legacy`)
   - Update fixtures as dependencies change

---

## 6. Testing Best Practices (Reminders)

### 6.1 What to Test

**DO test:**
- ✅ Business logic (workflows, components)
- ✅ Edge cases (null, empty, invalid)
- ✅ Error handling (exceptions, validation)
- ✅ Integration points (services coordinating workflows)
- ✅ User-facing features (API endpoints, CLI commands)

**DON'T test:**
- ❌ Third-party libraries (assume they work)
- ❌ Trivial getters/setters
- ❌ Framework internals (FastAPI, Click)

### 6.2 How to Test

**Unit tests:**
- Use real dependencies when simple (databases, temp files)
- Mock only external APIs or optional dependencies (Essentia, ML models)
- Test one function/class at a time
- Focus on edge cases and error paths

**Integration tests:**
- Test multiple layers together
- Use real services and databases
- Test happy paths and critical workflows
- Don't duplicate unit test coverage

**E2E tests:**
- Test complete user workflows
- Use real Application instance
- Test only the most critical paths
- Accept slower execution

### 6.3 Test Naming

**Format:** `test_<method>_<scenario>`

```python
# ✅ Good names
def test_cleanup_orphaned_tags_dry_run_returns_count()
def test_get_file_tags_nomarr_only_filters_correctly()
def test_enqueue_files_invalid_path_raises_error()

# ❌ Bad names
def test_cleanup()
def test_tags()
def test_1()
```

### 6.4 Test Structure

**Follow AAA pattern:**
```python
def test_get_file_tags_returns_all_tags(test_db):
    # Arrange
    file_id = test_db.files.create(...)
    tag_id = test_db.tags.get_or_create_tag(...)
    test_db.file_tags.set_file_tags_mixed(...)
    
    # Act
    result = get_file_tags_with_path(test_db, file_id, nomarr_only=False)
    
    # Assert
    assert len(result.tags) == 1
    assert result.tags[0].key == "genre"
```

---

## 7. Conclusion

**Summary:**
- **Strong foundation:** Database, architecture validation, some services
- **Critical gaps:** Components (3% coverage), workflows (22% coverage), interfaces (integration only)
- **NEW code untested:** Tag cleanup and file tags features added this session have ZERO tests
- **Immediate need:** Test NEW code, test components (especially tagging and ML)

**Next Steps:**
1. Create test files for NEW components/workflows (Priority 1)
2. Implement missing test directories
3. Apply markers consistently
4. Follow short-term strategy (test Priority 1 and 2 items)

**Long-Term Vision:**
- 80%+ overall coverage
- 90%+ coverage for critical paths (processing, calibration, tagging)
- Test-driven development for all new features
- Continuous coverage monitoring in CI
