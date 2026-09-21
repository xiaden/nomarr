# Nomarr workspace contract

This file is the repository-wide orientation for agents. The source tree, tests, CI, and the linked documents below are authoritative for current implementation details.

## Workspace purpose

Nomarr is an alpha, Docker-oriented music-library analysis and auto-tagging system. It runs ONNX Runtime audio/ML processing, stores library and analysis data in PostgreSQL, and writes portable metadata tags back to audio files. The React web UI and FastAPI/CLI backend are maintained in this repository.

## Repository map

| Area | Purpose |
|---|---|
| `nomarr/` | Python backend: transport interfaces, application services, workflows, domain/ML components, persistence, and helpers. |
| `frontend/` | React + TypeScript/Vite web UI; production output is built into the image, not committed. |
| `tests/` | Backend unit, integration, characterization, sabotage, and architecture-QC tests. |
| `e2e/` | Docker-oriented Playwright browser tests and fixtures; see `e2e/README.md`. |
| `scripts/` | Validation, diagnostics, maintenance, and embedding-research tooling. |
| `alembic/` | PostgreSQL migration environment and revisions under `alembic/versions/`. |
| `docker/`, `dockerfile`, `dockerfile.base` | Local Compose/deployment assets and the application/base image build. |
| `build_resources/` | Models, configuration, scripts, and the patched Essentia build context used by images. |
| `docs/` | User and developer documentation; start at `docs/index.md` and `docs/dev/`. |
| `.github/workflows/` | Independent backend, frontend, database, E2E, Docker publication, documentation, security, and maintenance workflows. |
| `.opencode/skills/` | Active project-specific agent skills; each skill is `.opencode/skills/<name>/SKILL.md`. |
| `artifacts/` | Repository-local engineering artifact categories when present; committed exceptions and ignore rules are defined by `artifacts/.gitignore`. |

## Start here by task

| Task | Start with | Also inspect |
|---|---|---|
| Backend API, CLI, or auth | `nomarr/interfaces/`, `nomarr/interfaces/INTERFACES.md` | The owning service guide and `docs/dev/architecture.md` |
| Application/service behavior | `nomarr/services/`, `nomarr/services/SERVICES.md` | The called workflow/component and `nomarr-layers` skill |
| Use-case orchestration | `nomarr/workflows/`, `nomarr/workflows/WORKFLOWS.md` | The owning components and `nomarr-testing` skill |
| Domain, tagging, library, or ML logic | `nomarr/components/`, `nomarr/components/COMPONENTS.md` | A matching `.opencode/skills/*` skill, especially `nomarr-tags`, `ml-inference-path`, or `nomarr-layers` |
| Database or schema changes | `nomarr/persistence/`, `nomarr/persistence/PERSISTENCE.md` | `docs/dev/architecture.md`, `docs/dev/migrations.md`, `alembic/versions/`, and persistence-specific skills |
| Frontend/API contract | `frontend/src/` | `frontend-api-contract` skill, `frontend/package.json`, and backend interface types |
| Backend tests or architecture boundaries | `tests/` and `tests/test_architecture_qc.py` | `pyproject.toml`, `docs/dev/qc.md`, and the relevant characterization/sabotage tests |
| Browser/E2E behavior | `e2e/` and `e2e/README.md` | `.github/workflows/e2e.yml` and `e2e` skill guidance |
| Docker, image build, or release | `dockerfile`, `dockerfile.base`, `.github/workflows/docker-publish.yml` | `.github/workflows/build-base.yml`, `BASE_VERSION`, `docs/dev/versioning.md`, and Docker skill guidance |
| CI admission or exact-commit validation | `.github/workflows/` and `scripts/validate_commit.py` | `docs/dev/validate-commit.md` and `ci-validate-commit` skill |
| Agent skills or repository guidance | `.opencode/skills/`, `agents.md` | `docs/dev/skills/README.md`, `docs/dev/skills/nomarr-skills.md`, and `scripts/human-scripts/validate_skills.py` |
| Design, requirements, plans, or reviews | `artifacts/` when populated | The applicable artifact convention and skill; do not assume ignored categories contain current artifacts |

## Working rules

