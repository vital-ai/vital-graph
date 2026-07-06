import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID } from '../seed-constants';

/**
 * Tier 7 — Indexes CRUD Write Operations
 *
 * Tests Create, List, and Delete flows for FTS and Vector indexes
 * via the unified Indexes page at /indexes.
 */

const FTS_INDEX_NAME = 'e2e_crud_fts';
const VECTOR_INDEX_NAME = 'e2e_crud_vec';

/** Delete test indexes via API (idempotent cleanup). */
async function cleanupTestIndexes() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  // Try to delete FTS index
  await ctx.delete('/api/fts-indexes', {
    params: { space_id: SPACE_ID, index_name: FTS_INDEX_NAME },
    headers,
  });

  // Try to delete vector index
  await ctx.delete('/api/vector-indexes', {
    params: { space_id: SPACE_ID, index_name: VECTOR_INDEX_NAME },
    headers,
  });

  await ctx.dispose();
}

test.describe('Indexes CRUD — FTS', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupTestIndexes(); });
  test.afterAll(async () => { await cleanupTestIndexes(); });

  test('create a new FTS index via the UI', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    // Select space and wait for any triggered fetch to settle
    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');

    // Click Create Index
    await page.locator('button', { hasText: 'Create Index' }).click();

    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByText('Create Index')).toBeVisible({ timeout: 5_000 });

    // Select FTS type
    await modal.locator('#createType').selectOption('fts');

    // Set index name
    await modal.locator('#createName').fill(FTS_INDEX_NAME);

    // Click Create
    await modal.locator('button', { hasText: 'Create' }).first().click();

    // Modal should close
    await expect(modal).not.toBeVisible({ timeout: 5_000 });

    // Index should appear in the table
    await expect(page.locator('table').getByText(FTS_INDEX_NAME)).toBeVisible({ timeout: 5_000 });
  });

  test('FTS index appears in the list', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('table').getByText(FTS_INDEX_NAME)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the FTS index via the UI', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('table').getByText(FTS_INDEX_NAME)).toBeVisible({ timeout: 10_000 });

    // Find the row and click delete
    const row = page.locator('table tbody tr', { hasText: FTS_INDEX_NAME });
    await row.locator('button').last().click();

    // Confirm in the delete modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByRole('heading', { name: 'Delete Index' })).toBeVisible({ timeout: 5_000 });
    await modal.locator('button', { hasText: 'Delete' }).first().click();

    // Index should be removed
    await expect(page.locator('table').getByText(FTS_INDEX_NAME)).not.toBeVisible({ timeout: 5_000 });
  });
});

test.describe('Indexes CRUD — Vector', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupTestIndexes(); });
  test.afterAll(async () => { await cleanupTestIndexes(); });

  test('create a new Vector index via the UI', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');

    // Click Create Index
    await page.locator('button', { hasText: 'Create Index' }).click();

    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByText('Create Index')).toBeVisible({ timeout: 5_000 });

    // Select Vector type (default)
    await modal.locator('#createType').selectOption('vector');

    // Set index name
    await modal.locator('#createName').fill(VECTOR_INDEX_NAME);

    // Set dimensions
    await modal.locator('#dimensions').fill('256');

    // Click Create
    await modal.locator('button', { hasText: 'Create' }).first().click();

    // Modal should close
    await expect(modal).not.toBeVisible({ timeout: 5_000 });

    // Index should appear
    await expect(page.locator('table').getByText(VECTOR_INDEX_NAME)).toBeVisible({ timeout: 5_000 });
  });

  test('Vector index appears in the list', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('table').getByText(VECTOR_INDEX_NAME)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the Vector index via the UI', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('table').getByText(VECTOR_INDEX_NAME)).toBeVisible({ timeout: 10_000 });

    // Find the row and click delete
    const row = page.locator('table tbody tr', { hasText: VECTOR_INDEX_NAME });
    await row.locator('button').last().click();

    // Confirm in the delete modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByRole('heading', { name: 'Delete Index' })).toBeVisible({ timeout: 5_000 });
    await modal.locator('button', { hasText: 'Delete' }).first().click();

    // Index should be removed
    await expect(page.locator('table').getByText(VECTOR_INDEX_NAME)).not.toBeVisible({ timeout: 5_000 });
  });
});
