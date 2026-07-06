import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Tier 7 — Triples CRUD Write Operations
 *
 * Tests the Add, List, Edit, and Delete flows for RDF triples
 * through the Triples page UI.
 */

const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);
const TEST_SUBJECT = 'urn:e2e:triples:test-subject';
const TEST_PREDICATE = 'http://vital.ai/ontology/vital-core#hasName';
const TEST_OBJECT = 'E2E Triple Test Value';
const UPDATED_OBJECT = 'E2E Triple Updated Value';

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

/** Delete any leftover test triples via API. */
async function cleanupTestTriples() {
  const { ctx, headers } = await getAuthHeaders();
  // List only triples with our test subject
  const resp = await ctx.get('/api/graphs/triples', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, page_size: 100, subject: TEST_SUBJECT },
    headers,
  });
  const data = await resp.json();
  const quads = data.results || [];
  if (quads.length > 0) {
    await ctx.delete('/api/graphs/triples', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID },
      headers,
      data: { quads },
    });
  }
  await ctx.dispose();
}

// ── tests ────────────────────────────────────────────────────────────────────

test.describe('Triples CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await cleanupTestTriples(); });
  test.afterAll(async () => { await cleanupTestTriples(); });

  test('add a triple via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/triples`);
    await expect(page.locator('[data-testid="triples-page"]')).toBeVisible({ timeout: 10_000 });

    // Click "Add Triple"
    await page.getByRole('button', { name: /add triple/i }).click();

    // Fill the modal form
    await page.locator('#m-subject').fill(TEST_SUBJECT);
    await page.locator('#m-predicate').fill(TEST_PREDICATE);
    // Switch object type to literal
    await page.locator('#m-otype').selectOption('literal');
    await page.locator('#m-object').fill(TEST_OBJECT);

    // Submit
    await page.getByRole('button', { name: /add triple/i }).last().click();

    // Wait for list to refresh with the new triple
    await expect(page.getByText(TEST_OBJECT).first()).toBeVisible({ timeout: 10_000 });
  });

  test('triple appears in the list via filter', async ({ page }) => {
    // First, confirm the triple exists via API before testing UI filter
    const { ctx, headers } = await getAuthHeaders();
    const apiCheck = await ctx.get('/api/graphs/triples', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, page_size: 10, subject: TEST_SUBJECT },
      headers,
    });
    const apiData = await apiCheck.json();
    expect(apiData.results?.length, 'API should find the test triple').toBeGreaterThan(0);
    await ctx.dispose();

    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/triples`);
    await expect(page.locator('[data-testid="triples-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for initial table load
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 15_000 });

    // Wait for network to settle before interacting with filter
    await page.waitForLoadState('networkidle');

    // Type filter and wait for debounce + filtered API response
    const filterInput = page.getByPlaceholder('Filter triples...');
    const responsePromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/graphs/triples') && resp.url().includes('object_filter'),
    );
    await filterInput.fill(TEST_OBJECT);
    const filterResp = await responsePromise;
    const filterBody = await filterResp.json();
    expect(filterBody.total_count, `object_filter API returned 0 for "${TEST_OBJECT}"`).toBeGreaterThan(0);

    // The filtered result should show our triple's subject
    const row = page.locator('table tbody tr', { hasText: 'triples:test-subject' });
    await expect(row.first()).toBeVisible({ timeout: 10_000 });
  });

  test('edit the triple via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/triples`);
    await expect(page.locator('[data-testid="triples-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for initial load then filter to find our triple
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 10_000 });
    await page.getByPlaceholder('Filter triples...').fill(TEST_OBJECT);

    // Find the row with our test value and click edit
    const row = page.locator('table tbody tr', { hasText: TEST_OBJECT });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('button[title="Edit"]').click();

    // Modal should show "Edit Triple"
    await expect(page.getByText('Edit Triple')).toBeVisible({ timeout: 5_000 });

    // Clear and update the object value
    await page.locator('#m-object').clear();
    await page.locator('#m-object').fill(UPDATED_OBJECT);

    // Save
    await page.getByRole('button', { name: /save changes/i }).click();

    // Modal should close
    await expect(page.getByText('Edit Triple')).not.toBeVisible({ timeout: 5_000 });

    // Clear old filter and search for the updated value
    const filterInput = page.getByPlaceholder('Filter triples...');
    await filterInput.clear();
    await filterInput.fill(UPDATED_OBJECT);

    // Updated value should appear in a row
    const updatedRow = page.locator('table tbody tr', { hasText: UPDATED_OBJECT });
    await expect(updatedRow.first()).toBeVisible({ timeout: 10_000 });
  });

  test('delete the triple via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/triples`);
    await expect(page.locator('[data-testid="triples-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for initial load then filter to find our updated triple
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 10_000 });
    await page.getByPlaceholder('Filter triples...').fill(UPDATED_OBJECT);

    // Find the row with our updated value and click delete
    const row = page.locator('table tbody tr', { hasText: UPDATED_OBJECT });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('button[title="Delete"]').click();

    // Confirm in the delete modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal.getByText('Delete Triple')).toBeVisible({ timeout: 5_000 });
    await modal.getByRole('button', { name: /delete/i }).click();

    // Triple should be removed
    await expect(row).not.toBeVisible({ timeout: 5_000 });
  });
});
