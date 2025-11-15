# Integration Test Suite

Real end-to-end integration tests for the nomarr production system.

> **⚠️ SKIPPED IN CI**: These tests require GPU and are automatically excluded from GitHub Actions.  
> Run manually in Docker container for pre-deployment validation.

## Purpose

These tests verify the **actual production system** works correctly:

✅ **Real ML models** - No mocking, actual inference  
✅ **Real audio processing** - Actual MP3 files processed  
✅ **Real database operations** - Actual SQLite interactions  
✅ **Real API endpoints** - HTTP calls to running API server  
✅ **Real CLI commands** - Subprocess execution of actual CLI

**NOT smoke tests** - These tests will catch real production issues, not just wiring problems.

## Test Coverage

### API Integration (`test_api_integration.py`)

- **Public API** (`/api/v1/*`)
  - Tag endpoints with real audio processing
  - Queue listing and filtering
  - Authentication enforcement
- **Internal API** (`/internal/*`)
  - Direct synchronous processing
  - SSE streaming with real progress updates
- **Admin API** (`/admin/*`)
  - Worker status and control
  - Model cache management
- **Web Auth** (`/web/auth/*`)
  - Login/logout flows
  - Session verification
- **Health Endpoints**
  - Health checks
  - Readiness checks

### CLI Integration (`test_cli_integration.py`)

Tests the actual CLI commands (admin tools only):

- `remove` - Queue management (remove jobs by ID or status)
- `cleanup` - Remove old completed jobs
- `cache-refresh` - Rebuild model cache
- `admin-reset` - Reset stuck or error jobs
- `manage-password` - Admin password management

**Note:** CLI does NOT have `tag` or workflow commands - those are API-only.

## Running Tests

### ⚠️ Important: CI Exclusion

These tests are **automatically skipped in GitHub Actions CI** because they require:
- GPU for ML inference (GitHub runners are CPU-only)
- Real ML model files (~400MB per worker)
- Docker container environment

They are marked with:
```python
@pytest.mark.gpu_required      # Needs GPU for fast inference
@pytest.mark.container_only    # Designed for Docker container
@pytest.mark.integration       # Real system testing
```

### Prerequisites

1. **GPU recommended** - CPU inference is 10-100x slower
2. **API server must be running** (for API tests)
3. **ML models must be available** (in `/app/models`)
4. **Test fixtures** - MP3 files in `tests/fixtures/`
5. **Environment variables** (optional):
   ```bash
   export NOMARR_API_URL="http://localhost:8356"
   export NOMARR_API_KEY="your-api-key"
   ```

### Run All Integration Tests

```bash
# Explicitly run GPU-required tests (skipped by default in CI)
pytest tests/integration/ -v -m "gpu_required or container_only"

# Or run all integration tests
pytest tests/integration/ -v
```

### Run Specific Test Category

```bash
# API tests only (requires GPU + running API)
pytest tests/integration/test_api_integration.py -v

# CLI tests only (no GPU needed, but needs container environment)
pytest tests/integration/test_cli_integration.py -v
```

### Skip GPU Tests Locally

If you want to run only non-GPU tests (like in CI):
```bash
pytest tests/ -v -m "not gpu_required and not container_only"
```

### Run in Docker Container

```bash
# Inside running container
docker exec -it nomarr pytest /app/tests/integration/ -v

# Or with docker compose
docker compose exec nomarr pytest /app/tests/integration/ -v
```

## Test Fixtures

### MP3 Files (Generated)

- `test_basic.mp3` - 65s (just over 60s minimum)
- `test_long.mp3` - 90s (longer processing)
- `test_short.mp3` - 30s (below minimum, should be rejected)
- `test_variety.mp3` - 120s (2 minutes)

**Generated with:**

```bash
python tests/fixtures/generate.py
```

Requires: `pydub` and `ffmpeg`

## Design Principles

### 1. Real System Testing

**NO MOCKING** - Tests use the actual production code paths:

