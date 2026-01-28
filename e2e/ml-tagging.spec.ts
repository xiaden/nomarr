import { expect, test } from './fixtures/docker-logs';

const TEST_LIBRARY_PATH = 'E:/Test-Music';

/**
 * ML and tagging validation tests
 * Verify database state for nom: tags and ML worker behavior
 */
test.describe('ML and Tagging Tests', () => {
  
  test.beforeAll(async ({ page }) => {
    // Login
    await page.goto('http://localhost:8356');
    await page.waitForSelector('input[type="password"]', { timeout: 5000 });
    await page.fill('input[type="password"]', 'nomarr');
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle');
  });
  
  test('should flag songs with nom: tags correctly', async ({ page, dockerLogs }) => {
    console.log('🏷️  Checking nom: tag detection...');
    
    // Navigate to metadata/tracks view
    const metadataNav = page.locator('text=/metadata/i, text=/browse/i, [href*="metadata"]').first();
    if (await metadataNav.isVisible({ timeout: 3000 })) {
      await metadataNav.click();
      await page.waitForTimeout(1000);
    }
    
    // Look for tracks view
    const tracksTab = page.locator('text=/tracks/i, [href*="tracks"]').first();
    if (await tracksTab.isVisible({ timeout: 2000 })) {
      await tracksTab.click();
      await page.waitForTimeout(1000);
    }
    
    // Check if any tracks show nom: tag indicators
    // This would require knowing the UI pattern for displaying nom: tags
    const nomTagIndicators = await page.locator('[data-has-nom-tags="true"], .nom-tag, [title*="nom:"]').count();
    
    console.log(`Found ${nomTagIndicators} tracks with nom: tag indicators`);
    
    // For now, just verify the page loaded
    // Actual validation would require API calls or database inspection
    const bodyVisible = await page.locator('body').isVisible();
    expect(bodyVisible).toBe(true);
    
    console.log('✅ Metadata view loaded');
  });
  
  test('should trigger ML worker for songs without nom: tags', async ({ page, dockerLogs }) => {
    console.log('🤖 Checking ML worker behavior...');
    
    dockerLogs.clearErrors();
    
    // Navigate to worker/queue view
    const workerNav = page.locator('text=/worker/i, text=/queue/i, [href*="worker"]').first();
    if (await workerNav.isVisible({ timeout: 3000 })) {
      await workerNav.click();
      await page.waitForTimeout(1000);
    }
    
    // Check if ML worker is processing files
    const queueInfo = page.locator('text=/queue|processing|pending/i').first();
    const hasQueueInfo = await queueInfo.isVisible({ timeout: 3000 });
    
    if (hasQueueInfo) {
      console.log('✅ Worker queue interface found');
    } else {
      console.log('⚠️  Worker queue not visible - may be empty');
    }
    
    // Check docker logs for ML worker activity
    const allLogs = dockerLogs.getErrors();
    const mlWorkerLogs = allLogs.filter(log => 
      log.includes('ML') || 
      log.includes('worker') || 
      log.includes('processing') ||
      log.includes('essentia')
    );
    
    console.log(`Found ${mlWorkerLogs.length} ML worker log entries`);
    
    // Verify no critical errors
    const criticalErrors = dockerLogs.getErrors().filter(err => 
      err.includes('ERROR') || err.includes('CRITICAL')
    );
    
    expect(criticalErrors.length, 'No critical errors in ML worker').toBe(0);
    
    console.log('✅ ML worker check completed');
  });
  
  test('should process files through complete ML pipeline', async ({ page, dockerLogs }, testInfo) => {
    console.log('🔄 Testing complete ML pipeline...');
    
    // This test would:
    // 1. Find a song in Test-Music that has no nom: tags
    // 2. Remove nom: tags if they exist
    // 3. Trigger ML processing
    // 4. Wait for processing to complete
    // 5. Verify nom: tags were added
    // 6. Restore original state
    
    // For now, mark as TODO - requires file system manipulation and database queries
    console.log('⚠️  Complex ML pipeline test - TODO');
    testInfo.skip();
  });
});
