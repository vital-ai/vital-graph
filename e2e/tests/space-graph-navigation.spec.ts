import { test, expect } from '@playwright/test';
import { SPACE_ID, SPACE_NAME, GRAPH_ID } from '../seed-constants';

/**
 * Navigation drill-down tests.
 *
 * Verifies the full hierarchy:
 *   Spaces → Space Detail → Graphs → Graph Detail
 * using the seeded test data.
 */
test.describe('Space & Graph Navigation', () => {
  test('drill from Spaces list into Space Detail', async ({ page }) => {
    await page.goto('/spaces');
    await expect(page.locator('[data-testid="spaces-page"]')).toBeVisible({ timeout: 10_000 });

    // Seeded space card should be present
    const card = page.locator(`[data-testid="space-card-${SPACE_ID}"]`);
    await expect(card).toBeVisible({ timeout: 10_000 });
    await expect(card).toContainText(SPACE_NAME);

    // Click into the space
    await card.click();
    await expect(page.locator('[data-testid="space-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page).toHaveURL(new RegExp(`/space/${SPACE_ID}`));
  });

  test('drill from Graphs list into Graph Detail', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graphs`);
    await expect(page.locator('[data-testid="graphs-page"]')).toBeVisible({ timeout: 10_000 });

    // Seeded graph card should be present
    const card = page.locator(`[data-testid="graph-card-${GRAPH_ID}"]`);
    await expect(card).toBeVisible({ timeout: 10_000 });

    // Click the link inside the graph card (card is a div, not a link)
    await card.locator('a').first().click();
    await expect(page.locator('[data-testid="graph-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page).toHaveURL(new RegExp(`graph/`));
  });

  test('Space Detail shows key info sections', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}`);
    await expect(page.locator('[data-testid="space-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Should display the space name somewhere on the page
    await expect(page.getByText(SPACE_NAME)).toBeVisible();
  });

  test('Graph Detail shows key info sections', async ({ page }) => {
    const G = encodeURIComponent(GRAPH_ID);
    await page.goto(`/space/${SPACE_ID}/graph/${G}`);
    await expect(page.locator('[data-testid="graph-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});
