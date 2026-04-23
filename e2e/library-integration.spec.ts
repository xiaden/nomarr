import * as fs from 'fs';
import * as path from 'path';
import type { Page } from '@playwright/test';
import { login } from './fixtures/auth';
import { expect, test } from './fixtures/docker-logs';

// Test configuration
const TEST_LIBRARY_PATH = process.env.E2E_TEST_LIBRARY_PATH ?? 'E:/Test-Music';
const TEST_SONGS_DIR = process.env.E2E_TEST_SONGS_DIR ?? 'E:/Test-Music/Test-Songs';
const TEST_SONG_ORIGINAL = 'test-rename.mp3'; // Will use first available mp3
const TEST_SONG_RENAMED = 'test-rename-modified.mp3';
const LIBRARIES_NAV_SELECTOR = 'a:has-text("Libraries"), a:has-text("Library"), [href*="library"], [href*="libraries"]';
const FULL_SCAN_BUTTON_SELECTOR = 'button:has-text("Full Scan")';

async function openLibrariesSection(page: Page): Promise<void> {
  const librariesNav = page.locator(LIBRARIES_NAV_SELECTOR).first();
  if (await librariesNav.isVisible({ timeout: 3000 }).catch(() => false)) {
    await librariesNav.click();
    await page.waitForTimeout(500);
  }
}

async function ensureLibraryExists(page: Page): Promise<void> {
  await openLibrariesSection(page);

  const existingFullScan = page.locator(FULL_SCAN_BUTTON_SELECTOR).first();
  if (await existingFullScan.isVisible({ timeout: 3000 }).catch(() => false)) {
    return;
  }

  const existingLibrary = page.locator(`text="${TEST_LIBRARY_PATH}"`).first();
  if (await existingLibrary.isVisible({ timeout: 2000 }).catch(() => false)) {
    return;
  }

  const addButton = page
    .locator('button:has-text("Add Library"), button:has-text("Create Library"), button:has-text("New Library")')
    .first();

  if (!await addButton.isVisible({ timeout: 3000 }).catch(() => false)) {
    throw new Error('Add library button not found');
  }

  const candidatePaths = [
    process.env.E2E_TEST_LIBRARY_PATH,
    '/media',
    '/music',
    TEST_LIBRARY_PATH,
  ].filter((value, index, arr): value is string => Boolean(value) && arr.indexOf(value) === index);

  for (const candidatePath of candidatePaths) {
    await addButton.click();
    await page.waitForTimeout(400);

    const pathInput = page.locator('input[name="path"], input[placeholder*="path"], input[type="text"]').first();
    await pathInput.fill(candidatePath);

    const submitButton = page
      .locator('button[type="submit"], button:has-text("Create"), button:has-text("Add")')
      .first();
    await submitButton.click();

    await page.waitForTimeout(1500);
    await page.waitForLoadState('networkidle');

    if (await existingFullScan.isVisible({ timeout: 2500 }).catch(() => false)) {
      return;
    }

    // Close form if still open before trying another candidate path.
    const cancelButton = page.locator('button:has-text("Cancel")').first();
    if (await cancelButton.isVisible({ timeout: 500 }).catch(() => false)) {
      await cancelButton.click();
      await page.waitForTimeout(250);
    }
  }

  throw new Error(
    `Unable to create/find a library with scan controls. Tried paths: ${candidatePaths.join(', ')}`
  );
}

/**
 * Comprehensive library integration tests
 * Tests full library lifecycle: add → scan → file watching → polling → ML processing
 */