- Preserve the dependency direction `interfaces → services → workflows → components → (persistence / helpers)`. Same-layer imports may be valid; upward imports are not. Import-linter and architecture-QC enforce this boundary.
- Keep interfaces transport-only: validate/serialize at the boundary and call services. Keep service code focused on dependency wiring and thin orchestration; put multi-step use cases in workflows and reusable/heavy domain logic in components.
- Use the injected public `Database` intent facades (`db.library`, `db.app`, `db.ml`). Do not import persistence implementation internals from higher layers or rebuild multi-step persistence intents by sequencing thin facade calls.
- Keep helpers generic and upward-independent: code under `nomarr/helpers/` must not import `nomarr.*`.
- ONNX Runtime is the ML backend. `essentia` imports are isolated to `nomarr/components/ml/audio/ml_audio_comp.py` and `nomarr/components/ml/audio/ml_preprocess_comp.py`.
- Use `uv` as the Python environment/dependency manager and keep the lockfile authoritative: `uv sync --locked`. Do not use the unsupported `pip install .`, `uv pip install .`, or `uv pip install -r pyproject.toml` routes.
- Treat Alembic as the schema authority. Put revisions in `alembic/versions/` and read `docs/dev/migrations.md` before changing schema or migration policy; do not reintroduce a parallel migration system.
- Do not commit generated frontend output (`frontend/dist/` or `nomarr/public_html/`); Docker builds the production bundle.
- Nomarr is alpha software with forward-only migration expectations and permitted breaking changes before 1.0. Update callers, tests, and migration documentation together when a contract changes; do not preserve obsolete parallel paths merely for compatibility.

## Architecture boundaries

- `nomarr/interfaces/` may call services only; it must not orchestrate workflows/components or access persistence directly.
- `nomarr/services/` owns long-lived resource wiring and stable application-facing contracts. It may make a thin single-intent call through the public `Database` facade, but business rules and persistence choreography belong below it.
- `nomarr/workflows/` owns ordered use-case control flow and may call components/other workflows, not services or interfaces.
- `nomarr/components/` owns reusable domain logic and is the primary home for complex persistence-backed operations; it may call helpers and public intent facades, not higher layers.
- `nomarr/persistence/` owns PostgreSQL access, repository implementation, row mapping, and facade wiring. Higher layers use `Database` and its intent namespaces; `database/`, `sql/`, `models/`, and mapper internals remain persistence-owned.
- `nomarr/helpers/` owns reusable DTOs, exceptions, and pure utilities and must remain independent of the application package.
- The image build owns production packaging: `dockerfile` builds the frontend, while `dockerfile.base` derives the GPU dependency set from `pyproject.toml` and `uv.lock` and builds the required Essentia runtime.

## Tooling and exploration

Use this file to narrow the likely area, then verify behavior in source and tests. Prefer indexed, symbol-aware exploration (`aft_search`, `aft_outline`, `aft_zoom`, and `aft_callgraph`) over broad scans. Search results, generated context, prior artifacts, and skill summaries are pointers—not proof; read the referenced source and tests before relying on them. Load the matching project skill from `.opencode/skills/` for subsystem procedures. The active skill inventory and reference validation are maintained by `scripts/human-scripts/validate_skills.py`; `agents.md` is only a convenience catalog.

## Validation and tests

Run the checks that match the changed surface. The exact CI definitions live in `.github/workflows/` and contributor-facing commands are maintained in `CONTRIBUTING.md`.

