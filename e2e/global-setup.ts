/**
 * Playwright global setup — runs once before all test suites.
 *
 * Two jobs:
 *   1. Wait for the VitalGraph server to be healthy.
 *   2. Verify the seeded fixture is what the specs assume.
 *
 * Seeding is handled by run-tests.sh before Playwright starts.
 * If running Playwright directly (without the shell script), seed
 * manually first:
 *   python -m tests.shared.seed_ui_test_data --server-url http://localhost:8002
 */

import {
  ADMIN_USER,
  ADMIN_PASS,
  SPACE_ID,
  GRAPH_ID,
  ENTITIES,
  EXPECTED_ENTITY_COUNT,
} from './seed-constants';

const BASE_URL = process.env.VG_TEST_URL || 'http://localhost:8002';
const MAX_WAIT_MS = 60_000;
const POLL_INTERVAL_MS = 2_000;

async function waitForHealthy(): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < MAX_WAIT_MS) {
    try {
      const res = await fetch(`${BASE_URL}/health`);
      if (res.ok) {
        console.log(`✅ VitalGraph server is healthy at ${BASE_URL}`);
        return;
      }
    } catch {
      // Server not ready yet
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error(`Server at ${BASE_URL} did not become healthy within ${MAX_WAIT_MS / 1000}s`);
}

async function login(): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: ADMIN_USER, password: ADMIN_PASS }),
  });
  const body = await res.json();
  if (!body.access_token) throw new Error(`Could not log in to ${BASE_URL} as ${ADMIN_USER}`);
  return body.access_token;
}

/**
 * Check the seeded space is in the state the specs assume.
 *
 * Specs assert exact counts against this shared graph — e.g.
 * `toHaveCount(EXPECTED_ENTITY_COUNT)`. When stale data accumulates there those
 * assertions fail in a way that looks like a product bug, and it has cost real
 * time twice: a leftover `urn:e2e:probe:e1` entity made two specs report
 * "expected 3, received 4", and orphaned FileNodes pushed a fixture off page 1
 * of the Files list. Both were data problems wearing a code-bug costume.
 *
 * Failing here, once, with the offending URIs named, turns that into a one-line
 * diagnosis. See issues/022 and issues/035.
 */
async function verifySeededFixture(token: string): Promise<void> {
  const headers = { Authorization: `Bearer ${token}` };
  const params = new URLSearchParams({
    space_id: SPACE_ID,
    graph_id: GRAPH_ID,
    page_size: '100',
  });
  const res = await fetch(`${BASE_URL}/api/graphs/kgentities?${params}`, { headers });
  if (!res.ok) {
    throw new Error(
      `Precondition check failed: could not list entities in ${SPACE_ID}/${GRAPH_ID} `
      + `(HTTP ${res.status}). Has the seed run?  `
      + `python -m tests.shared.seed_ui_test_data`,
    );
  }

  const data = await res.json();
  const byUri = new Map<string, string>();
  for (const quad of data.results ?? []) {
    const s = String(quad.s ?? '').replace(/^<|>$/g, '');
    if (String(quad.p ?? '').includes('hasName')) {
      byUri.set(s, String(quad.o ?? '').replace(/^"|"$/g, ''));
    }
  }

  const expected = new Set<string>(Object.values(ENTITIES).map((e) => e.uri));
  const found = [...byUri.keys()];
  const missing = [...expected].filter((uri) => !byUri.has(uri));
  const unexpected = found.filter((uri) => !expected.has(uri));

  if (missing.length > 0) {
    throw new Error(
      `Seeded fixture incomplete in ${SPACE_ID}/${GRAPH_ID}: `
      + `${missing.length} of ${EXPECTED_ENTITY_COUNT} seeded entities missing `
      + `(${missing.join(', ')}).\nRun: python -m tests.shared.seed_ui_test_data`,
    );
  }

  if (unexpected.length > 0) {
    throw new Error(
      `Seeded space ${SPACE_ID}/${GRAPH_ID} has ${unexpected.length} unexpected `
      + `entit${unexpected.length === 1 ? 'y' : 'ies'}: `
      + unexpected.map((uri) => `${uri} ("${byUri.get(uri)}")`).join(', ')
      + `.\nSpecs assert exact counts against this graph, so leftovers surface as `
      + `"expected ${EXPECTED_ENTITY_COUNT}, received ${found.length}" in unrelated `
      + `tests.\nDelete them, or reset the stack:\n`
      + `  docker compose -f docker-compose.test.yml down\n`
      + `  docker compose -f docker-compose.test.yml up -d --build --wait`,
    );
  }

  console.log(`✅ Seeded fixture verified: ${EXPECTED_ENTITY_COUNT} entities in ${SPACE_ID}`);
}

/**
 * Foreign spaces are not fatal, but they change which space a page selects by
 * default — one sorting ahead of the seeded space is how a stale `apitest_*`
 * space became a default selection and exposed a race in the Indexes page.
 * Worth a warning so a confusing run has a visible explanation.
 */
async function warnAboutForeignSpaces(token: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/spaces`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return;
  const body = await res.json();
  const spaces: string[] = (Array.isArray(body) ? body : body.spaces ?? [])
    .map((s: { space?: string }) => String(s.space ?? ''))
    .filter(Boolean);

  const known = new Set([SPACE_ID, 'sp_kg_types', 'entity_registry', 'agent_registry']);
  const foreign = spaces.filter((s) => !known.has(s) && !s.startsWith('e2e_'));
  if (foreign.length === 0) return;

  const sortsFirst = foreign.filter((s) => s < SPACE_ID);
  console.warn(
    `⚠️  ${foreign.length} space(s) here are not from the e2e fixture: ${foreign.join(', ')}`
    + (sortsFirst.length
      ? `\n   ${sortsFirst.join(', ')} sort(s) before "${SPACE_ID}" and may become a `
        + `page's default selection, which has caused confusing failures (issues/022).`
      : ''),
  );
}

async function globalSetup(): Promise<void> {
  await waitForHealthy();
  const token = await login();
  await verifySeededFixture(token);
  await warnAboutForeignSpaces(token);
}

export default globalSetup;
