# E2E Test Suite

Comprehensive end-to-end test suite for Nomarr using Playwright.

## Structure

```
e2e/
├── fixtures/
│   ├── auth.ts              # Authentication helpers and fixtures
│   └── api-helpers.ts       # API testing utilities
├── auth.spec.ts             # Authentication flow tests
├── libraries.spec.ts        # Library management tests
├── calibration.spec.ts      # Calibration workflow tests
├── analytics.spec.ts        # Analytics and insights tests
├── metadata.spec.ts         # Metadata browsing tests
├── worker.spec.ts           # Worker control tests
└── info-health.spec.ts      # System info and health checks
```

## Running Tests

### Run all tests
```bash
npx playwright test
```

### Run specific test file
```bash
npx playwright test e2e/auth.spec.ts
```

### Run tests in headed mode (see browser)
```bash
npx playwright test --headed
```

### Run tests in UI mode (interactive)
```bash
npx playwright test --ui
```

### Run tests in a specific browser
```bash
npx playwright test --project=chromium
npx playwright test --project=firefox
npx playwright test --project=webkit
```

### Debug tests
```bash
npx playwright test --debug
```

## Prerequisites

- Dev server must be running on `http://localhost:8356`
- Default password is `nomarr` (configured in auth.ts fixture)
- Backend and database must be accessible

## Test Categories

### Authentication (`auth.spec.ts`)
- Login with correct/incorrect password
- Logout functionality
- Protected route access

### Libraries (`libraries.spec.ts`)
- List libraries
- View library stats
- Navigate library management
- Create library form
- Create new library (skipped by default - requires valid path)

### Calibration (`calibration.spec.ts`)
- Load calibration status
- View calibration history
- Generate calibration UI
- Generate calibration (skipped - requires data)
- Convergence status

### Analytics (`analytics.spec.ts`)
- Navigate to analytics
- Load tag frequencies
- Load mood distribution
- Load tag correlations

### Metadata (`metadata.spec.ts`)
- Load entity counts
- Browse artists
- Browse albums
- View artist details (skipped - requires data)
- View artist albums (skipped - requires data)

### Worker Control (`worker.spec.ts`)
- Display worker status
- Pause worker (skipped - modifies state)
- Resume worker (skipped - modifies state)
- Load processing status

### System Info (`info-health.spec.ts`)
- Load system info
- Load health status
- Load GPU health
- Load work status
- Display system info in UI

## Test Patterns

### Using authenticated fixture
```typescript
test('my test', async ({ authenticatedPage: page }) => {
  // Already logged in
});
```

### Using API helpers
```typescript
const api = createApiHelpers(page);

// Wait for specific API call
const response = await api.waitForApiCall('/api/web/libraries', 'GET');

// Assert API success
await api.assertApiSuccess('/api/web/info', 'GET');

// Get JSON response
const data = await api.getApiResponse('/api/web/libraries', 'GET');
```

### Skipping tests conditionally
Some tests are skipped by default because they:
- Require specific data (e.g., libraries, artists)
- Modify system state (e.g., pause worker)
- Need valid file paths (e.g., create library)

Use `test.skip()` to skip tests conditionally or remove `.skip` to enable them when appropriate.

## Configuration

Tests are configured in `playwright.config.ts`:
- Base URL: `http://localhost:8356`
- Runs across Chromium, Firefox, and WebKit
- Screenshots and videos captured on failure
- Dev server auto-starts if not running
- Traces captured on retry

## Troubleshooting

### Server not starting
Ensure the dev server command in `playwright.config.ts` is correct:
```typescript
webServer: {
  command: 'npm run dev',
  url: 'http://localhost:8356',
}
```

### Authentication failing
Check the password in `e2e/fixtures/auth.ts`:
```typescript
export async function login(page: Page, password: string = 'nomarr') {
```

### Timeouts
Some operations may take longer than default timeouts. Increase timeouts as needed:
```typescript
await page.waitForSelector('selector', { timeout: 10000 });
```

### Viewing test results
```bash
npx playwright show-report
```
