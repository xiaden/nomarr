import { execSync } from 'child_process';

import type { Locator, Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

import {
  authenticatedApiJson,
  authenticatedApiRequest,
  getWorkStatus,
  getWorkStatusTimeoutMs,
  waitForWorkStatus,
  waitForWorkStatusIdle,
  type WorkStatus,
} from './fixtures/api-helpers';
import { login } from './fixtures/auth';
import { createContainerFile, deleteContainerFile } from './fixtures/container-mutation';
import { TEST_LIBRARY_PATH } from './fixtures/test-library';

const TEST_LIBRARY_NAME = 'Playwright Fixture Library';
const LIBRARIES_NAV_SELECTOR = 'a:has-text("Libraries"), a:has-text("Library"), [href*="library"], [href*="libraries"]';
const DOCKER_CHECK_TIMEOUT_MS = 5000;

type WatchMode = 'event' | 'poll';

interface LibraryRecord {
  library_id: string;
  name: string;
  root_path: string;
  watch_mode: string;
  scanned_at: string | null;
}

interface LibraryListResponse {
  libraries: LibraryRecord[];
}

function getLibraryCard(page: Page): Locator {
  return page
    .locator('div')
    .filter({ has: page.getByRole('heading', { name: TEST_LIBRARY_NAME, exact: true }) })
    .filter({ hasText: TEST_LIBRARY_PATH })
    .first();
}

function isContainerMutationAvailable(): boolean {
  if (process.env.SKIP_CONTAINER_MUTATION) {
    return false;
  }

  try {
    execSync('docker version --format "{{.Server.Version}}"', {
      stdio: 'pipe',
      timeout: DOCKER_CHECK_TIMEOUT_MS,
    });
    return true;
  } catch {
    return false;
  }
}

function didWorkStatusChangeSinceBaseline(status: WorkStatus, baseline: WorkStatus): boolean {
  return status.is_busy
    || status.is_scanning !== baseline.is_scanning
    || status.is_processing !== baseline.is_processing
    || status.pending_files !== baseline.pending_files
    || status.processed_files !== baseline.processed_files
    || status.total_files !== baseline.total_files
    || status.scanning_libraries.length !== baseline.scanning_libraries.length
    || (status.pipeline_libraries?.length ?? 0) !== (baseline.pipeline_libraries?.length ?? 0);
}

function createMutationFilePath(prefix: string): string {
  return `${TEST_LIBRARY_PATH}/${prefix}-${Date.now()}.txt`;
}

async function verifyWatchModeDetectsMutation(page: Page, watchMode: WatchMode, prefix: string): Promise<void> {
  const baselineStatus = await waitForWorkStatusIdle(page, `${watchMode} mode idle baseline before container mutation`);
  const mutationFilePath = createMutationFilePath(prefix);
  const timeoutMs = getWorkStatusTimeoutMs();
  const mutationStartedAt = Date.now();
  let cleanupNeeded = false;

  try {
    createContainerFile(mutationFilePath, `${watchMode} mode container mutation ${mutationStartedAt}`);
    cleanupNeeded = true;

    const mutationStatus = await waitForWorkStatus(
      page,
      (status) => didWorkStatusChangeSinceBaseline(status, baselineStatus),
      `${watchMode} watch mode to detect container mutation`,
    );

    expect(Date.now() - mutationStartedAt).toBeLessThanOrEqual(timeoutMs);
    expect(
      didWorkStatusChangeSinceBaseline(mutationStatus, baselineStatus),
      `Expected ${watchMode} mode work status to change after mutating ${mutationFilePath}`,
    ).toBe(true);

    const settledStatus = await waitForWorkStatusIdle(page, `${watchMode} watch mode mutation processing to settle`);
    expect(settledStatus.is_busy).toBe(false);
  } finally {
    if (cleanupNeeded) {
      deleteContainerFile(mutationFilePath);
      await waitForWorkStatusIdle(page, `${watchMode} watch mode cleanup to settle`);
    }
  }
}

async function openLibrariesSection(page: Page): Promise<void> {
  const librariesNav = page.locator(LIBRARIES_NAV_SELECTOR).first();
  if (await librariesNav.isVisible({ timeout: 3000 }).catch(() => false)) {
    await librariesNav.click();
  }

  await expect(page.getByRole('heading', { name: 'Libraries' })).toBeVisible({ timeout: 10000 });
}

async function listLibraries(page: Page): Promise<LibraryRecord[]> {
  const response = await authenticatedApiJson<LibraryListResponse>(page, '/api/web/libraries');
  return response.libraries;
}

async function deleteExistingFixtureLibraries(page: Page): Promise<void> {
  const libraries = await listLibraries(page);
  const existingLibraries = libraries.filter(
    (library) => library.name === TEST_LIBRARY_NAME || library.root_path === TEST_LIBRARY_PATH,
  );

  for (const library of existingLibraries) {
    const response = await authenticatedApiRequest(page, `/api/web/libraries/${library.library_id}`, {
      method: 'DELETE',
    });
    expect(response.ok(), `Expected DELETE /api/web/libraries/${library.library_id} to succeed`).toBe(true);
  }
}

async function createFreshLibrary(page: Page): Promise<Locator> {
  await deleteExistingFixtureLibraries(page);
  await openLibrariesSection(page);

  await page.getByRole('button', { name: '+ Add Library' }).click();
  await expect(page.getByText('Create Library')).toBeVisible();

  await page.getByPlaceholder('Auto-generated from path if left empty').fill(TEST_LIBRARY_NAME);
  await page.getByPlaceholder('/music').fill(TEST_LIBRARY_PATH);
  await page.getByRole('button', { name: 'Create' }).click();

  const libraryCard = getLibraryCard(page);
  await expect(libraryCard).toBeVisible({ timeout: 10000 });
  await expect(libraryCard).toContainText(TEST_LIBRARY_PATH);
  return libraryCard;
}

async function openLibraryEditor(page: Page, libraryCard: Locator): Promise<void> {
  await libraryCard.getByRole('button', { name: 'Edit' }).click();
  await expect(page.getByText('Edit Library')).toBeVisible({ timeout: 10000 });
}

async function setWatchModeViaUi(page: Page, libraryCard: Locator, watchMode: WatchMode): Promise<void> {
  const watchModeLabel = watchMode === 'event' ? 'Event' : 'Poll';

  await openLibraryEditor(page, libraryCard);
  await page.getByLabel('File Watching').click();
  await page.getByRole('option', { name: new RegExp(`^${watchModeLabel}$`) }).click();
  await page.getByRole('button', { name: 'Update' }).click();

  await expect(page.getByText(`File watching mode changed to ${watchMode}`)).toBeVisible({ timeout: 10000 });
  await expect(getLibraryCard(page).getByText(watchModeLabel, { exact: true }).first()).toBeVisible({ timeout: 10000 });
  await waitForWorkStatusIdle(page, `${watchMode} watch mode update to settle`);
}

async function runFullScanAndWaitForCompletion(page: Page, libraryCard: Locator): Promise<void> {
  const fullScanButton = libraryCard.getByRole('button', { name: 'Full Scan' });
  await expect(fullScanButton).toBeEnabled();
  await fullScanButton.click();

  await waitForWorkStatusIdle(page, 'full library scan to complete');
  await expect(getLibraryCard(page).getByRole('button', { name: 'Quick Scan' })).toBeEnabled({ timeout: 10000 });
}

async function assertQuickScanDisabledBeforeFirstFullScan(page: Page): Promise<void> {
  const quickScanButton = getLibraryCard(page).getByRole('button', { name: 'Quick Scan' });
  await expect(quickScanButton).toBeDisabled();
  await expect(quickScanButton).toHaveAttribute('title', /Run a Full Scan first/i);
}

test.describe('Library Integration Tests', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await openLibrariesSection(page);
  });

  test('1. should add library successfully using the canonical container fixture path', async ({ page }) => {
    const libraryCard = await createFreshLibrary(page);

    await expect(libraryCard).toContainText(TEST_LIBRARY_NAME);
    await expect(libraryCard).toContainText(TEST_LIBRARY_PATH);
  });

  test('2. should have quick scan disabled before the first full scan', async ({ page }) => {
    await createFreshLibrary(page);
    await assertQuickScanDisabledBeforeFirstFullScan(page);
  });

  test('3. should complete a full scan using bounded work-status polling', async ({ page }) => {
    const libraryCard = await createFreshLibrary(page);

    await runFullScanAndWaitForCompletion(page, libraryCard);

    const workStatus = await getWorkStatus(page);
    expect(workStatus.is_busy).toBe(false);
    await expect(getLibraryCard(page).getByRole('button', { name: 'Quick Scan' })).toBeEnabled();
  });

  test('4. should switch to event-based file watching through the UI', async ({ page }) => {
    const libraryCard = await createFreshLibrary(page);

    await setWatchModeViaUi(page, libraryCard, 'event');

    await expect(getLibraryCard(page)).toContainText('File Watching:');
    await expect(getLibraryCard(page).getByText('Event', { exact: true }).first()).toBeVisible();
  });

  test('5. should detect an in-container file mutation while event mode is active', async ({ page }) => {
    test.skip(Boolean(process.env.SKIP_CONTAINER_MUTATION), 'Container mutation not available');
    test.skip(!isContainerMutationAvailable(), 'Docker CLI not available for container mutation');

    const libraryCard = await createFreshLibrary(page);

    await runFullScanAndWaitForCompletion(page, libraryCard);
    await setWatchModeViaUi(page, getLibraryCard(page), 'event');
    await verifyWatchModeDetectsMutation(page, 'event', 'e2e-mutation-test-event');

    await expect(getLibraryCard(page).getByText('Event', { exact: true }).first()).toBeVisible();
  });

  test('6. should switch to polling mode through the UI', async ({ page }) => {
    const libraryCard = await createFreshLibrary(page);

    await setWatchModeViaUi(page, libraryCard, 'poll');

    await expect(getLibraryCard(page)).toContainText('File Watching:');
    await expect(getLibraryCard(page).getByText('Poll', { exact: true }).first()).toBeVisible();
  });

  test('7. should detect an in-container file mutation while polling mode is active', async ({ page }) => {
    test.skip(Boolean(process.env.SKIP_CONTAINER_MUTATION), 'Container mutation not available');
    test.skip(!isContainerMutationAvailable(), 'Docker CLI not available for container mutation');

    const libraryCard = await createFreshLibrary(page);

    await runFullScanAndWaitForCompletion(page, libraryCard);
    await setWatchModeViaUi(page, getLibraryCard(page), 'poll');
    await verifyWatchModeDetectsMutation(page, 'poll', 'e2e-mutation-test-poll');

    await expect(getLibraryCard(page).getByText('Poll', { exact: true }).first()).toBeVisible();
  });
});