- Real ML model loading and inference
- Real audio file I/O and processing
- Real database queries and transactions
- Real HTTP requests to live API server
- Real subprocess execution for CLI

### 2. Production-Ready

Tests are designed to run in the actual Docker container:

- Uses same paths as production (`/app/models`, `/app/config`)
- Tests real container environment
- Catches Docker-specific issues (permissions, paths, dependencies)

### 3. Fast Enough

Despite being real integration tests:

- Small test files (65-120s audio)
- Minimal model warm-up (cache after first run)
- Parallel test execution possible
- ~30-60s total runtime

### 4. Clear Failures

When tests fail, it means something is actually broken:

- ML models missing or corrupted
- Audio processing pipeline broken
- API routing issues
- Database migration problems
- CLI command regressions

## CI Integration

### In GitHub Actions

```yaml
jobs:
  integration-test:
    runs-on: ubuntu-latest
    services:
      nomarr:
        image: ghcr.io/xiaden/nomarr:latest
        ports:
          - 8356:8356
        volumes:
          - ./models:/app/models
          - ./config:/app/config

    steps:
      - uses: actions/checkout@v4

      - name: Wait for API
        run: |
          timeout 60 bash -c 'until curl -f http://localhost:8356/health; do sleep 2; done'

      - name: Run integration tests
        run: |
          pytest tests/integration/ -v
        env:
          NOMARR_API_URL: http://localhost:8356
          NOMARR_API_KEY: ${{ secrets.API_KEY }}
```

### In Docker Compose

Add to `docker-compose.yml`:

```yaml
services:
  nomarr-test:
    build: .
    command: pytest /app/tests/integration/ -v
    volumes:
      - ./models:/app/models
      - ./config:/app/config
      - ./tests:/app/tests
    environment:
      - NOMARR_API_URL=http://nomarr:8356
```

## Troubleshooting

### Tests Fail: "Connection refused"

API server not running or wrong URL:

```bash
# Check if API is up
curl http://localhost:8356/health

# Set correct URL
export NOMARR_API_URL="http://localhost:8356"
```

### Tests Fail: "403 Forbidden"

API key not set or incorrect:

```bash
# Show API key (inside container)
python3 -m nomarr.manage_key --show

# Set in environment
export NOMARR_API_KEY="your-key-here"
```

### Tests Fail: "Models not found"

ML models not available:

```bash
# Check models directory
ls -la models/effnet models/yamnet

# Ensure models mounted in container
docker compose config
```

### Tests Fail: "File below minimum duration"

This is expected for `test_short.mp3` - should be caught and rejected gracefully.

### Slow Test Execution

First run is slower (model loading):

- Subsequent runs use cached models
- Consider increasing `cache_idle_timeout` in config
- GPU speeds up inference significantly

## Maintenance

### Adding New Tests

1. Add test class to appropriate file
2. Use real system calls (no mocks)
3. Test both success and failure paths
4. Document expected behavior

### Updating Fixtures

```bash
# Edit generation parameters in generate.py
vim tests/fixtures/generate.py

# Regenerate
python tests/fixtures/generate.py

# Commit new fixtures
git add tests/fixtures/*.mp3
git commit -m "Update test fixtures"
```

### Verifying Test Quality

Good integration tests should:

- [ ] Use real API HTTP calls or subprocess CLI execution
- [ ] Process actual audio files through ML pipeline
- [ ] Interact with real database
- [ ] Fail when production code breaks
- [ ] Pass in Docker container environment
- [ ] Run in < 2 minutes total

## Comparison: Unit vs Integration

| Aspect       | Unit Tests     | Integration Tests (these) |
| ------------ | -------------- | ------------------------- |
| Mocking      | Heavy          | None                      |
| Speed        | Fast (<1s)     | Moderate (~60s)           |
| Coverage     | Function-level | System-level              |
| Dependencies | Minimal        | Full stack                |
| Catches      | Logic bugs     | System issues             |
| Runs         | Anywhere       | Container preferred       |

Both are valuable - unit tests for development, integration tests for deployment confidence.