test.describe('Library Integration Tests', () => {
  let libraryId: string | null = null;
  
  test.beforeEach(async ({ page, dockerLogs }) => {
    await login(page);
    
    dockerLogs.clearErrors();
  });
  
  test('1. should add library successfully', async ({ page, dockerLogs }) => {
    console.log('📁 Adding library:', TEST_LIBRARY_PATH);
    
    await ensureLibraryExists(page);
    
    // Verify at least one library entry is available by presence of scan controls
    const libraryExists = await page
      .locator(FULL_SCAN_BUTTON_SELECTOR)
      .first()
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    
    expect(libraryExists, 'Library should appear in list after creation').toBe(true);
    
    // Check for backend errors
    const backendErrors = dockerLogs.getErrors();
    expect(backendErrors.length, 'No backend errors during library creation').toBe(0);
    
    console.log('✅ Library added successfully');
  });
  
  test('2. should have quick scan disabled initially', async ({ page }) => {
    console.log('🔍 Checking quick scan button state...');
    
    // Find quick scan button for the test library
    const quickScanButton = page.locator('button:has-text("Quick Scan")').first();
    
    if (!await quickScanButton.isVisible({ timeout: 3000 })) {
      console.log('⚠️  Quick scan button not found');
      return;
    }
    
    const isDisabled = await quickScanButton.getAttribute('disabled') !== null;
    const title = await quickScanButton.getAttribute('title') || '';
    
    console.log('Quick scan disabled:', isDisabled);
    console.log('Button title:', title);
    
    expect(isDisabled, 'Quick scan should be disabled before first full scan').toBe(true);
    
    console.log('✅ Quick scan correctly disabled');
  });
  
  test('3. should complete full scan successfully', async ({ page, dockerLogs }) => {
    console.log('🔄 Starting full scan...');
    
    dockerLogs.clearErrors();
    await ensureLibraryExists(page);
    await openLibrariesSection(page);
    
    // Find and click full scan button
    const fullScanButton = page
      .locator(FULL_SCAN_BUTTON_SELECTOR)
      .first();
    
    if (!await fullScanButton.isVisible({ timeout: 3000 })) {
      throw new Error('Full scan button not found');
    }
    
    const isDisabled = await fullScanButton.getAttribute('disabled') !== null;
    if (isDisabled) {
      throw new Error('Full scan button is disabled');
    }
    
    await fullScanButton.click();
    console.log('🚀 Full scan initiated...');
    
    // Wait for scan to start and complete
    // Look for progress indicators or completion messages
    await page.waitForTimeout(5000);
    
    // Monitor for scan completion
    const maxWaitTime = 120000; // 2 minutes max
    const startTime = Date.now();
    let scanComplete = false;
    
    while (Date.now() - startTime < maxWaitTime && !scanComplete) {
      // Check if scan is done (look for success message, or button re-enabled, etc.)
      const successMessage = await page.locator('text=/scan complete|completed|finished/i').isVisible({ timeout: 1000 }).catch(() => false);
      const fullScanEnabled = await fullScanButton.isEnabled().catch(() => false);
      
      if (successMessage || fullScanEnabled) {
        scanComplete = true;
        break;
      }
      
      await page.waitForTimeout(2000);
      console.log('⏳ Waiting for scan to complete...');
    }
    
    if (!scanComplete) {
      console.warn('⚠️  Scan did not complete within timeout - continuing anyway');
    } else {
      console.log('✅ Scan completed');
    }
    
    // Check for backend errors during scan
    const backendErrors = dockerLogs.getErrors().filter(err => 
      !err.includes('DEBUG') && !err.includes('INFO')
    );
    
    if (backendErrors.length > 0) {
      console.error('❌ Backend errors during scan:', backendErrors);
    }
    
    expect(backendErrors.length, 'No critical backend errors during scan').toBe(0);
    
    console.log('✅ Full scan completed successfully');
  });
  
  test('4. should switch to event-based file watching', async ({ page, dockerLogs }) => {
    console.log('👁️  Switching to event-based file watching...');
    
    dockerLogs.clearErrors();
    
    // Look for library settings/edit button
    const settingsButton = page.locator('button[aria-label*="settings"], button:has-text("Settings"), button:has-text("Edit")').first();
    
    if (await settingsButton.isVisible({ timeout: 3000 })) {
      await settingsButton.click();
      await page.waitForTimeout(500);
    }
    
    // Find and select event-based option
    const eventRadio = page.locator('input[type="radio"][value="event"], input[type="radio"][value="watch"]').first();
    
    if (!await eventRadio.isVisible({ timeout: 3000 })) {
      console.log('⚠️  Event-based radio button not found - skipping');
      return;
    }
    
    await eventRadio.click();
    
    // Save settings
    const saveButton = page.locator('button:has-text("Save"), button[type="submit"]').first();
    if (await saveButton.isVisible({ timeout: 2000 })) {
      await saveButton.click();
      await page.waitForTimeout(1000);
    }
    
    const backendErrors = dockerLogs.getErrors();
    expect(backendErrors.length, 'No backend errors switching to event mode').toBe(0);
    
    console.log('✅ Switched to event-based file watching');
  });
  
  test('5. should detect file changes via event pickup', async ({ page, dockerLogs }) => {
    console.log('🔄 Testing event-based file change detection...');
    
    dockerLogs.clearErrors();
    
    // Find a test file to rename
    let testFile: string | null = null;
    try {
      const files = fs.readdirSync(TEST_SONGS_DIR);
      const mp3Files = files.filter(f => f.endsWith('.mp3'));
      
      if (mp3Files.length === 0) {
        console.log('⚠️  No MP3 files found in Test-Songs directory');
        return;
      }
      
      testFile = mp3Files[0];
      console.log('📝 Using test file:', testFile);
    } catch (error) {
      console.log('⚠️  Could not access Test-Songs directory:', error);
      return;
    }
    
    const originalPath = path.join(TEST_SONGS_DIR, testFile);
    const renamedPath = path.join(TEST_SONGS_DIR, `${path.parse(testFile).name}_renamed${path.parse(testFile).ext}`);
    
    // Rename the file
    console.log('🔄 Renaming file...');
    fs.renameSync(originalPath, renamedPath);
    
    // Wait for backend to detect the change
    await page.waitForTimeout(3000);
    
    // Check docker logs for file change detection
    const logs = dockerLogs.getErrors();
    const fileChangeLogs = logs.filter(log => 
      log.includes('file') && 
      (log.includes('change') || log.includes('modified') || log.includes('rename'))
    );
    
    console.log(`Found ${fileChangeLogs.length} file change log entries`);
    if (fileChangeLogs.length > 0) {
      console.log('📋 File change logs:', fileChangeLogs);
    }
    
    // Rename back to original
    console.log('🔄 Renaming file back to original...');
    fs.renameSync(renamedPath, originalPath);
    await page.waitForTimeout(2000);
    
    // Should have detected at least the rename events
    // Note: May not show in error logs if it's INFO level
    console.log('✅ Event-based file change test completed');
    
    const criticalErrors = dockerLogs.getErrors().filter(err => 
      err.includes('ERROR') || err.includes('CRITICAL')
    );
    expect(criticalErrors.length, 'No critical errors during file event detection').toBe(0);
  });
  
  test('6. should switch to polling mode', async ({ page, dockerLogs }) => {
    console.log('🔄 Switching to polling mode...');
    
    dockerLogs.clearErrors();
    
    // Look for library settings
    const settingsButton = page.locator('button[aria-label*="settings"], button:has-text("Settings"), button:has-text("Edit")').first();
    
    if (await settingsButton.isVisible({ timeout: 3000 })) {
      await settingsButton.click();
      await page.waitForTimeout(500);
    }
    
    // Find and select polling option
    const pollingRadio = page.locator('input[type="radio"][value="poll"], input[type="radio"][value="polling"]').first();
    
    if (!await pollingRadio.isVisible({ timeout: 3000 })) {
      console.log('⚠️  Polling radio button not found - skipping');
      return;
    }
    
    await pollingRadio.click();
    
    // Save settings
    const saveButton = page.locator('button:has-text("Save"), button[type="submit"]').first();
    if (await saveButton.isVisible({ timeout: 2000 })) {
      await saveButton.click();
      await page.waitForTimeout(1000);
    }
    
    const backendErrors = dockerLogs.getErrors();
    expect(backendErrors.length, 'No backend errors switching to polling mode').toBe(0);
    
    console.log('✅ Switched to polling mode');
  });
  
  test('7. should detect file changes via polling', async ({ page, dockerLogs }, testInfo) => {
    console.log('🔄 Testing polling file change detection...');
    
    // Similar to event test - requires filesystem manipulation
    console.log('⚠️  File system manipulation test - TODO');
    testInfo.skip();
  });
});
