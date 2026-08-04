import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Tier 7 — KG Relations sorting and paging through the UI.
 *
 * Relations have no dedicated sequence property; hasListIndex is inherited
 * from VITAL_Edge and is their ordering key.
 *
 * The fixture is built so that NO two orderings agree:
 *   - URI order      r01 … r12
 *   - list index     12 … 1   (reverse of URI order)
 *   - name           Z… … O…  (also reverse, and NOT the index order)
 * If the server ignored ORDER BY, sorted lexically ("10" < "9"), or lost the
 * order while rebuilding objects, the expected sequences below would not hold.
 *
 * Two relations are deliberately left WITHOUT a list index: they must sort
 * last in BOTH directions rather than being interleaved.
 */

const NS = 'urn:e2e:relsort:';
const ENTITY_SRC = `${NS}source`;
const ENTITY_DST = `${NS}dest`;
const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);

const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const KG_ENTITY_TYPE = 'http://vital.ai/ontology/haley-ai-kg#KGEntity';
const EDGE_TYPE = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation';
const HAS_EDGE_SOURCE = 'http://vital.ai/ontology/vital-core#hasEdgeSource';
const HAS_EDGE_DEST = 'http://vital.ai/ontology/vital-core#hasEdgeDestination';
const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
const HAS_LIST_INDEX = 'http://vital.ai/ontology/vital-core#hasListIndex';
const XSD_INT = 'http://www.w3.org/2001/XMLSchema#integer';

const INDEXED_COUNT = 12;
const UNINDEXED_COUNT = 2;

/** r01 → index 12, r12 → index 1. Spans 1..12 to catch a lexical sort. */
const indexFor = (i: number) => INDEXED_COUNT + 1 - i;
const uriFor = (i: number) => `${NS}r${String(i).padStart(2, '0')}`;
const shortFor = (i: number) => `r${String(i).padStart(2, '0')}`;

async function getAuthHeaders() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const loginResp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await loginResp.json();
  return { ctx, headers: { Authorization: `Bearer ${access_token}` } };
}

async function seed() {
  const { ctx, headers } = await getAuthHeaders();

  for (const [uri, name] of [[ENTITY_SRC, 'Rel Sort Source'], [ENTITY_DST, 'Rel Sort Dest']]) {
    await ctx.post('/api/graphs/kgentities', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, operation_mode: 'create' },
      headers,
      data: {
        quads: [
          { s: `<${uri}>`, p: `<${RDF_TYPE}>`, o: `<${KG_ENTITY_TYPE}>` },
          { s: `<${uri}>`, p: `<${HAS_NAME}>`, o: `"${name}"` },
        ],
      },
    });
  }

  const quads: { s: string; p: string; o: string }[] = [];
  for (let i = 1; i <= INDEXED_COUNT + UNINDEXED_COUNT; i++) {
    const uri = uriFor(i);
    quads.push({ s: `<${uri}>`, p: `<${RDF_TYPE}>`, o: `<${EDGE_TYPE}>` });
    quads.push({ s: `<${uri}>`, p: `<${HAS_EDGE_SOURCE}>`, o: `<${ENTITY_SRC}>` });
    quads.push({ s: `<${uri}>`, p: `<${HAS_EDGE_DEST}>`, o: `<${ENTITY_DST}>` });
    // Names run Z,Y,X… so name order differs from BOTH uri and index order.
    const letter = String.fromCharCode('Z'.charCodeAt(0) - (i - 1));
    quads.push({ s: `<${uri}>`, p: `<${HAS_NAME}>`, o: `"${letter} Sort Relation ${shortFor(i)}"` });
    if (i <= INDEXED_COUNT) {
      quads.push({
        s: `<${uri}>`, p: `<${HAS_LIST_INDEX}>`,
        o: `"${indexFor(i)}"^^<${XSD_INT}>`,
      });
    }
  }
  await ctx.post('/api/graphs/kgrelations', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, operation_mode: 'create' },
    headers,
    data: { quads },
  });
  await ctx.dispose();
}

