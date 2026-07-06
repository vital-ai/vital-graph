import { test, expect } from '@playwright/test';
import { SPACE_ID } from '../seed-constants';

/**
 * Tier 8 — SPARQL Execution + Results
 *
 * Tests executing SPARQL queries via the UI and verifying results render.
 */

test.describe('SPARQL Execution', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/sparql');
    await expect(page.locator('[data-testid="sparql-page"]')).toBeVisible({ timeout: 10_000 });
  });

  test('page loads with editor and space selector', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'SPARQL' })).toBeVisible();
    await expect(page.getByPlaceholder(/enter your sparql query/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /execute query/i })).toBeVisible();
  });

  test('execute a COUNT query and verify results', async ({ page }) => {
    // Select the e2e test space
    await page.locator('select').first().selectOption(SPACE_ID);

    // Type a COUNT query
    const editor = page.getByPlaceholder(/enter your sparql query/i);
    await editor.fill('SELECT (COUNT(*) as ?count)\nWHERE {\n  ?s ?p ?o .\n}');

    // Execute
    await page.getByRole('button', { name: /execute query/i }).click();

    // Wait for results table to appear
    await expect(page.locator('table')).toBeVisible({ timeout: 15_000 });

    // Should show column header "?count"
    await expect(page.getByRole('columnheader', { name: '?count' })).toBeVisible();

    // Result should be a number > 0
    const cell = page.locator('table tbody td').first();
    await expect(cell).toBeVisible();
    const text = await cell.textContent();
    expect(parseInt(text || '0', 10)).toBeGreaterThan(0);
  });

  test('execute a SELECT query and verify table rows', async ({ page }) => {
    // Select the e2e test space
    await page.locator('select').first().selectOption(SPACE_ID);

    // Use the "List all triples" sample which is guaranteed to return results
    const editor = page.getByPlaceholder(/enter your sparql query/i);
    await editor.fill(
      'SELECT ?subject ?predicate ?object\nWHERE {\n  ?subject ?predicate ?object .\n}\nLIMIT 5'
    );

    // Execute
    await page.getByRole('button', { name: /execute query/i }).click();

    // Wait for results
    await expect(page.locator('table')).toBeVisible({ timeout: 15_000 });

    // Should show column headers
    await expect(page.getByRole('columnheader', { name: '?subject' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '?predicate' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '?object' })).toBeVisible();

    // Should have at least one result row
    await expect(page.locator('table tbody tr').first()).toBeVisible();

    // Result count text should appear
    await expect(page.getByText(/\d+ results?/)).toBeVisible();
  });

  test('use a sample query shortcut', async ({ page }) => {
    // Select the e2e test space
    await page.locator('select').first().selectOption(SPACE_ID);

    // Click the "List all triples" sample query button
    await page.locator('button', { hasText: 'List all triples' }).click();

    // Editor should now have the sample query
    const editor = page.getByPlaceholder(/enter your sparql query/i);
    await expect(editor).not.toBeEmpty();

    // Execute
    await page.getByRole('button', { name: /execute query/i }).click();

    // Should get results
    await expect(page.locator('table')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('columnheader', { name: '?subject' })).toBeVisible();
  });

  test('clear button resets editor and results', async ({ page }) => {
    await page.locator('select').first().selectOption(SPACE_ID);

    // Enter and execute a query
    const editor = page.getByPlaceholder(/enter your sparql query/i);
    await editor.fill('SELECT (COUNT(*) as ?count)\nWHERE {\n  ?s ?p ?o .\n}');
    await page.getByRole('button', { name: /execute query/i }).click();
    await expect(page.locator('table')).toBeVisible({ timeout: 15_000 });

    // Click Clear
    await page.getByRole('button', { name: /clear/i }).click();

    // Editor should be empty, results gone
    await expect(editor).toHaveValue('');
    await expect(page.locator('table')).not.toBeVisible();
  });
});
