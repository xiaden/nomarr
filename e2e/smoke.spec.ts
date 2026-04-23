import { type APIResponse, type Page } from '@playwright/test';
import { authenticatedApiRequest } from './fixtures/api-helpers';
import { expect, test } from './fixtures/auth';

type JsonRecord = Record<string, unknown>;

type BrowserFetchResult = {
  status: number;
  body: unknown;
};

const navigationTabs = [
  { name: 'Libraries', selector: 'a:has-text("Libraries"), a:has-text("Library"), [href*="library"], [href*="libraries"]' },
  { name: 'Calibration', selector: 'a:has-text("Calibration"), [href*="calibration"]' },
  { name: 'Analytics', selector: 'a:has-text("Analytics"), a:has-text("Insights"), [href*="analytics"]' },
  { name: 'Metadata', selector: 'a:has-text("Metadata"), a:has-text("Browse"), [href*="metadata"]' },
  { name: 'Worker/Queue', selector: 'a:has-text("Worker"), a:has-text("Queue"), a:has-text("Processing"), [href*="worker"]' },
  { name: 'Settings/Config', selector: 'a:has-text("Settings"), a:has-text("Config"), [href*="settings"]' },
] as const;

function assertJsonObject(value: unknown, label: string): asserts value is JsonRecord {
  expect(value, `${label} should not be null`).not.toBeNull();
  expect(Array.isArray(value), `${label} should be a JSON object, not an array`).toBe(false);
  expect(typeof value, `${label} should be a JSON object`).toBe('object');
}

async function readJsonObject(response: APIResponse, label: string): Promise<JsonRecord> {
  expect(response.status(), `${label} should return HTTP 200`).toBe(200);
  const body: unknown = await response.json();
  assertJsonObject(body, label);
  return body;
}

function assertPublicInfoContract(body: JsonRecord): void {
  const config = body['config'];
  const models = body['models'];
  const queue = body['queue'];
  const worker = body['worker'];

  assertJsonObject(config, 'GET /api/v1/info config');
  assertJsonObject(models, 'GET /api/v1/info models');
  assertJsonObject(queue, 'GET /api/v1/info queue');
  assertJsonObject(worker, 'GET /api/v1/info worker');

  expect(typeof config['models_dir']).toBe('string');
  expect(typeof config['namespace']).toBe('string');
  expect(typeof models['total_heads']).toBe('number');
  expect(typeof queue['depth']).toBe('number');
  expect(typeof worker['enabled']).toBe('boolean');
}

function assertGpuHealthContract(body: JsonRecord): void {
  expect(typeof body['available']).toBe('boolean');
  expect(typeof body['monitor_healthy']).toBe('boolean');

  const errorSummary = body['error_summary'];
  expect(errorSummary === null || typeof errorSummary === 'string').toBe(true);
}

async function fetchJsonFromBrowser(page: Page, endpoint: string): Promise<BrowserFetchResult> {
  return await page.evaluate(async (path: string) => {
    const response = await fetch(path, { credentials: 'include' });
    const text = await response.text();

    let body: unknown = text;
    if (text.length > 0) {
      try {
        body = JSON.parse(text) as unknown;
      } catch {
        body = text;
      }
    } else {
      body = null;
    }

    return {
      status: response.status,
      body,
    };
  }, endpoint);
}

function startFrontendErrorTracking(page: Page): { consoleErrors: string[]; pageErrors: string[] } {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];

  page.on('console', msg => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
      console.error('🔴 Frontend error:', msg.text());
    }
  });

  page.on('pageerror', error => {
    pageErrors.push(error.message);
    console.error('🔴 Page exception:', error.message);
  });

  return { consoleErrors, pageErrors };
}

/**
 * Smoke coverage for startup health and core navigation.
 */
test.describe('Smoke Test - Startup and Core Navigation', () => {
  test('should report public app info via /api/v1/info', async ({ request }) => {
    const response = await request.get('/api/v1/info');
    const body = await readJsonObject(response, 'GET /api/v1/info');

    assertPublicInfoContract(body);
  });

  test('should report GPU health in degraded-or-available mode', async ({ authenticatedPage: page }) => {
    const responsePromise = authenticatedApiRequest(page, '/api/web/health/gpu');
    const browserFetchPromise = fetchJsonFromBrowser(page, '/api/web/health/gpu');

    const [response, browserFetch] = await Promise.all([responsePromise, browserFetchPromise]);
    expect(response.status(), 'GET /api/web/health/gpu should return HTTP 200').toBe(200);
    expect(browserFetch.status, 'Browser fetch for /api/web/health/gpu should return HTTP 200').toBe(200);

    assertJsonObject(browserFetch.body, 'GET /api/web/health/gpu response');
    assertGpuHealthContract(browserFetch.body);
  });

  test('should navigate through core tabs without critical frontend errors', async ({ authenticatedPage: page }) => {
    const { consoleErrors, pageErrors } = startFrontendErrorTracking(page);
    let visitedTabs = 0;

    for (const tab of navigationTabs) {
      const navItem = page.locator(tab.selector).first();
      const isVisible = await navItem.isVisible({ timeout: 3000 }).catch(() => false);

      if (!isVisible) {
        console.log(`⚠️ ${tab.name} tab not found in navigation - may not be implemented yet`);
        continue;
      }

      visitedTabs += 1;
      await navItem.click();
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});

      const hasErrorMessage = await page
        .locator('text=/error|failed|something went wrong/i')
        .isVisible({ timeout: 500 })
        .catch(() => false);

      expect(hasErrorMessage, `${tab.name} should load without an inline error message`).toBe(false);
    }

    expect(visitedTabs, 'At least one core navigation tab should be available').toBeGreaterThan(0);

    const criticalConsoleErrors = consoleErrors.filter(
      err => !err.includes('favicon') && !err.includes('404') && !err.includes('DevTools'),
    );
    const criticalPageErrors = pageErrors.filter(err => !err.includes('favicon') && !err.includes('404'));

    expect(criticalConsoleErrors, 'Should have no critical frontend console errors').toEqual([]);
    expect(criticalPageErrors, 'Should have no critical page exceptions').toEqual([]);
  });
});
