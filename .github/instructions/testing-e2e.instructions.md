---
name: E2E Testing
description: Guidelines for writing and running Playwright end-to-end tests against the Nomarr Docker environment
applyTo: "e2e/**/*.ts"
---

# E2E Testing

**Purpose:** Define how to write, organize, and run Playwright-based end-to-end tests for Nomarr.

**Stack:** Playwright · TypeScript · Docker (app + ArangoDB)

---

## Quick Reference

```powershell
# Run all E2E tests
npx playwright test

# Run a specific spec file
npx playwright test e2e/smoke.spec.ts

# Run tests matching a pattern
npx playwright test --grep "login"

# Run in headed mode (see the browser)
npx playwright test --headed

# Run in UI mode (interactive test runner)
npx playwright test --ui

# Debug a specific test
npx playwright test e2e/smoke.spec.ts --debug

# Run in a specific browser
npx playwright test --project=chromium
npx playwright test --project=firefox
npx playwright test --project=webkit

# View last test report
npx playwright show-report
```

---

## Prerequisites

E2E tests run against the **Docker environment**, not native dev:

1. Docker containers must be running (`nomarr-app` + `nomarr-arangodb`)
2. App accessible at `http://localhost:8356`
3. Admin password matches `e2e/fixtures/auth.ts` default (`nomarr`)
4. Playwright browsers installed: `npx playwright install`

**Start the environment:**
```powershell
Push-Location .docker; docker compose up -d; Pop-Location
```

**Use `127.0.0.1` not `localhost`** when debugging manually — Windows resolves `localhost` to IPv6 first, Docker only binds IPv4.

---

## Directory Structure

```
e2e/
├── fixtures/
│   ├── auth.ts              # Authentication fixture (login, authenticatedPage)
│   ├── api-helpers.ts       # API response waiting/asserting utilities
│   └── docker-logs.ts       # Docker container log monitoring
├── smoke.spec.ts            # Fast critical-path navigation test
├── library-integration.spec.ts  # Library lifecycle tests
├── ml-tagging.spec.ts       # ML processing pipeline tests
├── README.md                # Detailed E2E documentation
├── QUICK_REFERENCE.md       # Command cheatsheet
└── TEST_PLAN.md             # Planned test coverage
```

### Naming Conventions

- **Files:** `<feature>.spec.ts` or `<workflow>.spec.ts`
- **describe blocks:** Feature or workflow name
- **test blocks:** Numbered steps for sequential flows, or descriptive names for independent tests

---

## Configuration

Playwright config lives at [playwright.config.ts](../../playwright.config.ts):

- **testDir:** `./e2e`
- **baseURL:** `http://localhost:8356`
- **browsers:** Chromium, Firefox, WebKit
- **fullyParallel:** `true`
- **retries:** 2 on CI, 0 locally
- **trace:** On first retry
- **screenshot/video:** On failure
- **webServer.command:** `npm run dev` (for local; Docker for full E2E)

---

## Fixtures

### Authentication (`fixtures/auth.ts`)

Provides an `authenticatedPage` fixture that logs in before the test:

```typescript
import { test, expect } from './fixtures/auth';

test('my test', async ({ authenticatedPage: page }) => {
  // Already logged in, session token obtained
  await expect(page.locator('nav')).toBeVisible();
});
```

For tests that need unauthenticated access:
```typescript
import { test, expect } from '@playwright/test';

test('login flow', async ({ page }) => {
  await page.goto('/');
  // Not logged in
});
```

### API Helpers (`fixtures/api-helpers.ts`)

Wait for specific API calls and assert responses:

```typescript
import { createApiHelpers } from './fixtures/api-helpers';

test('my test', async ({ authenticatedPage: page }) => {
  const api = createApiHelpers(page);

  // Wait for API call triggered by navigation
  const response = await api.waitForApiCall('/api/web/libraries', 'GET');
  expect(response.status()).toBe(200);

  // Wait and get parsed JSON
  const data = await api.getApiResponse('/api/web/calibration/progress', 'GET');
  expect(data.total_heads).toBeGreaterThan(0);
});
```

**Important:** Set up `waitForApiCall` **before** the action that triggers the API call.

### Docker Logs (`fixtures/docker-logs.ts`)

Monitor Docker container logs for backend errors during tests:

```typescript
import { test, expect } from './fixtures/docker-logs';

test('my test', async ({ page, dockerLogs }) => {
  dockerLogs.clearErrors();

  // ... perform actions ...

  // Check no backend errors occurred
  const errors = dockerLogs.getErrors();
  expect(errors).toHaveLength(0);
});
```

---

## Writing Tests

### Smoke Tests (critical path)

Fast tests that verify the app loads and key sections are navigable:

```typescript
import { expect, test } from './fixtures/docker-logs';

test.describe('Smoke Test', () => {
  test('navigate all tabs without errors', async ({ page, dockerLogs }) => {
    // Login
    await page.goto('/');
    await page.fill('input[type="password"]', 'nomarr');
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle');

    // Track console errors
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    // Navigate to each section
    for (const tab of ['Libraries', 'Calibration', 'Analytics']) {
      const nav = page.locator(`text=/${tab}/i`).first();
      if (await nav.isVisible({ timeout: 3000 })) {
        await nav.click();
        await page.waitForTimeout(1000);
      }
    }

    expect(errors).toHaveLength(0);
  });
});
```

