# Redesign Playwright E2E for deterministic GitHub validation — Design Document

**Status:** Draft  
**Author:** GitHub Copilot  
**Created:** 2026-04-23  
**Revised:** 2026-04-23  

---

## Scope

Replace the current broad, environment-sensitive Playwright suite with a deterministic Docker-first E2E architecture that is reliable on GitHub Actions, covers CPU/no-GPU graceful fallback explicitly, and draws a clear boundary around what should and should not live in browser automation.

---

## Problem Statement

The current Playwright E2E suite is documented as having ~9 spec files but only 3 exist. Those 3 specs mix fundamentally different concerns — smoke navigation, destructive library workflows with hardcoded host paths, Docker log scraping as a backend oracle, and an ML tagging spec that is effectively a no-op. This is not an incidental bug collection: it is a mismatch between what the suite was imagined to cover and how the execution environment actually works.

Specific known failures:
- `e2e/library-integration.spec.ts` resolves library fixture paths on the Playwright **host** machine. When Nomarr runs in Docker (the only CI configuration) the container cannot see these paths, causing scan operations to fail silently or error.
- `e2e/ml-tagging.spec.ts` contains no meaningful assertions and should not be treated as ML coverage evidence. It gives false confidence.
- `e2e/smoke.spec.ts` uses Docker container log scraping as a backend oracle for startup success, which is fragile and introduces a hard dependency on Docker socket access from the test runner.
- `playwright.config.ts` declares Firefox and WebKit projects, but `.github/workflows/e2e.yml` runs `--project=chromium` only. The multi-browser config is misleading dead weight in CI.
- `fullyParallel: true` is set globally, but the library and scan workflows share mutable Docker volume state. Parallel execution against shared state is a race condition source.
- The workflow does not inject `E2E_WEB_PASSWORD` env var; any test that needs to authenticate has no contract-defined credential source.
- The fixture model in `beforeAll` has already caused Playwright failures due to incorrect page fixture lifecycle assumptions.

The architecture problem is that the suite has no disciplined contract for what E2E means. User-visible workflows that should block PR are mixed with non-E2E concerns such as ML correctness theater, log scraping, and environment guessing. The fix is not to create a soft non-blocking E2E tier; it is to make browser E2E mean one thing only: **every meaningful user action in the UI must work in GitHub CI, and those tests must block PRs**. GPU correctness, embedding quality, and performance remain outside E2E entirely.

---

## Architecture

### Is a Full Redesign Warranted?

Yes — but not a wholesale rewrite of every file. The redesign targets:
1. The **architecture** of the suite (tiering, fixture discipline, assertion strategy).
2. The **three existing specs** (repair `smoke.spec.ts`, rewrite `library-integration.spec.ts`, retire or stub `ml-tagging.spec.ts`).
3. The **GitHub Actions workflow** (fixture mount, password env, health check oracle).
4. The **`playwright.config.ts`** (Chromium-only CI project, no `fullyParallel` global).

Supporting infrastructure (Docker compose files, image build, ArangoDB config) does not need to change for this redesign.

---

### Blocking PR E2E Architecture

There is one browser E2E tier only:

| Scope | Runs Where | Blocking? | What It Covers |
|------|-----------|-----------|----------------|
| **Browser E2E** | GitHub Actions, Docker-first, Chromium only | **Yes — blocks PR and merge** | App boot, login, navigation, library creation using checked-in fixtures, scan initiation and completion, event-based file watching, polling mode, user-visible metadata/library flows, and graceful no-GPU fallback behavior |

Anything that a real user can do from the UI and that should not regress before shipping belongs here, even if it is slower or heavier. These are intentionally the expensive tests.

The separate boundary is not "Tier 2 E2E" — it is **non-E2E testing**:

| Concern | Correct home |
|--------|--------------|
| GPU availability/performance comparison | Backend/container-only tests |
| ML correctness / embedding quality | Backend integration tests |
| Performance benchmarks | Dedicated perf tests |

This keeps E2E honest: UI behavior blocks PR; ML science and performance testing do not masquerade as browser coverage.

---

### Blocking E2E Spec Contracts

