# E2E Test Suite Implementation Summary

## Overview

The Playwright E2E redesign trimmed the browser suite down to a deterministic, CI-friendly core:

- **3 spec files**
- **11 tests total**
- **Chromium-only CI execution**
- **PR-blocking workflow** on `pull_request` to `develop` and `main`, plus `workflow_dispatch`
- **API-first oracles** using `/api/v1/info`, `/api/web/work-status`, and `/api/web/health/gpu`
- **No container log scraping** as a readiness or assertion signal

## Active files

### Shared fixtures

1. **`e2e/fixtures/auth.ts`**
   - Provides the authenticated Playwright fixture
   - Centralizes browser login handling for authenticated specs

2. **`e2e/fixtures/api-helpers.ts`**
   - Provides authenticated API requests from browser sessions
   - Implements bounded polling against `/api/web/work-status`
   - Reads `E2E_WORK_STATUS_POLL_MS` and `E2E_WORK_STATUS_TIMEOUT_MS`

3. **`e2e/fixtures/container-mutation.ts`**
   - Provides `docker exec` helpers for in-container file mutation
   - Used by watch-mode mutation tests (tests 5 and 7 in `library-integration.spec.ts`)
   - Reads `NOMARR_CONTAINER_NAME`; skipped when `SKIP_CONTAINER_MUTATION` is set

4. **`e2e/fixtures/test-library.ts`**
   - Defines the canonical library fixture path contract
   - Uses `E2E_TEST_LIBRARY_PATH`
   - Defaults to `/app/tests/fixtures/library/good`

### Active specs

1. **`e2e/smoke.spec.ts`** — 3 tests
   - Verifies public startup information via `GET /api/v1/info`
   - Verifies authenticated GPU health via `GET /api/web/health/gpu`
   - Verifies core navigation without critical frontend errors

2. **`e2e/library-integration.spec.ts`** — 7 tests
   - Creates the fixture library using the canonical container-side path
   - Verifies quick scan is disabled before the first full scan
   - Runs a full scan and waits for completion with bounded work-status polling
   - Switches watch mode between event and poll in the UI
   - Confirms watch mode UI switching is reflected in the library card (event and poll)
   - Detects in-container file mutations via `docker exec` for both watch modes; skippable with `SKIP_CONTAINER_MUTATION`

3. **`e2e/no-gpu-fallback.spec.ts`** — 1 test
   - Confirms `GET /api/web/health/gpu` returns HTTP 200 with a valid non-error contract in CPU-only or degraded environments

## Current suite totals

| Scope | Count |
| --- | ---: |
| Spec files | 3 |
| Tests | 11 |
| Browsers used in CI | 1 |
| CI workflow triggers | 2 event types |

## API contracts exercised

### Primary deterministic oracles

- `/api/v1/info`
- `/api/web/work-status`
- `/api/web/health/gpu`

### Supporting authenticated endpoints used by integration flow

- `/api/web/libraries`
- `/api/web/libraries/{library_id}`

## Execution model

### Local execution

Typical deterministic local run:

```bash
npx playwright test --project=chromium
```

Recommended environment variables:

```bash
E2E_WEB_PASSWORD=nomarr
E2E_TEST_LIBRARY_PATH=/app/tests/fixtures/library/good
E2E_WORK_STATUS_POLL_MS=2000
E2E_WORK_STATUS_TIMEOUT_MS=60000
```

### CI execution

The GitHub Actions workflow:

- runs on `pull_request` to `develop` and `main`
- also supports `workflow_dispatch`
- installs **Chromium only**
- runs `npx playwright test --project=chromium --reporter=list,html`
- exports `E2E_WEB_PASSWORD` from GitHub secrets and feeds the same value into `NOMARR_ADMIN_PASSWORD` for the Nomarr container
- exports the library-path and polling env vars explicitly
- uploads Playwright HTML and raw test-results artifacts

## What changed in the redesign

### Removed from the old model

- Startup-log based readiness and password-discovery documentation
- Ambiguous multi-browser CI claims that no longer match the workflow
- Stale references to removed legacy spec files from the pre-redesign suite
- Stale pre-redesign work-status endpoint references
- External filesystem mutation assumptions for watch-mode coverage

### Kept and improved

- Authenticated browser fixtures
- API helper utilities
- Failure artifacts such as Playwright HTML reports and test results
- Explicit bounded polling for asynchronous backend work

## Validation snapshot

The redesigned docs and suite now align on these facts:

- **11 tests passing in Chromium** is the intended suite shape
- CI coverage is **Chromium-only**, not multi-browser
- The canonical async status endpoint is `/api/web/work-status`
- GPU checks validate degraded-but-usable behavior rather than requiring a GPU

## Follow-up boundaries

This suite is intentionally narrow. It does not claim comprehensive browser coverage for every Nomarr feature area. Additional E2E expansion should keep the same deterministic rules:

- prefer API-backed oracles over log scraping
- avoid host-environment coupling
- keep CI browser scope explicit
- use bounded waits with documented env knobs
