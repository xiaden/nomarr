# Nomarr E2E Test Plan

## Suite overview

Nomarr's active Playwright E2E suite is intentionally small and deterministic. It validates the browser flows and backend contracts that are most useful for blocking regressions in CI.

## Test matrix

| Test File | Tests | Browser | Status | Priority | Notes |
| --- | ---: | --- | --- | --- | --- |
| `smoke.spec.ts` | 3 | Chromium | ✅ Active | P0 | Startup, GPU-health, and navigation smoke checks |
| `library-integration.spec.ts` | 7 | Chromium | ✅ Active | P0 | Library creation, scan completion, and watch-mode behavior |
| `no-gpu-fallback.spec.ts` | 1 | Chromium | ✅ Active | P1 | Degraded CPU/no-GPU contract canary |

**Total: 11 tests across 3 spec files**

## Coverage by scenario

### Smoke coverage (P0)

- ✅ `GET /api/v1/info` returns the expected public-info contract
- ✅ `GET /api/web/health/gpu` returns HTTP 200 with a valid response contract
- ✅ Core UI navigation loads without critical frontend console or page errors

### Library integration coverage (P0)

- ✅ Create a library using `E2E_TEST_LIBRARY_PATH`
- ✅ Verify quick scan is disabled before the first full scan
- ✅ Run a full scan and wait for idle completion
- ✅ Switch file watching to event mode in the UI
- ✅ Confirm event mode remains stable with bounded work-status polling
- ✅ Switch file watching to polling mode in the UI
- ✅ Confirm polling mode remains stable with bounded work-status polling

### No-GPU fallback coverage (P1)

- ✅ Verify `/api/web/health/gpu` remains non-fatal in degraded CPU-only environments
- ✅ Reject top-level API error wrappers for the GPU health endpoint

## Primary endpoint coverage

The redesigned suite intentionally centers on these stable oracles:

- `/api/v1/info`
- `/api/web/work-status`
- `/api/web/health/gpu`

Supporting integration operations also touch authenticated library endpoints during setup and verification:

- `/api/web/libraries`
- `/api/web/libraries/{library_id}`

## What this suite does not cover

The suite does **not** currently attempt to cover:

- broad multi-feature browser exploration across every Nomarr page
- additional CI browser compatibility beyond the documented runner
- external filesystem mutation workflows
- startup-log based readiness or assertion flows
- the removed legacy 9-file / 43-test suite model

## Execution strategy

### Local development

Preferred deterministic runs:

```bash
npx playwright test --project=chromium
npx playwright test e2e/smoke.spec.ts --project=chromium
npx playwright test e2e/library-integration.spec.ts --project=chromium
npx playwright test e2e/no-gpu-fallback.spec.ts --project=chromium
```

Helpful debug variants:

```bash
npx playwright test --project=chromium --headed
npx playwright test --project=chromium --ui
npx playwright test --project=chromium --debug
```

### CI execution

GitHub Actions executes the suite on:

- `pull_request` to `develop`
- `pull_request` to `main`
- `workflow_dispatch`

CI run characteristics:

- installs Chromium only
- runs `npx playwright test --project=chromium --reporter=list,html`
- exports `E2E_WEB_PASSWORD` from secrets and mirrors it into `NOMARR_ADMIN_PASSWORD` for the Nomarr container
- exports `E2E_TEST_LIBRARY_PATH=/app/tests/fixtures/library/good`
- exports `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS`, `E2E_WORK_STATUS_POLL_MS`, and `E2E_WORK_STATUS_TIMEOUT_MS`
- uploads Playwright report and raw test-result artifacts

## Test data and environment requirements

### Required runtime pieces

- Nomarr available at `http://localhost:8356`
- Backend services and ArangoDB available
- Valid admin password deterministically configured in CI via matching `E2E_WEB_PASSWORD` and `NOMARR_ADMIN_PASSWORD`
- Fixture library path (`E2E_TEST_LIBRARY_PATH`) must exist inside the running Nomarr container — not only on the host via a bind mount
- Docker CLI available on the host when running mutation tests (tests 5 and 7); set `SKIP_CONTAINER_MUTATION=true` when Docker is unavailable
- `NOMARR_CONTAINER_NAME` must match the running container name (default: `nomarr`) for `docker exec` to succeed

### Timing knobs

| Variable | Default | Role |
| --- | --- | --- |
| `NOMARR_E2E_WATCH_POLL_INTERVAL_SECONDS` | CI sets `1` | Watch-mode polling cadence inside the runtime environment |
| `E2E_WORK_STATUS_POLL_MS` | `2000` | How often Playwright polls `/api/web/work-status` |
| `E2E_WORK_STATUS_TIMEOUT_MS` | `60000` | Maximum time Playwright waits for idle completion |

## Validation strategy

When validating this suite or future updates, confirm:

1. The active spec list is still `smoke.spec.ts`, `library-integration.spec.ts`, and `no-gpu-fallback.spec.ts`.
2. CI documentation remains Chromium-only unless the workflow changes.
3. Work-status references use `/api/web/work-status`.
4. Docs do not reintroduce log-scraping or external-filesystem mutation assumptions.
5. The suite description remains aligned with the real 11-test total.

## Future expansion guardrails

If the suite grows again, keep the redesign rules intact:

- prefer API-backed readiness and async status checks over log scraping
- document browser scope explicitly
- keep environment contracts in one place
- avoid over-claiming product coverage
- add coverage only when it remains deterministic enough to block PRs
