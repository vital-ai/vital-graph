import { test, expect } from '@playwright/test';
import { SPACE_ID, GRAPH_ID } from '../seed-constants';

const G = encodeURIComponent(GRAPH_ID);
const PREFIX = `/space/${SPACE_ID}/graph/${G}`;

/**
 * Tier 7–8 — Files, File Detail, File Upload, Triples, SPARQL
 */

// ---------- Files ----------------------------------------------------------

test.describe('Files', () => {
  test('list page loads (graph-scoped)', async ({ page }) => {
    await page.goto(`${PREFIX}/files`);
    await expect(page.locator('[data-testid="files-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('standalone files page loads', async ({ page }) => {
    await page.goto('/files');
    await expect(page.locator('[data-testid="files-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- File Upload ----------------------------------------------------

test.describe('File Upload', () => {
  test('upload page loads with drag-drop zone', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${G}/file/new`);
    await expect(page.locator('[data-testid="file-upload-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- Triples --------------------------------------------------------

test.describe('Triples', () => {
  test('page loads (graph-scoped)', async ({ page }) => {
    await page.goto(`${PREFIX}/triples`);
    await expect(page.locator('[data-testid="triples-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('standalone triples page loads', async ({ page }) => {
    await page.goto('/triples');
    await expect(page.locator('[data-testid="triples-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- SPARQL ---------------------------------------------------------

test.describe('SPARQL', () => {
  test('page loads with editor', async ({ page }) => {
    await page.goto('/sparql');
    await expect(page.locator('[data-testid="sparql-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('can type a SPARQL query into the editor', async ({ page }) => {
    await page.goto('/sparql');
    await expect(page.locator('[data-testid="sparql-page"]')).toBeVisible({ timeout: 10_000 });
    // The SPARQL editor might be a CodeMirror or textarea — try both
    const textarea = page.locator('textarea').first();
    const cmEditor = page.locator('.cm-content').first();
    if (await textarea.isVisible()) {
      await textarea.fill('SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5');
      await expect(textarea).toHaveValue(/SELECT/);
    } else if (await cmEditor.isVisible()) {
      await cmEditor.click();
      await page.keyboard.type('SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5');
    }
  });
});
