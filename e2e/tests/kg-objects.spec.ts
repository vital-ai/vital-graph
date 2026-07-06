import { test, expect } from '@playwright/test';
import {
  SPACE_ID,
  GRAPH_ID,
  ENTITIES,
  EXPECTED_ENTITY_COUNT,
} from '../seed-constants';

const G = encodeURIComponent(GRAPH_ID);
const PREFIX = `/space/${SPACE_ID}/graph/${G}`;

/**
 * KG object list pages — verify that list pages render correctly
 * and display seeded data where applicable.
 */
test.describe('KG Entities list', () => {
  test('shows seeded entities with correct count', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgentities`);
    await expect(page.locator('[data-testid="kgentities-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="kgentities-title"]')).toBeVisible();

    // All seeded entity names should appear
    for (const entity of Object.values(ENTITIES)) {
      await expect(page.getByText(entity.name)).toBeVisible({ timeout: 10_000 });
    }

    // Row count should match seeded entities
    const rows = page.locator('[data-testid="entity-row"]');
    await expect(rows).toHaveCount(EXPECTED_ENTITY_COUNT, { timeout: 10_000 });
  });

  test('can navigate to entity detail via view button', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgentities`);
    await expect(page.locator('[data-testid="kgentities-page"]')).toBeVisible({ timeout: 10_000 });

    // Click the view button for Alice
    await page.locator(`[data-testid="entity-view-${ENTITIES.alice.uri}"]`).click();
    await expect(page).toHaveURL(/entity/);
    await expect(page.locator('[data-testid="kgentity-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

test.describe('KG Frames list', () => {
  test('page loads and shows title', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgframes`);
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="kgframes-title"]')).toHaveText('KG Frames');
  });
});

test.describe('KG Relations list', () => {
  test('page loads and shows title', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgrelations`);
    await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="kgrelations-title"]')).toHaveText('KG Relations');
  });
});

test.describe('KG Documents list', () => {
  test('page loads and shows title', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/kgdocuments`);
    await expect(page.locator('[data-testid="kgdocuments-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="kgdocuments-title"]')).toContainText('KG Documents');
  });
});

test.describe('KG Types list', () => {
  test('page loads and shows title', async ({ page }) => {
    await page.goto('/kg-types');
    await expect(page.locator('[data-testid="kgtypes-page"]')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-testid="kgtypes-title"]')).toHaveText('KG Types');
  });
});

test.describe('KG Types detail', () => {
  test('new type page loads', async ({ page }) => {
    await page.goto('/kg-types/new');
    await expect(page.locator('[data-testid="kgtype-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('type detail page loads via space-scoped route', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/kg-types/new`);
    await expect(page.locator('[data-testid="kgtype-detail-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

test.describe('Graph Objects list', () => {
  test('page loads', async ({ page }) => {
    await page.goto(`${PREFIX}/objects/graphobjects`);
    await expect(page.locator('[data-testid="graph-objects-page"]')).toBeVisible({ timeout: 10_000 });
  });
});

test.describe('Triples page', () => {
  test('page loads', async ({ page }) => {
    await page.goto(`${PREFIX}/triples`);
    await expect(page.locator('[data-testid="triples-page"]')).toBeVisible({ timeout: 10_000 });
  });
});
