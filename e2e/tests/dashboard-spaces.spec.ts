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

  // The dashboard renders `spaces.slice(0, 5)` — a TOP-FIVE summary, not a list.
  // Both tests below used to assert that the seeded space appeared there by name,
  // which holds only while fewer than five spaces sort ahead of it. On a machine
  // carrying perf fixtures (`apitest_*`, `kg_load_test`, `sp_*`) it does not, and
  // they failed for a reason that had nothing to do with the dashboard.
  //
  // Same remedy as the object lists in issues/022: assert the STRUCTURE where the
  // view is capped, and scope the identity assertion to a view that can be
  // narrowed. `global-setup` already warns when foreign spaces are present.

  test('space summaries list spaces as links', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="home-page"]')).toBeVisible({ timeout: 10_000 });
    const links = page.locator('[data-testid^="space-link-"]');
    await expect(links.first()).toBeVisible({ timeout: 10_000 });
    // Capped at five by Home.tsx; asserting the cap is what makes the
    // "not on page 1" failure impossible to reintroduce here.
    expect(await links.count()).toBeGreaterThan(0);
    expect(await links.count()).toBeLessThanOrEqual(5);
  });

  test('the seeded space is listed and reachable, found by search', async ({ page }) => {
    await page.goto('/spaces');
    await expect(page.locator('[data-testid="spaces-page"]')).toBeVisible({ timeout: 10_000 });
    // Narrow to the space under test rather than hoping it is on screen.
    await page.getByPlaceholder('Search spaces...').fill(SPACE_ID);
    const card = page.locator(`[data-testid="space-card-${SPACE_ID}"]`);
    await expect(card).toBeVisible({ timeout: 10_000 });
    await expect(card).toContainText(SPACE_NAME);
  });

  test('a space link navigates to that space detail', async ({ page }) => {
    await page.goto('/');
    const link = page.locator('[data-testid^="space-link-"]').first();
    await expect(link).toBeVisible({ timeout: 10_000 });
    // Whichever space the summary happens to show: the behaviour under test is
    // that the link goes to ITS detail page, not that a particular space is on it.
    const testId = await link.getAttribute('data-testid');
    const spaceId = (testId || '').replace('space-link-', '');
    expect(spaceId).toBeTruthy();
    await link.click();
    await expect(page).toHaveURL(new RegExp(`/space/${spaceId}`));
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