async function cleanup() {
  const { ctx, headers } = await getAuthHeaders();
  const resp = await ctx.get('/api/graphs/kgrelations', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, page_size: 500 },
    headers,
  });
  const data = await resp.json();
  const uris: string[] = [...new Set(
    (data.results || [])
      .map((q: { s: string }) => q.s.replace(/^<|>$/g, ''))
      .filter((u: string) => u.startsWith(NS)),
  )] as string[];
  if (uris.length > 0) {
    await ctx.delete('/api/graphs/kgrelations', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID },
      headers,
      data: { relation_uris: uris },
    });
  }
  for (const uri of [ENTITY_SRC, ENTITY_DST]) {
    await ctx.delete('/api/graphs/kgentities', {
      params: { space_id: SPACE_ID, graph_id: GRAPH_ID, uri },
      headers,
    });
  }
  await ctx.dispose();
}

/**
 * Wait until the fixture's rows have settled to `expected`.
 *
 * Fixed sleeps were the original source of flake here: they were long enough
 * running this spec alone but not when the full suite saturates the machine,
 * so assertions ran against a half-refreshed table.
 */
async function expectRowCount(page: import('@playwright/test').Page, expected: number) {
  await expect(async () => {
    expect((await visibleOrder(page)).length).toBe(expected);
  }).toPass({ timeout: 20_000 });
}

/** Wait until the first rendered row is `expected`. */
async function expectFirstRow(
  page: import('@playwright/test').Page, expected: string,
) {
  await expect(async () => {
    expect((await visibleOrder(page))[0]).toBe(expected);
  }).toPass({ timeout: 20_000 });
}

/**
 * Wait until the rendered order differs from `previous`.
 *
 * A re-sort leaves the row COUNT unchanged, so counting cannot tell whether
 * the sort has landed; a toggle assertion can otherwise read the pre-sort
 * order and fail intermittently under load.
 */
async function expectOrderToChangeFrom(
  page: import('@playwright/test').Page, previous: string[],
) {
  await expect(async () => {
    const now = await visibleOrder(page);
    expect(now.length).toBe(previous.length);
    expect(now).not.toEqual(previous);
  }).toPass({ timeout: 20_000 });
}

/** Visible relation short-names (r01…), in render order, for our fixture only. */
async function visibleOrder(page: import('@playwright/test').Page): Promise<string[]> {
  // Read every row in ONE call. Looping `rows.nth(i).innerText()` re-queries
  // the DOM per row, so a React re-render mid-loop can hit a detached node —
  // which surfaced as intermittent timeouts while paging.
  const texts = await page.locator('[data-testid="relation-row"]').allInnerTexts();
  const out: string[] = [];
  for (const text of texts) {
    const m = text.match(/\br(\d{2})\b/);
    if (m) out.push('r' + m[1]);
  }
  return out;
}

async function openRelationsPage(page: import('@playwright/test').Page) {
  await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgrelations`);
  await expect(page.locator('[data-testid="kgrelations-page"]')).toBeVisible({ timeout: 15_000 });
  // Scope the list to this fixture's source entity. Specs run in parallel
  // against a shared space, so without this the fixture can be pushed off
  // page 1 by relations another spec created — which made the ordering
  // assertions flaky in full-suite runs while passing in isolation.
  await page.locator('[data-testid="relations-source-filter"]').fill(ENTITY_SRC);
  await expect(page.locator('[data-testid="relation-row"]').first()).toBeVisible({ timeout: 20_000 });
  // Let the filter's fetch fully settle before any further control change.
  // The page does not sequence or cancel in-flight requests, so firing a
  // second change immediately can let the FIRST response land last and
  // overwrite it — the list then shows a stale page and never refetches.
  await expectRowCount(page, INDEXED_COUNT + UNINDEXED_COUNT);
}

/** Set the page-size select to its largest option so one page holds the fixture. */
async function selectLargestPageSize(page: import('@playwright/test').Page) {
  // Address the control by testid, not by option text: `locator('select')
  // .filter({hasText:'100'})` also matches the space/graph selects and can
  // resolve to the wrong element after a re-render, which showed up as an
  // intermittent row-count timeout here.
  await page.locator('[data-testid="relations-page-size"]').selectOption('100');
  await expectRowCount(page, INDEXED_COUNT + UNINDEXED_COUNT);

}

