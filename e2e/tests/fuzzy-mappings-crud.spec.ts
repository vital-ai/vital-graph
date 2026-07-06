import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, SEEDED_FTS_INDEX } from '../seed-constants';

/**
 * Tier 7 — Fuzzy Mappings CRUD Write Operations
 *
 * Tests Create, List, Toggle (update), and Delete flows for fuzzy mappings
 * via the unified IndexMappings page at /index-mappings.
 */

const TEST_MAPPING_TYPE = 'kgframe'; // Distinct from seeded kgentity
const FUZZY_INDEX_NAME = SEEDED_FTS_INDEX; // Reuse existing index name

/** Delete any test fuzzy mapping we created via API. */
async function cleanupTestMappings() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  const listResp = await ctx.get('/api/fuzzy-mappings', {
    params: { space_id: SPACE_ID, mapping_type: TEST_MAPPING_TYPE },
    headers,
  });
  const data = await listResp.json();
  const mappings = data.mappings || [];

  for (const m of mappings) {
    if (m.index_name === FUZZY_INDEX_NAME) {
      await ctx.delete('/api/fuzzy-mappings', {
        params: { space_id: SPACE_ID, mapping_id: m.mapping_id },
        headers,
      });
    }
  }
  await ctx.dispose();
}

test.describe('Fuzzy Mappings CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupTestMappings(); });
  test.afterAll(async () => { await cleanupTestMappings(); });

  test('create a new fuzzy mapping via the UI', async ({ page }) => {
    await page.goto('/index-mappings');
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });

    // Select space
    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForTimeout(1_000);

    // Click Create Mapping
    await page.locator('button', { hasText: 'Create Mapping' }).click();

    // Fill the create modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByText('Create Mapping')).toBeVisible({ timeout: 5_000 });

    // Select Fuzzy kind
    await modal.locator('#createKind').selectOption('fuzzy');

    // Set index name
    await modal.locator('#createIndexName').fill(FUZZY_INDEX_NAME);

    // Select mapping type
    await modal.locator('#createMappingType').selectOption(TEST_MAPPING_TYPE);

    // Click Create
    await modal.locator('button', { hasText: 'Create' }).first().click();

    // Modal should close and mapping should appear in the list
    await expect(modal).not.toBeVisible({ timeout: 5_000 });

    // Filter to fuzzy to see our mapping
    await page.locator('#filterKind').selectOption('fuzzy');
    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).toBeVisible({ timeout: 5_000 });
  });

  test('fuzzy mapping appears in the list', async ({ page }) => {
    await page.goto(`/index-mappings?space=${SPACE_ID}&kind=fuzzy`);
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });

    // Verify our mapping type appears
    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).toBeVisible({ timeout: 10_000 });
  });

  test('toggle fuzzy mapping enabled state', async ({ page }) => {
    await page.goto(`/index-mappings?space=${SPACE_ID}&kind=fuzzy`);
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });

    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).toBeVisible({ timeout: 10_000 });

    const row = page.locator('table tbody tr').filter({
      has: page.locator('span', { hasText: /^kgframe$/ }),
    });
    const toggle = row.locator('button[role="switch"]');
    await toggle.click();

    await page.waitForTimeout(500);
    await expect(page.locator('[role="alert"]')).not.toBeVisible({ timeout: 2_000 });
  });

  test('delete the fuzzy mapping via the UI', async ({ page }) => {
    await page.goto(`/index-mappings?space=${SPACE_ID}&kind=fuzzy`);
    await expect(page.locator('[data-testid="index-mappings-page"]')).toBeVisible({ timeout: 10_000 });

    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).toBeVisible({ timeout: 10_000 });

    const row = page.locator('table tbody tr').filter({
      has: page.locator('span', { hasText: /^kgframe$/ }),
    });
    await row.locator('button').filter({ hasText: '' }).last().click();

    // Confirm in the delete modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByRole('heading', { name: 'Delete Mapping' })).toBeVisible({ timeout: 5_000 });
    await modal.locator('button', { hasText: 'Delete' }).first().click();

    // Mapping should be removed
    await expect(page.locator('table').getByText(TEST_MAPPING_TYPE, { exact: true })).not.toBeVisible({ timeout: 5_000 });
  });
});
