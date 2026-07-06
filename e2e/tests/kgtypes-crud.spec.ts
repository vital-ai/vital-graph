import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Tier 7 — KG Types CRUD Write Operations
 *
 * Tests the Create, List, Update, and Delete flows for KG types.
 * KG Types use a fixed system space (sp_kg_types) with no graph requirement.
 */

const SP_KG_TYPES = 'sp_kg_types';
const CRUD_TYPE_NAME = 'E2E CRUD Test Type';
const UPDATED_TYPE_DESC = 'Updated by E2E CRUD test';
const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
const HAS_DESC = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription';

/** Delete any KG type with CRUD_TYPE_NAME via API (idempotent cleanup). */
async function cleanupCrudType() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  // List all KG types in the system space
  const listResp = await ctx.get('/api/graphs/kgtypes', {
    params: { space_id: SP_KG_TYPES, page_size: 100 },
    headers,
  });
  const data = await listResp.json();
  const quads = data.results || [];

  // Find subjects whose hasName matches our test type
  const urisToDelete = new Set<string>();
  for (const q of quads) {
    const s = String(q.s || '').replace(/^<|>$/g, '');
    const p = String(q.p || '').replace(/^<|>$/g, '');
    const o = String(q.o || '').replace(/^<|>$/g, '').replace(/^"|"$/g, '');
    if (p === HAS_NAME && o === CRUD_TYPE_NAME) {
      urisToDelete.add(s);
    }
  }

  for (const uri of urisToDelete) {
    await ctx.delete('/api/graphs/kgtypes', {
      params: { space_id: SP_KG_TYPES, uri },
      headers,
    });
  }
  await ctx.dispose();
}

test.describe('KG Types CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupCrudType(); });
  test.afterAll(async () => { await cleanupCrudType(); });

  test('create a new KG type via the UI', async ({ page }) => {
    await page.goto('/kg-types/new?mode=create');
    await expect(page.locator('[data-testid="kgtype-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('object-detail-title')).toHaveText('Create KG Type');

    // Add a hasName property via the "Add Property" form
    const detail = page.locator('[data-testid="object-detail"]');
    await detail.locator('#new-predicate').fill(HAS_NAME);
    await detail.locator('#new-value').fill(CRUD_TYPE_NAME);
    await detail.locator('button', { hasText: 'Add' }).click();

    // Click Create
    await page.locator('button', { hasText: 'Create' }).click();

    // Should redirect back to the KG Types list
    await expect(page).toHaveURL(/\/kg-types/, { timeout: 10_000 });
  });

  test('new type appears in the types list', async ({ page }) => {
    await page.goto('/kg-types');
    await expect(page.locator('[data-testid="kgtypes-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for table rows to render
    await expect(page.locator('[data-testid="type-row"]').first()).toBeVisible({ timeout: 10_000 });

    // Verify type name appears
    await expect(page.locator('[data-testid="type-row"]', { hasText: CRUD_TYPE_NAME })).toBeVisible({ timeout: 5_000 });
  });

  test('update the type via the UI', async ({ page }) => {
    await page.goto('/kg-types');
    await expect(page.locator('[data-testid="type-row"]').first()).toBeVisible({ timeout: 10_000 });

    // Click the View button on the row with our type
    const typeRow = page.locator('[data-testid="type-row"]', { hasText: CRUD_TYPE_NAME });
    await typeRow.locator('button[title="View"]').click();

    // Wait for detail page
    await expect(page.locator('[data-testid="kgtype-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('object-detail-title')).toHaveText('KG Type Details');

    // Switch to edit mode
    await page.locator('button', { hasText: 'Edit' }).click();

    // Add a description property via the "Add Property" form
    const detail = page.locator('[data-testid="object-detail"]');
    await detail.locator('#new-predicate').fill(HAS_DESC);
    await detail.locator('#new-value').fill(UPDATED_TYPE_DESC);
    await detail.locator('button', { hasText: 'Add' }).click();

    // Click Save
    await page.locator('button', { hasText: 'Save' }).click();

    // Should switch back to view mode — verify the description appears in properties
    await expect(page.getByText(UPDATED_TYPE_DESC)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the type via the UI', async ({ page }) => {
    await page.goto('/kg-types');
    await expect(page.locator('[data-testid="type-row"]').first()).toBeVisible({ timeout: 10_000 });

    // Click the Delete (trash) button on the row with our type
    const typeRow = page.locator('[data-testid="type-row"]', { hasText: CRUD_TYPE_NAME });
    await expect(typeRow).toBeVisible({ timeout: 5_000 });
    await typeRow.locator('button[title="Delete"]').click();

    // Confirm modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await expect(modal.getByText(/delete kg type/i)).toBeVisible();

    // Click Delete in the modal
    await modal.getByRole('button', { name: /delete/i }).first().click();

    // Type should be removed from the list
    await expect(
      page.locator('[data-testid="type-row"]', { hasText: CRUD_TYPE_NAME })
    ).not.toBeVisible({ timeout: 5_000 });
  });
});
