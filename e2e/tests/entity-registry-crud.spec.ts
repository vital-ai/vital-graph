import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Tier 7 — Entity Registry CRUD Write Operations
 *
 * Tests the Create, List, Update, and Delete flows for entity registry entries.
 * Uses form-based UI (not the ObjectDetailRenderer pattern).
 */

const CRUD_ENTITY_NAME = 'E2E CRUD Registry Entity';
const CRUD_ENTITY_URI = 'urn:e2e:registry:crud-test';
const CRUD_ENTITY_TYPE = 'person';
const UPDATED_DESC = 'Updated by E2E CRUD test';

/** Delete any registry entity with the test URI via API (idempotent cleanup). */
async function cleanupCrudEntity() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  // Search for our test entity by name
  const listResp = await ctx.get('/api/registry/entities', {
    params: { query: CRUD_ENTITY_NAME, limit: 50 },
    headers,
  });
  const data = await listResp.json();
  const entities = data.entities || [];

  for (const entity of entities) {
    if (entity.primary_name === CRUD_ENTITY_NAME || entity.entity_uri === CRUD_ENTITY_URI) {
      await ctx.delete('/api/registry/entities/delete', {
        params: { entity_id: entity.entity_id },
        headers,
      });
    }
  }
  await ctx.dispose();
}

test.describe('Entity Registry CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupCrudEntity(); });
  test.afterAll(async () => { await cleanupCrudEntity(); });

  test('create a new registry entity via the UI', async ({ page }) => {
    await page.goto('/entity-registry/new');
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Fill in the create form
    await page.locator('#name').fill(CRUD_ENTITY_NAME);
    await page.locator('#uri').fill(CRUD_ENTITY_URI);
    await page.locator('#type').fill(CRUD_ENTITY_TYPE);
    await page.locator('#desc').fill('Initial description');

    // Click Create Entity
    await page.locator('button', { hasText: 'Create Entity' }).click();

    // Should redirect back to the registry list
    await expect(page).toHaveURL(/\/entity-registry$/, { timeout: 10_000 });
  });

  test('new entity appears in the registry list', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });

    // Verify entity name appears in the table
    await expect(page.getByText(CRUD_ENTITY_NAME)).toBeVisible({ timeout: 10_000 });
  });

  test('update the entity via the UI', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });

    // Click on the entity row to navigate to detail
    await page.getByText(CRUD_ENTITY_NAME).click();

    // Wait for detail page
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Switch to edit mode
    await page.locator('button', { hasText: 'Edit' }).click();

    // Update the description
    await page.locator('#desc').fill(UPDATED_DESC);

    // Click Save
    await page.locator('button', { hasText: 'Save' }).click();

    // Should switch back to view mode — verify the description appears
    await expect(page.getByText(UPDATED_DESC)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the entity via the UI', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });

    // Click on the entity row
    await page.getByText(CRUD_ENTITY_NAME).click();

    // Wait for detail page
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click the Delete button
    await page.locator('button', { hasText: 'Delete' }).click();

    // Confirm modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await expect(modal.getByText(/delete entity/i)).toBeVisible();

    // Click Delete in the modal
    await modal.getByRole('button', { name: /delete/i }).first().click();

    // Should redirect back to the registry list
    await expect(page).toHaveURL(/\/entity-registry$/, { timeout: 10_000 });

    // Entity should no longer appear
    await expect(page.getByText(CRUD_ENTITY_NAME)).not.toBeVisible({ timeout: 5_000 });
  });
});
