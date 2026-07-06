import { test, expect } from '@playwright/test';

/**
 * Data Import/Export pages — verify the tab-based Data page
 * and its sub-pages load correctly.
 */
test.describe('Data Import/Export', () => {
  test('Data page loads with import tab and sub-component', async ({ page }) => {
    await page.goto('/data/import');
    await expect(page.locator('[data-testid="data-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="data-import-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('Data page loads with export tab and sub-component', async ({ page }) => {
    await page.goto('/data/export');
    await expect(page.locator('[data-testid="data-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="data-export-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('New import job page loads', async ({ page }) => {
    await page.goto('/data/import/new');
    await expect(page.locator('[data-testid="data-import-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('New export job page loads', async ({ page }) => {
    await page.goto('/data/export/new');
    await expect(page.locator('[data-testid="data-export-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});
