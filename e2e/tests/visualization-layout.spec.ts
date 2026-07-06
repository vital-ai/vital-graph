import { test, expect } from '@playwright/test';

/**
 * Tier 10 — Graph Visualization and Not Found
 */

test.describe('Graph Visualization', () => {
  test('page loads with visualization container', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator('[data-testid="graph-visualization-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

test.describe('Not Found', () => {
  test('404 page renders for unknown route', async ({ page }) => {
    await page.goto('/this-does-not-exist-at-all');
    await expect(page.locator('[data-testid="not-found-page"]')).toBeVisible();
  });

  test('404 page has a link back to home', async ({ page }) => {
    await page.goto('/nonexistent-page');
    await expect(page.locator('[data-testid="not-found-page"]')).toBeVisible();
    // Should have some way to get back
    await expect(page.getByRole('link', { name: /go home/i })).toBeVisible();
  });
});
