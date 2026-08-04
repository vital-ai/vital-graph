import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID, GRAPH_ID } from '../seed-constants';

/**
 * Tier 7 — KG Frames sorting and paging through the UI (sequence plan step 9).
 *
 * The fixture makes NO two orderings agree:
 *   - URI order        f01 … f14
 *   - frame sequence   12 … 1  (reverse of URI order; 2 frames have none)
 *   - name             all share the search token, then a letter running Z…M
 * so an ignored ORDER BY, a lexical sort ("10" < "9"), or an order lost while
 * rebuilding objects from triples each produce a distinct, detectable wrong
 * answer.
 *
 * Note: the page deliberately enables sorting only once a search or form-type
 * filter narrows the set (sorting a whole space is a full scan + sort), so
 * every sorted case here types the search token first. That also scopes the
 * assertions to this fixture.
 */

const NS = 'urn:e2e:framesort:';
const TOKEN = 'ZzFrameSortFixture';
const ENCODED_GRAPH = encodeURIComponent(GRAPH_ID);

const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const KG_FRAME_TYPE = 'http://vital.ai/ontology/haley-ai-kg#KGFrame';
const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
const HAS_FRAME_SEQ = 'http://vital.ai/ontology/haley-ai-kg#hasFrameSequence';
const XSD_INT = 'http://www.w3.org/2001/XMLSchema#integer';

const SEQUENCED = 12;      // spans the 1..12 lexical trap
const UNSEQUENCED = 2;
const TOTAL = SEQUENCED + UNSEQUENCED;

const shortFor = (i: number) => `f${String(i).padStart(2, '0')}`;
const uriFor = (i: number) => `${NS}${shortFor(i)}`;
/** f01 → 12, f12 → 1 */
const seqFor = (i: number) => SEQUENCED + 1 - i;

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
  const quads: { s: string; p: string; o: string }[] = [];
  for (let i = 1; i <= TOTAL; i++) {
    const uri = uriFor(i);
    // Name order (Z,Y,X…) differs from BOTH uri order and sequence order.
    const letter = String.fromCharCode('Z'.charCodeAt(0) - (i - 1));
    quads.push({ s: `<${uri}>`, p: `<${RDF_TYPE}>`, o: `<${KG_FRAME_TYPE}>` });
    quads.push({ s: `<${uri}>`, p: `<${HAS_NAME}>`, o: `"${TOKEN} ${letter} ${shortFor(i)}"` });
    if (i <= SEQUENCED) {
      quads.push({ s: `<${uri}>`, p: `<${HAS_FRAME_SEQ}>`, o: `"${seqFor(i)}"^^<${XSD_INT}>` });
    }
  }
  await ctx.post('/api/graphs/kgframes', {
    params: { space_id: SPACE_ID, graph_id: GRAPH_ID, operation_mode: 'create' },
    headers,
    data: { quads },
  });
  await ctx.dispose();
}

async function cleanup() {
  const { ctx, headers } = await getAuthHeaders();
  const uris = Array.from({ length: TOTAL }, (_, k) => uriFor(k + 1));
  await ctx.delete('/api/graphs/kgframes', {
    params: {
      space_id: SPACE_ID, graph_id: GRAPH_ID, uri_list: uris.join(','),
    },
    headers,
  });
  await ctx.dispose();
}

type Page = import('@playwright/test').Page;

/**
 * Wait until the fixture's rows have settled to `expected`.
 *
 * Fixed sleeps are the classic flake source here — long enough when this spec
 * runs alone, too short when the full suite saturates the machine, so
 * assertions run against a half-refreshed table.
 */
async function expectRowCount(page: Page, expected: number) {
  await expect(async () => {
    expect((await visibleOrder(page)).length).toBe(expected);
  }).toPass({ timeout: 20_000 });
}

/**
 * Wait until the rendered order differs from `previous`.
 *
 * Row COUNT is unchanged by a re-sort, so waiting on it cannot tell whether a
 * sort has been applied yet — a toggle assertion can then read the pre-sort
 * order and fail intermittently under load. Wait on the thing that actually
 * changes.
 */
async function expectOrderToChangeFrom(page: Page, previous: string[]) {
  await expect(async () => {
    const now = await visibleOrder(page);
    expect(now.length).toBe(previous.length);
    expect(now).not.toEqual(previous);
  }).toPass({ timeout: 20_000 });
}

/** Wait until the first rendered row is `expected`. */
async function expectFirstRow(page: Page, expected: string) {
  await expect(async () => {
    expect((await visibleOrder(page))[0]).toBe(expected);
  }).toPass({ timeout: 20_000 });
}

