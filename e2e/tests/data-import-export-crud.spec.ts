import { test, expect, request } from '@playwright/test';
import * as fs from 'fs';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Tier 8 — Data Import/Export Functional Tests
 *
 * Tests the end-to-end import and export workflows through the UI:
 *   Import: create job → upload file → execute → verify completion → delete
 *   Export: create job → execute → verify completion → delete
 */

const IMPORT_FILENAME = 'e2e-import-test.nt';
const IMPORT_TRIPLES = [
  '<urn:e2e:import:subject1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/vital-core#VITAL_Node> .',
  '<urn:e2e:import:subject1> <http://vital.ai/ontology/vital-core#hasName> "Import Test Node" .',
].join('\n');

let importJobId = '';
let exportJobId = '';

/** Delete a job via API (idempotent). */
async function cleanupJob(jobType: 'import' | 'export', jobId: string) {
  if (!jobId) return;
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  const headers = { Authorization: `Bearer ${access_token}` };
  await ctx.delete(`/api/data/${jobType}`, { params: { job_id: jobId }, headers });
  await ctx.dispose();
}

test.describe('Data Import/Export CRUD', () => {
  test.describe.configure({ mode: 'serial' });

  test.afterAll(async () => {
    await cleanupJob('import', importJobId);
    await cleanupJob('export', exportJobId);
  });

  // -------------------------------------------------------------------------
  // IMPORT TESTS
  // -------------------------------------------------------------------------

  test('create and execute an import job via the UI', async ({ page }) => {
    await page.goto('/data/import/new');
    await expect(page.locator('[data-testid="data-import-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Select the E2E test space
    await page.locator('#space').selectOption(SPACE_ID);

    // Optionally set the graph URI
    await page.locator('#graph_uri').fill(GRAPH_ID);

    // Set file format to N-Triples
    await page.locator('#file_format').selectOption('nt');

    // Upload the test file via the hidden file input
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: IMPORT_FILENAME,
      mimeType: 'application/n-triples',
      buffer: Buffer.from(IMPORT_TRIPLES, 'utf-8'),
    });

    // Verify file name appears in the upload zone
    await expect(page.getByText(IMPORT_FILENAME)).toBeVisible({ timeout: 5_000 });

    // Intercept the create response to capture job ID
    const createPromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/data/import') && resp.request().method() === 'POST'
        && !resp.url().includes('/upload') && !resp.url().includes('/execute'),
    );

    // Click "Create & Start Import"
    await page.locator('button', { hasText: /create.*start/i }).click();

    const createResp = await createPromise;
    const createJson = await createResp.json();
    importJobId = createJson.job_id || createJson.job?.job_id || '';
    expect(importJobId).toBeTruthy();

    // Should redirect to the job detail page
    await expect(page).toHaveURL(new RegExp(`/data/import/${importJobId}`), { timeout: 10_000 });
  });

  test('import job completes successfully', async ({ page }) => {
    expect(importJobId).toBeTruthy();
    await page.goto(`/data/import/${importJobId}`);
    await expect(page.locator('[data-testid="data-import-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for the "completed" badge to appear (the page polls automatically)
    await expect(
      page.getByTestId('flowbite-badge').filter({ hasText: 'completed' }),
    ).toBeVisible({ timeout: 30_000 });
  });

  test('imported data is queryable via SPARQL UI', async ({ page }) => {
    // Navigate to the SPARQL editor
    await page.goto('/sparql');
    await expect(page.locator('[data-testid="sparql-page"]')).toBeVisible({ timeout: 10_000 });

    // Select the E2E test space
    await page.locator('select').first().selectOption(SPACE_ID);

    // Enter a SPARQL query that looks for the imported triple
    const editor = page.getByPlaceholder(/enter your sparql query/i);
    await editor.fill(
      'SELECT ?name\nWHERE {\n  <urn:e2e:import:subject1> <http://vital.ai/ontology/vital-core#hasName> ?name .\n}'
    );

    // Execute query
    await page.getByRole('button', { name: /execute query/i }).click();

    // Wait for results table
    await expect(page.locator('table')).toBeVisible({ timeout: 15_000 });

    // Verify the imported value appears in the results
    await expect(page.getByText('Import Test Node').first()).toBeVisible({ timeout: 5_000 });
  });

  test('delete import job via the UI', async ({ page }) => {
    expect(importJobId).toBeTruthy();
    await page.goto(`/data/import/${importJobId}`);
    await expect(page.locator('[data-testid="data-import-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Accept the confirmation dialog
    page.on('dialog', (dialog) => dialog.accept());

    // Intercept the delete response
    const deletePromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/data/import') && resp.request().method() === 'DELETE',
    );

    // Click Delete button
    await page.locator('button', { hasText: /delete/i }).click();
    await deletePromise;

    // Should navigate back to the import list
    await expect(page).toHaveURL(/\/data\/import$/, { timeout: 10_000 });

    // Mark as cleaned up so afterAll doesn't re-try
    importJobId = '';
  });

  // -------------------------------------------------------------------------
  // EXPORT TESTS
  // -------------------------------------------------------------------------

  test('create and execute an export job via the UI', async ({ page }) => {
    await page.goto('/data/export/new');
    await expect(page.locator('[data-testid="data-export-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Select the E2E test space
    await page.locator('#space').selectOption(SPACE_ID);

    // Set format to N-Triples
    await page.locator('#file_format').selectOption('nt');

    // Optionally set graph URI
    await page.locator('#graph_uri').fill(GRAPH_ID);

    // Intercept the create response to capture job ID
    const createPromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/data/export') && resp.request().method() === 'POST'
        && !resp.url().includes('/execute'),
    );

    // Click "Create & Start Export"
    await page.locator('button', { hasText: /create.*start/i }).click();

    const createResp = await createPromise;
    const createJson = await createResp.json();
    exportJobId = createJson.job_id || createJson.job?.job_id || '';
    expect(exportJobId).toBeTruthy();

    // Should redirect to the job detail page
    await expect(page).toHaveURL(new RegExp(`/data/export/${exportJobId}`), { timeout: 10_000 });
  });

  test('export job completes and file is valid', async ({ page }) => {
    expect(exportJobId).toBeTruthy();
    await page.goto(`/data/export/${exportJobId}`);
    await expect(page.locator('[data-testid="data-export-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Wait for the "completed" badge to appear
    await expect(
      page.getByTestId('flowbite-badge').filter({ hasText: 'completed' }),
    ).toBeVisible({ timeout: 30_000 });

    // Verify download button appears for completed export
    const downloadBtn = page.locator('button', { hasText: /download/i });
    await expect(downloadBtn).toBeVisible({ timeout: 5_000 });

    // Click download and capture the file
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      downloadBtn.click(),
    ]);

    // Save to a temp path and read contents
    const downloadPath = await download.path();
    expect(downloadPath).toBeTruthy();
    const fileContent = fs.readFileSync(downloadPath!, 'utf-8');

    // Parse as N-Triples: each non-empty line must be a valid triple
    const lines = fileContent.split('\n').filter((l) => l.trim().length > 0);
    expect(lines.length).toBeGreaterThan(0);

    // N-Triples line pattern: <subject> <predicate> <object> . OR <subject> <predicate> "literal"^^<type> .
    const ntLinePattern = /^<[^>]+>\s+<[^>]+>\s+(?:<[^>]+>|".*"(?:@\w+|\^\^<[^>]+>)?)\s*\.$/;
    const invalidLines: string[] = [];
    for (const line of lines) {
      if (!ntLinePattern.test(line)) {
        invalidLines.push(line);
      }
    }
    expect(invalidLines, `Invalid N-Triples lines: ${invalidLines.slice(0, 3).join(' | ')}`).toHaveLength(0);

    // Verify known seeded data is present in parsed triples
    const aliceLines = lines.filter((l) => l.includes('urn:e2e:entity:alice'));
    expect(aliceLines.length).toBeGreaterThan(0);
    const hasAliceName = lines.some((l) => l.includes('Alice Anderson'));
    expect(hasAliceName).toBe(true);
  });

  test('delete export job via the UI', async ({ page }) => {
    expect(exportJobId).toBeTruthy();
    await page.goto(`/data/export/${exportJobId}`);
    await expect(page.locator('[data-testid="data-export-detail-page"]')).toBeVisible({ timeout: 10_000 });

    // Accept the confirmation dialog
    page.on('dialog', (dialog) => dialog.accept());

    // Intercept the delete response
    const deletePromise = page.waitForResponse(
      (resp) => resp.url().includes('/api/data/export') && resp.request().method() === 'DELETE',
    );

    // Click Delete button
    await page.locator('button', { hasText: /delete/i }).click();
    await deletePromise;

    // Should navigate back to the export list
    await expect(page).toHaveURL(/\/data\/export$/, { timeout: 10_000 });

    // Mark as cleaned up so afterAll doesn't re-try
    exportJobId = '';
  });
});
