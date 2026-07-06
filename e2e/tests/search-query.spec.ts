import { test, expect } from '@playwright/test';
import { SPACE_ID, GRAPH_ID, ENTITIES } from '../seed-constants';

const G = encodeURIComponent(GRAPH_ID);

/**
 * Tier 5 — Semantic Search, Search Result Detail, KG Query Builder
 */

test.describe('Semantic Search', () => {
  test('page loads with title and search input', async ({ page }) => {
    await page.goto('/semantic-search');
    await expect(page.locator('[data-testid="semantic-search-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="semantic-search-title"]')).toHaveText('Semantic Search');
  });

  test('can type a query into the search input', async ({ page }) => {
    await page.goto('/semantic-search');
    await expect(page.locator('[data-testid="semantic-search-page"]')).toBeVisible({ timeout: 10_000 });
    const input = page.locator('[data-testid="semantic-search-input"]');
    if (await input.count() > 0) {
      await input.fill('Alice');
      await expect(input).toHaveValue('Alice');
    } else {
      // Fallback: any visible input/textarea
      const fallback = page.locator('input[type="text"], textarea').first();
      await fallback.fill('Alice');
      await expect(fallback).toHaveValue('Alice');
    }
  });
});

test.describe('Search Result Detail', () => {
  test('page loads for a known entity URI', async ({ page }) => {
    const subjectUri = encodeURIComponent(ENTITIES.alice.uri);
    await page.goto(`/space/${SPACE_ID}/graph/${G}/search-result/${subjectUri}`);
    await expect(page.locator('[data-testid="search-result-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

test.describe('KG Query Builder', () => {
  test('page loads with builder UI', async ({ page }) => {
    await page.goto('/kg-query-builder');
    await expect(page.locator('[data-testid="kgquery-builder-page"]')).toBeVisible({ timeout: 10_000 });
  });
});
