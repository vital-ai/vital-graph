import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Tier 7 — KG Relations CRUD
 *
 * Creates two KG entities via API, then creates a relation between them,
 * verifies the relation appears in the UI, and deletes it via the UI modal.
 */

const ENTITY_A_URI = 'urn:e2e:relation-test:entity-a';
const ENTITY_B_URI = 'urn:e2e:relation-test:entity-b';
const ENTITY_A_NAME = 'Relation Test Entity A';
const ENTITY_B_NAME = 'Relation Test Entity B';
const RELATION_URI = 'urn:e2e:relation:crud_test';
const RELATION_NAME = 'E2E CRUD Test Relation';
const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);

const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const KG_ENTITY_TYPE = 'http://vital.ai/ontology/haley-ai-kg#KGEntity';
const EDGE_TYPE = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation';
const HAS_EDGE_SOURCE = 'http://vital.ai/ontology/vital-core#hasEdgeSource';
const HAS_EDGE_DEST = 'http://vital.ai/ontology/vital-core#hasEdgeDestination';
const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';

// ── helpers ──────────────────────────────────────────────────────────────────

async function getAuthHeaders() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  return { ctx, headers: { Authorization: `Bearer ${access_token}` } };
}

/** Create two KG entities that the relation will connect. */
async function createTestEntities() {
  const { ctx, headers } = await getAuthHeaders();
  for (const [uri, name] of [[ENTITY_A_URI, ENTITY_A_NAME], [ENTITY_B_URI, ENTITY_B_NAME]]) {
    await ctx.post('/api/graphs/kgentities', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, operation_mode: 'create' },
      headers,
      data: {
        quads: [
          { s: `<${uri}>`, p: `<${RDF_TYPE}>`, o: `<${KG_ENTITY_TYPE}>` },
          { s: `<${uri}>`, p: `<${HAS_NAME}>`, o: `"${name}"` },
        ],
      },
    });
  }
  await ctx.dispose();
}

/** Create the test relation between entity A → entity B via API. */
async function createTestRelation() {
  const { ctx, headers } = await getAuthHeaders();
  const quads = [
    { s: `<${RELATION_URI}>`, p: `<${RDF_TYPE}>`, o: `<${EDGE_TYPE}>` },
    { s: `<${RELATION_URI}>`, p: `<${HAS_EDGE_SOURCE}>`, o: `<${ENTITY_A_URI}>` },
    { s: `<${RELATION_URI}>`, p: `<${HAS_EDGE_DEST}>`, o: `<${ENTITY_B_URI}>` },
    { s: `<${RELATION_URI}>`, p: `<${HAS_NAME}>`, o: `"${RELATION_NAME}"` },
  ];
  await ctx.post('/api/graphs/kgrelations', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, operation_mode: 'create' },
    headers,
    data: { quads },
  });
  await ctx.dispose();
}

/** Delete the test relation and entities via API (idempotent cleanup). */
async function cleanupAll() {
  const { ctx, headers } = await getAuthHeaders();

  // Delete relation
  const listResp = await ctx.get('/api/graphs/kgrelations', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, page_size: 200 },
    headers,
  });
  const data = await listResp.json();
  const quads = data.results || [];
  const relUris: string[] = [...new Set(
    quads
      .map((q: { s: string }) => q.s.replace(/^<|>$/g, ''))
      .filter((u: string) => u.includes('e2e:relation:crud_test')),
  )] as string[];

  if (relUris.length > 0) {
    await ctx.delete('/api/graphs/kgrelations', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID },
      headers,
      data: { relation_uris: relUris },
    });
  }

  // Delete entities
  for (const uri of [ENTITY_A_URI, ENTITY_B_URI]) {
    await ctx.delete('/api/graphs/kgentities', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
      headers,
    });
  }
  await ctx.dispose();
}

// ── tests ────────────────────────────────────────────────────────────────────

test.describe('KG Relations CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => {
    await cleanupAll();
    await createTestEntities();
    await createTestRelation();
  });
  test.afterAll(async () => {
    await cleanupAll();
  });

  test('page loads with KG Relations title', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgrelations`);
    await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="kgrelations-title"]')).toHaveText('KG Relations');
  });

  test('created relation appears in the list with correct source and destination', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgrelations`);
    await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for table rows to render
    await expect(page.locator('[data-testid="relation-row"]').first()).toBeVisible({ timeout: 15_000 });

    // Verify the test relation name
    const row = page.locator('[data-testid="relation-row"]', { hasText: RELATION_NAME });
    await expect(row).toBeVisible({ timeout: 5_000 });

    // Verify source and destination entity URIs are shown
    await expect(row.getByText(ENTITY_A_URI)).toBeVisible();
    await expect(row.getByText(ENTITY_B_URI)).toBeVisible();

    // Verify Edge type badge
    await expect(row.getByText('Edge_hasKGRelation')).toBeVisible();
  });

  test('view button navigates to relation detail page', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgrelations`);
    await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for our relation row
    const row = page.locator('[data-testid="relation-row"]', { hasText: RELATION_NAME });
    await expect(row).toBeVisible({ timeout: 15_000 });

    // Click the View (eye) button — first button in the row
    await row.locator('button').first().click();

    // Should navigate to the relation detail page
    await expect(page.locator('[data-testid="kgrelation-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('relation detail page shows properties and Visualize button', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgrelations`);
    await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 10_000 });

    // Navigate to detail via View button
    const row = page.locator('[data-testid="relation-row"]', { hasText: RELATION_NAME });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.locator('button').first().click();
    await expect(page.locator('[data-testid="kgrelation-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Properties table should contain the edge source and destination URIs
    await expect(page.getByText(ENTITY_A_URI)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(ENTITY_B_URI)).toBeVisible();

    // Should display the "Visualize in Graph" button
    await expect(page.getByText('Visualize in Graph')).toBeVisible();
  });

  test('delete the relation via the detail page', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgrelations`);
    await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 10_000 });

    // Navigate to detail via View button
    const row = page.locator('[data-testid="relation-row"]', { hasText: RELATION_NAME });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.locator('button').first().click();
    await expect(page.locator('[data-testid="kgrelation-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Click the Delete KG Relation button on the detail page
    await page.locator('button', { hasText: 'Delete KG Relation' }).click();

    // Confirm in the delete modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await modal.locator('button', { hasText: 'Delete' }).first().click();

    // Should redirect back to the relations list
    await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 10_000 });

    // Relation should be removed from the list
    await expect(
      page.locator('[data-testid="relation-row"]', { hasText: RELATION_NAME })
    ).not.toBeVisible({ timeout: 5_000 });
  });
});
