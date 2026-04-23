import { test as base, Page } from '@playwright/test';


function resolveWebPassword(): string {
  const envPassword = process.env.E2E_WEB_PASSWORD;
  if (!envPassword) {
    throw new Error(
      'E2E_WEB_PASSWORD is required for Playwright authentication. Set E2E_WEB_PASSWORD before running the E2E suite.'
    );
  }

  return envPassword;
}

/**
 * Authentication helper for tests
 */
export async function login(page: Page, password: string = resolveWebPassword()) {
  const effectivePassword = password;

  await page.goto('/');
  await page.waitForSelector('input[type="password"]', { timeout: 5000 });
  await page.fill('input[type="password"]', effectivePassword);
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');

  const stillOnLogin = await page
    .locator('input[type="password"]')
    .isVisible({ timeout: 1000 })
    .catch(() => false);

  if (stillOnLogin) {
    throw new Error(
      'Web UI login failed. Verify that E2E_WEB_PASSWORD matches the configured Nomarr web password.'
    );
  }
}

/**
 * Test fixture that provides an authenticated page with API tracking
 */
export const test = base.extend<{ 
  authenticatedPage: Page;
  apiResponses: Map<string, any>;
}>({
  apiResponses: async ({ page }, use) => {
    const responses = new Map<string, any>();
    
    // Track all API responses
    page.on('response', async (response) => {
      const url = response.url();
      if (url.includes('/api/')) {
        const key = `${response.request().method()} ${url}`;
        try {
          const data = await response.json();
          responses.set(key, { status: response.status(), data, response });
        } catch {
          responses.set(key, { status: response.status(), response });
        }
      }
    });
    
    await use(responses);
  },
  
  authenticatedPage: async ({ page, apiResponses }, use) => {
    await login(page);
    await use(page);
  },
});

export { expect } from '@playwright/test';
