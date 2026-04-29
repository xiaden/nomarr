# Playwright E2E Quick Reference

## Current suite at a glance

```text
e2e/
├── smoke.spec.ts             # 3 tests
├── library-integration.spec.ts
│                            # 7 tests
└── no-gpu-fallback.spec.ts  # 1 test
```

**Total:** 3 spec files, 11 tests, Chromium-only in CI.

## Quick commands

```bash
# Run the full suite in the supported CI browser
npx playwright test --project=chromium

# Run a single spec
npx playwright test smoke.spec.ts --project=chromium
npx playwright test library-integration.spec.ts --project=chromium
npx playwright test no-gpu-fallback.spec.ts --project=chromium

# Helpful local variants
npx playwright test --project=chromium --headed
npx playwright test --project=chromium --ui
npx playwright test --project=chromium --debug

# Reports
npx playwright show-report
```

## Environment variables

```bash
E2E_WEB_PASSWORD=nomarr
E2E_TEST_LIBRARY_PATH=/app/tests/fixtures/library/good
NOMARR_CONTAINER_NAME=nomarr
# SKIP_CONTAINER_MUTATION=true   # uncomment if Docker CLI is unavailable locally
NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS=1
E2E_WORK_STATUS_POLL_MS=2000
E2E_WORK_STATUS_TIMEOUT_MS=60000
```

| Variable | Purpose |
| --- | --- |
| `E2E_WEB_PASSWORD` | Auth password for Playwright login; required in all environments and must match the app admin password |
| `E2E_TEST_LIBRARY_PATH` | Canonical fixture library path for library integration coverage |
| `NOMARR_CONTAINER_NAME` | Container name used by watch-mode mutation tests via `docker exec`; default `nomarr` |
| `SKIP_CONTAINER_MUTATION` | Set to skip watch-mode mutation tests when Docker CLI is unavailable locally |
| `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS` | Runtime watch polling knob used in the containerized environment |
| `E2E_WORK_STATUS_POLL_MS` | Interval between work-status polls |
| `E2E_WORK_STATUS_TIMEOUT_MS` | Maximum wait for work-status completion |

## Canonical API oracles

- `GET /api/v1/info`
- `GET /api/web/work-status`
- `GET /api/web/health/gpu`

## Test organization

| Spec | Tests | Coverage summary |
| --- | ---: | --- |
| `smoke.spec.ts` | 3 | Startup contract, GPU health contract, and core navigation smoke |
| `library-integration.spec.ts` | 7 | Library creation, full scan, quick-scan enablement, and watch-mode UI coverage |
| `no-gpu-fallback.spec.ts` | 1 | CPU-only / degraded GPU health contract canary |

## CI facts

- Runs on `pull_request` to `develop` and `main`
- Also supports `workflow_dispatch`
- Installs and runs **Chromium only**
- Uses `E2E_WEB_PASSWORD` from GitHub Actions secrets and mirrors it into `NOMARR_ADMIN_PASSWORD` for the Nomarr container
- Uses `/app/tests/fixtures/library/good` as the default fixture path
- Uploads Playwright report artifacts after each run

## Deterministic rules

- Do **not** use container log output as a test oracle.
- Do **not** assume unsupported CI browser coverage.
- Do **not** rely on external filesystem mutation assumptions for watch-mode assertions.
- Do use bounded polling via `E2E_WORK_STATUS_POLL_MS` and `E2E_WORK_STATUS_TIMEOUT_MS`.

## When something fails

- Re-run the failing spec with `--project=chromium` first.
- Check the Playwright HTML report.
- Verify the app password and fixture library path env vars.
- If async work is slow, inspect the work-status endpoint behavior before increasing timeouts.
