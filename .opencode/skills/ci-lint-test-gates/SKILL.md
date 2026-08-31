---
name: ci-lint-test-gates
description: The authoritative lint and test gate commands for Nomarr CI — backend quality (ruff check, ruff format --check, mypy, lint-imports, deptry), backend tests (pytest gate with marker exclusions, ADR-042 architecture-qc, DB characterization/sabotage tier), frontend checks (ESLint, tsc -b --noEmit, vitest, build), plus e2e/docs/codeql trigger semantics. Use when running verification before a commit/PR, when asked "what checks must pass", when adding a test or changing lint config, or when CI fails on a lint/test job and you need the exact invocation.
---

# Nomarr CI Lint & Test Gates

## Mental Model

Nomarr has **no pre-commit hook** (`pre-commit` is in dev deps but there is no
`.pre-commit-config.yaml`; `readme.md:139` and `CONTRIBUTING.md:56` state
enforcement is CI-owned). Merge gates are independent GitHub Actions workflows,
each reporting its own result. The single source of truth for *which checks are
required for a commit* is `REQUIRED_CHECKS` in `scripts/validate_commit.py`
(see the `ci-validate-commit` skill for its matching machinery). This skill is
the companion: the exact commands each gate runs, so you can reproduce them
locally.

## Coverage

**Documented:** exact commands for every backend/frontend/e2e gate, pytest
marker semantics and exclusions, local tooling (`lint_project_backend`,
`lint_project_frontend`), venv requirements, no-pre-commit status.
**Not yet documented:** none known.
**Last extended:** 2026-08-31

## Key Findings

### Backend quality — `.github/workflows/backend-quality.yml`
- **Location:** `.github/workflows/backend-quality.yml:76-94` (job `lint`), `:124-127` (job `deptry`)
- **What:** Job `lint` runs four commands in order:
  1. `ruff check .`
  2. `ruff format --check .`
  3. `mypy nomarr/ --config-file pyproject.toml`
  4. `lint-imports`
  Job `deptry` runs: `deptry . --known-first-party nomarr`
- **Why it matters:** These are required, merge-blocking checks (`REQUIRED_CHECKS` keys `lint`, `deptry`). mypy is scoped to `nomarr/` only (tests/, scripts/ excluded in `pyproject.toml [tool.mypy] exclude`).

### Backend tests — `.github/workflows/backend-tests.yml`
- **Location:** `.github/workflows/backend-tests.yml:91-94` (job `test`), `:129-132` (job `architecture-qc`), `:184-187` (job `database-tests`)
- **What:** Three jobs:
  - `test`: `pytest tests/ -v -m "not container_only and not requires_database and not code_smell"` (needs `libchromaprint1` system package)
  - `architecture-qc`: `pytest tests/test_architecture_qc.py -v` — runs the ADR-042 code_smell suite EXPLICITLY because the main gate excludes `code_smell`
  - `database-tests`: `pytest tests/characterization/ tests/sabotage/test_no_facades_begin_transactions.py -v -m requires_database` — testcontainers spawns `pgvector/pgvector:pg17` via the Docker socket; fixtures apply Alembic migrations themselves (no manual DB setup)
- **Why it matters:** `requires_database` tests are EXCLUDED from the local-friendly gate — the broad pytest run is NOT the complete backend test suite. Required keys: `test`, `architecture-qc`.

### Frontend checks — `.github/workflows/frontend-checks.yml`
- **Location:** `.github/workflows/frontend-checks.yml:66-80`; scripts in `frontend/package.json:6-13`
- **What:** Node 24 + `npm ci --prefix frontend`, then (cwd `frontend`):
  1. `npm run lint` → `eslint .`
  2. `npx tsc -b --noEmit`
  3. `npm run test` → `vitest run`
  4. `npm run build` → `tsc -b && vite build` (emits `frontend/dist`; the served `nomarr/public_html/` is gitignored and populated only by the Docker build)
- **Why it matters:** Required key `frontend-checks`. `npm run build` was ADDED vs the legacy job to prove the production bundle compiles.

