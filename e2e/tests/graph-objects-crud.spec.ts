import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Tier 7 — Graph Objects CRUD Write Operations
 *
 * Tests the Create, List, Update, and Delete flows for generic graph objects
 * through the Graph Objects UI.
 */

const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
const VALID_RDF_TYPE = 'http://vital.ai/ontology/vital-core#VITAL_Node';
const CRUD_OBJECT_NAME = 'E2E Graph Object Test';
const UPDATED_OBJECT_NAME = 'E2E Graph Object Updated';
const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);

let testObjectUri = '';

/** Delete the test object via API (idempotent). */
async function cleanupTestObject() {
  if (!testObjectUri) return;
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  await ctx.delete('/api/graphs/objects', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri: testObjectUri },
    headers,
  });
  await ctx.dispose();
}

test.describe('Graph Objects CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.afterAll(async () => { await cleanupTestObject(); });

  test('create a new graph object via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/graphobjects`);
    await expect(page.locator('[data-testid="graph-objects-page"]')).toBeVisible({ timeout: 10_000 });

    // Click "Add Object"
    await page.getByRole('button', { name: /add object/i }).click();

    // Should navigate to create form
    await expect(page.locator('[data-testid="object-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('object-detail-title')).toHaveText('Create Graph Object');

    // Fix the pre-populated rdf:type value to a valid VitalSigns type
    // (the default "haley-ai-kg#GraphObject" is not registered in VitalSigns)
    const typeRow = page.locator('table tbody tr').first();
    const typeValueInput = typeRow.locator('input').nth(1);
    await typeValueInput.fill(VALID_RDF_TYPE);

    // Add a hasName property
    await page.locator('#new-predicate').fill(HAS_NAME);
    await page.locator('#new-value').fill(CRUD_OBJECT_NAME);
    await page.locator('button', { hasText: 'Add' }).click();

    // Intercept the create response to capture the generated URI
    const createPromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/graphs/objects') && resp.request().method() === 'POST',
    );

    // Click Create
    await page.locator('button', { hasText: 'Create' }).click();

    const createResp = await createPromise;
    const createJson = await createResp.json();
    testObjectUri = createJson.created_uris?.[0] || '';
    expect(testObjectUri).toBeTruthy();

    // Should redirect back to the objects list
    await expect(page).toHaveURL(/\/objects\/graphobjects/, { timeout: 10_000 });
  });

  test('object appears in the graph objects list', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/graphobjects`);
    await expect(page.locator('[data-testid="graph-objects-page"]')).toBeVisible({ timeout: 10_000 });

    // Search for the created object by URI
    await page.locator('input[placeholder="Search objects..."]').fill(testObjectUri);
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 10_000 });

    // The URI should be visible in the filtered table
    await expect(page.getByText(testObjectUri).first()).toBeVisible({ timeout: 5_000 });
  });

  test('update the object via the UI', async ({ page }) => {
    // Navigate directly to the object detail page via generic objects route
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/${encodeURIComponent(testObjectUri)}`);
    await expect(page.locator('[data-testid="object-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('object-detail-title')).toHaveText('Graph Object Details');

    // Switch to edit mode and wait for editable form to render
    await page.locator('button', { hasText: 'Edit' }).click();
    await expect(page.locator('#new-predicate')).toBeVisible({ timeout: 5_000 });

    // Find the hasName row by checking input values (hasText doesn't match input values)
    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5_000 });
    const rowCount = await rows.count();
    let nameRowIdx = -1;
    for (let i = 0; i < rowCount; i++) {
      const predVal = await rows.nth(i).locator('input').first().inputValue();
      if (predVal === HAS_NAME) { nameRowIdx = i; break; }
    }
    expect(nameRowIdx).toBeGreaterThanOrEqual(0);
    await rows.nth(nameRowIdx).locator('input').nth(1).fill(UPDATED_OBJECT_NAME);

    // Click Save and wait for the API response
    const savePromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/graphs/objects') && resp.request().method() === 'PUT',
    );
    await page.locator('button', { hasText: 'Save' }).click();
    await savePromise;

    // Verify the updated name appears in view mode
    await expect(page.getByText(UPDATED_OBJECT_NAME)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the object via the UI', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/graphobjects`);
    await expect(page.locator('[data-testid="graph-objects-page"]')).toBeVisible({ timeout: 10_000 });

    // Search for the object to bring it into view
    await page.locator('input[placeholder="Search objects..."]').fill(testObjectUri);
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 10_000 });

    // Find the row with our object URI and click its Delete button
    const row = page.locator('table tbody tr', { hasText: testObjectUri });
    await expect(row).toBeVisible({ timeout: 5_000 });
    await row.locator('button[title="Delete"]').click();

    // Confirm modal
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await expect(modal.getByText(/delete object/i)).toBeVisible();

    // Click Delete in the modal and wait for the API response
    const deletePromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/') && resp.request().method() === 'DELETE',
    );
    await modal.getByRole('button', { name: /delete/i }).first().click();
    await deletePromise;

    // Wait for the list to refresh — object should be removed
    await expect(row).not.toBeVisible({ timeout: 10_000 });
  });
});
