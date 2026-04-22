import { test as base, Page } from '@playwright/test';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);
let cachedDiscoveredPassword: Promise<string | null> | null = null;

async function discoverFirstRunPasswordFromDockerLogs(): Promise<string | null> {
  try {
    const { stdout: containerStdout } = await execAsync('docker ps --filter "name=nomarr" --format "{{.Names}}"', {
      timeout: 10_000,
    });

    const containerName = containerStdout.trim().split('\n')[0];
    if (!containerName) {
      return null;
    }

    const { stdout: logs } = await execAsync(`docker logs --since 24h ${containerName} 2>&1`, {
      timeout: 10_000,
      maxBuffer: 4 * 1024 * 1024,
    });

    const lines = logs.split(/\r?\n/);
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      if (!lines[i].includes('AUTO-GENERATED ADMIN PASSWORD')) {
        continue;
      }

      for (let j = i + 1; j < Math.min(i + 6, lines.length); j += 1) {
        const match = lines[j].match(/\[KeyManagement\]\s+([^\s]+)\s*$/);
        const candidate = match?.[1]?.trim();
        if (candidate && candidate.length >= 16) {
          return candidate;
        }
      }
    }
  } catch {
    return null;
  }

  return null;
}

async function resolveWebPassword(defaultPassword: string): Promise<string> {
  const envPassword = process.env.E2E_WEB_PASSWORD ?? process.env.NOMARR_WEB_PASSWORD;
  if (envPassword) {
    return envPassword;
  }

  if (!cachedDiscoveredPassword) {
    cachedDiscoveredPassword = discoverFirstRunPasswordFromDockerLogs();
  }

  const discovered = await cachedDiscoveredPassword;
  if (discovered) {
    return discovered;
  }

  return defaultPassword;
}

/**
 * Authentication helper for tests
 */
export async function login(page: Page, password: string = 'nomarr') {
  const effectivePassword = await resolveWebPassword(password);

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
      'Web UI login failed. E2E tries E2E_WEB_PASSWORD/NOMARR_WEB_PASSWORD, then Docker first-run log discovery, then default nomarr. If this is not a fresh first-run container or logs are unavailable, set E2E_WEB_PASSWORD explicitly.'
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
