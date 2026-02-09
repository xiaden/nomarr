---
name: Backend Testing
description: Guidelines for writing and running Python backend tests with pytest
applyTo: tests/**/*.py
---

# Backend Testing

**Purpose:** Define how to write, organize, and run pytest-based backend tests for Nomarr.

---

## Quick Reference

```bash
# Activate venv first
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# Run all unit tests
pytest -m unit

# Run a specific test file
pytest tests/unit/helpers/test_time_helper.py

# Run a specific test
pytest tests/unit/helpers/test_time_helper.py::TestNowMs::test_now_ms_returns_milliseconds_type

# Fast local dev (skip expensive tests)
pytest -m "unit and not slow and not requires_models"

# Pre-commit (unit + integration, skip expensive)
pytest -m "(unit or integration) and not slow and not container_only"

# Full suite (CI with models available)
pytest -m "not container_only and not code_smell"
```

---

## Directory Structure

Tests mirror the `nomarr/` source tree:

```
tests/
├── conftest.py                          # Root fixtures (library paths, etc.)
├── test_architecture_qc.py              # Architecture quality checks
├── fixtures/                            # Shared test data
│   └── library/good/                    # Sample audio files by genre
├── unit/                                # Fast, isolated tests
│   ├── components/
│   │   ├── ml/                          # ML component tests
│   │   ├── platform/                    # Platform component tests
│   │   └── tagging/                     # Tagging component tests
│   ├── helpers/                         # Helper/DTO tests
│   │   └── dto/                         # DTO validation tests
│   ├── persistence/                     # Persistence layer tests
│   │   └── database/                    # AQL operation tests
│   ├── services/                        # Service layer tests
│   └── workflows/                       # Workflow tests
└── integration/                         # Multi-component tests
```

### Naming Conventions

- **Files:** `test_<module_name>.py` — matches the source module being tested
- **Classes:** `Test<ClassName>` or `Test<BehaviorGroup>` — groups related tests
- **Functions:** `test_<behavior_under_test>` — describes expected behavior, not implementation

```python
# ✅ Good names
test_normalize_tag_key_lowercases_input
test_scan_library_skips_unchanged_files
test_capacity_estimate_is_conservative_by_default

# ❌ Bad names
test_function_works
test_1
test_library  # Too vague
```

---

## Test Types and Markers

Every test MUST have at least one type marker.

### Type Markers (required — pick one)

| Marker | Speed | Dependencies | Use When |
|--------|-------|--------------|----------|
| `@pytest.mark.unit` | ms | None (mocked) | Testing pure functions, single methods |
| `@pytest.mark.integration` | <1s | Real DB, filesystem | Testing workflows, multi-component flows |
| `@pytest.mark.e2e` | seconds | Full stack running | Testing API → service → DB pipelines |

### Resource Markers (add as needed)

| Marker | Meaning |
|--------|---------|
| `@pytest.mark.slow` | Takes >1 second |
| `@pytest.mark.requires_models` | Needs ML model files on disk |
| `@pytest.mark.requires_audio` | Needs real audio files (not just fixtures) |
| `@pytest.mark.requires_database` | Needs ArangoDB running |
| `@pytest.mark.requires_essentia` | Needs Essentia library installed |
| `@pytest.mark.requires_tensorflow` | Needs TensorFlow installed |
| `@pytest.mark.container_only` | Must run inside Docker (GPU, prod-like env) |

### Informational Markers (optional)

| Marker | Meaning |
|--------|---------|
| `@pytest.mark.code_smell` | Architecture/style check, not functionality |
| `@pytest.mark.mocked` | Uses mocked dependencies (documentation only) |

---

## Writing Unit Tests

Unit tests are the foundation. They test **one thing**, run **fast**, and have **no external dependencies**.

### Pure Functions (preferred — no mocking needed)

```python
"""Tests for nomarr.helpers.time_helper module."""

import pytest

from nomarr.helpers.time_helper import Milliseconds, now_ms


class TestNowMs:
    """Tests for now_ms function."""

    @pytest.mark.unit
    def test_returns_milliseconds_type(self) -> None:
        result = now_ms()
        assert isinstance(result, Milliseconds)

    @pytest.mark.unit
    def test_value_is_reasonable_timestamp(self) -> None:
        result = now_ms()
        assert result.value > 1_577_836_800_000  # After 2020
```

### Mocking Dependencies

Use `unittest.mock` for external dependencies. Mock at the **boundary**, not deep internals.

```python
from unittest.mock import MagicMock, patch

import pytest


class TestMyComponent:
    @pytest.mark.unit
    @pytest.mark.mocked
    def test_processes_files(self) -> None:
        # Mock the database dependency
        mock_db = MagicMock()
        mock_db.library_files.get_pending_files.return_value = [
            {"_key": "f1", "file_path": "/music/song.mp3"},
        ]

        result = process_pending(mock_db, library_key="lib1")

        assert result["processed"] == 1
        mock_db.library_files.get_pending_files.assert_called_once_with("lib1")
```

