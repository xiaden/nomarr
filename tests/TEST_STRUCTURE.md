# Test Structure and Guidelines

This document describes how tests are organized in Nomarr and when to use each pytest marker.

## Directory Structure

The `tests/` directory mirrors the structure of `nomarr/` to make it easy to find tests for specific modules:

```
tests/
├── unit/                           # Unit tests (fast, isolated)
│   ├── components/                 # Tests for nomarr/components/
│   │   ├── analytics/              # Analytics components
│   │   ├── events/                 # Event system components
│   │   ├── library/                # Library management components
│   │   ├── ml/                     # ML inference components
│   │   ├── queue/                  # Queue management components
│   │   ├── tagging/                # Tagging logic components
│   │   └── workers/                # Worker components
│   ├── helpers/                    # Tests for nomarr/helpers/
│   │   └── dto/                    # DTO validation tests
│   ├── interfaces/                 # Tests for nomarr/interfaces/
│   │   ├── api/                    # API interface tests
│   │   │   ├── types/              # API type/model tests
│   │   │   └── web/                # Web endpoint tests
│   │   └── cli/                    # CLI interface tests
│   ├── persistence/                # Tests for nomarr/persistence/
│   │   └── database/               # Database operations tests
│   ├── services/                   # Tests for nomarr/services/
│   │   ├── domain/                 # Domain service tests
│   │   └── infrastructure/         # Infrastructure service tests
│   └── workflows/                  # Tests for nomarr/workflows/
│       ├── calibration/            # Calibration workflow tests
│       ├── library/                # Library workflow tests
│       ├── navidrome/              # Navidrome sync workflow tests
│       ├── processing/             # Processing workflow tests
│       └── queue/                  # Queue workflow tests
│
├── integration/                    # Integration tests (multiple components)
│   └── ...                         # Organized by feature/workflow
│
├── fixtures/                       # Shared test fixtures and data
│   ├── audio/                      # Test audio files
│   └── config/                     # Test configuration files
│
└── conftest.py                     # Shared fixtures and configuration

```

### Naming Conventions

- **Test files**: `test_<module_name>.py` (e.g., `test_library_service.py` for `library_service.py`)
- **Test classes**: `Test<ClassName>` (e.g., `TestLibraryService`)
- **Test functions**: `test_<behavior>` (e.g., `test_scan_library_queues_files`)

## Test Types and Markers

### Core Test Type Markers

#### `@pytest.mark.unit`
Fast, isolated tests for individual functions/classes with minimal mocking.

**When to use:**
- Testing pure functions
- Testing single methods with mocked dependencies
- No database, no filesystem, no network
- Should run in milliseconds

**Example:**
```python
@pytest.mark.unit
def test_normalize_tag_key():
    assert normalize_tag_key("Genre") == "genre"
    assert normalize_tag_key("ALBUM_ARTIST") == "albumartist"
```

#### `@pytest.mark.integration`
Tests multiple components working together with real dependencies.

**When to use:**
- Testing workflows that call multiple components
- Testing service layer orchestration
- Using real database (ArangoDB test instance)
- Testing file I/O with test fixtures

**Example:**
```python
@pytest.mark.integration
def test_library_scan_workflow(test_db, tmp_audio_files):
    # Tests workflow → components → persistence
    stats = start_library_scan_workflow(
        db=test_db,
        params=ScanParams(...)
    )
    assert stats["files_queued"] > 0
```

#### `@pytest.mark.e2e`
End-to-end tests that exercise full pipelines through API/CLI.

**When to use:**
- Testing complete user workflows
- API endpoint → service → workflow → components → database
- CLI command execution
- Rarely used (expensive, fragile)

### Resource Requirement Markers

#### `@pytest.mark.slow`
Tests that take >1 second to complete.

**When to use:**
- Model loading/inference
- Heavy computation
- Processing multiple files
- May be skipped in watch mode

**Example:**
```python
@pytest.mark.slow
@pytest.mark.requires_models
def test_embedding_generation(audio_file):
    embeddings = compute_embeddings_for_backbone(...)
    assert embeddings.shape[0] > 0
```

#### `@pytest.mark.requires_models`
Tests that need model files (embeddings, heads) to be present.

**When to use:**
- ML inference tests
- Embedding generation
- Head prediction
- Should be skipped if models not downloaded

#### `@pytest.mark.requires_audio`
Tests that need real audio files (not just fixtures).

**When to use:**
- Audio metadata extraction
- Audio file validation
- Processing real-world audio files

#### `@pytest.mark.requires_essentia`
Tests that need the Essentia library (optional dependency).

