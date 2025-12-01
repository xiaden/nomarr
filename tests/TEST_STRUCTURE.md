# Test Structure and Organization

This document defines the test suite organization, fixture usage, and testing conventions for Nomarr.

## Test Categories (Suites)

### 1. Unit Tests - Data Layer (`tests/unit/data/`)

**Purpose**: Test database operations and queue data structures in isolation.

**Files**:

- `test_database.py` - Database class (schema, connections, queries)
- `test_job.py` - Job dataclass operations
- `test_processing_queue.py` - ProcessingQueue CRUD operations

**Fixtures Used**:

- `temp_db` - Temporary SQLite file
- `in_memory_db` - Fast in-memory database
- `test_db` - Initialized Database instance

**Characteristics**:

- ✅ Use REAL SQLite databases (temp or in-memory)
- ❌ NO mocking of database operations
- ⚡ Fast (in-memory preferred)
- 🔒 Isolated (each test gets fresh DB)

---

### 2. Unit Tests - Services Layer (`tests/unit/services/`)

**Purpose**: Test business logic and service operations with real dependencies.

**Files**:

- `test_queue_service.py` - QueueService business operations
- `test_processing_service.py` - ProcessingService operations
- `test_library_service.py` - LibraryService scan operations
- `test_worker_service.py` - WorkerService state management
- `test_health_monitor.py` - HealthMonitor tracking

**Fixtures Used**:

- `test_db` - Real Database instance
- `mock_job_queue` - Real JobQueue instance
- `temp_dir` - Temporary directory for file operations
- `mock_audio_file` - Temporary audio file

**Characteristics**:

- ✅ Use REAL services with real databases
- ✅ Use REAL temp files for file operations
- ❌ NO mocking of internal services
- ⚠️ Mock only external APIs (if needed)
- 🧪 Test business logic and error handling

---

### 3. Unit Tests - ML Layer (`tests/unit/ml/`)

**Purpose**: Test ML inference and model management (conditionally).

**Files**:

- `test_model_cache.py` - ModelCache loading/eviction
- `test_inference.py` - Inference engine operations
- `test_model_discovery.py` - Model discovery logic
- `test_embeddings.py` - Embedding model interfaces
- `test_heads.py` - Classification head interfaces

**Fixtures Used**:

- `essentia_available` - Check if Essentia installed
- `tensorflow_available` - Check if TensorFlow installed
- `skip_if_no_essentia` - Skip test if unavailable
- `skip_if_no_tensorflow` - Skip test if unavailable
- `mock_sidecar` - Mock model metadata
- `mock_embeddings` - Synthetic embedding data
- `mock_predictor` - Mock predictor function

**Characteristics**:

- ⚠️ Skip tests if ML dependencies unavailable
- ✅ Use REAL models if available
- ⚠️ Mock models ONLY if TensorFlow/Essentia missing
- 🧪 Test model loading, caching, inference logic

---

### 4. Unit Tests - Tagging Layer (`tests/unit/tagging/`)

**Purpose**: Test tag processing and aggregation logic.

**Files**:

- `test_aggregation.py` - Mood tier aggregation
- `test_tag_writer.py` - Tag writing logic

**Fixtures Used**:

- `mock_head_scores` - Synthetic head output
- `temp_audio_file` - Real audio file for writing
- `mock_config` - Configuration for namespace

**Characteristics**:

- ✅ Use REAL aggregation functions
- ✅ Test actual mood tier logic
- 🧪 Validate tag format and structure

---

### 5. Integration Tests - Services (`tests/integration/services/`)

**Purpose**: Test service interactions and coordination.

**Files**:

- `test_service_coordination.py` - Multi-service workflows
- `test_processing_pipeline.py` - QueueService → ProcessingService flow

**Fixtures Used**:

- `test_db` - Shared database
- `real_queue_service` - Real QueueService instance
- `real_processing_service` - Real ProcessingService instance
- `temp_audio_file` - Real audio file

**Characteristics**:

- ✅ Test multiple services together
- ✅ Use real service instances
- 🔄 Test service-to-service communication
- 🧪 Validate coordination and state management

---

### 6. Integration Tests - API (`tests/integration/api/`)

**Purpose**: Test HTTP API endpoints with real Application instance.

**Files**:

- `test_public_endpoints.py` - /api/v1/tag, /api/v1/list, etc.
- `test_admin_endpoints.py` - /admin/worker/pause, /admin/cache/refresh
- `test_web_endpoints.py` - /web/auth/login, /web/api/process
- `test_authentication.py` - API key and session auth

**Fixtures Used**:

- `test_client` - FastAPI TestClient
- `test_application` - Real Application instance
- `mock_api_key` - API key for auth
- `mock_admin_password` - Admin password for web auth

**Characteristics**:

- ✅ Use FastAPI TestClient
- ✅ Real Application instance (not mocked)
- 🌐 Test HTTP layer and serialization
- 🔐 Test authentication and authorization

---

### 7. Integration Tests - CLI (`tests/integration/cli/`)

**Purpose**: Test CLI command operations.

**Files**:

- `test_cli_run.py` - `run` command
- `test_cli_queue.py` - `queue`, `list`, `remove` commands
- `test_cli_admin.py` - `admin-reset`, `cache-refresh` commands

**Fixtures Used**:

- `cli_runner` - Click CliRunner for command invocation
- `test_application` - Real Application instance
- `temp_audio_file` - Real audio file

**Characteristics**:

- ✅ Use Click's CliRunner
- ✅ Test actual command execution
- 🖥️ Test output formatting and error messages

---

### 8. Integration Tests - End-to-End (`tests/integration/`)

**Purpose**: Test complete workflows from start to finish.

**Files**:

- `test_application_lifecycle.py` - Application.start() → stop()
- `test_full_pipeline.py` - Queue → Process → Tag → Done
- `test_lidarr_webhook.py` - Simulated Lidarr POST → tag written

**Fixtures Used**:

- `test_application` - Real Application instance
- `test_client` - FastAPI TestClient
- `temp_audio_file` - Real audio file
- `temp_music_library` - Full library structure

**Characteristics**:

- ✅ Full system integration
- ✅ Real Application lifecycle
- 🔄 Complete processing pipeline
- 🧪 End-to-end validation

---

## Key Fixtures Reference

### Database Fixtures

- **`temp_db`** - Temporary SQLite file (real database)
- **`in_memory_db`** - In-memory SQLite (faster for unit tests)
- **`test_db`** - Initialized Database instance with schema

### Service Fixtures

- **`mock_job_queue`** - Real JobQueue instance (uses test_db)
- **`mock_key_service`** - Real KeyManagementService instance

### File Fixtures

- **`temp_dir`** - Temporary directory for file operations
- **`temp_audio_file`** - Real audio file for testing (to be created)
- **`temp_music_library`** - Full library structure (to be created)

### ML Fixtures

- **`essentia_available`** - Boolean: Is Essentia installed?
- **`tensorflow_available`** - Boolean: Is TensorFlow installed?
- **`skip_if_no_essentia`** - Skip test if Essentia unavailable
- **`skip_if_no_tensorflow`** - Skip test if TensorFlow unavailable
- **`mock_sidecar`** - Mock model metadata JSON
- **`mock_embeddings`** - Synthetic embedding data
- **`mock_head_scores`** - Synthetic head output
- **`mock_predictor`** - Mock predictor function

### Auth Fixtures

- **`mock_api_key`** - API key for authentication tests
- **`mock_admin_password`** - Admin password for web auth tests
- **`mock_session_token`** - Session token for web UI tests

### Config Fixtures

- **`mock_config`** - Configuration dictionary for tests

---

## Testing Principles

### ✅ DO:

1. **Use REAL components** - Real databases, real services, real files
2. **Create temp resources** - Use fixtures to create/cleanup temp DBs and files
3. **Test actual behavior** - Don't mock internal code
4. **Isolate tests** - Each test gets fresh resources
5. **Follow the layer** - Test data layer separately from services
6. **Skip conditionally** - Skip ML tests if dependencies unavailable

### ❌ DON'T:

1. **Mock internal code** - Don't mock Database, ProcessingQueue, services
2. **Use production DB** - Always use temp/in-memory databases
3. **Leave resources** - Always cleanup temp files/databases
4. **Assume dependencies** - Check availability before using ML libraries
5. **Mix layers** - Don't test services in data layer tests

---

## Running Tests

### All Tests

```bash
pytest tests/ -v
```

### Specific Suite

```bash
# Data layer only
pytest tests/unit/data/ -v

# Services layer only
pytest tests/unit/services/ -v

# ML layer (skip if dependencies unavailable)
pytest tests/unit/ml/ -v

# Integration tests
pytest tests/integration/ -v
```

### With Coverage

```bash
pytest tests/ --cov=nomarr --cov-report=html
```

### Skip Slow Tests

```bash
pytest tests/ -v -m "not slow"
```

---

## Test Naming Conventions

### Test Files

- `test_<module>.py` - Unit tests for specific module
- `test_<feature>.py` - Integration tests for feature

### Test Classes

- `Test<ClassName><Operation>` - e.g., `TestQueueServiceAddFiles`
- Group related tests in classes

### Test Functions

- `test_<what>_<condition>` - e.g., `test_add_file_success`
- `test_<what>_raises_<error>` - e.g., `test_add_file_raises_not_found`

### Example

```python
class TestQueueServiceEnqueueFiles:
    """Test QueueService.enqueue_files_for_tagging() operations."""

    def test_add_single_file(self, queue_service):
        """Should add single file to queue successfully."""
        # Test implementation

    def test_add_directory_recursive(self, queue_service, temp_dir):
        """Should recursively add all files in directory."""
        # Test implementation

    def test_add_nonexistent_file_raises_error(self, queue_service):
        """Should raise FileNotFoundError for missing files."""
        # Test implementation
```

---

## Next Steps

1. **Create missing fixtures** (temp_audio_file, temp_music_library, cli_runner, test_client, test_application)
2. **Generate unit tests** for each layer following this structure
3. **Generate integration tests** after unit tests pass
4. **Add pytest markers** for slow tests, integration tests, etc.
5. **Update CI/CD** to run test suites separately

---

## Questions?

This structure follows the "test in layers" philosophy:

- Test basic components first (data layer)
- Test business logic next (services layer)
- Test ML conditionally (skip if unavailable)
- Test integration last (full system)

All tests use REAL components with temp resources - no mocking of internal code!