Each blocking E2E spec must satisfy all of the following:
- Uses only container-visible paths for fixtures (no host path resolution).
- Uses stable API endpoints as backend oracles, not Docker log scraping.
- Runs sequentially (no `fullyParallel` within a spec that shares library state).
- Has a defined credential source via `E2E_WEB_PASSWORD` env var (falls back to `NOMARR_WEB_PASSWORD`; CI must not rely on log discovery).
- Times out predictably: each API polling loop uses bounded retries with a fixed interval driven by explicit E2E env/config knobs.
- Uses a CI-specific fast watch/poll configuration so file-watching scenarios complete in PR-friendly time.

**Proposed blocking spec files:**

| File | Status | Action |
|------|--------|--------|
| `e2e/smoke.spec.ts` | Repair | Replace Docker log scraping with `GET /api/v1/info` and `GET /api/web/health/gpu` assertions; keep navigation smoke |
| `e2e/library-integration.spec.ts` | Rewrite | Use a single container-visible packaged fixture path; cover create library, scan completion, event-based change detection, polling-mode change detection, and other user-visible library actions |
| `e2e/no-gpu-fallback.spec.ts` | New or merged into smoke | Assert graceful CPU/degraded-mode startup: `GET /api/web/health/gpu` returns a non-error body; no hard crash |
| `e2e/ml-tagging.spec.ts` | Delete or repurpose | Do not keep a fake ML-coverage spec. If retained, it must assert real UI-visible behavior only; otherwise remove it. |

---

### Affected Implementation Touchpoints

This redesign requires changes across the following implementation files and locations. These are the concrete surfaces where the E2E contract materializes:

| File/Location | Role | Responsibility |
|--|--|--|
| `nomarr/app.py` | App wiring | Consume `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS` at startup, inject into `FileWatcherService` constructor |
| `nomarr/services/infrastructure/file_watcher_svc.py` | Backend watcher | Accept `polling_interval_seconds` from app wiring; emit polling behavior observable to API |
| `frontend/src/shared/api/processing.ts` | API client centralization | **Single source of truth** for `/api/web/machine-learning/work-status` endpoint path; exported for use by LibraryManagement and Dashboard |
| `e2e/fixtures/api-helpers.ts` | E2E API polling helpers | Implement bounded retry loops using `E2E_WORK_STATUS_POLL_MS`, `E2E_WORK_STATUS_TIMEOUT_MS` for work-status polling; used by multiple specs |
| `e2e/fixtures/` (shared container mutation) | E2E container control | Add helper(s) for bounded waits on container file mutations and work-status endpoint transitions (may be in `api-helpers.ts` or new `container-helpers.ts`) |

Each of these files must be updated as part of the implementation plan derived from this design.

---

### Affected Fixture Infrastructure

The following fixture files are in scope for this redesign. They are not spec files but directly determine whether tests pass or fail in CI.

| File | Current Behavior | Required Change |
|------|------------------|-----------------|
| `e2e/fixtures/auth.ts` | 3-tier resolution: `E2E_WEB_PASSWORD` → `NOMARR_WEB_PASSWORD` → Docker log scraping → default `'nomarr'`. Log scraping shells out to `docker ps` and `docker logs`, requiring Docker socket access from the test runner. | Deterministic credential sourcing only: `E2E_WEB_PASSWORD` env var must be set in CI (see GitHub Actions changes). The Docker log scraping fallback (`discoverFirstRunPasswordFromDockerLogs`) must not be relied upon in CI — its presence is acceptable for local dev but the CI job must never reach that branch. |
| `e2e/fixtures/test-library.ts` | Guesses across 6 candidates: `E2E_TEST_LIBRARY_PATH`, host-relative `tests/fixtures/library/good`, `/app/tests/fixtures/library/good`, `/app/tests/fixtures/good`, `/media`, `/music`. Silently picks the first that exists or returns a non-existent path. | Single canonical container-visible path. Keep the packaged fixture path contract (`/app/tests/fixtures/library/good`) and inject it via `E2E_TEST_LIBRARY_PATH` in CI/local E2E. Remove path roulette from runtime resolution logic. |
| `e2e/fixtures/docker-logs.ts` | Exports a `dockerLogs` fixture that spawns a `docker logs -f` background process, scraping for `ERROR`/`CRITICAL`/`Exception` patterns. Requires Docker socket access; silently degrades in CI when container is not found. | **Remove or retire this fixture.** It is a symptom of using Docker log inspection as an oracle — the same anti-pattern this redesign eliminates. Backend error surface must be asserted via API responses, not log tailing. Any spec currently importing this fixture must be updated or dropped. |

