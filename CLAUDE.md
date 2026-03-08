# CLAUDE.md — Nomarr

AI-powered music organization and tagging system. Analyzes music libraries using ONNX ML models (Essentia/MTG) and writes rich metadata tags into audio files.

**Stack:** Python 3.12 (FastAPI/Uvicorn) + React 19 (TypeScript/Vite/MUI) + ArangoDB 3.11 + ONNX Runtime GPU

## Quick Commands

```bash
# Backend tests (default CI gate)
pytest -m "not container_only and not requires_database and not code_smell"

# Fast local dev tests
pytest -m "unit and not slow and not requires_models"

# Specific test file
pytest tests/unit/helpers/test_time_helper.py

# Python linting + formatting
ruff check nomarr/ tests/ --fix
ruff format nomarr/ tests/

# Type checking
mypy nomarr/

# Architecture enforcement (import contracts)
lint-imports

# Frontend (always from frontend/ subdirectory)
cd frontend && npm run lint && npm run build && cd ..

# Frontend tests
cd frontend && npm test && cd ..

# E2E tests (requires Docker containers running)
npx playwright test
```

## Architecture — Layered, Enforced by import-linter

```
interfaces → services → workflows → components → (persistence / helpers)
```

Each layer can only import from layers to its right. Violations fail CI. Contracts are defined in `pyproject.toml` under `[tool.importlinter]`.

| Layer | Location | Role | Naming |
|---|---|---|---|
| **Interfaces** | `nomarr/interfaces/` | Thin HTTP/CLI adapters. Validate input, call ONE service method, serialize output. | `*_if.py` |
| **Services** | `nomarr/services/` | DI wiring + thin orchestration. No business logic. | `*_svc.py` or `*_svc/` package |
| **Workflows** | `nomarr/workflows/` | Use-case recipes. One public function per file. No private helpers. | `*_wf.py` |
| **Components** | `nomarr/components/` | Heavy domain logic (ML, tagging, analytics). Stateless functions preferred. | `*_comp.py` |
| **Persistence** | `nomarr/persistence/` | AQL query modules. No ORM. Access via `db.<module>.<method>()`. | `*_aql.py` |
| **Helpers** | `nomarr/helpers/` | Pure utilities, DTOs, exceptions. No nomarr imports. | `*_helper.py`, `dto/*_dto.py` |

### Key Architecture Rules

- **Pydantic only in interfaces** — services/workflows/components use TypedDicts or dataclasses from `helpers/dto/`
- **No direct DB imports** — external code accesses persistence via `Database` instance (`db.library_files.get_pending_files(...)`)
- **ArangoDB `_id`/`_key` never renamed** — these are native identifiers
- **Essentia isolated** — only `nomarr/components/ml/audio/ml_audio_comp.py` and `nomarr/components/ml/audio/ml_preprocess_comp.py` may import Essentia
- **LibraryPath authority** — `path_comp` is the sole constructor for `LibraryPath`; never accept raw path strings where `LibraryPath` exists
- **Time functions banned** — use `now_ms()`/`now_s()` from `nomarr.helpers.time_helper`, not `time.time()` or `datetime.now()`
- **No `print()`** — use `logging` (logger.info/debug/warning)
- **Workers** live in `services/infrastructure/workers/` and end in `_worker.py` — they are subprocess runners exempt from normal service thinness rules

### Auth Separation

| Router | Auth | Consumer |
|---|---|---|
| `/api/web/*` | `verify_session` (session token) | Web frontend |
| `/api/v1/*` | `verify_key` (API key) | External tools |

Frontend must only call `/api/web/*` endpoints. Never mix auth methods.

## Code Style

- **Line length:** 120 chars
- **Quotes:** Double
- **Indent:** 4 spaces
- **Linter:** ruff (E/W/F/I/N/UP/B/C4/SIM/RUF/TID/ERA/PERF/ASYNC/PIE/RET/LOG/FURB/TC/ARG)
- **Formatter:** ruff format
- **Type checker:** mypy (Python 3.12 target)
- **Imports:** sorted by isort via ruff, `nomarr` is first-party
- **Frontend:** ESLint + TypeScript strict mode, no `any`, MUI `sx` prop (not inline styles)

## Testing

**Backend:** pytest 8.3 with markers. Every test MUST have a type marker (`unit`, `integration`, or `e2e`).

```python
@pytest.mark.unit
def test_something() -> None: ...
```

Resource markers: `slow`, `requires_models`, `requires_audio`, `requires_database`, `requires_essentia`, `container_only`, `code_smell`

Tests mirror `nomarr/` source tree under `tests/unit/` and `tests/integration/`.

**Frontend:** Vitest + React Testing Library. Tests co-located next to source files as `*.test.ts(x)`.

**E2E:** Playwright against Docker environment.

## Project Structure

```
nomarr/                     # Python backend package
  start.py                  # Entry point
  app.py                    # DI container / composition root
  interfaces/api/           # FastAPI routes (web/ and v1/)
  services/domain/          # Business services
  services/infrastructure/  # Config, health, workers, ML
  workflows/                # Use-case orchestration
  components/               # Heavy domain logic
  persistence/              # ArangoDB data access
  helpers/                  # Pure utilities + DTOs
  migrations/               # DB schema migrations (V004-V014)
  public_html/              # Built frontend assets (committed)
frontend/                   # React + TypeScript + Vite source
tests/                      # pytest test suite
e2e/                        # Playwright E2E tests
docker/                     # Docker Compose (ArangoDB + Nomarr)
dockerfile                  # App image (fast, uses pre-built base)
dockerfile.base             # Base image (CUDA, Essentia, ONNX RT)
scripts/                    # Build tools and diagnostics
build_resources/            # Docker build assets, ML models
```

## Docker

```bash
cd docker
cp nomarr-arangodb.env.example nomarr-arangodb.env
cp nomarr.env.example nomarr.env
# Edit .env files, then:
docker compose up -d
```

API at `http://127.0.0.1:8356`. Use `127.0.0.1` not `localhost` on Windows (IPv6 resolution issue).

## Key Collections (ArangoDB)

- `libraries` — library config and scan state
- `library_files` — scanned audio files
- `tags` — tag vertices with `{rel, value}` (e.g., `{rel: "artist", value: "Beatles"}`)
- `song_has_tags` — edges from `library_files/*` to `tags/*`
- `calibration_state`, `calibration_history` — calibration data
- No separate `songs`/`artists`/`albums` collections — entity data comes from `tags` filtered by `rel`

## CI (GitHub Actions)

1. **test** — Python 3.12, unit tests, verify frontend build up-to-date
2. **build-and-push** — Docker build to ghcr.io (depends on test passing)
3. **build-base** — Base image rebuild (manual or on essentia changes)
