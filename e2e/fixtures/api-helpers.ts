import { type APIResponse, Page, expect } from '@playwright/test';

const DEFAULT_API_TIMEOUT_MS = 30000;
const DEFAULT_WORK_STATUS_POLL_MS = 2000;
const DEFAULT_WORK_STATUS_TIMEOUT_MS = 60000;
const WORK_STATUS_PATH = '/api/web/work-status';

type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

export interface ScanningLibrary {
  library_id: string;
  name: string;
  progress: number;
  total: number;
}

export interface PipelineLibrary {
  library_id: string;
  name: string;
  state: string;
  library_auto_write: boolean;
}

export interface WorkStatus {
  is_scanning: boolean;
  scanning_libraries: ScanningLibrary[];
  pipeline_libraries?: PipelineLibrary[];
  is_processing: boolean;
  pending_files: number;
  processed_files: number;
  total_files: number;
  files_per_minute: number;
  estimated_minutes_remaining: number | null;
  is_busy: boolean;
}

function parsePositiveIntegerEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function getWorkStatusPollMs(): number {
  return parsePositiveIntegerEnv(process.env.E2E_WORK_STATUS_POLL_MS, DEFAULT_WORK_STATUS_POLL_MS);
}

export function getWorkStatusTimeoutMs(): number {
  return parsePositiveIntegerEnv(process.env.E2E_WORK_STATUS_TIMEOUT_MS, DEFAULT_WORK_STATUS_TIMEOUT_MS);
}

async function getSessionToken(page: Page): Promise<string> {
  const sessionToken = await page.evaluate(() => window.localStorage.getItem('nomarr_session_token'));

  if (!sessionToken) {
    throw new Error('Missing Nomarr session token in localStorage. Call login(page) before using authenticated API helpers.');
  }

  return sessionToken;
}

export async function authenticatedApiRequest(
  page: Page,
  path: string,
  options: { method?: HttpMethod; data?: unknown } = {},
): Promise<APIResponse> {
  const sessionToken = await getSessionToken(page);
  const method = options.method ?? 'GET';

  const headers: Record<string, string> = {
    Authorization: `Bearer ${sessionToken}`,
  };

  if (options.data !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  return page.request.fetch(path, {
    method,
    headers,
    data: options.data,
    timeout: DEFAULT_API_TIMEOUT_MS,
  });
}

export async function authenticatedApiJson<T>(
  page: Page,
  path: string,
  options: { method?: HttpMethod; data?: unknown } = {},
): Promise<T> {
  const method = options.method ?? 'GET';
  const response = await authenticatedApiRequest(page, path, options);
  const responseText = await response.text();

  expect(
    response.ok(),
    `Expected ${method} ${path} to succeed, got ${response.status()} ${responseText}`,
  ).toBe(true);

  if (!responseText.trim()) {
    return undefined as T;
  }

  return JSON.parse(responseText) as T;
}

/**
 * API response helper for asserting page-driven API calls.
 */
export class ApiHelpers {
  constructor(private page: Page) {}

  /**
   * Wait for a specific API call and return the response.
   * Set up listener BEFORE navigating or triggering actions.
   */
  async waitForApiCall(urlPattern: string | RegExp, method: HttpMethod = 'GET') {
    const response = await this.page.waitForResponse(
      (resp) => {
        const matchesUrl = typeof urlPattern === 'string'
          ? resp.url().includes(urlPattern)
          : urlPattern.test(resp.url());
        return matchesUrl && resp.request().method() === method;
      },
      { timeout: DEFAULT_API_TIMEOUT_MS },
    );
    return response;
  }

  /**
   * Wait for API call and assert it succeeded.
   */
  async assertApiSuccess(urlPattern: string | RegExp, method: HttpMethod = 'GET') {
    const response = await this.waitForApiCall(urlPattern, method);
    expect(response.status()).toBeLessThan(400);
    return response;
  }

  /**
   * Wait for API call and get JSON response.
   */
  async getApiResponse<T = unknown>(urlPattern: string | RegExp, method: HttpMethod = 'GET'): Promise<T> {
    const response = await this.waitForApiCall(urlPattern, method);
    return await response.json() as T;
  }
}

export async function getWorkStatus(page: Page): Promise<WorkStatus> {
  return authenticatedApiJson<WorkStatus>(page, WORK_STATUS_PATH);
}

export async function waitForWorkStatus(
  page: Page,
  predicate: (status: WorkStatus) => boolean,
  description: string,
): Promise<WorkStatus> {
  const timeoutMs = getWorkStatusTimeoutMs();
  const pollMs = getWorkStatusPollMs();
  const deadline = Date.now() + timeoutMs;
  let lastStatus: WorkStatus | null = null;

  while (Date.now() <= deadline) {
    lastStatus = await getWorkStatus(page);
    if (predicate(lastStatus)) {
      return lastStatus;
    }

    await page.waitForTimeout(pollMs);
  }

  const lastStatusSummary = lastStatus ? JSON.stringify(lastStatus) : 'no status received';
  throw new Error(`Timed out after ${timeoutMs}ms waiting for ${description}. Last work status: ${lastStatusSummary}`);
}

export async function waitForWorkStatusIdle(
  page: Page,
  description = 'Nomarr work to become idle',
): Promise<WorkStatus> {
  return waitForWorkStatus(page, (status) => !status.is_busy, description);
}

/**
 * Create API helpers for a page.
 */
export function createApiHelpers(page: Page) {
  return new ApiHelpers(page);
}