---

### Docker-First Fixture Strategy

The preferred contract is **packaged, checked-in fixtures with one canonical in-container path**, not a bind mount.

Rationale:

- Nomarr already packages the repository `tests/` tree into the runtime image under `/app/tests`.
- Using that packaged path keeps CI and local Docker runs aligned.
- It avoids introducing special-case container mounts that none of the other test layers need.
- It keeps local execution simple: run the same Docker-backed E2E flow and use the same library path the app already sees.

The canonical E2E library fixture path should therefore be:

- `/app/tests/fixtures/library/good`

The key constraint is still the same: **Playwright test code must submit a container-visible path, never a host filesystem path.**

In `library-integration.spec.ts`, the library path passed to the "add library" UI form must be the canonical in-container fixture path — not `process.cwd()` or `__dirname` on the test runner.

For clarity and determinism, the workflow may still export:

- `E2E_TEST_LIBRARY_PATH=/app/tests/fixtures/library/good`

but it should not be required to create an alternate bind-mounted copy of the fixtures.

### Real Integration vs Mocking Boundary (Required)

This redesign uses **real integration behavior plus config injection**, not backend/API mocking.

- **Real integration (must remain real):**
   - Real Nomarr API + real ArangoDB in Docker.
   - Real library creation, scan triggers, and watcher mode changes through the UI/API.
   - Real backend async status from `/api/web/machine-learning/work-status`.
   - Real GPU-health response from `/api/web/health/gpu` in no-GPU CI.
- **Mocking/stubbing policy:**
   - No network-route mocking of Nomarr endpoints in blocking E2E.
   - No backend state fabrication in Playwright.
   - Test doubles are allowed only for pure test utilities (for example, helper wrappers around container file mutation commands), not for product behavior.
- **Configuration injection (required):**
   - Timing is controlled via explicit test-only env/config overrides in CI/local E2E runs.
   - Fixture root is injected via `E2E_TEST_LIBRARY_PATH=/app/tests/fixtures/library/good`.

### Fixture Mutation in Docker-Backed E2E (Packaged Strategy)

Current tests mutate host files (`fs.renameSync` on Playwright host paths), which does not reliably exercise the running container library when the authoritative fixture root is container-local.

Required mutation approach for event and poll watch tests:

1. Keep library root as the packaged in-image fixture path: `/app/tests/fixtures/library/good`.
2. Perform test mutations **inside the running Nomarr container** (for example via a small helper that executes `docker exec nomarr` file operations against the packaged fixture tree).
3. Use reversible mutations (rename/copy/delete) and always restore fixture state in teardown.
4. Verify change detection only through stable product surfaces (UI state + `/api/web/machine-learning/work-status`), not container logs.

This preserves the packaged-fixture preference and avoids bind-mount coupling.

---

### Stable Assertion Strategy

Replace fragile oracles with the following stable API surfaces:

| Assertion Goal | Recommended Surface | Why |
|----------------|---------------------|-----|
| App is up and responding | `GET /api/v1/info` → `200` with `PublicInfoResponse` shape: top-level fields `config`, `models`, `queue`, `worker` | Public, no auth, stable contract — `version` is not a top-level field |
| Async scan/processing complete | `GET /api/web/machine-learning/work-status` → poll until `is_busy === false` (equivalently, both `is_scanning === false` and `is_processing === false`) | Aligned with ADR-023 HTTP polling approach; fields match `WorkStatusResponse` contract: `is_scanning`, `is_processing`, `is_busy`, `pending_files`, `processed_files`, `total_files` — not `active` or `queue_length` |
| No-GPU / CPU fallback | `GET /api/web/health/gpu` → non-error body indicating degraded or CPU mode | Designed for this purpose; `GET /api/web/health` alone is too weak |
| User-visible library state | UI assertions via Playwright selectors on the library list page | User-facing contract |

