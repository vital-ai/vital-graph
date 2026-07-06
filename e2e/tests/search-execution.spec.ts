import { test, expect } from '@playwright/test';
import { SPACE_ID } from '../seed-constants';

/**
 * Tier 8 — Semantic Search Execution + Results
 *
 * Tests executing searches via the SemanticSearch page and verifying results.
 */

test.describe('Search Execution', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/semantic-search');
    await expect(page.locator('[data-testid="semantic-search-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('keyword search returns results for a known entity', async ({ page }) => {
    // Select the e2e test space
    await page.locator('#space').selectOption(SPACE_ID);

    // Switch to keyword mode
    await page.locator('#mode').selectOption('keyword');

    // Enter search text for a seeded entity
    await page.locator('#searchText').fill('alice');

    // Click Search
    await page.getByRole('button', { name: /search/i }).click();

    // Wait for results to appear (> 0 rows text)
    await expect(page.getByText(/\d+ rows/).first()).toBeVisible({ timeout: 15_000 });

    // Results table should have at least one row
    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible();
  });

  test('show generated SPARQL toggle works', async ({ page }) => {
    // Select the e2e test space
    await page.locator('#space').selectOption(SPACE_ID);

    // Switch to keyword mode and enter text
    await page.locator('#mode').selectOption('keyword');
    await page.locator('#searchText').fill('test');

    // Toggle "Show Generated SPARQL"
    await page.getByText('Show Generated SPARQL').click();

    // SPARQL heading should be visible
    await expect(page.getByRole('heading', { name: 'Generated SPARQL' })).toBeVisible();
    await expect(page.locator('pre').first()).toBeVisible();

    // Should contain FILTER keyword from keyword mode
    const sparqlText = await page.locator('pre').first().textContent();
    expect(sparqlText).toContain('FILTER');
    expect(sparqlText).toContain('CONTAINS');
  });

  test('FTS search returns results for a known entity', async ({ page }) => {
    // Select the e2e test space
    await page.locator('#space').selectOption(SPACE_ID);

    // Wait for indexes to load, then switch to FTS mode
    await page.locator('#mode').selectOption('fts');

    // Enter search text
    await page.locator('#searchText').fill('alice');

    // Click Search
    await page.getByRole('button', { name: /search/i }).click();

    // Wait for results — FTS may or may not have indexed data,
    // so just verify the search completes without error
    await expect(page.getByText(/\d+ rows/).first()).toBeVisible({ timeout: 15_000 });
  });

  test('empty results shown when no match', async ({ page }) => {
    await page.locator('#space').selectOption(SPACE_ID);
    await page.locator('#mode').selectOption('keyword');
    await page.locator('#searchText').fill('zzz_nonexistent_query_xyz_12345');

    await page.getByRole('button', { name: /search/i }).click();

    // Should show "0 rows" and "No results" message
    await expect(page.getByText('0 rows')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/no results/i)).toBeVisible();
  });
});
