import { test, expect, request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS, SPACE_ID } from '../seed-constants';

/**
 * Tier 7 — Entity graph frame/slot paging (sequence plan step 8).
 *
 * Two entities, so both sides of the threshold rule are covered:
 *   SMALL — 3 frames, few slots       → NO paging controls anywhere
 *   BIG   — 30 frames; frame 0 has 40 slots → controls at both levels
 *
 * Ordering is decorrelated as everywhere else in this suite: frame sequence
 * and slot sequence both run OPPOSITE to URI order, so a dropped ORDER BY or a
 * lexical sort is visible.
 */

const NS = 'urn:e2e:egpage:';
const SMALL = `${NS}small`;
const BIG = `${NS}big`;

/**
 * This spec gets its OWN graph rather than sharing the seeded one.
 *
 * It creates 2 entities and 33 frames, and other specs assert seeded entity /
 * frame COUNTS in the shared graph — running in parallel, those counts broke.
 * An isolated graph removes the interference entirely rather than papering
 * over it with ordering or retries.
 */
const OWN_GRAPH = 'urn:e2e:graph:egpage';
const ENCODED_GRAPH = encodeURIComponent(OWN_GRAPH);

const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const KG_ENTITY = 'http://vital.ai/ontology/haley-ai-kg#KGEntity';
const KG_FRAME = 'http://vital.ai/ontology/haley-ai-kg#KGFrame';
const KG_TEXT_SLOT = 'http://vital.ai/ontology/haley-ai-kg#KGTextSlot';
const EDGE_ENTITY_FRAME = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame';
const EDGE_FRAME_SLOT = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot';
const HAS_SOURCE = 'http://vital.ai/ontology/vital-core#hasEdgeSource';
const HAS_DEST = 'http://vital.ai/ontology/vital-core#hasEdgeDestination';
const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';
const FRAME_SEQ = 'http://vital.ai/ontology/haley-ai-kg#hasFrameSequence';
const SLOT_SEQ = 'http://vital.ai/ontology/haley-ai-kg#hasSlotSequence';
const TEXT_VALUE = 'http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue';
const XSD_INT = 'http://www.w3.org/2001/XMLSchema#integer';

const SMALL_FRAMES = 3;
const BIG_FRAMES = 30;      // > default page size (25)
const BIG_SLOTS = 40;       // > default page size, on frame 0

type Page = import('@playwright/test').Page;
type Quad = { s: string; p: string; o: string };

const u = (x: string) => `<${x}>`;
const lit = (v: string) => `"${v}"`;
const int = (n: number) => `"${n}"^^<${XSD_INT}>`;

