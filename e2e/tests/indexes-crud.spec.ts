import { test, expect } from '@playwright/test';
import { createSpace, dropSpace } from './space-fixtures';

/**
 * Tier 7 — Indexes CRUD Write Operations
 *
 * Tests Create, List, and Delete flows for FTS and Vector indexes
 * via the unified Indexes page at /indexes.
 */

const FTS_INDEX_NAME = 'e2e_crud_fts';
const VECTOR_INDEX_NAME = 'e2e_crud_vec';

// Each describe gets its OWN space. The FTS and Vector blocks are `serial` but
// run in separate workers (fullyParallel) even though they share this file, so
// they must not share a space — otherwise one block's afterAll space-drop would
// wipe the other's index mid-flight. Dropping the space removes its index, so no
// per-index cleanup is needed.
const FTS_SPACE_ID = 'e2e_indexes_fts_space';
const VEC_SPACE_ID = 'e2e_indexes_vec_space';
const GRAPH_ID = 'urn:e2e:indexes:graph';

test.describe('Indexes CRUD — FTS', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await createSpace(FTS_SPACE_ID, GRAPH_ID, { name: 'E2E Indexes FTS Space' }); });
  test.afterAll(async () => { await dropSpace(FTS_SPACE_ID); });

  const SPACE_ID = FTS_SPACE_ID;

  test('create a new FTS index via the UI', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    // Select space and wait for any triggered fetch to settle
    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');

    // Click Create Index
    await page.locator('button', { hasText: 'Create Index' }).click();

    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByText('Create Index')).toBeVisible({ timeout: 5_000 });

    // Select FTS type
    await modal.locator('#createType').selectOption('fts');

    // Set index name
    await modal.locator('#createName').fill(FTS_INDEX_NAME);

    // Click Create
    await modal.locator('button', { hasText: 'Create' }).first().click();

    // Modal should close
    await expect(modal).not.toBeVisible({ timeout: 5_000 });

    // Index should appear in the table
    await expect(page.locator('table').getByText(FTS_INDEX_NAME)).toBeVisible({ timeout: 5_000 });
  });

  test('FTS index appears in the list', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('table').getByText(FTS_INDEX_NAME)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the FTS index via the UI', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('table').getByText(FTS_INDEX_NAME)).toBeVisible({ timeout: 10_000 });

    // Find the row and click delete
    const row = page.locator('table tbody tr', { hasText: FTS_INDEX_NAME });
    await row.locator('button').last().click();

    // Confirm in the delete modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByRole('heading', { name: 'Delete Index' })).toBeVisible({ timeout: 5_000 });
    await modal.locator('button', { hasText: 'Delete' }).first().click();

    // Index should be removed
    await expect(page.locator('table').getByText(FTS_INDEX_NAME)).not.toBeVisible({ timeout: 5_000 });
  });
});

test.describe('Indexes CRUD — Vector', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => { await createSpace(VEC_SPACE_ID, GRAPH_ID, { name: 'E2E Indexes Vector Space' }); });
  test.afterAll(async () => { await dropSpace(VEC_SPACE_ID); });

  const SPACE_ID = VEC_SPACE_ID;

  test('create a new Vector index via the UI', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');

    // Click Create Index
    await page.locator('button', { hasText: 'Create Index' }).click();

    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByText('Create Index')).toBeVisible({ timeout: 5_000 });

    // Select Vector type (default)
    await modal.locator('#createType').selectOption('vector');

    // Set index name
    await modal.locator('#createName').fill(VECTOR_INDEX_NAME);

    // Set dimensions
    await modal.locator('#dimensions').fill('256');

    // Click Create
    await modal.locator('button', { hasText: 'Create' }).first().click();

    // Modal should close
    await expect(modal).not.toBeVisible({ timeout: 5_000 });

    // Index should appear
    await expect(page.locator('table').getByText(VECTOR_INDEX_NAME)).toBeVisible({ timeout: 5_000 });
  });

  test('Vector index appears in the list', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('table').getByText(VECTOR_INDEX_NAME)).toBeVisible({ timeout: 10_000 });
  });

  test('delete the Vector index via the UI', async ({ page }) => {
    await page.goto('/indexes');
    await expect(page.locator('[data-testid="indexes-page"]')).toBeVisible({ timeout: 10_000 });

    await page.locator('#space').selectOption(SPACE_ID);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('table').getByText(VECTOR_INDEX_NAME)).toBeVisible({ timeout: 10_000 });

    // Find the row and click delete
    const row = page.locator('table tbody tr', { hasText: VECTOR_INDEX_NAME });
    await row.locator('button').last().click();

    // Confirm in the delete modal
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal.getByRole('heading', { name: 'Delete Index' })).toBeVisible({ timeout: 5_000 });
    await modal.locator('button', { hasText: 'Delete' }).first().click();

    // Index should be removed (allow extra time for backend deletion + UI refresh)
    await expect(page.locator('table').getByText(VECTOR_INDEX_NAME)).not.toBeVisible({ timeout: 20_000 });
  });
});