### E2E, docs, codeql — trigger semantics
- **Location:** `.github/workflows/e2e.yml:3-11`, `docs-check.yml:3-14`, `codeql.yml:14-20`
- **What:**
  - E2E is **manual-only** (`workflow_dispatch`, image tag defaults to short-SHA). Local: `cd e2e && npx playwright test` against the Docker stack.
  - `docs-check` is **PR-only**: if changed files match `nomarr/(interfaces|services|workflows|components|persistence|helpers)/*.py` or `build_resources/models/*.json`, then `readme.md` or `API_REFERENCE.md` must also change.
  - CodeQL is **main-target only** (push to main, PR to main, weekly). Check-runs are matrix legs `Analyze (actions)`, `Analyze (go)`, `Analyze (javascript-typescript)`, `Analyze (python)` — validated with `--require analyze`.
- **Why it matters:** These three are NOT required on every commit. `REQUIRED_CHECKS` marks e2e NOT-APPLICABLE on push/pr, docs-check NOT-APPLICABLE on push/manual, analyze main-target only.

### Pytest configuration
- **Location:** `pyproject.toml:83-113`
- **What:** `testpaths = ["tests"]`, `addopts = -v --strict-markers --tb=short`. Markers: `unit`, `integration`, `e2e` (type markers — every test must have one), plus `slow`, `requires_models`, `requires_audio`, `requires_database`, `requires_essentia`, `requires_tensorflow`, `container_only`, `code_smell`, `mocked`, `hnsw_build`, `serial`, `characterization`, `sabotage_check`. `--strict-markers` means an undeclared marker fails collection.
- **Why it matters:** Unknown markers break the whole suite (`--strict-markers`). Tests must be in `tests/` mirroring `nomarr/` structure.

### Ruff/mypy config facts
- **Location:** `pyproject.toml:143-233`
- **What:** ruff `line-length = 120` (NOTE: CONTRIBUTING.md:272 says 100 — the formatter config is authoritative at 120), `output-format = "json"`, `fix = true`, `unsafe-fixes = true`; banned-api rules redirect `time.time`/`datetime.datetime.now`/`builtins.print` to `nomarr.helpers.time_helper`. mypy: `python_version = "3.12"`, `ignore_missing_imports = true`, excludes tests/scripts/artifacts.
- **Why it matters:** `ruff check .` failing on banned `time.time` etc. is a common local friction point — the fix is the helper, not an ignore.

### Local workspace tooling
- **Location:** environment tools `lint_project_backend`, `lint_project_frontend`
- **What:** `lint_project_backend` runs ruff (check+fix+format), mypy, import-linter, and pytest on **git-modified/untracked files** by default (`check_all: true` for everything). `lint_project_frontend` runs ESLint, tsc, and Vitest.
- **Why it matters:** These mirror the CI gates for local verification; `check_all: true` on `lint_project_backend` reproduces the full CI scope when needed.

## Critical Invariants
- NO pre-commit hook — CI is the enforcement point; run gates locally before pushing (CONTRIBUTING.md:187).
- The broad pytest gate excludes `container_only`, `requires_database`, `code_smell` — those tiers must be run explicitly (architecture-qc job, database-tests job) to be "done".
- mypy is scoped to `nomarr/` only.
- Backend requires Python 3.12 venv with `pip install -e ".[dev]"`; frontend requires Node 24 (CI) / Node 18+ (CONTRIBUTING) with `npm ci`.
- Every pytest test needs a type marker; `--strict-markers` fails on undeclared markers.

## Sources
- `.github/workflows/backend-quality.yml`, `backend-tests.yml`, `frontend-checks.yml`, `e2e.yml`, `docs-check.yml`, `codeql.yml`
- `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.mypy]`, `[tool.ruff]`, `[tool.deptry]`, `[tool.importlinter]`)
- `CONTRIBUTING.md` (PR Requirements, Running Tests sections)
- `readme.md:139-142`
- `scripts/validate_commit.py` (`REQUIRED_CHECKS`)
- `.opencode/skills/nomarr-testing/` (test-writing conventions; sibling skill `ci-validate-commit` for the validator)
