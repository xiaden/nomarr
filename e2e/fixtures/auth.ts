import { test as base, Page } from '@playwright/test';

/**
 * Authentication helper for tests
 */
export async function login(page: Page, password: string = 'nomarr') {
  await page.goto('/');
  await page.waitForSelector('input[type="password"]', { timeout: 5000 });
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');
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