**Do not use:**
- Docker container log scraping as a primary oracle.
- `GET /api/web/health` alone as a deep startup oracle (it is too shallow).
- Any endpoint that requires parsing unstructured text or log lines.

---

### No-GPU Graceful Fallback Validation in GitHub Actions

GitHub-hosted runners provide no GPU. This is the natural test environment for fallback behavior.

**Design:**
1. The standard GHCR image runs on the runner without `--gpus` or any CUDA device mapping (already true in the current compose override — `deploy: {}` removes GPU requirements).
2. After container health check passes, `e2e/no-gpu-fallback.spec.ts` makes a direct API call:
   ```ts
   const res = await request.get('/api/web/health/gpu');
   expect(res.status()).toBe(200);
   const body = await res.json();
   // GPUHealthResponse contract: { available: bool, error_summary: string|null, monitor_healthy: bool }
   // On GitHub-hosted runners, available === false is expected (no GPU hardware).
   // The test asserts the app is alive and returns a well-formed response — not that GPU is present.
   expect(typeof body.available).toBe('boolean');
   // available === false in CI is the correct degraded-but-running state.
   ```
3. The test asserts that the app is **usable in CPU mode**, not that GPU is available.

This approach satisfies **ASR-0003** (degrade rather than crash under constrained ML resources) and **ASR-0010** (ML quality/performance belongs outside browser E2E).

---

### File Watching and Polling in Blocking CI

File watching and polling are part of user-visible behavior and therefore belong in blocking E2E.

#### Verified Current Defaults and Origins

| Surface | Current value | Origin |
|---|---:|---|
| Backend watcher poll interval (effective default) | **300s** | `nomarr/services/infrastructure/file_watcher_svc.py` (`polling_interval_seconds: float = 300.0`, constructor default) and `nomarr/app.py` (service constructed without poll override) |
| Backend watcher docstring text (stale/inconsistent) | 60s | `nomarr/services/infrastructure/file_watcher_svc.py` module docstring says "Conservative default: 60 seconds" |
| User docs polling description (range, not code default) | 30–120s | `docs/user/getting_started.md` file-watching section |
| Event debounce before triggering scan | 2.0s | `FileWatcherService(... debounce_seconds=2.0)` in `nomarr/app.py` |
| Library page polling | 5s status check + 500ms refresh when busy | `frontend/src/features/library/components/LibraryManagement.tsx` (`setInterval(checkAndPoll, 5000)` and inner `setInterval(..., 500)`) |
| Dashboard polling | 1s busy / 30s idle | `frontend/src/features/dashboard/DashboardPage.tsx` (`pollInterval = isBusy ? 1000 : 30000`) |
| Current E2E scan wait loop | 2-minute max, 2s loop step | `e2e/library-integration.spec.ts` (`maxWaitTime = 120000`, `waitForTimeout(2000)`) |

Resolution of ambiguity: the **actual backend poll-mode default in running code is 300s**, not 60s and not 120s.

#### CI/Local Timing Control Contract (Actionable)

To make watch tests deterministic and PR-gate viable, adopt config injection with explicit knobs:

1. Add a backend test-only override for watcher poll interval (recommended env):
   - `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS`
   - **Startup-only override:** consumed in `nomarr/app.py` at wiring time, injected into `FileWatcherService` constructor
   - Used only in E2E workflow/local E2E scripts.
   - Not a regular runtime config UI setting; baked into the service instance on app startup.
2. Add Playwright-side poll controls for async waits (recommended env):
   - `E2E_WORK_STATUS_POLL_MS` (default for E2E helper loops)
   - `E2E_WORK_STATUS_TIMEOUT_MS` (max wait bound)
3. In CI, set fast values (for example `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS=5`, `E2E_WORK_STATUS_POLL_MS=1000`, `E2E_WORK_STATUS_TIMEOUT_MS=45000`) so poll-mode tests complete quickly.
4. In local runs, keep defaults safe but overridable from shell env.

This keeps production defaults unchanged while giving deterministic E2E behavior.

---

### Backend API Endpoints as Test Oracles

Three tiers of endpoints service different validation needs:

