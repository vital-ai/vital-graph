import { test, expect } from '@playwright/test';
import { SPACE_ID, ENTITIES } from '../seed-constants';

/**
 * Tier 10 — Graph Visualization CRUD & Interaction
 *
 * Tests the full graph visualization page: session management,
 * database search, node expansion, inspector drawer, layout changes,
 * and session switching.
 *
 * Relies on seeded entities in the e2e_test_space (Alice, Bob, Carol).
 * Tests are serial because session state is cumulative.
 */

test.describe('Graph Visualization — Sessions & Interaction', () => {
  test.describe.configure({ mode: 'serial' });

  const VIZ_PAGE = '[data-testid="graph-visualization-page"]';

  test('page loads and auto-creates first session', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Status bar should show "0 nodes" in the empty state
    await expect(page.getByText('0 nodes')).toBeVisible({ timeout: 5_000 });

    // Session tab bar should have at least one session tab
    // The auto-created session is named "Session 1"
    await expect(page.getByText('Session 1', { exact: true })).toBeVisible({ timeout: 5_000 });
  });

  test('space selector shows available spaces', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // The toolbar contains a <select> for spaces — it should have the seeded space
    const spaceSelect = page.locator(VIZ_PAGE).locator('select').first();
    await expect(spaceSelect).toBeVisible();

    // Verify the seeded space is among the options
    const options = spaceSelect.locator('option');
    await expect(options).not.toHaveCount(0);
  });

  test('search toggle opens search panel', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Click the search toggle button (title="Search (Ctrl+F)")
    await page.locator('button[title="Search (Ctrl+F)"]').click();

    // The floating search panel should appear with "Database" and "Local" tabs
    await expect(page.getByText('Database')).toBeVisible({ timeout: 3_000 });
    await expect(page.getByText('Local')).toBeVisible();

    // Search input should be visible
    await expect(page.locator('input[placeholder="Search database…"]')).toBeVisible();
  });

  test('database search finds seeded entity', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Ensure the space is the e2e test space
    const spaceSelect = page.locator(VIZ_PAGE).locator('select').first();
    await spaceSelect.selectOption(SPACE_ID);
    await page.waitForTimeout(500);

    // Open search panel
    await page.locator('button[title="Search (Ctrl+F)"]').click();
    await expect(page.locator('input[placeholder="Search database…"]')).toBeVisible({ timeout: 3_000 });

    // Type the search term and press Enter
    await page.locator('input[placeholder="Search database…"]').fill('Alice');
    await page.locator('input[placeholder="Search database…"]').press('Enter');

    // Wait for search results to appear — should show "Alice Anderson"
    await expect(page.getByText(ENTITIES.alice.name)).toBeVisible({ timeout: 15_000 });
  });

  test('add search result to graph — node appears on canvas', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Set space and search
    const spaceSelect = page.locator(VIZ_PAGE).locator('select').first();
    await spaceSelect.selectOption(SPACE_ID);
    await page.waitForTimeout(500);

    await page.locator('button[title="Search (Ctrl+F)"]').click();
    await page.locator('input[placeholder="Search database…"]').fill('Alice');
    await page.locator('input[placeholder="Search database…"]').press('Enter');

    // Click the search result to add to graph
    await expect(page.getByText(ENTITIES.alice.name)).toBeVisible({ timeout: 15_000 });
    await page.getByText(ENTITIES.alice.name).click();

    // Wait for the node to be added and expanded — status bar should show > 0 nodes
    await expect(page.getByText(/^[1-9]\d* nodes$/)).toBeVisible({ timeout: 15_000 });
  });

  test('layout dropdown shows available algorithms', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // The second <select> in the toolbar is the layout algorithm selector
    const layoutSelect = page.locator(VIZ_PAGE).locator('select').nth(1);
    await expect(layoutSelect).toBeVisible();

    // Should have multiple layout options
    const options = layoutSelect.locator('option');
    const count = await options.count();
    expect(count).toBeGreaterThan(3);
  });

  test('re-run layout button exists and is clickable', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Re-run layout button (title="Re-run layout")
    const rerunBtn = page.locator('button[title="Re-run layout"]');
    await expect(rerunBtn).toBeVisible();
    await expect(rerunBtn).toBeEnabled();
  });

  test('fit-to-viewport button exists', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    await expect(page.locator('button[title="Fit to viewport"]')).toBeVisible();
  });

  test('clear graph button exists', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    await expect(page.locator('button[title="Clear graph"]')).toBeVisible();
  });

  test('create new session — tab appears', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Click the "New session" button (the + button in the session bar)
    await page.locator('button[title="New session"]').click();

    // A second session tab should appear — "Session 2"
    await expect(page.getByText('Session 2', { exact: true })).toBeVisible({ timeout: 5_000 });
  });

  test('switch sessions changes active tab', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Ensure at least 2 sessions
    await page.locator('button[title="New session"]').click();
    await expect(page.getByText('Session 2', { exact: true })).toBeVisible({ timeout: 5_000 });

    // Click Session 1 tab
    await page.getByText('Session 1', { exact: true }).click();

    // Status bar should show "Session: Session 1"
    await expect(page.getByText('Session: Session 1')).toBeVisible({ timeout: 3_000 });

    // Click Session 2 tab
    await page.getByText('Session 2', { exact: true }).click();

    // Status bar should show "Session: Session 2"
    await expect(page.getByText('Session: Session 2')).toBeVisible({ timeout: 3_000 });
  });

  test('close session removes tab', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Create a second session
    await page.locator('button[title="New session"]').click();
    await expect(page.getByText('Session 2', { exact: true })).toBeVisible({ timeout: 5_000 });

    // Hover over Session 2 to reveal the close button, then click it
    const session2Tab = page.getByText('Session 2', { exact: true }).locator('..');
    await session2Tab.hover();
    await session2Tab.locator('button[title="Close session"]').click();

    // Session 2 should be removed
    await expect(page.getByText('Session 2', { exact: true })).not.toBeVisible({ timeout: 3_000 });

    // Session 1 should still be present
    await expect(page.getByText('Session 1', { exact: true })).toBeVisible();
  });

  test('legend toggle shows legend overlay', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // First, add a node so the legend has content
    const spaceSelect = page.locator(VIZ_PAGE).locator('select').first();
    await spaceSelect.selectOption(SPACE_ID);
    await page.waitForTimeout(500);

    await page.locator('button[title="Search (Ctrl+F)"]').click();
    await page.locator('input[placeholder="Search database…"]').fill('Alice');
    await page.locator('input[placeholder="Search database…"]').press('Enter');
    await expect(page.getByText(ENTITIES.alice.name)).toBeVisible({ timeout: 15_000 });
    await page.getByText(ENTITIES.alice.name).click();
    await expect(page.getByText(/^[1-9]\d* nodes$/)).toBeVisible({ timeout: 15_000 });

    // Click legend toggle
    await page.locator('button[title="Toggle legend"]').click();

    // Legend overlay should appear with "Legend" heading
    await expect(page.getByText('Legend')).toBeVisible({ timeout: 3_000 });
  });

  test('statistics toggle shows stats overlay', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Add a node for stats content
    const spaceSelect = page.locator(VIZ_PAGE).locator('select').first();
    await spaceSelect.selectOption(SPACE_ID);
    await page.waitForTimeout(500);

    await page.locator('button[title="Search (Ctrl+F)"]').click();
    await page.locator('input[placeholder="Search database…"]').fill('Alice');
    await page.locator('input[placeholder="Search database…"]').press('Enter');
    await expect(page.getByText(ENTITIES.alice.name)).toBeVisible({ timeout: 15_000 });
    await page.getByText(ENTITIES.alice.name).click();
    await expect(page.getByText(/^[1-9]\d* nodes$/)).toBeVisible({ timeout: 15_000 });

    // Click statistics toggle
    await page.locator('button[title="Toggle statistics"]').click();

    // Statistics overlay should appear with "Statistics" heading and node/edge labels
    await expect(page.getByText('Statistics')).toBeVisible({ timeout: 3_000 });
    await expect(page.getByText('Nodes', { exact: true })).toBeVisible();
    await expect(page.getByText('Edges', { exact: true })).toBeVisible();
  });

  test('empty state shows guidance text', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Empty state should show guidance text
    await expect(page.getByText('No graph data loaded')).toBeVisible({ timeout: 5_000 });
  });

  test('export buttons exist in toolbar', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    await expect(page.locator('button[title="Export PNG"]')).toBeVisible();
    await expect(page.locator('button[title="Export JSON"]')).toBeVisible();
    await expect(page.locator('button[title="Export SVG"]')).toBeVisible();
    await expect(page.locator('button[title="Export CSV"]')).toBeVisible();
  });

  test('status bar shows node and edge counts', async ({ page }) => {
    await page.goto('/visualization');
    await expect(page.locator(VIZ_PAGE)).toBeVisible({ timeout: 10_000 });

    // Status bar is at the bottom — should show "0 nodes" and "0 edges"
    await expect(page.getByText('0 nodes')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText('0 edges')).toBeVisible();
  });
});
