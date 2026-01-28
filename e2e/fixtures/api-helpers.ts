import { Page, expect } from '@playwright/test';

/**
 * API response helper for asserting API calls
 */
export class ApiHelpers {
  constructor(private page: Page) {}

  /**
   * Wait for a specific API call and return the response
   * Set up listener BEFORE navigating or triggering actions
   */
  async waitForApiCall(urlPattern: string | RegExp, method: 'GET' | 'POST' | 'PATCH' | 'DELETE' = 'GET') {
    const response = await this.page.waitForResponse(
      resp => {
        const matchesUrl = typeof urlPattern === 'string' 
          ? resp.url().includes(urlPattern)
          : urlPattern.test(resp.url());
        return matchesUrl && resp.request().method() === method;
      },
      { timeout: 30000 }
    );
    return response;
  }

  /**
   * Wait for API call and assert it succeeded
   */
  async assertApiSuccess(urlPattern: string | RegExp, method: 'GET' | 'POST' | 'PATCH' | 'DELETE' = 'GET') {
    const response = await this.waitForApiCall(urlPattern, method);
    expect(response.status()).toBeLessThan(400);
    return response;
  }

  /**
   * Wait for API call and get JSON response
   */
  async getApiResponse<T = any>(urlPattern: string | RegExp, method: 'GET' | 'POST' | 'PATCH' | 'DELETE' = 'GET'): Promise<T> {
    const response = await this.waitForApiCall(urlPattern, method);
    return await response.json();
  }
}

/**
 * Create API helpers for a page
 */
export function createApiHelpers(page: Page) {
  return new ApiHelpers(page);
}
