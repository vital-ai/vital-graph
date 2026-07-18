import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID, ENTITIES } from '../seed-constants';

/**
 * Tier 7 — KG Entities CRUD Write Operations
 *
 * Tests the Create, List, Update, and Delete flows for KG entities.
 * Uses the seeded space/graph and cleans up the test entity via API.
 */

const CRUD_ENTITY_NAME = 'E2E CRUD Test Entity';
const UPDATED_ENTITY_DESC = 'Updated by E2E CRUD test';
const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
const HAS_DESC = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription';
const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);

/** Delete any entity with CRUD_ENTITY_NAME via API (idempotent cleanup). */
async function cleanupCrudEntity() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  // Search for entities with our name
  const listResp = await ctx.get('/api/graphs/kgentities', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, search: CRUD_ENTITY_NAME, page_size: 100 },
    headers,
  });
  const data = await listResp.json();
  const quads = data.results || [];

  // Extract unique subject URIs (strip angle brackets)
  const uris: string[] = [...new Set(quads.map((q: { s: string }) => q.s.replace(/^<|>$/g, '')))] as string[];
  for (const uri of uris) {
    await ctx.delete('/api/graphs/kgentities', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
      headers,
    });
  }
  await ctx.dispose();
}

test.describe('KG Entities CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupCrudEntity(); });
  test.afterAll(async () => { await cleanupCrudEntity(); });

  test('create a new entity via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/entity/new?mode=create`);
    await expect(page.locator('[data-testid="kgentity-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('object-detail-title')).toHaveText('Create KG Entity');

    // Add a hasName property via the "Add Property" form
    await page.locator('#new-predicate').fill(HAS_NAME);
    await page.locator('#new-value').fill(CRUD_ENTITY_NAME);
    await page.locator('button', { hasText: 'Add' }).click();

    // Click Create
    await page.locator('button', { hasText: 'Create' }).click();

    // Should redirect back to the entities list
    await expect(page).toHaveURL(/\/objects\/kgentities/, { timeout: 10_000 });
  });

  test('new entity appears in the entities list', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgentities`);
    await expect(page.locator('[data-testid="kgentities-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for entities table to render
    await expect(page.locator('[data-testid="entities-table"]')).toBeVisible({ timeout: 10_000 });

    // Verify entity name appears
    await expect(page.locator('[data-testid="entities-table"]').getByText(CRUD_ENTITY_NAME)).toBeVisible({ timeout: 5_000 });
  });

  test('update the entity via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgentities`);
    await expect(page.locator('[data-testid="entities-table"]')).toBeVisible({ timeout: 10_000 });

    // Click the View button on the row with our entity
    const entityRow = page.locator('[data-testid="entity-row"]', { hasText: CRUD_ENTITY_NAME });
    await entityRow.locator('button[title="View"]').click();

    // Wait for detail page
    await expect(page.locator('[data-testid="kgentity-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('object-detail-title')).toHaveText('KG Entity Details');

    // Switch to edit mode
    await page.locator('button', { hasText: 'Edit' }).click();

    // Add a description property via the "Add Property" form
    await page.locator('#new-predicate').fill(HAS_DESC);
    await page.locator('#new-value').fill(UPDATED_ENTITY_DESC);
    await page.locator('button', { hasText: 'Add' }).click();

    // Click Save
    await page.locator('button', { hasText: 'Save' }).click();

    // Should switch back to view mode — verify the description appears in properties
    await expect(page.getByText(UPDATED_ENTITY_DESC)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the entity via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgentities`);
    await expect(page.locator('[data-testid="entities-table"]')).toBeVisible({ timeout: 10_000 });

    // Click the Delete (trash) button on the row with our entity
    const entityRow = page.locator('[data-testid="entity-row"]', { hasText: CRUD_ENTITY_NAME });
    await expect(entityRow).toBeVisible({ timeout: 5_000 });
    await entityRow.locator('button[title="Delete"]').click();

    // Confirm modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await expect(modal.getByText(/delete entity/i)).toBeVisible();

    // Click Delete in the modal
    await modal.getByRole('button', { name: /delete/i }).first().click();

    // Entity should be removed from the list
    await expect(
      page.locator('[data-testid="entity-row"]', { hasText: CRUD_ENTITY_NAME })
    ).not.toBeVisible({ timeout: 5_000 });
  });
});

// ── Visualize in Graph button ─────────────────────────────────────────────

test.describe('KG Entity — Visualize in Graph', () => {
  test('entity detail page shows Visualize in Graph button', async ({ page }) => {
    // Navigate to the seeded Alice entity detail page
    const entityUrl = `/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/entity/${encodeURIComponent(ENTITIES.alice.uri)}`;
    await page.goto(entityUrl);
    await expect(page.locator('[data-testid="kgentity-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // The "Visualize in Graph" button should be visible
    await expect(page.getByText('Visualize in Graph')).toBeVisible({ timeout: 5_000 });
  });

  test('clicking Visualize in Graph navigates to visualization page', async ({ page }) => {
    const entityUrl = `/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/entity/${encodeURIComponent(ENTITIES.alice.uri)}`;
    await page.goto(entityUrl);
    await expect(page.locator('[data-testid="kgentity-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click the Visualize in Graph button — opens a session picker menu
    await page.getByText('Visualize in Graph').click();

    // Either a dropdown appears (if sessions exist) or it navigates directly.
    // Click "+ New session" if the dropdown is shown, otherwise we already navigated.
    const newSessionBtn = page.getByText('+ New session');
    if (await newSessionBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await newSessionBtn.click();
    }

    // Should navigate to the visualization page
    await expect(page.locator('[data-testid="graph-visualization-page"]')).toBeVisible({ timeout: 10_000 });

    // The URL should contain /visualization
    await expect(page).toHaveURL(/\/visualization/);
  });
});