async function getAuthHeaders() {
  const baseURL = process.env.VG_TEST_URL || 'http://localhost:8002';
  const ctx = await request.newContext({ baseURL });
  const resp = await ctx.post('/api/login', {
    form: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  const { access_token } = await resp.json();
  return { ctx, headers: { Authorization: `Bearer ${access_token}` } };
}

/** Frames (+ slots on frame 0) for an entity that already exists. */
function frameQuads(entity: string, frames: number, slotsOnFirst: number): Quad[] {
  const q: Quad[] = [];
  for (let i = 0; i < frames; i++) {
    const f = `${entity}:f${String(i).padStart(3, '0')}`;
    q.push({ s: u(f), p: u(RDF_TYPE), o: u(KG_FRAME) });
    q.push({ s: u(f), p: u(HAS_NAME), o: lit(`Frame ${i}`) });
    // Sequence runs OPPOSITE to URI order.
    q.push({ s: u(f), p: u(FRAME_SEQ), o: int(frames - i) });
    const e = `${entity}:ef${i}`;
    q.push({ s: u(e), p: u(RDF_TYPE), o: u(EDGE_ENTITY_FRAME) });
    q.push({ s: u(e), p: u(HAS_SOURCE), o: u(entity) });
    q.push({ s: u(e), p: u(HAS_DEST), o: u(f) });
  }
  const f0 = `${entity}:f000`;
  for (let j = 0; j < slotsOnFirst; j++) {
    const s = `${entity}:s${String(j).padStart(3, '0')}`;
    q.push({ s: u(s), p: u(RDF_TYPE), o: u(KG_TEXT_SLOT) });
    q.push({ s: u(s), p: u(HAS_NAME), o: lit(`Slot ${j}`) });
    q.push({ s: u(s), p: u(TEXT_VALUE), o: lit(`value ${j}`) });
    q.push({ s: u(s), p: u(SLOT_SEQ), o: int(slotsOnFirst - j) });
    const se = `${entity}:se${j}`;
    q.push({ s: u(se), p: u(RDF_TYPE), o: u(EDGE_FRAME_SLOT) });
    q.push({ s: u(se), p: u(HAS_SOURCE), o: u(f0) });
    q.push({ s: u(se), p: u(HAS_DEST), o: u(s) });
  }
  return q;
}

async function seed() {
  const { ctx, headers } = await getAuthHeaders();

  const g = await ctx.put('/api/graphs/graph', {
    params: { space_id: SPACE_ID, graph_uri: OWN_GRAPH },
    headers,
  });
  expect(g.status(), 'create own graph').toBe(200);

  // Entities first, then their frames/slots via the entity-frames endpoint.
  // Posting everything as one /kgentities payload silently created only the
  // entities — the frames never landed and the page rendered empty, so every
  // response is asserted here rather than assumed.
  for (const [uri, name] of [[SMALL, 'Small Entity'], [BIG, 'Big Entity']]) {
    const r = await ctx.post('/api/graphs/kgentities', {
      params: { space_id: SPACE_ID, graph_id: OWN_GRAPH, operation_mode: 'create' },
      headers,
      data: {
        quads: [
          { s: u(uri), p: u(RDF_TYPE), o: u(KG_ENTITY) },
          { s: u(uri), p: u(HAS_NAME), o: lit(name) },
        ],
      },
    });
    expect(r.status(), `seed entity ${uri}`).toBe(200);
  }

  for (const [uri, frames, slots] of [
    [SMALL, SMALL_FRAMES, 2] as const,
    [BIG, BIG_FRAMES, BIG_SLOTS] as const,
  ]) {
    const r = await ctx.post('/api/graphs/kgentities/kgframes', {
      params: { space_id: SPACE_ID, graph_id: OWN_GRAPH, entity_uri: uri, operation_mode: 'create' },
      headers,
      data: { quads: frameQuads(uri, frames, slots) },
    });
    expect(r.status(), `seed frames for ${uri}`).toBe(200);
    const body = await r.json();
    expect(body.success, `seed frames for ${uri}: ${JSON.stringify(body).slice(0, 200)}`).toBeTruthy();
  }

  await ctx.dispose();
}

async function cleanup() {
  const { ctx, headers } = await getAuthHeaders();
  // Dropping the graph removes entities, frames, slots and edges in one go.
  await ctx.delete('/api/graphs/graph', {
    params: { space_id: SPACE_ID, graph_uri: OWN_GRAPH },
    headers,
  });
  await ctx.dispose();
}

async function openEntity(page: Page, entityUri: string) {
  await page.goto(
    `/space/${SPACE_ID}/graph/${ENCODED_GRAPH}/entity/${encodeURIComponent(entityUri)}`,
  );
  await expect(page.locator('[data-testid="entity-graph-viewer"]'))
    .toBeVisible({ timeout: 25_000 });
  await expect(page.locator('[data-testid="frame-card"]').first())
    .toBeVisible({ timeout: 25_000 });
}

/** Frame short-ids (f000…) in render order — one atomic DOM read. */
async function frameOrder(page: Page): Promise<string[]> {
  const uris = await page.locator('[data-testid="frame-card"]')
    .evaluateAll(els => els.map(e => e.getAttribute('data-frame-uri') ?? ''));
  return uris.map(x => x.split(':').pop() ?? '').filter(Boolean);
}

test.describe('Entity graph frame/slot paging', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => {
    await cleanup();
    await seed();
  });
  test.afterAll(async () => {
    await cleanup();
  });

  test('a small entity shows no paging controls at any level', async ({ page }) => {
    await openEntity(page, SMALL);

    await expect(page.locator('[data-testid="frame-pagination"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="slot-pagination"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="frame-card"]')).toHaveCount(SMALL_FRAMES);
  });

  test('expand-all is enabled for a small entity', async ({ page }) => {
    await openEntity(page, SMALL);
    await expect(page.locator('[data-testid="entity-graph-expand-all"]')).toBeEnabled();
  });

  test('a large entity pages its frames and reports the true total', async ({ page }) => {
    await openEntity(page, BIG);

    await expect(page.locator('[data-testid="frame-pagination"]')).toBeVisible();
    // The header count comes from total_count, not from what is loaded.
    await expect(page.locator('[data-testid="entity-graph-frame-count"]'))
      .toHaveText(`${BIG_FRAMES} frames`);
  });

  test('expand-all is disabled while frames are paged', async ({ page }) => {
    await openEntity(page, BIG);
    await expect(page.locator('[data-testid="entity-graph-expand-all"]')).toBeDisabled();
  });

  test('frames render in sequence order, which is the reverse of URI order', async ({ page }) => {
    await openEntity(page, BIG);
    const order = await frameOrder(page);
    expect(order.length).toBeGreaterThan(0);
    // sequence = BIG_FRAMES - i, so ascending sequence starts at the LAST uri.
    expect(order[0]).toBe(`f${String(BIG_FRAMES - 1).padStart(3, '0')}`);
  });

  test('paging frames yields each frame once, in order', async ({ page }) => {
    await openEntity(page, BIG);

    const seen: string[] = [];
    for (let guard = 0; guard < 10; guard++) {
      const current = await frameOrder(page);
      seen.push(...current);
      const next = page.locator('[data-testid="frame-pagination-next"]');
      if (await next.isDisabled()) break;
      await next.click();
      // Compare against the FIRST row of the page we just read. Comparing
      // against its last row is always already true, so the wait returned
      // immediately and the same page was collected twice.
      await expect(async () => {
        expect((await frameOrder(page))[0]).not.toBe(current[0]);
      }).toPass({ timeout: 20_000 });
    }

    expect(seen.length).toBe(BIG_FRAMES);
    expect(new Set(seen).size).toBe(BIG_FRAMES);
    // Whole list, concatenated, is descending URI order (== ascending sequence).
    const expected = Array.from({ length: BIG_FRAMES },
      (_, k) => `f${String(BIG_FRAMES - 1 - k).padStart(3, '0')}`);
    expect(seen).toEqual(expected);
  });

  test('a frame with many slots advertises slot paging and pages them', async ({ page }) => {
    await openEntity(page, BIG);

    // Frame 0 (sequence BIG_FRAMES, so LAST in ascending order) holds the slots.
    // Page to the end to reach it.
    const next = page.locator('[data-testid="frame-pagination-next"]');
    while (!(await next.isDisabled())) {
      await next.click();
      await page.waitForLoadState('networkidle');
    }

    const card = page.locator('[data-testid="frame-card"]')
      .filter({ has: page.locator(`[data-testid="frame-slot-count"]`) })
      .last();
    await card.locator('[data-testid="frame-toggle"]').first().click();

    const slotPager = page.locator('[data-testid="slot-pagination"]');
    await expect(slotPager).toBeVisible({ timeout: 25_000 });
    await expect(page.locator('[data-testid="slot-pagination-range"]'))
      .toContainText(`of ${BIG_SLOTS}`);
  });
});
