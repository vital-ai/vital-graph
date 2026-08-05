import { test, expect, request, APIRequestContext } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Entity Registry — lookup-driven UI.
 *
 * Covers the selectors backed by the registry's reference tables
 * (entity_type, category, relationship_type) and the relationships tab.
 *
 * These lookups are FK targets, not cosmetic: entity.entity_type_id and
 * entity_relationship.relationship_type_id are NOT NULL REFERENCES, so a
 * free-text value fails server-side. The tests assert the UI only ever
 * offers registered keys.
 */

const BASE_URL = process.env.VG_TEST_URL || 'http://localhost:8002';

// The config runs specs fullyParallel, so each describe block owns a distinct
// set of entity names. Sharing names across blocks lets one block's cleanup()
// delete another block's fixtures mid-run.
const names = (suffix: string) => ({
  source: `E2E Lookup Source ${suffix}`,
  target: `E2E Lookup Target ${suffix}`,
  inactive: `E2E Lookup Inactive ${suffix}`,
});

const REL_TYPE_KEY = 'owner_of';
const REL_TYPE_LABEL = 'Owner Of';
const REL_INVERSE_LABEL = 'Owned By';
const CATEGORY_KEY = 'lead_new';
const CATEGORY_LABEL = 'Lead - New';

async function apiContext(): Promise<{ ctx: APIRequestContext; headers: Record<string, string> }> {
  const ctx = await request.newContext({ baseURL: BASE_URL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  return { ctx, headers: { Authorization: `Bearer ${access_token}` } };
}

/**
 * Delete the named registry entities (idempotent).
 *
 * Two traps here, both of which silently defeated the previous version:
 *
 *  - The endpoint's page parameter is `page_size` (default 20, max 100), NOT
 *    `limit`. Passing `limit: 50` was ignored, so only 20 rows were ever seen.
 *  - Delete is a SOFT delete: the row stays and keeps matching the search with
 *    `status: 'deleted'`. Tombstones accumulate one per run, and once 20 of
 *    them precede the live row, the live row falls outside the first page —
 *    cleanup deletes nothing, and the next run's beforeAll adds a SECOND live
 *    entity with the same name. `getByText(SOURCE_NAME)` then hits two rows and
 *    fails strict mode. That is why this failure looked intermittent and then
 *    became permanent. See issues/022.
 *
 * So: page through every result and skip rows that are already deleted.
 */
async function cleanup(targets: string[]) {
  const { ctx, headers } = await apiContext();
  const PAGE_SIZE = 100;
  for (const name of targets) {
    for (let page = 1; ; page++) {
      const resp = await ctx.get('/api/registry/entities', {
        params: { query: name, status: '', page, page_size: PAGE_SIZE },
        headers,
      });
      const { entities = [], total_count = 0 } = await resp.json();
      for (const e of entities) {
        if (e.primary_name === name && e.status !== 'deleted') {
          await ctx.delete('/api/registry/entities/delete', {
            params: { entity_id: e.entity_id },
            headers,
          });
        }
      }
      if (entities.length < PAGE_SIZE || page * PAGE_SIZE >= total_count) break;
    }
  }
  await ctx.dispose();
}

/** Create an entity directly via the API and return its entity_id. */
async function createEntity(name: string, typeKey: string, status?: string): Promise<string> {
  const { ctx, headers } = await apiContext();
  const resp = await ctx.post('/api/registry/entities', {
    data: { primary_name: name, type_key: typeKey, description: 'Seeded by lookup spec' },
    headers,
  });
  const body = await resp.json();
  const entityId = body.entity_id;
  if (status && status !== 'active') {
    await ctx.put('/api/registry/entities/update', {
      params: { entity_id: entityId },
      data: { status },
      headers,
    });
  }
  await ctx.dispose();
  return entityId;
}

test.describe('Entity Registry lookup selectors', () => {
  test.describe.configure({ mode: 'serial' });

  const { source: SOURCE_NAME, target: TARGET_NAME, inactive: INACTIVE_NAME } = names('Sel');
  const all = [SOURCE_NAME, TARGET_NAME, INACTIVE_NAME];

  test.beforeAll(async () => {
    await cleanup(all);
    await createEntity(SOURCE_NAME, 'business');
    await createEntity(TARGET_NAME, 'person');
    await createEntity(INACTIVE_NAME, 'person', 'inactive');
  });

  test.afterAll(async () => { await cleanup(all); });

  test('type filter is populated from the entity_type table', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });

    const filter = page.locator('[data-testid="entity-type-filter"]');
    await expect(filter).toBeVisible();
    // Options arrive from an async lookup fetch — wait for them rather than
    // reading the select while it still holds only the "All types" placeholder.
    await expect(filter.locator('option')).not.toHaveCount(1, { timeout: 10_000 });

    // Values must be real type_keys — the canonical reference set
    const values = await filter.locator('option').evaluateAll(
      (opts) => opts.map((o) => (o as HTMLOptionElement).value),
    );
    expect(values[0]).toBe(''); // "All types"
    for (const key of ['person', 'business', 'organization', 'government']) {
      expect(values).toContain(key);
    }
  });

  test('filtering by type narrows the result set', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });

    // Search first — the list paginates, so both fixtures must be on one page
    // before the type filter can be shown to remove one of them.
    await page.getByPlaceholder('Search entities...').fill('E2E Lookup');
    await expect(page.getByText(SOURCE_NAME)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(TARGET_NAME)).toBeVisible();

    await page.locator('[data-testid="entity-type-filter"]').selectOption('business');
    await expect(page.getByText(SOURCE_NAME)).toBeVisible({ timeout: 10_000 });
    // TARGET_NAME is a person, so it must drop out of a business-only list
    await expect(page.getByText(TARGET_NAME)).toHaveCount(0);
  });

  test('status filter reveals non-active entities', async ({ page }) => {
    await page.goto('/entity-registry');
    await expect(page.locator('[data-testid="entity-registry-page"]')).toBeVisible({ timeout: 10_000 });

    // Narrow to this spec's fixtures — the list paginates at 25 rows
    await page.getByPlaceholder('Search entities...').fill(INACTIVE_NAME);

    // The list defaults to active-only, so the inactive entity is hidden...
    await page.locator('[data-testid="entity-status-filter"]').selectOption('active');
    await expect(page.getByText(INACTIVE_NAME)).toHaveCount(0);

    // ...and "All statuses" (empty value = no server-side status predicate) reveals it
    await page.locator('[data-testid="entity-status-filter"]').selectOption('');
    await expect(page.getByText(INACTIVE_NAME).first()).toBeVisible({ timeout: 10_000 });
  });

  test('create form offers only registered entity types', async ({ page }) => {
    await page.goto('/entity-registry/new');
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    const select = page.locator('[data-testid="entity-type-select"]');
    await expect(select).toBeVisible();
    // It is a <select>, not a text input — free text is impossible
    expect(await select.evaluate((el) => el.tagName)).toBe('SELECT');

    // Create is blocked until a type is chosen, since type_key is required
    const createBtn = page.getByRole('button', { name: /create entity/i });
    await page.locator('#name').fill('E2E Lookup Gating Check');
    await expect(createBtn).toBeDisabled();
    await select.selectOption('person');
    await expect(createBtn).toBeEnabled();
  });
});

