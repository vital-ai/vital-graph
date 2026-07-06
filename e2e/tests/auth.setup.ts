import { test as setup, expect } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

const AUTH_FILE = '.auth/user.json';

/**
 * Authenticate once and persist browser storage state.
 *
 * All subsequent tests in the "chromium" project use the saved
 * storageState so they start already logged in.
 */
setup('authenticate', async ({ page }) => {
  // Navigate to the login page
  await page.goto('/');

  // Fill login form
  await page.getByLabel('Username').fill(ADMIN_USER);
  await page.getByLabel('Password').fill(ADMIN_PASS);
  await page.getByRole('button', { name: /sign in|log in/i }).click();

  // Wait for redirect to the dashboard / home page
  await expect(page).not.toHaveURL(/login/, { timeout: 15_000 });

  // Persist authentication state
  await page.context().storageState({ path: AUTH_FILE });
});
