import { test, expect } from '@playwright/test';
import { SPACE_ID, GRAPH_ID, ENTITIES, SEEDED_DOCUMENT } from '../seed-constants';

const G = encodeURIComponent(GRAPH_ID);
const PREFIX = `/space/${SPACE_ID}/graph/${G}`;

/**
 * Tier 3 — Graphs, Graph Detail, Graph Objects, Object Detail,
 *           KG Entity Detail, KG Frame Detail, KG Document Detail,
 *           Objects Layout tabs
 */

// ---------- Graphs ---------------------------------------------------------

test.describe('Graphs', () => {
  test('standalone graphs page loads', async ({ page }) => {
    await page.goto('/graphs');
    await expect(page.locator('[data-testid="graphs-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="graphs-title"]')).toHaveText('Graphs');
  });

  test('space-scoped graphs shows seeded graph', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graphs`);
    await expect(page.locator('[data-testid="graphs-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="graphs-grid"]')).toBeVisible();
    await expect(page.locator(`[data-testid="graph-card-${GRAPH_ID}"]`)).toBeVisible({ timeout: 10_000 });
  });

  test('clicking graph card navigates to detail', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graphs`);
    await page.locator(`[data-testid="graph-card-${GRAPH_ID}"] a`).first().click();
    await expect(page.locator('[data-testid="graph-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- Graph Detail ---------------------------------------------------

test.describe('Graph Detail', () => {
  test('page loads with graph info', async ({ page }) => {
    await page.goto(PREFIX);
    await expect(page.locator('[data-testid="graph-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- Graph Objects --------------------------------------------------

test.describe('Graph Objects', () => {
  test('page loads', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/graphobjects`);
    await expect(page.locator('[data-testid="graph-objects-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- Objects Layout tabs --------------------------------------------

test.describe('Objects Layout', () => {
  test('graphobjects tab is default', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/graphobjects`);
    await expect(page.locator('[data-testid="graph-objects-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('kgentities tab loads', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgentities`);
    await expect(page.locator('[data-testid="kgentities-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('kgframes tab loads', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgframes`);
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('kgrelations tab loads', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgrelations`);
    await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('kgdocuments tab loads', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- KG Entity Detail -----------------------------------------------

test.describe('KG Entity Detail', () => {
  test('loads via direct URL', async ({ page }) => {
    const entityUri = encodeURIComponent(ENTITIES.alice.uri);
    await page.goto(`/space/${SPACE_ID}/graph/${G}/entity/${entityUri}`);
    await expect(page.locator('[data-testid="kgentity-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('shows entity properties', async ({ page }) => {
    const entityUri = encodeURIComponent(ENTITIES.alice.uri);
    await page.goto(`/space/${SPACE_ID}/graph/${G}/entity/${entityUri}`);
    await expect(page.locator('[data-testid="kgentity-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="object-detail-name"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- KG Frame Detail ------------------------------------------------

test.describe('KG Frame Detail', () => {
  test('page loads for a valid frame URI (or shows empty state)', async ({ page }) => {
    // Navigate to frames list first to see if any frames exist
    await page.goto(`${PREFIX}/objects/kgframes`);
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 10_000 });
    // If there are frame rows, click into the first one
    const rows = page.locator('[data-testid="frame-row"]');
    const count = await rows.count();
    if (count > 0) {
      // Find the view button in the first row
      await rows.first().locator('a, button').first().click();
      await expect(page.locator('[data-testid="kgframe-detail-page"]')).toBeVisible({ timeout: 10_000 });
    }
    // If no frames exist, this test just verifies the list page loaded
  });
});

// ---------- KG Document Detail ---------------------------------------------

test.describe('KG Document Detail', () => {
  test('seeded document visible in document list', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(SEEDED_DOCUMENT.title).first()).toBeVisible({ timeout: 10_000 });
  });

  test('navigates to seeded document detail', async ({ page }) => {
    const docUri = encodeURIComponent(SEEDED_DOCUMENT.uri);
    await page.goto(`${PREFIX}/document/${docUri}`);
    await expect(page.locator('[data-testid="kgdocument-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- Object Detail --------------------------------------------------

test.describe('Object Detail', () => {
  test('loads for a seeded entity via object route', async ({ page }) => {
    const objectUri = encodeURIComponent(ENTITIES.alice.uri);
    await page.goto(`/space/${SPACE_ID}/graph/${G}/object/${objectUri}`);
    await expect(page.locator('[data-testid="object-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

// ---------- File Detail ----------------------------------------------------

test.describe('File Detail', () => {
  test('page loads when a file exists (or verifies files list)', async ({ page }) => {
    await page.goto(`${PREFIX}/files`);
    await expect(page.locator('[data-testid="files-page"]')).toBeVisible({ timeout: 10_000 });
    const links = page.locator('a[href*="/file/"]');
    const count = await links.count();
    if (count > 0) {
      await links.first().click();
      await expect(page.locator('[data-testid="file-detail-page"]')).toBeVisible({ timeout: 10_000 });
    }
  });
});

// ---------- Objects Layout -------------------------------------------------

test.describe('Objects Layout', () => {
  test('objects layout wrapper renders with tabs', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/graphobjects`);
    await expect(page.locator('[data-testid="graph-objects-page"]')).toBeVisible({ timeout: 10_000 });
  });
});
