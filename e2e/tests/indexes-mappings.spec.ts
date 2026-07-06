import { test, expect } from '@playwright/test';
import {
  SPACE_ID,
  SEEDED_FTS_INDEX,
  SEEDED_VECTOR_INDEX,
} from '../seed-constants';

/**
 * Tier 6 — Indexes, Mappings, and Geo
 *
 * Covers: Indexes, VectorIndexes, VectorIndexDetail, FtsIndexes, FtsIndexDetail,
 *         IndexMappings, SearchMappings, SearchMappingDetail,
 *         FuzzyMappings, FuzzyMappingDetail, GeoShapes
 *
 * Depends on seeded FTS index (e2e_fts_idx), vector index (e2e_vec_idx),
 * search mapping, and fuzzy mapping created by seed_ui_test_data.py.
 */

// ---------- Indexes (combined tab page) ------------------------------------

test.describe('Indexes', () => {
  test('page loads with tabs', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('shows seeded FTS index in the list', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });
    await page.locator('#space').selectOption({ value: SPACE_ID });
    await expect(page.getByText(SEEDED_FTS_INDEX).first()).toBeVisible({ timeout: 10_000 });
  });

  test('shows seeded vector index in the list', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });
    await page.locator('#space').selectOption({ value: SPACE_ID });
    await expect(page.getByText(SEEDED_VECTOR_INDEX).first()).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- Vector Index Detail --------------------------------------------

test.describe('Vector Index Detail', () => {
  test('detail page loads for seeded index', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/indexes/vector/${SEEDED_VECTOR_INDEX}`);
    await expect(page.locator('[data-testid="vector-index-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SEEDED_VECTOR_INDEX).first()).toBeVisible();
  });
});

// ---------- FTS Index Detail -----------------------------------------------

test.describe('FTS Index Detail', () => {
  test('detail page loads for seeded index', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/indexes/fts/${SEEDED_FTS_INDEX}`);
    await expect(page.locator('[data-testid="fts-index-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SEEDED_FTS_INDEX).first()).toBeVisible();
  });
});

// ---------- Index Mappings -------------------------------------------------

test.describe('Index Mappings', () => {
  test('page loads', async ({ page }) => {
    await page.goto('/index-mappings');
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('shows mappings for the seeded space', async ({ page }) => {
    await page.goto('/index-mappings');
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });
    // Wait for the space dropdown to be rendered (not spinner)
    await expect(page.locator('#space')).toBeVisible({ timeout: 10_000 });
    await page.locator('#space').selectOption({ value: SPACE_ID });
    // Wait for data to load after space selection
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 10_000 });
    // Verify seeded FTS index name appears in the mapping list
    await expect(page.getByText(SEEDED_FTS_INDEX).first()).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- Search Mapping Detail ------------------------------------------

test.describe('Search Mapping Detail', () => {
  test('navigates to detail via search mapping row', async ({ page }) => {
    await page.goto('/index-mappings');
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });
    const viewLinks = page.locator('a[href*="/index-mappings/"]');
    const count = await viewLinks.count();
    if (count > 0) {
      await viewLinks.first().click();
      await expect(page.locator('[data-testid="search-mapping-detail-page"]')).toBeVisible({ timeout: 10_000 });
    }
  });
});

// ---------- Fuzzy Mapping Detail -------------------------------------------

test.describe('Fuzzy Mapping Detail', () => {
  test('navigates to detail via fuzzy mapping row', async ({ page }) => {
    await page.goto('/index-mappings');
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });
    const viewLinks = page.locator('a[href*="/fuzzy-mappings/"]');
    const count = await viewLinks.count();
    if (count > 0) {
      await viewLinks.first().click();
      await expect(page.locator('[data-testid="fuzzy-mapping-detail-page"]')).toBeVisible({ timeout: 10_000 });
    }
  });
});

// ---------- Geo Shapes -----------------------------------------------------

test.describe('Geo Shapes', () => {
  test('page loads', async ({ page }) => {
    await page.goto('/geo-shapes');
    await expect(page.locator('[data-testid="geo-shapes-page"]')).toBeVisible({ timeout: 10_000 });
  });
});