| Endpoint | Layer | Use Case | Auth | Responsibility |
|--|--|--|--|--|
| `GET /info` (root, no version) | Root / compose health check | Compose/container health probe (e.g., Healthcheck in docker-compose.yaml) | None | Return HTTP 200 when container is booted (minimal—no AI subsystem check) |
| `GET /api/v1/info` | API v1 structural / startup | Startup assertions: app boot complete, configuration loaded, schema version match | None | Return structured startup metadata (AI backend availability, version, schema version) |
| `GET /api/web/health/gpu` | Authenticated user-facing | GPU availability check with degraded-mode graceful fallback | Required (user logged in) | Return {status, available, message} for GPU health; never hard-crash |
| `GET /api/web/machine-learning/work-status` | Authenticated work queue | Poll file-watching and scan progress (library scans, tagging status, etc.) | Required (user logged in) | Return {inProgress, queued_items, current_task} for LibraryManagement and Dashboard polling |

**Endpoint Ownership Note:** The `/api/web/machine-learning/work-status` endpoint path is centralized in `frontend/src/shared/api/processing.ts` and is consumed by both `LibraryManagement` and `Dashboard` components. This single source of truth ensures consistency across polling consumers and simplifies E2E test helper updates.

---

### GitHub Actions Workflow Changes

The current `e2e.yml` needs the following targeted changes:

#### Credential and Environment Variable Setup

The redesign splits credentials and environment variables by context:

| Variable | Purpose | Source | Consumed In |
|--|--|--|--|
| `NOMARR_ADMIN_PASSWORD` | Container app auth / admin user creation | Baked into `docker/nomarr.env.example` (or hardcoded in workflow heredoc `nomarr.env` block) | Container startup — sets up admin user |
| `E2E_WEB_PASSWORD` | Playwright login credential | Must match `NOMARR_ADMIN_PASSWORD` value; exported to E2E test runner | `e2e/fixtures/auth.ts` — web UI login |
| `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS` | Backend file watcher poll override | E2E workflow env var (short interval for CI) | `nomarr/app.py` at startup — injected into `FileWatcherService` |
| `E2E_TEST_LIBRARY_PATH` | Packaged test fixture location | Explicit path `/app/tests/fixtures/library/good` | `e2e/fixtures/test-library.ts` — library resolution |
| `E2E_WORK_STATUS_POLL_MS`, `E2E_WORK_STATUS_TIMEOUT_MS` | Playwright polling config | E2E workflow env vars (fast intervals for CI) | `e2e/fixtures/api-helpers.ts` — bounded retry loops |

**In CI workflow (`e2e.yml`), the `Run E2E tests` step must export:**

```yaml
env:
  NOMARR_ADMIN_PASSWORD: "nomarr"         # Container admin user password
  E2E_WEB_PASSWORD: "nomarr"              # Must match NOMARR_ADMIN_PASSWORD; passed to Playwright
  NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS: "5"
  E2E_TEST_LIBRARY_PATH: "/app/tests/fixtures/library/good"
  E2E_WORK_STATUS_POLL_MS: "1000"
  E2E_WORK_STATUS_TIMEOUT_MS: "45000"
```

#### Workflow Step Changes

| Change | Why |
|--------|-----|
| Set `E2E_WEB_PASSWORD: <web-password>` matching `NOMARR_ADMIN_PASSWORD` | Ensures `e2e/fixtures/auth.ts` can log in without falling back to Docker log scraping (which is a CI anti-pattern) |
| Export `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS=5` and polling env vars | Accelerates file-watching and polling tests for PR-gate viability |
| Export `E2E_TEST_LIBRARY_PATH=/app/tests/fixtures/library/good` | Makes the canonical packaged fixture path explicit in CI |
| Add `e2e/no-gpu-fallback.spec.ts` implicitly (no workflow change needed — it runs with `--project=chromium`) | New blocking spec or explicit fallback coverage inside smoke |
| Trigger on `pull_request` and `push` for protected branches | If E2E does not run in CI, it does not protect shipping quality |

The workflow's existing structure (Chromium-only, GHCR pull, compose override, health-check wait) is largely correct and should be preserved.

#### Blocking Means Pull Request Trigger

