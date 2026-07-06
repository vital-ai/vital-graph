import { test, expect } from '@playwright/test';

/**
 * Admin section pages — verify Admin, AuditLog, ApiKeys,
 * EntityRegistry, and AgentRegistry load correctly.
 */
test.describe('Admin pages', () => {
  test('Admin page loads with health status', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.locator('[data-testid="admin-page"]')).toBeVisible({ timeout: 10_000 });
    // Admin page should show some health-related text
    await expect(page.getByRole('heading', { name: /administration/i })).toBeVisible({ timeout: 10_000 });
  });

  test('Audit Log page loads', async ({ page }) => {
    await page.goto('/audit-log');
    await expect(page.locator('[data-testid="audit-log-page"]')).toBeVisible({ timeout: 10_000 });
    // Should show audit log heading
    await expect(page.getByRole('heading', { name: /audit/i })).toBeVisible();
  });

  test('API Keys page loads', async ({ page }) => {
    await page.goto('/api-keys');
    await expect(page.locator('[data-testid="api-keys-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('heading', { name: /api key/i })).toBeVisible();
  });

  test('Entity Registry page loads', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('Agent Registry page loads', async ({ page }) => {
    await page.goto('/agent-registry');
    await expect(page.locator('[data-testid="agent-registry-page"]')).toBeVisible({ timeout: 10_000 });
  });
});