test.describe('KG Relations sorting and paging', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => {
    await cleanup();
    await seed();
  });
  test.afterAll(async () => {
    await cleanup();
  });

  test('index column renders values and a dash for unindexed relations', async ({ page }) => {
    await openRelationsPage(page);
    await selectLargestPageSize(page);

    const cells = page.locator('[data-testid="relation-index"]');
    expect(await cells.count()).toBeGreaterThan(0);
    const texts = await cells.allInnerTexts();
    expect(texts.some(t => t.trim() === '—')).toBeTruthy();
    expect(texts.some(t => /^\d+$/.test(t.trim()))).toBeTruthy();
  });

  test('sorting by list index ascending is numeric and reverses URI order', async ({ page }) => {
    await openRelationsPage(page);
    await selectLargestPageSize(page);

    await page.locator('[data-testid="relations-sort-index"]').click();
    await expectRowCount(page, INDEXED_COUNT + UNINDEXED_COUNT);
    await expectFirstRow(page, shortFor(INDEXED_COUNT));

    const order = await visibleOrder(page);
    const indexed = order.filter(n => Number(n.slice(1)) <= INDEXED_COUNT);
    // index 1..12 == URI order reversed. A lexical sort would give r03,r02,r01,r12…
    const expected = Array.from({ length: INDEXED_COUNT }, (_, k) => shortFor(INDEXED_COUNT - k));
    expect(indexed).toEqual(expected);
  });

  test('unindexed relations sort last in both directions', async ({ page }) => {
    await openRelationsPage(page);
    await selectLargestPageSize(page);

    const unindexed = Array.from(
      { length: UNINDEXED_COUNT }, (_, k) => shortFor(INDEXED_COUNT + 1 + k),
    );

    // ascending
    await page.locator('[data-testid="relations-sort-index"]').click();
    await expectRowCount(page, INDEXED_COUNT + UNINDEXED_COUNT);
    let order = await visibleOrder(page);
    expect(order.slice(-UNINDEXED_COUNT).sort()).toEqual([...unindexed].sort());

    // descending — still last, not first
    await page.locator('[data-testid="relations-sort-index"]').click();
    await expectRowCount(page, INDEXED_COUNT + UNINDEXED_COUNT);
    order = await visibleOrder(page);
    expect(order.slice(-UNINDEXED_COUNT).sort()).toEqual([...unindexed].sort());
  });

  test('toggling to descending reverses the indexed order', async ({ page }) => {
    await openRelationsPage(page);
    await selectLargestPageSize(page);

    const initial = await visibleOrder(page);
    await page.locator('[data-testid="relations-sort-index"]').click();
    await expectOrderToChangeFrom(page, initial);
    const ascAll = await visibleOrder(page);
    const asc = ascAll.filter(n => Number(n.slice(1)) <= INDEXED_COUNT);

    await page.locator('[data-testid="relations-sort-index"]').click();
    await expectOrderToChangeFrom(page, ascAll);
    const desc = (await visibleOrder(page)).filter(n => Number(n.slice(1)) <= INDEXED_COUNT);

    expect(desc).toEqual([...asc].reverse());
  });

  test('paging through a sorted list yields each relation exactly once', async ({ page }) => {
    // The sorted order is fully determined by the fixture, so assert it
    // directly instead of snapshotting an "unpaged" render and comparing.
    // That removes a whole phase — and the page-size change that used to
    // happen AFTER sorting, which raced the sort's refetch.
    const expectedOrder = [
      // list index 1..12 == reverse URI order
      ...Array.from({ length: INDEXED_COUNT }, (_, k) => shortFor(INDEXED_COUNT - k)),
      // then the unindexed tail, in subject order
      ...Array.from({ length: UNINDEXED_COUNT }, (_, k) => shortFor(INDEXED_COUNT + 1 + k)),
    ];

    await openRelationsPage(page);

    // Page size first, then sort — one state change settles before the next.
    const PAGE = 10;
    await page.locator('[data-testid="relations-page-size"]').selectOption(String(PAGE));
    await expectRowCount(page, PAGE);

    await page.locator('[data-testid="relations-sort-index"]').click();
    await expectFirstRow(page, expectedOrder[0]);

    const seen: string[] = [];
    const total = INDEXED_COUNT + UNINDEXED_COUNT;
    const pages = Math.ceil(total / PAGE);
    for (let p = 0; p < pages; p++) {
      const expected = p === pages - 1 ? total - p * PAGE : PAGE;
      await expectRowCount(page, expected);
      seen.push(...await visibleOrder(page));
      if (p === pages - 1) break;
      await page.getByRole('button', { name: /next/i }).click();
    }

    expect(new Set(seen).size).toBe(seen.length);   // no relation on two pages
    expect(seen).toEqual(expectedOrder);            // and the order is preserved
  });
});
