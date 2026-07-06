import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Tier 7 — KG Frames CRUD Write Operations
 *
 * Tests the Create, List, Update, and Delete flows for KG frames.
 * Uses the seeded space/graph and cleans up the test frame via API.
 */

const CRUD_FRAME_NAME = 'E2E CRUD Test Frame';
const UPDATED_FRAME_DESC = 'Updated by E2E CRUD test';
const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
const HAS_DESC = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription';
const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);

/** Delete any frame with CRUD_FRAME_NAME via API (idempotent cleanup). */
async function cleanupCrudFrame() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  const listResp = await ctx.get('/api/graphs/kgframes', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, search: CRUD_FRAME_NAME, page_size: 100 },
    headers,
  });
  const data = await listResp.json();
  const quads = data.results || [];

  const uris: string[] = [...new Set(quads.map((q: { s: string }) => q.s.replace(/^<|>$/g, '')))] as string[];
  for (const uri of uris) {
    await ctx.delete('/api/graphs/kgframes', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
      headers,
    });
  }
  await ctx.dispose();
}

test.describe('KG Frames CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupCrudFrame(); });
  test.afterAll(async () => { await cleanupCrudFrame(); });

  test('create a new frame via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/frame/new?mode=create`);
    await expect(page.locator('[data-testid="kgframe-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('object-detail-title')).toHaveText('Create KG Frame');

    // Add a hasName property via the "Add Property" form
    await page.locator('#new-predicate').fill(HAS_NAME);
    await page.locator('#new-value').fill(CRUD_FRAME_NAME);
    await page.locator('button', { hasText: 'Add' }).click();

    // Click Create
    await page.locator('button', { hasText: 'Create' }).click();

    // Should redirect back to the frames list
    await expect(page).toHaveURL(/\/objects\/kgframes/, { timeout: 10_000 });
  });

  test('new frame appears in the frames list', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgframes`);
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for frames table to render (at least one row)
    await expect(page.locator('[data-testid="frame-row"]').first()).toBeVisible({ timeout: 10_000 });

    // Verify frame name appears
    await expect(page.locator('[data-testid="frame-row"]', { hasText: CRUD_FRAME_NAME })).toBeVisible({ timeout: 5_000 });
  });

  test('update the frame via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgframes`);
    await expect(page.locator('[data-testid="frame-row"]').first()).toBeVisible({ timeout: 10_000 });

    // Click the View button on the row with our frame
    const frameRow = page.locator('[data-testid="frame-row"]', { hasText: CRUD_FRAME_NAME });
    await frameRow.locator('button[title="View"]').click();

    // Wait for detail page
    await expect(page.locator('[data-testid="kgframe-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('object-detail-title')).toHaveText('KG Frame Details');

    // Switch to edit mode
    await page.locator('button', { hasText: 'Edit' }).click();

    // Add a description property via the "Add Property" form
    await page.locator('#new-predicate').fill(HAS_DESC);
    await page.locator('#new-value').fill(UPDATED_FRAME_DESC);
    await page.locator('button', { hasText: 'Add' }).click();

    // Click Save
    await page.locator('button', { hasText: 'Save' }).click();

    // Should switch back to view mode — verify the description appears in properties
    await expect(page.getByText(UPDATED_FRAME_DESC)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the frame via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgframes`);
    await expect(page.locator('[data-testid="frame-row"]').first()).toBeVisible({ timeout: 10_000 });

    // Click the Delete (trash) button on the row with our frame
    const frameRow = page.locator('[data-testid="frame-row"]', { hasText: CRUD_FRAME_NAME });
    await expect(frameRow).toBeVisible({ timeout: 5_000 });
    await frameRow.locator('button[title="Delete"]').click();

    // Confirm modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await expect(modal.getByText(/delete frame/i)).toBeVisible();

    // Click Delete in the modal
    await modal.getByRole('button', { name: /delete/i }).first().click();

    // Frame should be removed from the list
    await expect(
      page.locator('[data-testid="frame-row"]', { hasText: CRUD_FRAME_NAME })
    ).not.toBeVisible({ timeout: 5_000 });
  });
});
