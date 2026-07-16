# E2E Testing (Playwright)

**Stack:** Playwright · TypeScript · Docker (app + PostgreSQL)

---

## Prerequisites

E2E tests run against the **Docker environment**, not native dev:
1. Docker containers must be running (`nomarr-app` + `nomarr-postgres`)
2. App accessible at `http://localhost:8356`
3. Admin password matches `e2e/fixtures/auth.ts` default (`nomarr`)
4. Playwright browsers installed: `npx playwright install`

**Start the environment:**
```powershell
Push-Location .docker; docker compose up -d; Pop-Location
```

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

Playwright config at `e2e/playwright.config.ts`:
- **testDir:** `.`
- **baseURL:** `http://localhost:8356`
- **browsers:** Chromium, Firefox, WebKit
- **fullyParallel:** `true`
- **retries:** 2 on CI, 0 locally
- **trace:** On first retry
- **screenshot/video:** On failure

---

## Fixtures

### Authentication (`fixtures/auth.ts`)

```typescript
import { test, expect } from './fixtures/auth';

test('my test', async ({ authenticatedPage: page }) => {
  // Already logged in, session token obtained
  await expect(page.locator('nav')).toBeVisible();
});
```

For tests that need unauthenticated access, import from `@playwright/test` directly.

### API Helpers (`fixtures/api-helpers.ts`)

```typescript
import { createApiHelpers } from './fixtures/api-helpers';

test('my test', async ({ authenticatedPage: page }) => {
  const api = createApiHelpers(page);
  const response = await api.waitForApiCall('/api/web/library', 'GET');
  expect(response.status()).toBe(200);
});
```

**Important:** Set up `waitForApiCall` **before** the action that triggers the API call.

### Docker Logs (`fixtures/docker-logs.ts`)

```typescript
import { test, expect } from './fixtures/docker-logs';

test('my test', async ({ page, dockerLogs }) => {
  dockerLogs.clearErrors();
  // ... perform actions ...
  const errors = dockerLogs.getErrors();
  expect(errors).toHaveLength(0);
});
```

---

## Writing Tests

### Smoke Tests (critical path)

Fast tests that verify the app loads and key sections are navigable.

### Feature Tests (functionality)

Test specific features through the UI:

```typescript
import { test, expect } from './fixtures/auth';
import { createApiHelpers } from './fixtures/api-helpers';

test.describe('Calibration', () => {
  test('displays calibration status', async ({ authenticatedPage: page }) => {
    const api = createApiHelpers(page);
    await page.locator('text=/calibration/i').first().click();
    const progress = await api.getApiResponse('/api/web/calibration/progress');
    expect(progress).toHaveProperty('total_heads');
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
```

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
```

---

## Validation

- Tests run against Docker environment, not native dev
- Auth fixture used for authenticated pages
- No hardcoded `localhost:8356` URLs (use `baseURL` from config)
- Selectors use role/text queries, not MUI class names
- Waits are condition-based, not fixed `setTimeout`
- Docker log monitoring checks for backend errors
- `npx playwright test <your-spec>` passes locally
- Spec file is in `e2e/` directory with `.spec.ts` extension