The current `e2e.yml` is `workflow_dispatch` only. That is incompatible with the purpose of E2E in this repository.

**Required outcome:** `e2e.yml` (or its replacement) must run on `pull_request` to protected branches and block merge on failure.

Manual-only E2E does not satisfy the design goal of catching bad code before it ships. This redesign assumes PR-triggered blocking execution as a non-negotiable end state, not an optional future enhancement.

#### Documentation and Configuration File Rollout

The following files must be updated or created to document the E2E redesign, environment setup, and CI contract:

| File | Current State | Required Update |
|--|--|--|
| `docker/nomarr.env.example` | May or may not document `NOMARR_ADMIN_PASSWORD` | Ensure it explicitly names and documents the admin password variable; document `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS` as optional E2E-only override |
| `e2e/README.md` | References non-existent test files, hardcoded auth defaults | Rewrite with actual tier structure, env var contract (`E2E_WEB_PASSWORD`, `NOMARR_ADMIN_PASSWORD`), and Chromium-only CI note |
| `e2e/QUICK_REFERENCE.md` | CI/CD section incomplete, missing env vars | Update with full `e2e.yml` env var table and endpoint oracle mappings |
| `e2e/TEST_PLAN.md` | Stale test inventory and browser compatibility | Update with tier-based test inventory, accurate browser/env contract, and timing override explanations |

---

### What Must NOT Live in Playwright E2E

The following concerns must be explicitly excluded from the E2E layer:

| Concern | Correct home |
|---------|-------------|
| ML tagging accuracy / correctness | Backend integration tests with known fixture hashes |
| GPU vs CPU performance benchmarks | Dedicated perf test or backend container test |
| ArangoDB schema validation | Backend unit/integration tests |
| Docker container log inspection as primary oracle | Removed; use API assertions |
| Firefox / WebKit cross-browser coverage | Optional local/manual coverage only; not part of blocking PR E2E contract |
| Embedding distance / ML model output quality | Non-E2E, per ASR-0010 |

---

### Stale Documentation Cleanup (Deferred to Implementation)

The following `e2e/` documentation files describe the original auto-generated suite and contain inaccurate file lists, test counts, auth assumptions, and CI instructions. They are actively misleading to contributors and downstream agents. Cleanup is in scope for this redesign and will be completed after specs and fixtures are working.

| File | Staleness | Required Action |
|------|-----------|----------------|
| `e2e/README.md` | References non-existent test files, describes auth with hardcoded `'nomarr'` default (ignoring env var chain), lists Firefox/WebKit as active CI browsers | Rewrite: actual tier structure, file list, env var contract (`E2E_WEB_PASSWORD`), Chromium-only CI note |
| `e2e/IMPLEMENTATION_SUMMARY.md` | Describes the original 10-file/50+-test generated suite; claims CI readiness that is inaccurate for the Docker environment | Archive or replace with a one-page summary of the redesigned suite once implementation is complete |
| `e2e/QUICK_REFERENCE.md` | CI/CD section shows a generic GitHub Actions snippet, not the actual `e2e.yml` structure; environment variable section omits `E2E_WEB_PASSWORD` and `E2E_TEST_LIBRARY_PATH` | Update CI section and env var table to match `e2e.yml` and the fixture contracts |
| `e2e/TEST_PLAN.md` | Test categories, file names, test counts, and browser compatibility section are all stale; CI section references `auth.spec.ts` and `libraries.spec.ts` which do not exist | Update with tier-based test inventory and accurate browser/env contract |

Doc cleanup should happen as a final step, after specs are working and fixture contracts are finalized.

---

## Design Goals

1. Every browser E2E test produces a deterministic pass/fail on GitHub Actions with no environment-specific dependencies.
2. CPU/no-GPU graceful fallback is an explicitly validated behavior, not an assumed one.
3. Docker fixture paths are container-visible and version-controlled via checked-in packaged fixtures — no host path guessing.
4. Stable API endpoints (`/api/v1/info`, `/api/web/machine-learning/work-status`, `/api/web/health/gpu`) replace log scraping as backend oracles.
5. The `playwright.config.ts` and `e2e.yml` agree on browser scope; no ghost browser projects.
6. Browser E2E is a blocking PR gate, not a manual smoke check.
7. File watching and polling are covered in blocking E2E with accelerated CI-specific timing.

