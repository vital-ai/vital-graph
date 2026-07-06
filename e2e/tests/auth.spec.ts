import { test, expect } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Tier 1 — Authentication & Protected Routes
 *
 * Tests login flow, invalid credentials, protected route redirect,
 * and session persistence.
 */
test.describe('Authentication', () => {
  // Use a fresh context (no stored auth) for login tests
  test.use({ storageState: { cookies: [], origins: [] } });

  test('login page renders with form', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('[data-testid="login-page"]')).toBeVisible();
    await expect(page.locator('[data-testid="login-form"]')).toBeVisible();
    await expect(page.getByLabel('Username')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
    await expect(page.locator('[data-testid="login-submit"]')).toBeVisible();
  });

  test('valid credentials → redirect to dashboard', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill(ADMIN_USER);
    await page.getByLabel('Password').fill(ADMIN_PASS);
    await page.locator('[data-testid="login-submit"]').click();
    await expect(page).not.toHaveURL(/login/, { timeout: 15_000 });
    await expect(page.locator('[data-testid="home-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('invalid credentials → error shown', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('wrong_user');
    await page.getByLabel('Password').fill('wrong_pass');
    await page.locator('[data-testid="login-submit"]').click();
    // Should stay on login page and show an error
    await expect(page).toHaveURL(/login/);
    await expect(page.getByText(/invalid|error|failed|incorrect/i)).toBeVisible({ timeout: 5_000 });
  });

  test('unauthenticated access → redirect to login', async ({ page }) => {
    await page.goto('/spaces');
    await expect(page).toHaveURL(/login/);
  });

  test('unauthenticated access to admin → redirect to login', async ({ page }) => {
    await page.goto('/admin');
    await expect(page).toHaveURL(/login/);
  });
});
