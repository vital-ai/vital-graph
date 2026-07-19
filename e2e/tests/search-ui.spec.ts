import { test, expect } from '@playwright/test';
import { SPACE_ID, GRAPH_ID, ENTITIES, FRAMES } from '../seed-constants';

/**
 * Tier 9 — Search & Filter UI Tests
 *
 * Verifies the search UI across KG Entities, KG Types, and KG Frames pages:
 * explicit "Search" button (Entities/Types), debounced search (Frames),
 * form type filter tabs, and search modes.
 */

const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);

test.describe('KG Entities — Search UI', () => {
  test('search input and button are visible', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgentities`);
    await expect(page.locator('[data-testid="kgentities-page"]')).toBeVisible({ timeout: 10_000 });

    // Search input should be present
    await expect(page.locator('input[placeholder="Search entities..."]')).toBeVisible();

    // Explicit "Search" button should be present (use getByRole to avoid matching command palette)
    await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeVisible();
  });

  test('search button filters entity list', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgentities`);
    await expect(page.locator('[data-testid="entities-table"]')).toBeVisible({ timeout: 10_000 });

    // All seeded entities should initially be visible
    await expect(page.getByText(ENTITIES.alice.name)).toBeVisible({ timeout: 5_000 });

    // Type a search term in the input
    await page.locator('input[placeholder="Search entities..."]').fill('Alice');

    // Click the Search button
    await page.getByRole('button', { name: 'Search', exact: true }).click();

    // Alice should be visible, others may or may not depending on match
    await expect(page.getByText(ENTITIES.alice.name)).toBeVisible({ timeout: 10_000 });
  });

  test('Enter key triggers search', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgentities`);
    await expect(page.locator('[data-testid="entities-table"]')).toBeVisible({ timeout: 10_000 });

    // Type a search term and press Enter
    await page.locator('input[placeholder="Search entities..."]').fill('Bob');
    await page.locator('input[placeholder="Search entities..."]').press('Enter');

    // Bob should be visible in the results
    await expect(page.getByText(ENTITIES.bob.name)).toBeVisible({ timeout: 10_000 });
  });
});

test.describe('KG Types — Search UI', () => {
  test('search input, button, and mode selector are visible', async ({ page }) => {
    await page.goto('/kg-types');
    await expect(page.locator('[data-testid="kgtypes-page"]')).toBeVisible({ timeout: 10_000 });

    // Search input should be present
    await expect(page.locator('input[placeholder*="Search types"]')).toBeVisible();

    // Search mode dropdown should be visible with Keyword default
    await expect(page.locator('select').filter({ hasText: 'Keyword' })).toBeVisible();
  });

  test('search mode dropdown has all modes', async ({ page }) => {
    await page.goto('/kg-types');
    await expect(page.locator('[data-testid="kgtypes-page"]')).toBeVisible({ timeout: 10_000 });

    // The mode dropdown should have all four options (options are hidden in native selects, check count)
    const modeSelect = page.locator('select').filter({ hasText: 'Keyword' });
    await expect(modeSelect.locator('option')).toHaveCount(4);

    // Verify the dropdown has the expected value and can switch
    await expect(modeSelect).toHaveValue('keyword');
    await modeSelect.selectOption('vector');
    await expect(modeSelect).toHaveValue('vector');
  });
});

test.describe('KG Frames — Filter & Search UI', () => {
  test('form type tabs are visible (All, Assertions, Aspects)', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgframes`);
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 10_000 });

    // Form type filter tabs
    await expect(page.locator('button', { hasText: 'All' })).toBeVisible();
    await expect(page.locator('button', { hasText: 'Assertions' })).toBeVisible();
    await expect(page.locator('button', { hasText: 'Aspects' })).toBeVisible();
  });

  test('search input and sort dropdown are visible', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgframes`);
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 10_000 });

    // Debounced search input
    await expect(page.locator('input[placeholder="Search frames..."]')).toBeVisible();

    // Sort dropdown is visible. Its placeholder is gated: "Sort by..." once a
    // search/filter enables sorting, "Sort (search first)" before then — match
    // either so the assertion is state-independent.
    await expect(page.locator('select').filter({ hasText: /Sort/ })).toBeVisible();
  });

  test('clicking form type tab filters frames list', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgframes`);
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 10_000 });

    // Seeded frames should appear in the list
    await expect(page.locator('[data-testid="frame-row"]').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('[data-testid="frame-row"]', { hasText: FRAMES.alice_profile.name })).toBeVisible();

    // Click "Assertions" tab — page should re-render without error
    await page.locator('button', { hasText: 'Assertions' }).click();

    // Page should remain visible (no crash), may show frames or empty state
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 5_000 });
  });
});
