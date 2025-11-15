# Smoke Test Suite

Comprehensive end-to-end smoke tests for all nomarr commands and endpoints.

## Purpose

These tests verify that all CLI commands, API endpoints, and web UI operations don't crash with minimal setup. They use:

- **Fake databases** - No real DB required
- **Generated audio files** - Programmatically created WAV files (no external downloads)
- **Mocked services** - Services are mocked to avoid ML model dependencies

## Test Coverage

### CLI Commands (`test_cli_smoke.py`)

- **tag**: Basic tagging, force flag, nonexistent files, files below min_duration
- **queue**: List, status, remove, clear operations
- **library**: Scan, list, stats operations
- **calibration**: Status, start, history operations
- **worker**: Status, pause, resume operations
- **cache**: Refresh, list operations
- **admin**: Reset stuck jobs, reset errors, cleanup
- **help**: All help outputs

### API Endpoints (`test_api_smoke.py`)

- **Public API (`/api/v1/*`)**: Tag, queue listing, job status, legacy endpoints
- **Internal API (`/internal/*`)**: Direct processing, streaming, batch processing
- **Admin API (`/admin/*`)**: Worker control, queue management, cache operations
- **Web Auth (`/web/auth/*`)**: Login, logout, session verification
- **Web API (`/web/api/*`)**: Proxy endpoints for browser UI
- **Health**: Health check and readiness endpoints

## Running Tests

### Run All Smoke Tests

```bash
pytest tests/smoke/ -v
```

### Run Specific Test Category

```bash
# CLI tests only
pytest tests/smoke/test_cli_smoke.py -v

# API tests only
pytest tests/smoke/test_api_smoke.py -v
```

### Run Specific Test Class

```bash
# Test CLI tag command only
pytest tests/smoke/test_cli_smoke.py::TestCLITag -v

# Test API tag endpoints only
pytest tests/smoke/test_api_smoke.py::TestPublicAPITag -v
```

## Test Fixtures

### Generated Audio Files

Test audio files are generated programmatically using pure Python (wave module):

- `test_basic.wav` - 8s, 440 Hz (A4), standard test file
- `test_long.wav` - 15s, 523.25 Hz (C5), longer processing test
- `test_short.wav` - 5s, 330 Hz (E4), below min_duration test
- `test_variety.wav` - 10s, 659.25 Hz (E5), variety test

**No external downloads required!** All audio is generated on-the-fly.

### Regenerating Fixtures

```bash
python tests/fixtures/generate.py
```

## Architecture

### Isolation

- Each test runs in a temporary directory
- Fake databases are created per-test or per-session
- No shared state between tests
- Environment variables override default paths

### Mocking Strategy

- **CLI tests**: Subprocess execution with environment variable overrides
- **API tests**: FastAPI TestClient with mocked Application and services
- **Services**: MagicMock for all service dependencies

### Acceptable Outcomes

Tests check that commands/endpoints don't crash, not that they succeed:

- **CLI**: Exit codes 0 or 1 are acceptable (not crash codes like -1, 137, etc.)
- **API**: Status codes 200, 400, 404, 503 are acceptable depending on context
- **Errors**: Graceful error messages expected, not stack traces or crashes

## Integration with CI

These smoke tests can run in GitHub Actions without:

- GPU/CUDA
- ML models
- External audio files
- Real database with production data

Add to CI workflow:

```yaml
- name: Run smoke tests
  run: pytest tests/smoke/ -v --tb=short
```

## Extending Tests

### Adding New CLI Command Tests

1. Add test class to `test_cli_smoke.py`
2. Use `run_cli_command()` helper
3. Check exit codes, not output content
4. Test both success and failure paths

### Adding New API Endpoint Tests

1. Add test class to `test_api_smoke.py`
2. Use `test_client` fixture
3. Mock authentication as needed
4. Check status codes, not response bodies

### Adding New Test Fixtures

1. Edit `tests/fixtures/generate.py`
2. Add new audio file generation in `create_test_fixtures()`
3. Update fixture dictionary
4. Document in fixtures README

## Troubleshooting

### Import Errors

If you see import errors during linting, this is expected. Tests import nomarr modules that require the full environment. Tests run fine with pytest.

### Audio Generation Fails

If WAV generation fails, check:

- Python `wave` module is available (standard library)
- Temp directory is writable
- Sufficient disk space

### Tests Fail on CI

Check:

- Environment variables are set correctly
- Temp directories are accessible
- No hardcoded paths (use fixtures)

## Design Principles

1. **Fast**: No ML model loading, no real processing
2. **Isolated**: Each test is independent
3. **Comprehensive**: Cover all commands and endpoints
4. **Maintainable**: Clear naming, minimal mocking
5. **CI-friendly**: No external dependencies or GPU requirements
