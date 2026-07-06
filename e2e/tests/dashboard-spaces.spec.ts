import { test, expect } from '@playwright/test';
import { SPACE_ID, SPACE_NAME, ADMIN_USER } from '../seed-constants';

/**
 * Tier 2 — Dashboard, Spaces, and Users
 */

// ---------- Dashboard / Home -----------------------------------------------

test.describe('Dashboard', () => {
  test('displays stat cards', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="home-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="home-title"]')).toHaveText('Dashboard');
    await expect(page.locator('[data-testid="stats-row"]')).toBeVisible();
  });

  test('shows seeded space in space summaries', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="home-page"]')).toBeVisible({ timeout: 10_000 });
    // The seeded space should appear as a link
    await expect(page.locator(`[data-testid="space-link-${SPACE_ID}"]`)).toBeVisible({ timeout: 10_000 });
  });

  test('space link navigates to space detail', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator(`[data-testid="space-link-${SPACE_ID}"]`)).toBeVisible({ timeout: 10_000 });
    await page.locator(`[data-testid="space-link-${SPACE_ID}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/space/${SPACE_ID}`));
  });
});

// ---------- Spaces ---------------------------------------------------------

test.describe('Spaces', () => {
  test('list page shows title and grid', async ({ page }) => {
    await page.goto('/spaces');
    await expect(page.locator('[data-testid="spaces-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="spaces-title"]')).toHaveText('Spaces');
    await expect(page.locator('[data-testid="spaces-grid"]')).toBeVisible();
  });

  test('seeded space card is visible with correct name', async ({ page }) => {
    await page.goto('/spaces');
    const card = page.locator(`[data-testid="space-card-${SPACE_ID}"]`);
    await expect(card).toBeVisible({ timeout: 10_000 });
    await expect(card).toContainText(SPACE_NAME);
  });

  test('clicking space card navigates to detail', async ({ page }) => {
    await page.goto('/spaces');
    await page.locator(`[data-testid="space-card-${SPACE_ID}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/space/${SPACE_ID}`));
    await expect(page.locator('[data-testid="space-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('space detail shows space name', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}`);
    await expect(page.locator('[data-testid="space-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SPACE_NAME)).toBeVisible();
  });
});

// ---------- Users ----------------------------------------------------------

test.describe('Users', () => {
  test('list page loads and shows admin user', async ({ page }) => {
    await page.goto('/users');
    await expect(page.locator('[data-testid="users-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: new RegExp(ADMIN_USER) }).first()).toBeVisible({ timeout: 10_000 });
  });

  test('clicking admin user navigates to detail', async ({ page }) => {
    await page.goto('/users');
    await expect(page.locator('[data-testid="users-page"]')).toBeVisible({ timeout: 10_000 });
    // Find and click the admin user row/link
    await page.getByRole('link', { name: new RegExp(ADMIN_USER) }).first().click();
    await expect(page).toHaveURL(/\/user\//);
    await expect(page.locator('[data-testid="user-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});
