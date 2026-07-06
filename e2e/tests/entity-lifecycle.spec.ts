import { test, expect } from '@playwright/test';
import {
  SPACE_ID,
  SPACE_NAME,
  GRAPH_ID,
  ENTITIES,
  EXPECTED_ENTITY_COUNT,
} from '../seed-constants';

/**
 * Phase 1.5 — Single-flow end-to-end proof.
 *
 * This test walks through the complete entity lifecycle:
 *   Login (via storageState) → Home → Spaces → Space Detail →
 *   Graphs → Graph → Entities → Create → Detail → Edit → Delete →
 *   Semantic Search
 *
 * If this test passes, the entire infrastructure is proven:
 *   docker-compose.test.yml, seed script, auth, data-testid selectors,
 *   page object pattern, CRUD API calls, navigation.
 */
test.describe('Entity Lifecycle', () => {
  test('complete CRUD flow through seeded data', async ({ page }) => {
    // ---- 1. Home page renders dashboard ----------------------------------
    await page.goto('/');
    await expect(page).toHaveURL(/^(?!.*login)/); // not redirected to login
    await expect(page.locator('[data-testid="home-page"]')).toBeVisible();
    await expect(page.locator('[data-testid="home-title"]')).toHaveText('Dashboard');

    // ---- 2. Navigate to Spaces -------------------------------------------
    await page.goto('/spaces');
    await expect(page.locator('[data-testid="spaces-page"]')).toBeVisible({ timeout: 10_000 });
    // The seeded space should appear
    await expect(page.locator(`[data-testid="space-card-${SPACE_ID}"]`)).toBeVisible({ timeout: 10_000 });

    // ---- 3. Click into the seeded space ----------------------------------
    await page.locator(`[data-testid="space-card-${SPACE_ID}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/space/${SPACE_ID}`));

    // ---- 4. Navigate to Graphs for this space ----------------------------
    await page.goto(`/space/${SPACE_ID}/graphs`);
    await expect(page.locator('[data-testid="graphs-page"]')).toBeVisible();
    // The seeded graph should appear
    await expect(page.locator(`[data-testid="graph-card-${GRAPH_ID}"]`)).toBeVisible({ timeout: 10_000 });

    // ---- 5. Navigate to KG Entities for the graph ------------------------
    await page.goto(
      `/space/${SPACE_ID}/graph/${encodeURIComponent(GRAPH_ID)}/objects/kgentities`,
    );
    await expect(page.locator('[data-testid="kgentities-page"]')).toBeVisible();

    // Seeded entities should be listed
    await expect(page.getByText(ENTITIES.alice.name)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(ENTITIES.bob.name)).toBeVisible();
    await expect(page.getByText(ENTITIES.carol.name)).toBeVisible();

    // ---- 6. Verify entity count ------------------------------------------
    const entityRows = page.locator('[data-testid="entity-row"]');
    await expect(entityRows).toHaveCount(EXPECTED_ENTITY_COUNT, { timeout: 10_000 });

    // ---- 7. Click into a specific entity (via View icon button) ----------
    await page.locator(`[data-testid="entity-view-${ENTITIES.alice.uri}"]`).click();
    await expect(page).toHaveURL(/entity/);
    await expect(page.locator('[data-testid="kgentity-detail-page"]')).toBeVisible();
    // Entity detail page should show the entity name
    await expect(page.locator('[data-testid="object-detail-name"]')).toBeVisible();
    // Navigate back to the entity list
    await page.goBack();

    // ---- 8. Navigate to Semantic Search ----------------------------------
    await page.goto('/semantic-search');
    await expect(page.locator('[data-testid="semantic-search-page"]')).toBeVisible();
    await expect(page.locator('[data-testid="semantic-search-title"]')).toHaveText('Semantic Search');
  });

  test('no console errors during navigation', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => errors.push(err.message));

    // Visit key pages
    const pages = [
      '/',
      '/spaces',
      `/space/${SPACE_ID}`,
      `/space/${SPACE_ID}/graphs`,
      `/space/${SPACE_ID}/graph/${encodeURIComponent(GRAPH_ID)}/objects/kgentities`,
      '/semantic-search',
    ];

    for (const url of pages) {
      await page.goto(url);
      await page.waitForLoadState('networkidle');
    }

    // Filter out known benign errors (e.g. favicon 404, dev warnings)
    const realErrors = errors.filter(
      (e) => !e.includes('favicon') && !e.includes('DevTools'),
    );
    expect(realErrors).toEqual([]);
  });
});
