# Contributing to Nomarr

Thank you for your interest in contributing to Nomarr! This document provides guidelines for contributing to this alpha project.

## ⚠️ Project Status

**Nomarr is alpha software** and changes frequently. The architecture is actively being refined, and breaking changes are expected before 1.0. We welcome contributions but ask for patience as the codebase stabilizes.

## 🤝 How to Contribute

### Reporting Bugs

1. Check [existing issues](https://github.com/xiaden/nomarr/issues) to avoid duplicates
2. Use the bug report template when creating a new issue
3. Include:
   - Nomarr version (check container logs or `config/nomarr.yaml`)
   - Docker/system environment details
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant logs (from `docker compose logs nomarr`)

### Suggesting Features

1. Check [existing discussions](https://github.com/xiaden/nomarr/discussions) and issues
2. Use the feature request template
3. Describe the use case and why it fits Nomarr's goals (music library auto-tagging for self-hosted systems)

### Submitting Pull Requests

> **Nomarr uses a three-tier GitFlow-lite branching strategy** (see [ADR-029](artifacts/decisions/ADR-029-adopt-gitflow-lite-branching-strategy.md)):
>
> - **`feat/*`, `fix/*`, `chore/*`** — short-lived work branches. Squash-merged into `develop` via PR.
> - **`develop`** — integration branch. Working at every commit. PR-only, no direct push. Merged into `main` via PR.
> - **`main`** — stable releases only. PR-only, no direct push.
>
> **Your PR targets `develop`.** Open your branch from `develop`, do your work, then open a PR back to `develop`.

**Before starting work on a PR:**

1. **Discuss first** - For anything beyond trivial fixes, open an issue or discussion first
2. **Understand the architecture** - Read [docs/dev/architecture.md](docs/dev/architecture.md) and [.github/copilot-instructions.md](.github/copilot-instructions.md)
3. **Check the layer structure** - Nomarr uses clean architecture with strict layer boundaries

**PR Requirements:**

- Code follows the existing architecture patterns (see below)
- Pull requests target `develop` (hotfixes targeting `main` require explicit coordination)
- CI must pass before merge on `develop` or `main`. Checks run in **independent workflows** that each report their own result (no monolithic chain):
  - **Backend quality** (`.github/workflows/backend-quality.yml`): `ruff check .`, `ruff format --check .`, `mypy nomarr/ --config-file pyproject.toml`, `lint-imports`, `deptry . --known-first-party nomarr`
  - **Backend tests** (`.github/workflows/backend-tests.yml`): `pytest tests/ -v -m "not container_only and not requires_database and not code_smell"` plus the ADR-042 architecture-QC suite run explicitly (`pytest tests/test_architecture_qc.py -v`)
  - **Frontend checks** (`.github/workflows/frontend-checks.yml`): `npm ci`, `npm run lint`, `npx tsc -b --noEmit`, `npm run test`, and `npm run build`
  - **Docker publish** (`.github/workflows/docker-publish.yml`): builds and publishes the image on push / `workflow_dispatch` only
  - **CodeQL** (`.github/workflows/codeql.yml`) on push to `main`, pull requests to `main`, and on a weekly schedule
- Python code passes `ruff` linting and `mypy` type checking (zero errors)
- Frontend code passes ESLint
- **There is no `pre-commit` hook.** Enforcement is CI-owned; run the gates locally before pushing (see [Running Tests](#running-tests)).
- **The frontend production bundle is built by CI/Docker, not committed.** The generated tree under `nomarr/public_html/` is gitignored and produced inside the Docker image by the `dockerfile`'s Node builder stage. Do not commit frontend build output.
- All relevant tests pass locally before you open or update the PR
- Commit messages are descriptive
- PR description explains what changed and why

**Branch Naming:**

- `feat/<name>` for new features, for example `feat/library-health-panel`
- `fix/<name>` for bug fixes, for example `fix/calibration-status-count`
- `chore/<name>` for maintenance work, for example `chore/update-ci-docs`
- `refactor/<name>` for internal code restructuring, for example `refactor/tagging-workflow-split`
- `docs/<name>` for documentation-only changes, for example `docs/update-branching-guide`

Keep names short, lowercase, and descriptive.

**For ML model contributions:**

⚠️ **Consult with Music Technology Group, Universitat Pompeu Fabra** before submitting PRs that:

- Modify model processing logic
- Create derivative works of Essentia models
- Change how model outputs are interpreted or normalized

Essentia models are licensed under CC BY-NC-SA 4.0 with ShareAlike requirements.

## 🏗️ Architecture Guidelines

Nomarr uses a **layered clean architecture** with strict dependency rules:

```
interfaces → services → workflows → components → (persistence / helpers)
```

**Key Rules:**

1. **Layer boundaries are enforced** by `import-linter` - violations will fail CI
2. **Dependency injection** is used for major resources (database, config, ML backends)
3. **No global state** - config is loaded once and passed via parameters
4. **Type annotations are mandatory** - all Python code must be fully typed
5. **Essentia is isolated** — only `components/ml/audio/ml_audio_comp.py` (audio loading) and `components/ml/audio/ml_preprocess_comp.py` (mel spectrogram) import essentia. Essentia is not the ML backend — ONNX Runtime is.
6. **Persistence is components-only** — only the components layer may call persistence. Services, workflows, and interfaces must never access the database directly.
7. **Discovery-based workers** — a single worker type claims files from the `songs` collection. There is no queue-based processing.

**Layer-specific instructions:**

- `nomarr/interfaces/` - FastAPI routes, request/response models, DI wiring
- `nomarr/services/` - Service layer, orchestrates workflows and components
- `nomarr/workflows/` - Multi-step business logic, calls components
- `nomarr/components/` - Reusable domain logic, calls persistence/helpers
- `nomarr/persistence/` - Database access, SQL queries
- `nomarr/helpers/` - Pure utility functions, no nomarr imports

See [.github/instructions/](.github/instructions/) for detailed layer conventions.

## 🔧 Development Setup

All development targets the `develop` branch. Clone the repository and switch to `develop` before making changes.

### Prerequisites

- Python 3.12+
- Node.js 18+ (for frontend)
- Docker + Docker Compose
- NVIDIA GPU with CUDA support (for ML inference)

### Local Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/xiaden/nomarr.git
   cd nomarr
   git checkout develop
   ```

2. **Backend setup:**

   ```bash
   # Create and activate virtual environment
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate

   # Install dependencies
   pip install -e ".[dev]"
   ```

3. **Frontend setup:**

   ```bash
   cd frontend
   npm install
   ```

4. **Start development environment:**

   ```bash
   # From repo root
   docker compose -f docker/compose.yaml up -d nomarr-postgres  # Start database only

   # In one terminal - backend
   source .venv/bin/activate
   uvicorn nomarr.interfaces.api.api_app:api_app --reload --port 8356

   # In another terminal - frontend
   cd frontend
   npm run dev
   ```

   **Source-mode frontend behavior:** when running the backend from the checkout
   (source mode), it serves the SPA from `nomarr/public_html/` only. That tree is
   gitignored and absent from a fresh checkout, so the backend returns a JSON
   `` "Web UI not found" `` 404 for `/` unless it has been populated. **The
   backend does NOT serve `frontend/dist`** — running `npm run build` is not
   enough to make the UI show up through the backend. Two supported ways to view
   the UI while developing:

   - **Vite dev server (recommended):** `cd frontend && npm run dev`, then open
     the URL Vite prints (default `http://localhost:5173`). Vite hot-reloads and
     proxies API calls to the backend. This is the intended source-mode workflow.
   - **Mirror what Docker does:** `cd frontend && npm run build` and copy the
     result into the package path the backend serves:
     `rm -rf nomarr/public_html && cp -r frontend/dist nomarr/public_html`
     (remember `nomarr/public_html/` is gitignored — do not commit it).

   Production always ships via Docker, which builds the frontend in a Node stage
   and copies `frontend/dist` into the image at `/app/nomarr/public_html/` — see
   the `dockerfile`.

### Running Tests

These commands mirror the independent CI gates. Run them locally before pushing — CI enforces the same commands, but does not run on your machine, and there is no pre-commit hook to do it for you.

```bash
# Backend quality (matches backend-quality.yml)
ruff check .
ruff format --check .
mypy nomarr/ --config-file pyproject.toml
lint-imports  # Check layer boundaries
deptry . --known-first-party nomarr  # dependency audit

# Backend tests (matches backend-tests.yml)
pytest tests/ -v -m "not container_only and not requires_database and not code_smell"
# ADR-042 architecture/quality enforcement is excluded by the `not code_smell`
# expression above, so run it explicitly as CI does:
pytest tests/test_architecture_qc.py -v

# Frontend checks (matches frontend-checks.yml; run from frontend/)
cd frontend
npm ci
npm run lint          # ESLint
npx tsc -b --noEmit   # TypeScript
npm run test          # Vitest
npm run build         # production build -> frontend/dist
cd ..

# End-to-end tests (requires Docker environment; run from e2e/)
cd e2e && npx playwright test
```

**E2E, docs, and security are independent workflows.** E2E (`.github/workflows/e2e.yml`) is manual-only (`workflow_dispatch`) and by default runs against the image tagged with the short SHA of the commit under test. Docs consistency (`.github/workflows/docs-check.yml`) runs on pull requests. CodeQL (`.github/workflows/codeql.yml`) is the security gate, scheduled weekly and on PRs to `main`.

### Validating CI Completion for an Exact Commit

Before pushing a branch, verify that every required CI gate completed **and**
passed for the **exact** commit you are about to push, using the local validator:

```bash
python scripts/validate_commit.py "$(git rev-parse HEAD)"
```

This is a **read-only, local** check against the GitHub API. It **never re-runs,
repairs, merges, or pushes** anything, and it never alters GitHub state — it only
tells you whether the required checks for that exact SHA are done. Pass a full
40-character SHA or a sufficiently-unique short SHA; a short SHA is resolved to
its canonical full SHA via a read-only `gh api` commit lookup before validation.

**Prerequisites:** the [GitHub CLI](https://cli.github.com) (`gh`) installed and
authenticated (`gh auth status` must report a logged-in account with `repo`
scope). The validator only issues read-only `gh api` GET calls.

**Required-check semantics:** the contract is defined in `REQUIRED_CHECKS`
inside `scripts/validate_commit.py` (see [docs/dev/validate-commit.md](docs/dev/validate-commit.md)).
Checks are keyed on the GitHub check-run *job* names: `lint`, `deptry`, `test`,
`architecture-qc` (ADR-042), `frontend-checks`, `build-and-push`, `promote`,
`e2e`, `docs-check`, and `analyze` (CodeQL). Which checks are required depends on
the trigger context (`--trigger push|pr|manual`, default `push`); checks that are
documented as not applicable to the context are reported as `NOT-APPLICABLE`,
never silently treated as success. `docs-check` is PR-only (`docs-check.yml` has
no `workflow_dispatch` trigger), so a `--trigger manual` run does not falsely
require it. CodeQL is main-target only, so a main-target commit must be validated
with `--require analyze`. `analyze` is the one exception to the exact job-name
rule: the `codeql.yml` job is a matrix (`name: Analyze (${{ matrix.language }})`),
so the real check runs are `Analyze (actions)`, `Analyze (go)`, and so on. The
validator uses a prefix-aware matcher that consumes and requires every leg whose
name starts with `Analyze (` — see
[docs/dev/validate-commit.md](docs/dev/validate-commit.md).

**Exit codes:** `0` = every required check present, completed, and successful.
`1` = a required check is missing, pending, or unsuccessful (failure/skipped/
cancelled/neutral/etc.), or the API returned runs for a different `head_sha`
(exact-commit violation). `2` = could not validate (`gh` missing/unauth'd,
network/auth error, malformed response, or bad arguments). Diagnostics name
exactly which checks failed and why.

**Scope limits:** validation only. There is no self-hosted runner automation and
no automatic repair or rerun of failed checks — a non-zero exit means "do not
consider this commit done", not "go fix it for me".

## 📝 Code Style

### Python

- **Formatter:** `ruff format` (automatically applied)
- **Linter:** `ruff check` (must pass with zero errors)
- **Type checker:** `mypy` (must pass with zero errors, config in `pyproject.toml`)
- **Line length:** 100 characters
- **Imports:** Sorted with `ruff` (groups: stdlib, third-party, local)

### TypeScript/React

- **Linter:** ESLint with React plugin
- **Style:** Functional components with hooks
- **Naming:** PascalCase for components, camelCase for functions/variables

### Commit Messages

- Use present tense ("Add feature" not "Added feature")
- Be descriptive but concise
- Reference issues when applicable (`Fixes #123`)

Examples:

```
Fix calibration calculation for edge case with zero variance
Add file watcher polling mode for network mounts
Refactor service layer to use workflow orchestration
```

## 🚫 What We're Not Accepting (Yet)

- Forward-only database migrations (migrations exist but no rollback support)
- Alternative ML backends without discussion first
- UI framework changes
- Major architectural changes without RFC

## 📚 Resources

- [Architecture Documentation](docs/dev/architecture.md)
- [Copilot Instructions](.github/copilot-instructions.md) (developer context)
- [Layer-Specific Instructions](.github/instructions/)

## 📄 License

By contributing, you agree that your contributions will be licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) (same as the project).

## 💬 Questions?

- Open a [Discussion](https://github.com/xiaden/nomarr/discussions)
- Ask in an existing issue thread
- Check the [documentation](docs/)

---

**Thank you for helping make Nomarr better! 🎵**
