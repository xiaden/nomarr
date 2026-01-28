# Playwright Test Quick Reference

## Quick Commands

```bash
# Run all tests
npx playwright test

# Run specific test file
npx playwright test e2e/smoke.spec.ts
npx playwright test e2e/auth.spec.ts
npx playwright test e2e/libraries.spec.ts

# Run tests matching a pattern
npx playwright test --grep "login"
npx playwright test --grep "library"

# Run in headed mode (see browser)
npx playwright test --headed

# Run in UI mode (interactive)
npx playwright test --ui

# Run in debug mode
npx playwright test --debug

# Run specific browser
npx playwright test --project=chromium
npx playwright test --project=firefox
npx playwright test --project=webkit

# Run with different reporters
npx playwright test --reporter=list
npx playwright test --reporter=dot
npx playwright test --reporter=html

# View last test report
npx playwright show-report

# Run only failed tests
npx playwright test --last-failed
```

## Test Organization

```
e2e/
├── smoke.spec.ts         # Fast critical path tests
├── auth.spec.ts          # Login/logout
├── libraries.spec.ts     # Library management
├── calibration.spec.ts   # Calibration workflows
├── analytics.spec.ts     # Analytics features
├── metadata.spec.ts      # Browse artists/albums
├── worker.spec.ts        # Worker control
├── info-health.spec.ts   # System status
└── workflows.spec.ts     # End-to-end scenarios
```

## Writing Tests

### Basic test
```typescript
import { test, expect } from '@playwright/test';

test('my test', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toBeVisible();
});
```

### Authenticated test
```typescript
import { test, expect } from './fixtures/auth';

test('my test', async ({ authenticatedPage: page }) => {
  // Already logged in
  await expect(page.locator('nav')).toBeVisible();
});
```

### API testing
```typescript
import { test, expect } from './fixtures/auth';
import { createApiHelpers } from './fixtures/api-helpers';

test('my test', async ({ authenticatedPage: page }) => {
  const api = createApiHelpers(page);
  
  const response = await api.waitForApiCall('/api/web/info', 'GET');
  expect(response.status()).toBe(200);
  
  const data = await api.getApiResponse('/api/web/libraries', 'GET');
  expect(data).toBeDefined();
});
```

## Debugging Tips

### Take screenshots
```typescript
await page.screenshot({ path: 'screenshot.png' });
```

### Wait for specific state
```typescript
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1000);
await page.waitForSelector('button[type="submit"]');
```

### Console logging
```typescript
page.on('console', msg => console.log('Browser:', msg.text()));
```

### Pause execution
```typescript
await page.pause(); // Opens inspector
```

## Selectors

### By role
```typescript
page.getByRole('button', { name: 'Submit' })
page.getByRole('textbox', { name: 'Email' })
```

### By text
```typescript
page.locator('text=Login')
page.locator('text=/login/i') // regex
```

### By test ID
```typescript
page.locator('[data-testid="my-element"]')
```

### By CSS
```typescript
page.locator('button[type="submit"]')
page.locator('.my-class')
page.locator('#my-id')
```

## Assertions

### Visibility
```typescript
await expect(page.locator('h1')).toBeVisible();
await expect(page.locator('h1')).not.toBeVisible();
```

### Text content
```typescript
await expect(page.locator('h1')).toHaveText('Welcome');
await expect(page.locator('h1')).toContainText('Welcome');
```

### Count
```typescript
await expect(page.locator('.item')).toHaveCount(5);
```

### Value
```typescript
await expect(page.locator('input')).toHaveValue('test');
```

### URL
```typescript
await expect(page).toHaveURL('/dashboard');
await expect(page).toHaveURL(/dashboard/);
```

## Best Practices

1. ✅ Use `baseURL` in config, then `page.goto('/')`
2. ✅ Use `data-testid` attributes for stable selectors
3. ✅ Wait for specific conditions, not fixed timeouts
4. ✅ Use fixtures for common setup (like auth)
5. ✅ Keep tests independent - no shared state
6. ✅ Use page object pattern for complex pages
7. ✅ Tag tests with `.skip()` for data-dependent tests
8. ✅ Capture screenshots/videos on failure
9. ✅ Test one thing per test
10. ✅ Use descriptive test names

## CI/CD Integration

### GitHub Actions example
```yaml
- name: Install dependencies
  run: npm ci
  
- name: Install Playwright Browsers
  run: npx playwright install --with-deps
  
- name: Run Playwright tests
  run: npx playwright test
  env:
    CI: true
    
- name: Upload test results
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: playwright-report
    path: playwright-report/
```

## Environment Variables

```bash
# Skip browser install
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Set browser
BROWSER=chromium

# Set base URL
PLAYWRIGHT_BASE_URL=http://localhost:8356

# Enable debug logging
DEBUG=pw:api
```

## Troubleshooting

### Tests timing out
- Increase timeout in test: `test.setTimeout(60000)`
- Check if server is running
- Look for network issues

### Selector not found
- Use `await page.pause()` to inspect
- Check if element is in shadow DOM
- Verify element actually exists in UI

### Flaky tests
- Add explicit waits
- Use `waitForLoadState('networkidle')`
- Check for race conditions
- Use `test.retry()` for known flaky tests

### Browser not launching
- Run `npx playwright install`
- Check system dependencies
- Verify no port conflicts
