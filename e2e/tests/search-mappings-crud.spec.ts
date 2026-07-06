import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, SEEDED_FTS_INDEX } from '../seed-constants';

/**
 * Tier 7 — Index Mappings CRUD Write Operations
 *
 * Tests Create, List, Toggle (update), and Delete flows for search/fuzzy mappings
 * via the unified IndexMappings page at /index-mappings.
 * The test space already has an FTS index (e2e_fts_idx) seeded.
 */

const TEST_MAPPING_TYPE = 'kgdocument'; // Different from seeded 'kgentity' mapping

/** Delete any test mapping we created (by type) via API. */
async function cleanupTestMappings() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  const listResp = await ctx.get('/api/search-mappings', {
    params: { space_id: SPACE_ID, mapping_type: TEST_MAPPING_TYPE },
    headers,
  });
  const data = await listResp.json();
  const mappings = data.mappings || [];

  for (const m of mappings) {
    if (m.index_name === SEEDED_FTS_INDEX) {
      await ctx.delete(`/api/search-mappings/${m.mapping_id}`, {
        params: { space_id: SPACE_ID },
        headers,
      });
    }
  }
  await ctx.dispose();
}

test.describe('Index Mappings CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupTestMappings(); });
  test.afterAll(async () => { await cleanupTestMappings(); });

  test('create a new search mapping via the UI', async ({ page }) => {
    await page.goto('/index-mappings');
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });

    // Select space
    await page.locator('#space').selectOption(SPACE_ID);

    // Wait for data to load
    await page.waitForTimeout(1_000);

    // Click Create Mapping
    await page.locator('button', { hasText: 'Create Mapping' }).click();

    // Fill the create modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByText('Create Mapping')).toBeVisible({ timeout: 5_000 });

    // Set kind to FTS/Vector (default)
    // Set index name
    await modal.locator('#createIndexName').fill(SEEDED_FTS_INDEX);

    // Select mapping type (kgdocument)
    await modal.locator('#createMappingType').selectOption(TEST_MAPPING_TYPE);

    // Click Create
    await modal.locator('button', { hasText: 'Create' }).first().click();

    // Modal should close and mapping should appear in the list
    await expect(modal).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).toBeVisible({ timeout: 5_000 });
  });

  test('mapping appears in the list', async ({ page }) => {
    await page.goto(`/index-mappings?space=${SPACE_ID}`);
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });

    // Verify our mapping type appears in the table
    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).toBeVisible({ timeout: 10_000 });
  });

  test('toggle mapping enabled state', async ({ page }) => {
    await page.goto(`/index-mappings?space=${SPACE_ID}`);
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for table to load
    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).toBeVisible({ timeout: 10_000 });

    // Find the row with our mapping type — use exact Badge text
    const row = page.locator('table tbody tr').filter({
      has: page.locator('span', { hasText: /^kgdocument$/ }),
    });
    const toggle = row.locator('button[role="switch"]');
    await toggle.click();

    // Wait for the API call to complete
    await page.waitForTimeout(500);

    // No error alert should be visible
    await expect(page.locator('[role="alert"]')).not.toBeVisible({ timeout: 2_000 });
  });

  test('delete the mapping via the UI', async ({ page }) => {
    await page.goto(`/index-mappings?space=${SPACE_ID}`);
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for table
    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).toBeVisible({ timeout: 10_000 });

    // Find row with exact Badge match and click the delete button
    const row = page.locator('table tbody tr').filter({
      has: page.locator('span', { hasText: /^kgdocument$/ }),
    });
    await row.locator('button').filter({ hasText: '' }).last().click();

    // Confirm in the delete modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByRole('heading', { name: 'Delete Mapping' })).toBeVisible({ timeout: 5_000 });
    await modal.locator('button', { hasText: 'Delete' }).first().click();

    // Mapping should be removed from the list
    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).not.toBeVisible({ timeout: 5_000 });
  });
});