/** Visible frame short-names (f01…), in render order, fixture rows only. */
async function visibleOrder(page: Page): Promise<string[]> {
  // Read every row in ONE call. Looping `rows.nth(i).innerText()` re-queries
  // the DOM per row, so a React re-render mid-loop can hit a detached node —
  // which surfaced as intermittent timeouts while paging.
  const texts = await page.locator('[data-testid="frame-row"]').allInnerTexts();
  const out: string[] = [];
  for (const text of texts) {
    const m = text.match(/\bf(\d{2})\b/);
    if (m) out.push('f' + m[1]);
  }
  return out;
}

/** Open the page, search for the fixture (which also enables sorting). */
async function openAndSearch(page: Page, pageSize = '100') {
  await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgframes`);
  await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 15_000 });
  await page.locator('[data-testid="frames-page-size"]').selectOption(pageSize);
  await page.locator('[data-testid="frames-search"]').fill(TOKEN);
  // search is debounced (400ms) then refetches — wait for the fixture, not a clock
  await expect(page.locator('[data-testid="frame-row"]').first()).toBeVisible({ timeout: 20_000 });
  await expectRowCount(page, TOTAL);
}

async function sortBySequence(page: Page) {
  await page.locator('[data-testid="frames-sort-select"]').selectOption(HAS_FRAME_SEQ);
  await expectRowCount(page, TOTAL);
  // Sequence 1 belongs to the LAST frame by URI, so this also proves the sort
  // actually landed rather than us reading the pre-sort page.
  await expectFirstRow(page, shortFor(SEQUENCED));
}

test.describe('KG Frames sorting and paging', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => {
    await cleanup();
    await seed();
  });
  test.afterAll(async () => {
    await cleanup();
  });

  test('sorting is disabled until a search or filter narrows the set', async ({ page }) => {
    await page.goto(`/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/objects/kgframes`);
    await expect(page.locator('[data-testid="kgframes-page"]')).toBeVisible({ timeout: 15_000 });

    const sortSelect = page.locator('[data-testid="frames-sort-select"]');
    await expect(sortSelect).toBeDisabled();

    await page.locator('[data-testid="frames-search"]').fill(TOKEN);
    await expect(sortSelect).toBeEnabled({ timeout: 20_000 });
  });

  test('the fixture is fully visible on one page', async ({ page }) => {
    await openAndSearch(page);
    expect((await visibleOrder(page)).length).toBe(TOTAL);
  });

  test('sorting by sequence is numeric and reverses URI order', async ({ page }) => {
    await openAndSearch(page);
    await sortBySequence(page);

    const order = await visibleOrder(page);
    const sequenced = order.filter(n => Number(n.slice(1)) <= SEQUENCED);
    // sequence 1..12 == URI order reversed. A lexical sort would start f03,f02,f01,f12…
    expect(sequenced).toEqual(
      Array.from({ length: SEQUENCED }, (_, k) => shortFor(SEQUENCED - k)),
    );
  });

  test('frames without a sequence render last', async ({ page }) => {
    await openAndSearch(page);
    await sortBySequence(page);

    const order = await visibleOrder(page);
    const unsequenced = Array.from(
      { length: UNSEQUENCED }, (_, k) => shortFor(SEQUENCED + 1 + k),
    );
    expect(order.slice(-UNSEQUENCED).sort()).toEqual([...unsequenced].sort());
  });

  test('toggling the name column reverses the rendered order', async ({ page }) => {
    await openAndSearch(page);

    // Names are assigned Z,Y,X… by URI order, so alphabetical ASC is exactly
    // reverse-URI order: f14 leads ascending, f01 leads descending. Waiting on
    // those concrete leaders is load-proof, where "the order changed" could
    // capture an intermediate render.
    await page.locator('[data-testid="frames-sort-name"]').click();
    await expectFirstRow(page, shortFor(TOTAL));
    const asc = await visibleOrder(page);

    await page.locator('[data-testid="frames-sort-name"]').click();
    await expectFirstRow(page, shortFor(1));
    const desc = await visibleOrder(page);

    expect(asc.length).toBe(TOTAL);
    expect(desc).toEqual([...asc].reverse());
  });

  test('paging a sorted list yields each frame once, in the same order', async ({ page }) => {
    await openAndSearch(page);
    await sortBySequence(page);
    const unpaged = await visibleOrder(page);
    expect(unpaged.length).toBe(TOTAL);

    // Shrink the page so the fixture spans several pages.
    const PAGE = 10;
    await page.locator('[data-testid="frames-page-size"]').selectOption(String(PAGE));
    await expectRowCount(page, PAGE);

    const seen: string[] = [];
    const pages = Math.ceil(TOTAL / PAGE);
    for (let p = 0; p < pages; p++) {
      const expected = p === pages - 1 ? TOTAL - p * PAGE : PAGE;
      await expectRowCount(page, expected);
      seen.push(...await visibleOrder(page));
      if (p === pages - 1) break;
      await page.getByRole('button', { name: /next/i }).click();
    }

    expect(new Set(seen).size).toBe(seen.length);   // no frame on two pages
    expect(seen).toEqual(unpaged);                  // and the order is preserved
  });
});