After `uv sync --locked`, the normal backend quality gate is:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy nomarr/ --config-file pyproject.toml
.venv/bin/lint-imports
.venv/bin/deptry . --known-first-party nomarr
```

The normal backend test gate and explicit architecture gate are:

```bash
.venv/bin/pytest tests/ -v -m "not container_only and not requires_database and not code_smell"
.venv/bin/pytest tests/test_architecture_qc.py -v
```

PostgreSQL/pgvector characterization, integration, and sabotage coverage requires Docker/testcontainers:

```bash
.venv/bin/pytest tests/characterization/ tests/characterization/test_mood_owner_pg.py tests/integration/test_library_uuid_locator_identity_pg.py tests/integration/test_song_upsert_state_boundary_pg.py tests/sabotage/test_no_facades_begin_transactions.py -v -m requires_database
```

For frontend changes, from the repository root use the CI-equivalent checks:

```bash
npm ci --prefix frontend
npm run lint --prefix frontend
(cd frontend && npx tsc -b --noEmit)
npm run test --prefix frontend
npm run build --prefix frontend
```

For browser-visible changes, use the Docker-backed prerequisites and Playwright commands in `e2e/README.md`; CI is defined by `.github/workflows/e2e.yml`. Before treating a commit as CI-complete, use the read-only exact-SHA validator documented in `docs/dev/validate-commit.md` and implemented by `scripts/validate_commit.py`:

```bash
.venv/bin/python scripts/validate_commit.py "$(git rev-parse HEAD)"
```

A documentation-only or tooling-only change still requires scope-appropriate checks; do not claim CI or unavailable Docker/browser evidence from local results. Review the final diff and report unavailable or deferred checks explicitly.

## Build, release, and CI

- Independent quality/test workflows are authoritative for backend lint, typing, imports, dependencies, tests, architecture-QC, and database tests: `.github/workflows/backend-quality.yml` and `.github/workflows/backend-tests.yml`.
- `.github/workflows/frontend-checks.yml` owns frontend lint, TypeScript, Vitest, and production-build gates.
- `.github/workflows/docker-publish.yml` owns application image publication and channel promotion. Release tag policy and required-check semantics are implemented there and in `scripts/validate_commit.py`; read both before changing release admission.
- `.github/workflows/build-base.yml`, `dockerfile.base`, and `BASE_VERSION` own the reusable GPU base-image build. Changes to the base build context trigger `.github/workflows/base-version-bump.yml`.
- `.github/workflows/docs-check.yml` defines the PR documentation-consistency gate; `.github/workflows/codeql.yml` defines the CodeQL security gate. `.github/workflows/e2e.yml` defines the Docker/Playwright workflow.
- Branching and PR conventions are documented in `CONTRIBUTING.md`; versioning and alpha release policy are in `docs/dev/versioning.md`.

## Artifacts, design, and planning

When these repository-local artifacts are present, use their category locations under `artifacts/`: `requests/` for captured request context, `requirements/` for architectural requirements, `decisions/` for ADRs, `designs/` for design documents, `plans/` for implementation plans, `reviews/` for reviews, and `logs/` for durable work logs. The artifact ignore policy is in `artifacts/.gitignore`; stable committed categories include ADRs, ASRs, completed design docs, plan examples, and archived skills. Do not treat an ignored or absent artifact as current authority. For active agent guidance, `.opencode/skills/` is authoritative, with conventions documented in `docs/dev/skills/README.md` and the generated inventory in `docs/dev/skills/nomarr-skills.md`.

## Security and safety boundaries

Nomarr is alpha software and must not be exposed directly to the public internet; use a trusted network and a reverse proxy for HTTPS, rate limiting, and access control as described in `SECURITY.md`. Do not commit environment credentials or generated secrets; environment files are ignored and first-run credentials are emitted by the deployment path. Treat the music library as user data: deployment guidance recommends read-only media access and regular database backups. Preserve API-key/session authentication and do not bypass the interface/service authorization path.

## Deeper guidance

- Start with `CONTRIBUTING.md`, `docs/dev/architecture.md`, `docs/dev/qc.md`, `docs/dev/migrations.md`, and `docs/dev/validate-commit.md` for repository-wide contributor and architecture details.
- Read the local layer guides: `nomarr/interfaces/INTERFACES.md`, `nomarr/services/SERVICES.md`, `nomarr/workflows/WORKFLOWS.md`, `nomarr/components/COMPONENTS.md`, `nomarr/persistence/PERSISTENCE.md`, and `nomarr/helpers/HELPERS.md`.
- Load task-specific skills from `.opencode/skills/`, especially `nomarr-layers`, `nomarr-testing`, `ci-lint-test-gates`, `persistence-domain-model`, `nomarr-tags`, `docker`, `playwright-cli`, and `uv-package-management-state` when their triggers match.
- No subordinate `AGENTS.md` files currently exist. The layer guides and skills above provide the deeper local guidance; add subordinate agent contracts only if a subsystem develops durable rules that cannot be represented by those authoritative documents.