test.describe('Entity Registry relationships tab', () => {
  test.describe.configure({ mode: 'serial' });

  const { source: SOURCE_NAME, target: TARGET_NAME } = names('Rel');
  const all = [SOURCE_NAME, TARGET_NAME];
  let sourceId: string;
  let targetId: string;

  test.beforeAll(async () => {
    await cleanup(all);
    sourceId = await createEntity(SOURCE_NAME, 'business');
    targetId = await createEntity(TARGET_NAME, 'person');
  });

  test.afterAll(async () => { await cleanup(all); });

  test('add a relationship using the type selector and entity typeahead', async ({ page }) => {
    await page.goto(`/entity-registry/${sourceId}`);
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /Relationships/ }).click();
    const tab = page.locator('[data-testid="relationships-tab"]');
    await expect(tab).toBeVisible();
    await expect(tab.locator('tbody tr')).toHaveCount(0);

    // Relationship type options show the inverse, so the reciprocal is visible
    const typeSelect = page.locator('[data-testid="relationship-type-select"]');
    await expect(typeSelect.locator(`option[value="${REL_TYPE_KEY}"]`))
      .toHaveText(new RegExp(`${REL_TYPE_LABEL}.*inverse: owned_by`));
    await typeSelect.selectOption(REL_TYPE_KEY);

    // Add stays disabled until a real entity is resolved — no hand-typed IDs
    const addBtn = page.locator('[data-testid="add-relationship-button"]');
    await expect(addBtn).toBeDisabled();

    await page.locator('[data-testid="relationship-target-picker"]').fill(TARGET_NAME);
    await page.getByRole('button', { name: TARGET_NAME }).first().click();
    await expect(addBtn).toBeEnabled();
    await addBtn.click();

    await expect(tab.locator('tbody tr')).toHaveCount(1, { timeout: 10_000 });
    const row = tab.locator('tbody tr').first();
    await expect(row).toContainText(REL_TYPE_LABEL);
    // Counterpart is resolved to a name, not a bare entity_id
    await expect(row).toContainText(TARGET_NAME);
  });

  test('the inverse relation appears on the target entity', async ({ page }) => {
    await page.goto(`/entity-registry/${targetId}`);
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /Relationships/ }).click();
    const tab = page.locator('[data-testid="relationships-tab"]');
    await expect(tab.locator('tbody tr')).toHaveCount(1, { timeout: 10_000 });

    // Read from the target's side the edge is the inverse, shown by label
    // (not the raw inverse_key) and pointing back at the source
    const row = tab.locator('tbody tr').first();
    await expect(row).toContainText(REL_INVERSE_LABEL);
    await expect(row).toContainText(SOURCE_NAME);
  });

  test('direction filter separates incoming from outgoing', async ({ page }) => {
    await page.goto(`/entity-registry/${sourceId}`);
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: /Relationships/ }).click();
    const tab = page.locator('[data-testid="relationships-tab"]');
    await expect(tab.locator('tbody tr')).toHaveCount(1, { timeout: 10_000 });

    await page.locator('[data-testid="relationship-direction-filter"]').selectOption('outgoing');
    await expect(tab.locator('tbody tr')).toHaveCount(1);

    // The source has no inbound edges, so incoming-only must be empty
    await page.locator('[data-testid="relationship-direction-filter"]').selectOption('incoming');
    await expect(tab.locator('tbody tr')).toHaveCount(0);
  });

  test('remove a relationship', async ({ page }) => {
    await page.goto(`/entity-registry/${sourceId}`);
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: /Relationships/ }).click();
    const tab = page.locator('[data-testid="relationships-tab"]');
    await expect(tab.locator('tbody tr')).toHaveCount(1, { timeout: 10_000 });

    await tab.locator('[data-testid="remove-relationship-button"]').first().click();
    await expect(tab.locator('tbody tr')).toHaveCount(0, { timeout: 10_000 });
  });
});