---

## Constraints

- GitHub-hosted runners have no GPU; CPU fallback must be testable without hardware changes.
- The app image is pulled from GHCR; the E2E workflow cannot rebuild it.
- Blocking E2E depends on a deliberate fixture packaging contract: the runtime image must continue to include the checked-in E2E media fixtures at a stable path.
- ML correctness and GPU acceleration cannot be proven through browser automation — this is a feature boundary, not a gap.
- ADR-023 (HTTP polling) is the canonical async status model; E2E polling must follow that contract.
- File watching defaults are too slow for PR gating unless a CI-specific fast interval/config override is provided.

---

## Migration Guidance

For implementors picking this up, the recommended sequence is:

0. **`e2e/fixtures/docker-logs.ts`**: Remove this file. It is an explicit anti-pattern (Docker log inspection as a test oracle) and its removal is a prerequisite for the rest of the redesign. Identify any spec that imports it and either rewrite the assertion using an API call or delete the test.

1. **`playwright.config.ts`**: Remove Firefox and WebKit projects from the CI-intended config (or gate them behind `CI !== 'true'`). Set `fullyParallel: false` as default; enable per-file if isolation is guaranteed.

2. **`e2e/smoke.spec.ts`**: Replace Docker log oracle with `GET /api/v1/info` on startup assertion. Keep navigation smoke tests. Add `GET /api/web/health/gpu` assertion as a canary for degraded-but-usable state.

3. **`.github/workflows/e2e.yml`**: Export `E2E_TEST_LIBRARY_PATH=/app/tests/fixtures/library/good`. Add `E2E_WEB_PASSWORD` to the `Run E2E tests` step env. Inject CI timing overrides (`NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS`, `E2E_WORK_STATUS_POLL_MS`, `E2E_WORK_STATUS_TIMEOUT_MS`).

4. **`e2e/library-integration.spec.ts`**: Rewrite fixture path resolution to use the canonical packaged in-container path. Replace `beforeAll` page fixture usage with proper Playwright `request` context or per-test setup. Poll `GET /api/web/machine-learning/work-status` for scan completion. Add real event-mode and poll-mode mutation tests against the packaged fixture library using container-side fixture mutation helpers (not host-path mutation).

5. **`e2e/no-gpu-fallback.spec.ts`**: New spec or explicit smoke coverage. Assert `GET /api/web/health/gpu` returns 200 with a non-error status body. This must pass in every CI run.

6. **`e2e/ml-tagging.spec.ts`**: Delete it or repurpose it to a real UI-visible behavior. Do not preserve a fake ML-coverage file just to keep the filename alive.

7. **`.github/workflows/e2e.yml`**: Move from `workflow_dispatch` only to PR-triggered blocking execution. Manual dispatch may remain as an additional trigger, but not as the only one.

---

## Acceptance Criteria (Watch/Poll Behavior)

1. Event-mode test mutates packaged fixture content inside running container and detects change without Docker log scraping.
2. Poll-mode test mutates packaged fixture content inside running container and detects change within `E2E_WORK_STATUS_TIMEOUT_MS` under CI overrides.
3. E2E job sets and uses all required env knobs: `E2E_WEB_PASSWORD`, `E2E_TEST_LIBRARY_PATH`, `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS`, `E2E_WORK_STATUS_POLL_MS`, `E2E_WORK_STATUS_TIMEOUT_MS`.
4. Blocking E2E assertions use `/api/web/machine-learning/work-status` and `/api/web/health/gpu`; no `/api/web/work-status` usage remains.
5. Production defaults remain unchanged unless test-only overrides are explicitly set.

---

## Open Questions

1. **Override naming finalization**: Confirm final names for the proposed test-only timing knobs (`NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS`, `E2E_WORK_STATUS_POLL_MS`, `E2E_WORK_STATUS_TIMEOUT_MS`) before implementation.

2. **Fixture size optimization**: Keep `tests/fixtures/library/good` as canonical packaged root, or add a smaller packaged subset for faster PR-gate runtime.

---
