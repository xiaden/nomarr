/**
 * Take screenshots of all Nomarr pages for README documentation.
 * Run: node scripts/take-screenshots.mjs
 */

import { chromium } from "playwright";
import { mkdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCREENSHOT_DIR = join(__dirname, "..", "docs", "screenshots");
const BASE_URL = "http://127.0.0.1:8356";
const PASSWORD = "nomarr";

async function main() {
  mkdirSync(SCREENSHOT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
  });
  const page = await context.newPage();

  // Login
  console.log("Logging in...");
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState("networkidle");
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL(`${BASE_URL}/`);
  await page.waitForLoadState("networkidle");
  console.log("Logged in.");

  // --- Dashboard ---
  console.log("Capturing Dashboard...");
  await page.goto(`${BASE_URL}/`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);
  await page.screenshot({ path: join(SCREENSHOT_DIR, "dashboard.png") });
  console.log("  -> dashboard.png");

  // --- Browse (library management accordion collapsed) ---
  console.log("Capturing Browse...");
  await page.goto(`${BASE_URL}/browse`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);

  // The Library Management accordion is defaultExpanded — click to collapse it
  const browseAccordion = page.locator('.MuiAccordion-root').first();
  const browseAccordionSummary = browseAccordion.locator('.MuiAccordionSummary-root');
  // Check if it's expanded
  const isExpanded = await browseAccordion.getAttribute('class');
  if (isExpanded && isExpanded.includes('Mui-expanded')) {
    await browseAccordionSummary.click();
    await page.waitForTimeout(500);
  }
  await page.screenshot({ path: join(SCREENSHOT_DIR, "browse.png") });
  console.log("  -> browse.png");

  // --- Library Management (dedicated screenshot) ---
  console.log("Capturing Library Management section...");
  // Re-expand the accordion
  await browseAccordionSummary.click();
  await page.waitForTimeout(500);
  // Take a clipped screenshot of just the accordion area
  const accordionBox = await browseAccordion.boundingBox();
  if (accordionBox) {
    await page.screenshot({
      path: join(SCREENSHOT_DIR, "library-management.png"),
      clip: {
        x: accordionBox.x,
        y: accordionBox.y,
        width: accordionBox.width,
        height: accordionBox.height,
      },
    });
  } else {
    // Fallback: screenshot the element itself
    await browseAccordion.screenshot({ path: join(SCREENSHOT_DIR, "library-management.png") });
  }
  console.log("  -> library-management.png");

  // --- Insights ---
  console.log("Capturing Insights...");
  await page.goto(`${BASE_URL}/insights`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);
  await page.screenshot({ path: join(SCREENSHOT_DIR, "insights.png") });
  console.log("  -> insights.png");

  // --- Calibration (collapse all accordions so action buttons are visible) ---
  console.log("Capturing Calibration...");
  await page.goto(`${BASE_URL}/calibration`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);

  // Collapse any expanded accordions (Per-Head Convergence table, P5/P95 charts)
  const calAccordions = page.locator('.MuiAccordion-root');
  const calAccordionCount = await calAccordions.count();
  for (let i = 0; i < calAccordionCount; i++) {
    const acc = calAccordions.nth(i);
    const cls = await acc.getAttribute('class');
    if (cls && cls.includes('Mui-expanded')) {
      await acc.locator('.MuiAccordionSummary-root').click();
      await page.waitForTimeout(400);
    }
  }
  await page.waitForTimeout(500);
  await page.screenshot({ path: join(SCREENSHOT_DIR, "calibration.png") });
  console.log("  -> calibration.png");

  // --- Navidrome (expand Playlist Maker accordion) ---
  console.log("Capturing Navidrome...");
  await page.goto(`${BASE_URL}/navidrome`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1000);

  // Playlist Maker is the second accordion (collapsed by default)
  const playlistAccordion = page.locator('.MuiAccordion-root').nth(1);
  const playlistSummary = playlistAccordion.locator('.MuiAccordionSummary-root');
  const playlistExpanded = await playlistAccordion.getAttribute('class');
  if (!playlistExpanded || !playlistExpanded.includes('Mui-expanded')) {
    await playlistSummary.click();
    await page.waitForTimeout(800);
  }
  await page.screenshot({ path: join(SCREENSHOT_DIR, "navidrome.png") });
  console.log("  -> navidrome.png");

  // --- Playlist Import ---
  console.log("Capturing Playlist Import...");
  await page.goto(`${BASE_URL}/playlist-import`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1000);
  await page.screenshot({ path: join(SCREENSHOT_DIR, "playlist-import.png") });
  console.log("  -> playlist-import.png");

  // --- Config: SKIP per user request ---

  await browser.close();
  console.log(`\nDone! Screenshots saved to ${SCREENSHOT_DIR}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