test.describe('Entity Registry category assignment', () => {
  test.describe.configure({ mode: 'serial' });

  const { source: SOURCE_NAME } = names('Cat');
  let sourceId: string;

  test.beforeAll(async () => {
    await cleanup([SOURCE_NAME]);
    sourceId = await createEntity(SOURCE_NAME, 'business');
  });

  test.afterAll(async () => { await cleanup([SOURCE_NAME]); });

  test('assign and remove a category from the lookup list', async ({ page }) => {
    await page.goto(`/entity-registry/${sourceId}`);
    await expect(page.locator('[data-testid="entity-registry-detail-page"]')).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /Categories/ }).click();
    const select = page.locator('[data-testid="add-category-select"]');
    await expect(select).toBeVisible();

    // The lead_* categories are part of the canonical reference set
    await expect(select.locator(`option[value="${CATEGORY_KEY}"]`)).toHaveCount(1);
    await select.selectOption(CATEGORY_KEY);
    await page.getByRole('button', { name: /^Add$/ }).click();

    await expect(page.getByText(CATEGORY_LABEL)).toBeVisible({ timeout: 10_000 });
    // An assigned category drops out of the picker
    await expect(select.locator(`option[value="${CATEGORY_KEY}"]`)).toHaveCount(0);

    await page.locator('[data-testid="remove-category-button"]').first().click();
    await expect(select.locator(`option[value="${CATEGORY_KEY}"]`)).toHaveCount(1, { timeout: 10_000 });
  });
});
