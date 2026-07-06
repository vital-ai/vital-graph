import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID } from '../seed-constants';

/**
 * Tier 6 — Graphs CRUD Write Operations
 *
 * Tests the Create and Delete flows for graphs within the seeded space.
 * Uses a fixed graph URI and cleans up before/after via API.
 */

const CRUD_GRAPH_URI = 'urn:e2e:crud:test-graph';

/** Delete the CRUD graph via API if it exists (idempotent cleanup). */
async function cleanupCrudGraph() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  await ctx.delete('/api/graphs/graph', {
    params: { space_id: SPACE_ID, graph_uri: CRUD_GRAPH_URI },
    headers: { Authorization: `Bearer ${access_token}` },
  });
  await ctx.dispose();
}

test.describe('Graphs CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  // Cleanup before and after to avoid leftover state
  test.beforeAll(async () => { await cleanupCrudGraph(); });
  test.afterAll(async () => { await cleanupCrudGraph(); });

  test('create a new graph via the UI', async ({ page }) => {
    // Navigate to graphs list for the seeded space
    await page.goto(`/space/${SPACE_ID}/graphs`);
    await expect(page.locator('[data-testid="graphs-page"]')).toBeVisible({ timeout: 10_000 });

    // Click "New Graph" button
    await page.getByRole('button', { name: /new graph/i }).click();

    // Should land on the create page
    await expect(page).toHaveURL(new RegExp(`/space/${SPACE_ID}/graph/new`));
    await expect(page.locator('[data-testid="graph-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Fill graph URI
    await page.locator('#graph_uri').fill(CRUD_GRAPH_URI);

    // Submit
    await page.getByRole('button', { name: /create graph/i }).click();

    // Success banner should appear
    await expect(page.getByText(/created successfully/i)).toBeVisible({ timeout: 5_000 });

    // Should redirect back to graphs list after delay
    await expect(page).toHaveURL(new RegExp(`/space/${SPACE_ID}/graphs$`), { timeout: 10_000 });
  });

  test('new graph appears in the graphs list', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graphs`);
    await expect(page.locator('[data-testid="graphs-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="graphs-grid"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId(`graph-card-${CRUD_GRAPH_URI}`)).toBeVisible({ timeout: 10_000 });
  });

  test('navigate to graph detail page', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${encodeURIComponent(CRUD_GRAPH_URI)}`);
    await expect(page.locator('[data-testid="graph-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Verify the graph URI is shown on the detail page
    await expect(page.getByText(CRUD_GRAPH_URI).first()).toBeVisible({ timeout: 5_000 });

    // Verify the Browse Content section is rendered
    await expect(page.getByText('Browse Content')).toBeVisible();
  });

  test('purge the graph via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${encodeURIComponent(CRUD_GRAPH_URI)}`);
    await expect(page.locator('[data-testid="graph-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click the Purge button
    await page.getByRole('button', { name: /purge/i }).first().click();

    // Confirm modal should appear
    const modal = page.locator('[role="dialog"]');
    await expect(modal.getByText(/purge graph/i)).toBeVisible({ timeout: 5_000 });

    // Confirm purge
    await modal.getByRole('button', { name: /purge/i }).click();

    // Success banner
    await expect(page.getByText(/purged successfully/i)).toBeVisible({ timeout: 5_000 });
  });

  test('delete the graph via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${encodeURIComponent(CRUD_GRAPH_URI)}`);
    await expect(page.locator('[data-testid="graph-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click first Delete button (header actions)
    await page.getByRole('button', { name: /delete/i }).first().click();

    // Confirm modal should appear
    await expect(page.getByText(/delete graph/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/cannot be undone/i)).toBeVisible();

    // Confirm deletion via the modal button
    await page.locator('[role="dialog"]').getByRole('button', { name: /^delete$/i }).click();

    // Should redirect back to graphs list
    await expect(page).toHaveURL(new RegExp(`/space/${SPACE_ID}/graphs`), { timeout: 10_000 });

    // The deleted graph should no longer appear
    await expect(page.getByTestId(`graph-card-${CRUD_GRAPH_URI}`)).not.toBeVisible({ timeout: 5_000 });
  });
});
