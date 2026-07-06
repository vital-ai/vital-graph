import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Tier 6 — Spaces CRUD Write Operations
 *
 * Tests the Create, Update, and Delete flows for spaces.
 * Uses a fixed space ID and cleans up before/after via API.
 */

const CRUD_SPACE_ID = 'e2e_crud_space';
const CRUD_SPACE_NAME = 'CRUD Test Space';
const CRUD_SPACE_DESC = 'Created by Playwright CRUD test';
const UPDATED_NAME = 'CRUD Test Space (Updated)';
const UPDATED_DESC = 'Updated description';

/** Delete the CRUD space via API if it exists (idempotent cleanup). */
async function cleanupCrudSpace() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  await ctx.delete(`/api/spaces/${CRUD_SPACE_ID}`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  await ctx.dispose();
}

test.describe('Spaces CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  // Cleanup before and after to avoid leftover state
  test.beforeAll(async () => { await cleanupCrudSpace(); });
  test.afterAll(async () => { await cleanupCrudSpace(); });

  test('create a new space via the UI', async ({ page }) => {
    // Navigate to create page
    await page.goto('/spaces');
    await expect(page.locator('[data-testid="spaces-page"]')).toBeVisible({ timeout: 10_000 });
    await page.getByRole('link', { name: /create space/i }).or(page.getByRole('button', { name: /create space/i })).click();

    // Should land on /space/new with the form in edit mode
    await expect(page).toHaveURL(/\/space\/new/);
    await expect(page.locator('[data-testid="space-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Fill the form
    await page.locator('#space-identifier').fill(CRUD_SPACE_ID);
    await page.locator('#space-name').fill(CRUD_SPACE_NAME);
    await page.locator('#space-description').fill(CRUD_SPACE_DESC);

    // Submit
    await page.getByRole('button', { name: /create space/i }).click();

    // Should redirect to the new space's detail page
    await expect(page).toHaveURL(new RegExp(`/space/${CRUD_SPACE_ID}`), { timeout: 10_000 });
    // Success banner should appear
    await expect(page.getByText(/created successfully/i)).toBeVisible({ timeout: 5_000 });
  });

  test('new space appears in the spaces list', async ({ page }) => {
    await page.goto('/spaces');
    await expect(page.locator('[data-testid="spaces-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(`[data-testid="space-card-${CRUD_SPACE_ID}"]`)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(`[data-testid="space-card-${CRUD_SPACE_ID}"]`)).toContainText(CRUD_SPACE_NAME);
  });

  test('update space name and description', async ({ page }) => {
    await page.goto(`/space/${CRUD_SPACE_ID}`);
    await expect(page.locator('[data-testid="space-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click Settings tab to see the form fields
    await page.getByRole('button', { name: /settings/i }).click();

    // Click Edit button
    await page.getByRole('button', { name: /edit/i }).click();

    // Clear and fill updated values
    await page.locator('#space-name').clear();
    await page.locator('#space-name').fill(UPDATED_NAME);
    await page.locator('#space-description').clear();
    await page.locator('#space-description').fill(UPDATED_DESC);

    // Save
    await page.getByRole('button', { name: /save changes/i }).click();

    // Success banner
    await expect(page.getByText(/updated successfully/i)).toBeVisible({ timeout: 5_000 });

    // Verify the values persisted — reload and check
    await page.reload();
    await expect(page.locator('[data-testid="space-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: /settings/i }).click();
    await expect(page.locator('#space-name')).toHaveValue(UPDATED_NAME);
  });

  test('delete the space via the UI', async ({ page }) => {
    await page.goto(`/space/${CRUD_SPACE_ID}`);
    await expect(page.locator('[data-testid="space-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click Delete button
    await page.getByRole('button', { name: /delete/i }).first().click();

    // Confirm modal should appear
    await expect(page.getByText(/confirm delete/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/cannot be undone/i)).toBeVisible();

    // Confirm deletion
    await page.getByRole('button', { name: /delete space/i }).click();

    // Should redirect back to spaces list
    await expect(page).toHaveURL(/\/spaces/, { timeout: 10_000 });

    // The deleted space should no longer appear
    await expect(page.locator(`[data-testid="space-card-${CRUD_SPACE_ID}"]`)).not.toBeVisible({ timeout: 5_000 });
  });
});
