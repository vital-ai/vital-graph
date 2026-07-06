import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Tier 6 — Users CRUD Write Operations
 *
 * Tests the Create, Update, and Delete flows for users.
 * Cleans up the test user before/after via API.
 */

const CRUD_USERNAME = 'e2e_crud_testuser';
const CRUD_FULL_NAME = 'E2E CRUD Test User';
const CRUD_EMAIL = 'e2e_crud@test.local';
const CRUD_PASSWORD = 'TestPass123!';
const UPDATED_FULL_NAME = 'E2E Updated User';
const UPDATED_EMAIL = 'e2e_updated@test.local';

/** Delete the CRUD test user via API if it exists (idempotent cleanup). */
async function cleanupCrudUser() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  // List all users and delete any matching our test username
  const listResp = await ctx.get('/api/users', { headers });
  const { users } = await listResp.json();
  if (Array.isArray(users)) {
    for (const user of users) {
      if (user.username === CRUD_USERNAME) {
        await ctx.delete('/api/users', { params: { user_id: user.id }, headers });
      }
    }
  }
  await ctx.dispose();
}

test.describe('Users CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupCrudUser(); });
  test.afterAll(async () => { await cleanupCrudUser(); });

  test('create a new user via the UI', async ({ page }) => {
    await page.goto('/user/new');
    await expect(page.locator('[data-testid="user-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Verify we're on the create form
    await expect(page.getByText('Create User')).toBeVisible();

    // Fill the form
    await page.locator('#username').fill(CRUD_USERNAME);
    await page.locator('#full_name').fill(CRUD_FULL_NAME);
    await page.locator('#email').fill(CRUD_EMAIL);
    await page.locator('#password').fill(CRUD_PASSWORD);

    // Submit
    await page.getByRole('button', { name: /create/i }).first().click();

    // Success banner
    await expect(page.getByText(/user created/i)).toBeVisible({ timeout: 5_000 });
  });

  test('new user appears in the users list', async ({ page }) => {
    await page.goto('/users');
    await expect(page.locator('[data-testid="users-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for table to render
    await expect(page.locator('table')).toBeVisible({ timeout: 10_000 });

    // Verify the username appears
    await expect(page.locator('table').getByText(CRUD_USERNAME)).toBeVisible({ timeout: 5_000 });
  });

  test('update the user via the UI', async ({ page }) => {
    // Navigate to users list and click into our user
    await page.goto('/users');
    await expect(page.locator('[data-testid="users-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('table')).toBeVisible({ timeout: 10_000 });

    // Click the user link
    await page.locator('table').getByText(CRUD_USERNAME).click();
    await expect(page.locator('[data-testid="user-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Enter edit mode
    await page.getByRole('button', { name: /edit/i }).click();

    // Update fields
    await page.locator('#full_name').clear();
    await page.locator('#full_name').fill(UPDATED_FULL_NAME);
    await page.locator('#email').clear();
    await page.locator('#email').fill(UPDATED_EMAIL);

    // Save
    await page.locator('button', { hasText: 'Save' }).click();

    // Success banner
    await expect(page.getByText(/user updated/i)).toBeVisible({ timeout: 5_000 });

    // Reload the page to verify the update persisted
    await page.reload();
    await expect(page.locator('[data-testid="user-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(UPDATED_FULL_NAME)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(UPDATED_EMAIL)).toBeVisible();
  });

  test('delete the user via the UI', async ({ page }) => {
    await page.goto('/users');
    await expect(page.locator('[data-testid="users-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('table')).toBeVisible({ timeout: 10_000 });

    // Navigate to user detail
    await page.locator('table').getByText(CRUD_USERNAME).click();
    await expect(page.locator('[data-testid="user-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click Delete button
    await page.getByRole('button', { name: /delete/i }).click();

    // Confirm modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await expect(modal.getByText(/delete user/i)).toBeVisible();

    // Confirm deletion
    await modal.getByRole('button', { name: /delete/i }).first().click();

    // Should redirect to users list
    await expect(page).toHaveURL(/\/users$/, { timeout: 10_000 });

    // User should no longer appear
    await expect(page.locator('table').getByText(CRUD_USERNAME)).not.toBeVisible({ timeout: 5_000 });
  });
});
