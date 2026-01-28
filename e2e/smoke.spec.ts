import { expect, test } from './fixtures/docker-logs';

/**
 * Comprehensive smoke test: Navigate through all application tabs
 * Verify each section loads without frontend or backend errors
 */
test.describe('Smoke Test - Full Application Navigation', () => {
  test('should navigate through all tabs without errors', async ({ page, dockerLogs }) => {
    // Login first
    console.log('🔐 Logging in...');
    await page.goto('http://localhost:8356');
    await page.waitForSelector('input[type="password"]', { timeout: 5000 });
    await page.fill('input[type="password"]', 'nomarr');
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle');
    
    // Track console errors
    const consoleErrors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
        console.error('🔴 Frontend error:', msg.text());
      }
    });
    
    // Track uncaught exceptions
    const pageErrors: string[] = [];
    page.on('pageerror', error => {
      pageErrors.push(error.message);
      console.error('🔴 Page exception:', error.message);
    });
    
    dockerLogs.clearErrors();
    
    // Define all tabs to navigate through
    const tabs = [
      { name: 'Libraries', selector: 'text=/libraries/i, [href*="library"], [href*="libraries"]' },
      { name: 'Calibration', selector: 'text=/calibration/i, [href*="calibration"]' },
      { name: 'Analytics', selector: 'text=/analytics/i, text=/insights/i, [href*="analytics"]' },
      { name: 'Metadata', selector: 'text=/metadata/i, text=/browse/i, [href*="metadata"]' },
      { name: 'Worker/Queue', selector: 'text=/worker/i, text=/queue/i, text=/processing/i, [href*="worker"]' },
      { name: 'Settings/Config', selector: 'text=/settings/i, text=/config/i, [href*="settings"]' }
    ];
    
    console.log('\n🚀 Starting full application navigation test...\n');
    
    for (const tab of tabs) {
      console.log(`📑 Navigating to ${tab.name}...`);
      
      // Find and click the tab/nav item
      const navItem = page.locator(tab.selector).first();
      const isVisible = await navItem.isVisible({ timeout: 3000 }).catch(() => false);
      
      if (!isVisible) {
        console.log(`⚠️  ${tab.name} tab not found in navigation - may not be implemented yet`);
        continue;
      }
      
      await navItem.click();
      
      // Wait for content to load
      await page.waitForTimeout(1000);
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
      
      // Verify page loaded (check for body content, not error messages)
      const hasErrorMessage = await page.locator('text=/error|failed|something went wrong/i').isVisible({ timeout: 500 }).catch(() => false);
      
      if (hasErrorMessage) {
        console.error(`❌ ${tab.name} page shows error message`);
      } else {
        console.log(`✅ ${tab.name} loaded successfully`);
      }
      
      expect(hasErrorMessage).toBe(false);
    }
    
    console.log('\n📊 Test Summary:');
    console.log(`Frontend console errors: ${consoleErrors.length}`);
    console.log(`Page exceptions: ${pageErrors.length}`);
    console.log(`Backend errors: ${dockerLogs.getErrors().length}`);
    
    // Filter out known benign errors
    const criticalConsoleErrors = consoleErrors.filter(err => 
      !err.includes('favicon') && 
      !err.includes('404') &&
      !err.includes('DevTools')
    );
    
    const criticalPageErrors = pageErrors.filter(err =>
      !err.includes('favicon') &&
      !err.includes('404')
    );
    
    const criticalBackendErrors = dockerLogs.getErrors().filter(err =>
      !err.includes('favicon') &&
      !err.includes('404')
    );
    
    // Assert no critical errors occurred
    if (criticalConsoleErrors.length > 0) {
      console.error('❌ Critical frontend console errors:', criticalConsoleErrors);
    }
    if (criticalPageErrors.length > 0) {
      console.error('❌ Critical page exceptions:', criticalPageErrors);
    }
    if (criticalBackendErrors.length > 0) {
      console.error('❌ Critical backend errors:', criticalBackendErrors);
    }
    
    expect(criticalConsoleErrors.length, 'Should have no critical frontend console errors').toBe(0);
    expect(criticalPageErrors.length, 'Should have no critical page exceptions').toBe(0);
    expect(criticalBackendErrors.length, 'Should have no critical backend errors').toBe(0);
    
    console.log('\n✅ All tabs navigated successfully without critical errors');
  });
});