### Mock Patterns for Nomarr Layers

**Mocking `Database`:**
```python
mock_db = MagicMock()
mock_db.calibration_state.get_all_calibration_states.return_value = [...]
mock_db.calibration_history.get_latest_snapshot.return_value = {...}
mock_db.libraries.list_libraries.return_value = [...]
mock_db.library_files.get_calibration_status_by_library.return_value = [...]
```

**Mocking filesystem:**
```python
# Prefer tmp_path (pytest built-in) over manual tempfile
@pytest.mark.unit
def test_discovers_audio_files(tmp_path) -> None:
    (tmp_path / "song.mp3").write_bytes(b"fake")
    (tmp_path / "image.jpg").write_bytes(b"fake")

    files = discover_files(str(tmp_path))
    assert len(files) == 1
```

**Mocking config:**
```python
from dataclasses import dataclass

@dataclass
class FakeConfig:
    models_dir: str = "/tmp/models"
    namespace: str = "nom"
```

---

## Writing Integration Tests

Integration tests verify multiple components working together. They may use real databases or filesystems.

```python
@pytest.mark.integration
@pytest.mark.requires_database
def test_library_scan_discovers_files(test_db, good_library_root) -> None:
    """Library scan workflow should discover all audio files in fixture library."""
    result = start_scan_workflow(
        db=test_db,
        library_root=str(good_library_root),
    )
    assert result["files_scanned"] > 0
```

---

## Fixture Conventions

### Root conftest.py

Shared fixtures live in `tests/conftest.py`:
- `good_library_root` — path to `tests/fixtures/library/good/`
- `good_library_paths` — dict of known fixture file paths

### Layer-Specific conftest.py

Add `conftest.py` in subdirectories for layer-specific fixtures:

```python
# tests/unit/persistence/conftest.py
@pytest.fixture
def mock_arango():
    """Mock ArangoDB client."""
    ...
```

### Fixture Guidelines

- **Prefer `tmp_path`** over `tempfile.TemporaryDirectory()` — pytest manages cleanup
- **Prefer factory fixtures** over static data when tests need variations
- **Scope fixtures tightly** — use `function` scope (default) unless expensive setup justifies `session`
- **Name fixtures after what they provide**, not how they work

---

## What to Test per Layer

| Layer | What to Test | What to Mock |
|-------|-------------|---------------|
| **Helpers** | Pure functions, DTOs, exceptions | Nothing (no external deps) |
| **Components** | Domain logic, data transformation | Database, filesystem, ML backends |
| **Workflows** | Orchestration flow, error handling | Components (or use real components with mocked DB) |
| **Services** | DI wiring, delegation correctness | Workflows, components |
| **Persistence** | Query correctness, data shapes | ArangoDB client (or use real test DB) |
| **Interfaces** | Request/response shapes, auth | Services |

### Priority Order

1. **Helpers and Components** — most value per test (pure logic, many callers)
2. **Workflows** — verify orchestration correctness
3. **Persistence** — verify queries return expected shapes
4. **Services** — thin wrappers, test only if non-trivial wiring exists
5. **Interfaces** — tested better via E2E; unit test only for complex request validation

---

## Anti-Patterns

```python
# ❌ Testing implementation details
def test_calls_db_twice():
    mock_db.some_method.assert_called_exactly(2)  # Brittle

# ✅ Testing behavior
def test_returns_all_pending_files():
    result = get_pending(mock_db)
    assert len(result) == 3

# ❌ Huge test with no focus
def test_everything():
    # 50 lines testing 5 different behaviors
    ...

# ✅ One behavior per test
def test_skips_hidden_files(): ...
def test_includes_flac_files(): ...
def test_handles_empty_directory(): ...

# ❌ Mocking what you're testing
@patch("nomarr.components.ml.calibration_state_comp.compute_convergence_status")
def test_compute_convergence_status(mock_fn):
    mock_fn.return_value = {...}  # You're testing the mock, not the function

# ✅ Mock dependencies, not the subject
def test_compute_convergence_status():
    mock_db = MagicMock()
    mock_db.calibration_state.get_all_calibration_states.return_value = [...]
    result = compute_convergence_status(mock_db)
    assert result["head_key"]["converged"] is True
```

---

## Validation Checklist

Before committing test code:

- [ ] Every test has at least one type marker (`unit`, `integration`, or `e2e`)
- [ ] Tests are in the correct subdirectory (mirrors `nomarr/` structure)
- [ ] File is named `test_<module>.py`
- [ ] Tests are deterministic (no time-dependent, no random, no network)
- [ ] Expensive tests are marked `slow` and/or `requires_*`
- [ ] `pytest -m unit` passes with all new tests
- [ ] `lint_project_backend(path="tests")` passes with zero errors
