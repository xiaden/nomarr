# E2E Test Suite

Playwright covers a small, deterministic Nomarr browser suite that is intended to block regressions in GitHub Actions without depending on log scraping, external filesystem-coupled mutation tricks, or ambiguous CI browser scope.

## Current suite

```text
e2e/
├── fixtures/
│   ├── api-helpers.ts        # Authenticated API requests + bounded work-status polling
│   ├── auth.ts               # Login helper and authenticated Playwright fixture
│   ├── container-mutation.ts # Docker exec helpers for in-container file mutation (watch-mode tests)
│   └── test-library.ts       # Canonical container-side fixture library path
├── smoke.spec.ts            # 3 smoke tests for startup, GPU health, and core navigation
├── library-integration.spec.ts
│                           # 7 library lifecycle and watch-mode tests
└── no-gpu-fallback.spec.ts # 1 degraded CPU/no-GPU contract canary
```

The redesigned suite currently contains **3 spec files** and **11 tests total**:

| Spec file | Tests | What it validates |
| --- | ---: | --- |
| `smoke.spec.ts` | 3 | Public startup contract via `/api/v1/info`, authenticated GPU health via `/api/web/health/gpu`, and core tab navigation without critical frontend failures |
| `library-integration.spec.ts` | 7 | Library creation using the canonical fixture path, full scan completion, and UI watch-mode switching with bounded `/api/web/work-status` polling |
| `no-gpu-fallback.spec.ts` | 1 | `/api/web/health/gpu` stays usable in degraded CPU-only or no-GPU environments |

## Approved API oracles

The suite is intentionally anchored on a short list of stable backend checks:

- `/api/v1/info`
- `/api/web/work-status`
- `/api/web/health/gpu`

Those endpoints replace older startup-log and "guess from container startup" style oracles.

## Local prerequisites

- Nomarr reachable at `http://localhost:8356`
- Backend services and ArangoDB running
- Playwright dependencies installed
- A usable admin password exposed to the tests
- The container-side fixture library available at the configured path when running `library-integration.spec.ts`

## Environment variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `E2E_WEB_PASSWORD` | Required | none | Password used for authenticated browser login; in CI it must match `NOMARR_ADMIN_PASSWORD` configured for the Nomarr container |
| `E2E_TEST_LIBRARY_PATH` | Optional | `/app/tests/fixtures/library/good` | Canonical fixture library path used by library integration coverage; this path must exist inside the running Nomarr container image, not only on the host via a bind mount |
| `NOMARR_CONTAINER_NAME` | Optional | `nomarr` | Container name used by the watch-mode mutation helper when calling `docker exec` |
| `SKIP_CONTAINER_MUTATION` | Optional | unset | Skips the two watch-mode mutation tests when Docker CLI/container access is unavailable locally |
| `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS` | Optional | app/runtime default | Watch-mode timing knob used by the containerized test environment |
| `E2E_WORK_STATUS_POLL_MS` | Optional | `2000` | Poll interval for `/api/web/work-status` |
| `E2E_WORK_STATUS_TIMEOUT_MS` | Optional | `60000` | Upper bound for work-status polling waits |

## Running locally

### Run the full suite

```bash
npx playwright test --project=chromium
```

### Run individual specs

```bash
npx playwright test smoke.spec.ts --project=chromium
npx playwright test library-integration.spec.ts --project=chromium
npx playwright test no-gpu-fallback.spec.ts --project=chromium
```

### Useful local variants

```bash
npx playwright test --project=chromium --headed
npx playwright test --project=chromium --ui
npx playwright test --project=chromium --debug
npx playwright show-report
```

### Local setup example

```bash
E2E_WEB_PASSWORD=nomarr
E2E_TEST_LIBRARY_PATH=/app/tests/fixtures/library/good
NOMARR_CONTAINER_NAME=nomarr
E2E_WORK_STATUS_POLL_MS=2000
E2E_WORK_STATUS_TIMEOUT_MS=60000
```

`E2E_WEB_PASSWORD` is required in all environments — the login helper throws immediately if it is not set. Set it before running any spec locally, e.g. `export E2E_WEB_PASSWORD=nomarr` if that matches your local admin password. In CI, the workflow sets the Nomarr container's `NOMARR_ADMIN_PASSWORD` to the same secret so browser auth stays deterministic on fresh volumes.

Watch-mode change-detection coverage mutates files inside the running container and therefore requires Docker CLI access via `docker exec`. If Docker is unavailable in your local environment, set `SKIP_CONTAINER_MUTATION=true` to skip those mutation-dependent tests.

## CI behavior

GitHub Actions runs the E2E workflow on:

- `pull_request` targeting `develop`
- `pull_request` targeting `main`
- `workflow_dispatch`

Current CI characteristics:

- **PR-blocking** for `develop` and `main`
- **Chromium-only** Playwright execution in CI
- `E2E_WEB_PASSWORD` provided from GitHub Actions secrets and mirrored into `NOMARR_ADMIN_PASSWORD` for the Nomarr container
- `E2E_TEST_LIBRARY_PATH` set to `/app/tests/fixtures/library/good`
- Polling knobs exported explicitly for deterministic async waits
- HTML report and test-results artifacts uploaded on every run

## What the suite intentionally does not do

- It does **not** use container-startup log output as an assertion oracle.
- It does **not** claim unsupported CI browser coverage.
- It does **not** mutate external filesystem paths from the test runner.
- It does **not** try to prove full product coverage; it focuses on deterministic blocking checks.

## Troubleshooting

### Login failures

- Verify `E2E_WEB_PASSWORD` matches the app admin password or the container's `NOMARR_ADMIN_PASSWORD`.
- Confirm the app is reachable at `http://localhost:8356`.
- Re-run a single spec first to isolate whether the failure is auth-specific or app startup-related.

### Library integration failures

- Confirm `E2E_TEST_LIBRARY_PATH` exists inside the runtime environment.
- Check whether the fixture library path is mounted where the app can read it.
- Set `NOMARR_CONTAINER_NAME` if your local container is not named `nomarr`, or set `SKIP_CONTAINER_MUTATION=1` when running outside Docker.
- Increase `E2E_WORK_STATUS_TIMEOUT_MS` only if your environment is genuinely slower.

### CPU-only runners

`e2e/no-gpu-fallback.spec.ts` and the GPU-health smoke assertion expect `/api/web/health/gpu` to return HTTP 200 with a valid response body even when GPU hardware is unavailable. A missing GPU is not itself a test failure.
