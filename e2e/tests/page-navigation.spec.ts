import { test, expect } from '@playwright/test';
import { SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Smoke tests — verify every major page loads its container element
 * without console errors. Each test is independent and fast.
 */

const G = encodeURIComponent(GRAPH_ID);

// ---------- Top-level pages (no space/graph context) -----------------------

test.describe('Top-level pages', () => {
  const pages: [string, string, string][] = [
    ['/', 'home-page', 'Dashboard'],
    ['/spaces', 'spaces-page', 'Spaces'],
    ['/users', 'users-page', 'Users'],
    ['/graphs', 'graphs-page', 'Graphs'],
    ['/sparql', 'sparql-page', 'SPARQL'],
    ['/kg-types', 'kgtypes-page', 'KG Types'],
    ['/kg-types/new', 'kgtype-detail-page', 'KG Type New'],
    ['/kg-query-builder', 'kgquery-builder-page', 'KG Query Builder'],
    ['/data/import', 'data-page', 'Data Import'],
    ['/data/export', 'data-page', 'Data Export'],
    ['/admin', 'admin-page', 'Admin'],
    ['/audit-log', 'audit-log-page', 'Audit Log'],
    ['/api-keys', 'api-keys-page', 'API Keys'],
    ['/entity-registry', 'entity-registry-page', 'Entity Registry'],
    ['/agent-registry', 'agent-registry-page', 'Agent Registry'],
    ['/semantic-search', 'semantic-search-page', 'Semantic Search'],
    ['/indexes', 'indexes-page', 'Indexes'],
    ['/index-mappings', 'index-mappings-page', 'Index Mappings'],
    ['/visualization', 'graph-visualization-page', 'Graph Visualization'],
    ['/files', 'files-page', 'Files'],
    ['/triples', 'triples-page', 'Triples'],
    ['/geo-shapes', 'geo-shapes-page', 'Geo Shapes'],
  ];

  for (const [url, testId, label] of pages) {
    test(`${label} page loads at ${url}`, async ({ page }) => {
      await page.goto(url);
      await expect(page.locator(`[data-testid="${testId}"]`)).toBeVisible({ timeout: 10_000 });
    });
  }
});

// ---------- Space-scoped pages (require seeded space) ----------------------

test.describe('Space-scoped pages', () => {
  const pages: [string, string, string][] = [
    [`/space/${SPACE_ID}`, 'space-detail-page', 'Space Detail'],
    [`/space/${SPACE_ID}/graphs`, 'graphs-page', 'Graphs'],
  ];

  for (const [url, testId, label] of pages) {
    test(`${label} page loads`, async ({ page }) => {
      await page.goto(url);
      await expect(page.locator(`[data-testid="${testId}"]`)).toBeVisible({ timeout: 10_000 });
    });
  }
});

// ---------- Graph-scoped pages (require seeded space + graph) --------------

test.describe('Graph-scoped pages', () => {
  const prefix = `/space/${SPACE_ID}/graph/${G}`;

  const pages: [string, string, string][] = [
    [prefix, 'graph-detail-page', 'Graph Detail'],
    [`${prefix}/objects/kgentities`, 'kgentities-page', 'KG Entities'],
    [`${prefix}/objects/kgframes`, 'kgframes-page', 'KG Frames'],
    [`${prefix}/objects/kgrelations`, 'kgrelations-page', 'KG Relations'],
    [`${prefix}/objects/kgdocuments`, 'kgdocuments-page', 'KG Documents'],
    [`${prefix}/objects/graphobjects`, 'graph-objects-page', 'Graph Objects'],
    [`${prefix}/triples`, 'triples-page', 'Triples'],
    [`${prefix}/files`, 'files-page', 'Files'],
  ];

  for (const [url, testId, label] of pages) {
    test(`${label} page loads`, async ({ page }) => {
      await page.goto(url);
      await expect(page.locator(`[data-testid="${testId}"]`)).toBeVisible({ timeout: 10_000 });
    });
  }
});

// ---------- 404 page -------------------------------------------------------

test('Not Found page renders for invalid route', async ({ page }) => {
  await page.goto('/this-route-does-not-exist');
  await expect(page.locator('[data-testid="not-found-page"]')).toBeVisible();
});