**When to use:**
- Tests importing `essentia` or `essentia_tensorflow`
- Audio analysis using Essentia
- Should be skipped if Essentia not installed

#### `@pytest.mark.requires_tensorflow`
Tests that need TensorFlow (optional ML dependency).

**When to use:**
- Tests using TensorFlow models
- Tests importing `tensorflow`
- Should be skipped if TensorFlow not installed

#### `@pytest.mark.container_only`
Tests designed to run only in Docker container environment.

**When to use:**
- Tests requiring GPU (containers provide GPU access)
- Tests requiring specific container setup
- Tests with models/data only available in container
- **Replaces `gpu_required`** - if a test needs GPU, mark it `container_only`

**Note:** This marker implies the test may need GPU, models, or other container-specific resources. Do NOT use both `container_only` and `gpu_required`.

### Informational Markers

#### `@pytest.mark.code_smell`
Architecture/style tests that don't indicate broken functionality.

**When to use:**
- Import-linter checks
- Code structure validation
- Naming convention checks
- Should be skipped in CI (doesn't block merges)

**Example:**
```python
@pytest.mark.code_smell
def test_no_circular_imports():
    # Validates architecture rules
    result = subprocess.run(["lint-imports"], ...)
    assert result.returncode == 0
```

#### `@pytest.mark.mocked`
Informational marker indicating test uses mocked dependencies.

**When to use:**
- Optional, for documentation
- Helps identify tests that might need integration equivalents
- Not used for test selection

#### `@pytest.mark.real_db`
Informational marker indicating test uses real database (not in-memory).

**When to use:**
- Tests using persistent ArangoDB instance
- Helps identify tests that need cleanup
- Usually combined with `@pytest.mark.integration`

## Running Tests

### By Test Type
```bash
# Fast unit tests only
pytest -m unit

# Integration tests
pytest -m integration

# Unit + integration (skip slow/expensive)
pytest -m "unit or integration"

# Everything except slow tests
pytest -m "not slow"
```

### By Resource Requirements
```bash
# Skip tests needing models
pytest -m "not requires_models"

# Skip tests needing Essentia
pytest -m "not requires_essentia"

# Skip container-only tests (typical for local dev)
pytest -m "not container_only"

# Skip code smell tests (typical for CI)
pytest -m "not code_smell"
```

### Common Combinations
```bash
# Fast local development (unit tests, no external deps)
pytest -m "unit and not slow and not requires_models"

# Pre-commit checks (fast unit + integration, skip expensive)
pytest -m "(unit or integration) and not slow and not container_only"

# Full test suite (CI with models)
pytest -m "not container_only and not code_smell"

# Container-only tests (in Docker)
pytest -m "container_only"
```

## Test Development Guidelines

### 1. Start with Unit Tests
- Test individual functions/methods in isolation
- Mock external dependencies (DB, filesystem, ML models)
- Aim for 100% coverage of business logic

### 2. Add Integration Tests for Complex Flows
- Test workflows that orchestrate multiple components
- Use real database (ArangoDB test instance)
- Test actual file operations with fixtures

### 3. Use Appropriate Markers
- Always mark tests with at least one type marker (`unit`/`integration`/`e2e`)
- Add resource markers (`slow`, `requires_*`) as needed
- Use `container_only` for tests that need GPU or container setup
- Mark architecture tests with `code_smell`

### 4. Keep Tests Fast
- Unit tests should run in milliseconds
- Integration tests should run in <1 second
- Mark anything slower with `@pytest.mark.slow`
- Consider mocking expensive operations

### 5. Make Tests Deterministic
- No reliance on system time (mock `datetime.now()`)
- No network calls (mock API clients)
- Use fixtures for test data
- Clean up after tests (temp files, DB state)

### 6. Structure Tests by Behavior
```python
class TestLibraryService:
    """Tests for LibraryService."""
    
    def test_scan_library_discovers_files(self, ...):
        """Library scan should discover all audio files."""
        ...
    
    def test_scan_library_skips_unchanged_files(self, ...):
        """Library scan should skip files with matching mtimes."""
        ...
    
    def test_scan_library_handles_missing_paths(self, ...):
        """Library scan should log warning for missing paths."""
        ...
```

## Deprecated/Removed Markers

The following markers have been removed to avoid duplication:

- ~~`gpu_required`~~ - Use `container_only` instead (GPU tests run in containers)

## Future Considerations

As the test suite grows, consider adding:
- Performance benchmarking marks
- Flaky test identification
- Test ownership/team tags
- Browser/UI testing marks (if web UI tests added)