### Feature Tests (functionality)

Test specific features through the UI:

```typescript
import { test, expect } from './fixtures/auth';
import { createApiHelpers } from './fixtures/api-helpers';

test.describe('Calibration', () => {
  test('displays calibration status', async ({ authenticatedPage: page }) => {
    const api = createApiHelpers(page);

    // Navigate to calibration page
    await page.locator('text=/calibration/i').first().click();

    // Verify API response loaded
    const progress = await api.getApiResponse('/api/web/calibration/progress');
    expect(progress).toHaveProperty('total_heads');

    // Verify UI reflects data
    await expect(page.locator('text=/heads/i')).toBeVisible();
  });
});
```

### Integration Tests (workflows)

Test multi-step user workflows. Number steps sequentially:

```typescript
test.describe('Library Lifecycle', () => {
  test('1. add library', async ({ page }) => { ... });
  test('2. scan library', async ({ page }) => { ... });
  test('3. verify files discovered', async ({ page }) => { ... });
});
```

---

## Selector Strategy

Prefer selectors in this priority order:

1. **Role-based** (best): `page.getByRole('button', { name: 'Submit' })`
2. **Text-based**: `page.locator('text=/libraries/i')` (regex for case-insensitivity)
3. **Label-based**: `page.getByLabel('Password')`
4. **CSS with attributes**: `page.locator('input[type="password"]')`
5. **data-testid** (last resort): `page.locator('[data-testid="my-element"]')`

**Avoid:**
- CSS class selectors (`.MuiButton-root`) — brittle, MUI-internal
- Deep DOM path selectors — break on layout changes
- XPath — unreadable

---

## Timing and Waits

```typescript
// ✅ Wait for specific state
await page.waitForLoadState('networkidle');
await page.waitForSelector('button[type="submit"]');
await expect(page.locator('h1')).toBeVisible({ timeout: 5000 });

// ✅ Wait for API response (set up BEFORE action)
const responsePromise = page.waitForResponse(r => r.url().includes('/api/web/info'));
await page.click('nav a');
const response = await responsePromise;

// ⚠️ Use fixed waits sparingly, only for animations/transitions
await page.waitForTimeout(500);

// ❌ Never rely on fixed waits for data loading
await page.waitForTimeout(5000); // Hoping the API finished
```

---

## Debugging

```powershell
# Step through test interactively
npx playwright test e2e/smoke.spec.ts --debug

# Open trace viewer for a failed test
npx playwright show-trace test-results/smoke-spec-ts/trace.zip

# Take a screenshot mid-test
await page.screenshot({ path: 'debug-screenshot.png' });

# Pause for manual inspection
await page.pause();
```

**Traces, screenshots, and videos** are captured automatically on failure (configured in `playwright.config.ts`).

---

## Anti-Patterns

```typescript
// ❌ Hardcoded URLs
await page.goto('http://localhost:8356/calibration');

// ✅ Use baseURL from config
await page.goto('/calibration');

// ❌ Asserting exact text that may change
expect(await page.textContent('h1')).toBe('Nomarr - Music Tag Manager v0.3.2');

// ✅ Assert the meaningful part
await expect(page.locator('h1')).toContainText('Nomarr');

// ❌ Sleeping instead of waiting
await new Promise(resolve => setTimeout(resolve, 5000));

// ✅ Wait for the condition
await expect(page.locator('[data-testid="results"]')).toBeVisible({ timeout: 10000 });

// ❌ Testing API logic through the UI
// (verifying exact JSON shapes via browser — use backend tests for that)

// ✅ Testing user-visible outcomes
await expect(page.locator('text=/12 heads calibrated/')).toBeVisible();
```

---

## When to Use E2E vs Backend/Frontend Tests

| Test This With... | E2E (Playwright) | Backend (pytest) | Frontend (Vitest) |
|---|---|---|---|
| Login flow works end-to-end | ✅ | | |
| API returns correct JSON shape | | ✅ | |
| Component renders correctly for given props | | | ✅ |
| Navigation between pages works | ✅ | | |
| Business logic computes correct result | | ✅ | |
| Button click triggers correct API call | ✅ | | |
| Form validation shows error messages | | | ✅ |
| Full library scan → ML tagging pipeline | ✅ | | |
| Utility function handles edge cases | | ✅ | ✅ |

---

## Validation Checklist

Before committing E2E test code:

- [ ] Tests run against Docker environment, not native dev
- [ ] Auth fixture used for authenticated pages
- [ ] No hardcoded `localhost:8356` URLs (use `baseURL` from config or `page.goto('/')`)
- [ ] Selectors use role/text queries, not MUI class names
- [ ] Waits are condition-based, not fixed `setTimeout`
- [ ] Docker log monitoring checks for backend errors
- [ ] `npx playwright test <your-spec>` passes locally
- [ ] Spec file is in `e2e/` directory with `.spec.ts` extension
