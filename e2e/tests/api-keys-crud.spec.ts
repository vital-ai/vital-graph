import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Tier 6 — API Keys CRUD Write Operations
 *
 * Tests the Create and Revoke flows for API keys.
 * Cleans up test keys before/after via API.
 */

const CRUD_KEY_NAME = 'E2E CRUD Test Key';

/** Remove any API keys matching the CRUD test name (idempotent cleanup). */
async function cleanupCrudKeys() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  // List all keys and revoke any matching our test name
  const listResp = await ctx.get('/api/keys', { headers });
  const { keys } = await listResp.json();
  if (Array.isArray(keys)) {
    for (const key of keys) {
      if (key.name === CRUD_KEY_NAME && key.is_active) {
        await ctx.delete('/api/keys', { params: { key_id: key.key_id }, headers });
      }
    }
  }
  await ctx.dispose();
}

test.describe('API Keys CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupCrudKeys(); });
  test.afterAll(async () => { await cleanupCrudKeys(); });

  test('create a new API key via the UI', async ({ page }) => {
    await page.goto('/api-keys');
    await expect(page.locator('[data-testid="api-keys-page"]')).toBeVisible({ timeout: 10_000 });

    // Click "Create Key" button in header
    await page.getByRole('button', { name: /create key/i }).click();

    // Modal should appear
    await expect(page.getByText('Create API Key')).toBeVisible({ timeout: 5_000 });

    // Fill the form
    await page.locator('#key-name').fill(CRUD_KEY_NAME);
    // Leave expiry as "Never expires" (default)

    // Submit the form
    await page.locator('form').getByRole('button', { name: /create key/i }).click();

    // Success alert with the revealed key
    await expect(page.getByText(/api key created successfully/i)).toBeVisible({ timeout: 5_000 });
    // The revealed key value (vg_ prefix) should be visible inside the success alert
    const successAlert = page.locator('[role="alert"]', { hasText: /api key created successfully/i });
    await expect(successAlert.locator('code').first()).toHaveText(/^vg_/);
  });

  test('new key appears in the keys table as active', async ({ page }) => {
    await page.goto('/api-keys');
    await expect(page.locator('[data-testid="api-keys-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for table to render
    await expect(page.locator('table')).toBeVisible({ timeout: 10_000 });

    // Find the row that has both our key name AND "Active" status
    const activeRow = page.locator('tr', { has: page.getByText(CRUD_KEY_NAME) })
      .filter({ has: page.getByText('Active') });
    await expect(activeRow).toBeVisible({ timeout: 5_000 });
    await expect(activeRow.getByText(CRUD_KEY_NAME)).toBeVisible();
  });

  test('revoke the API key via the UI', async ({ page }) => {
    await page.goto('/api-keys');
    await expect(page.locator('[data-testid="api-keys-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('table')).toBeVisible({ timeout: 10_000 });

    // Find the active row with our key name (there may be leftover revoked ones)
    const activeRow = page.locator('tr', { has: page.getByText(CRUD_KEY_NAME) })
      .filter({ has: page.getByText('Active') });
    await expect(activeRow).toBeVisible({ timeout: 5_000 });

    // Click the revoke (trash) button in the active row
    await activeRow.getByRole('button').click();

    // Revoke confirmation modal should appear
    await expect(page.getByText(/revoke api key/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/cannot be undone/i)).toBeVisible();

    // Confirm revocation
    await page.getByRole('button', { name: /revoke key/i }).click();

    // After revocation, no active row with our key name should exist
    await expect(
      page.locator('tr', { has: page.getByText(CRUD_KEY_NAME) })
        .filter({ has: page.getByText('Active') })
    ).not.toBeVisible({ timeout: 5_000 });
  });
});
