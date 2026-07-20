import { request } from '@playwright/test';
import { ADMIN_USER, ADMIN_PASS } from '../seed-constants';

/**
 * Per-suite space isolation helpers.
 *
 * Mutating CRUD specs share one seeded space (`e2e_test_space`) by default,
 * which — under `fullyParallel` — lets specs running in different workers
 * clobber each other's data (the alternating "not visible" / "count 0" flakes).
 * A spec that gives itself a dedicated space via these helpers can't race any
 * other suite, no matter the interleaving.
 *
 * Spaces are created and dropped through the sanctioned space-manager REST path
 * (POST/DELETE /api/spaces) — never by inserting space rows directly. Dropping a
 * space cascades all its per-space tables (data + graphs), so `dropSpace` is the
 * only teardown needed.
 */

const BASE_URL = process.env.VG_TEST_URL || 'http://localhost:8002';

async function authContext() {
  const ctx = await request.newContext({ baseURL: BASE_URL });
  // Retry login on transient connection errors ("socket hang up", ECONNRESET).
  // This runs in beforeAll/afterAll, so a one-off dropped connection under the
  // full suite's load would otherwise fail the whole describe block.
  let lastErr: unknown;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const loginResp = await ctx.post('/api/login', {
        form: { username: ADMIN_USER, password: ADMIN_PASS },
      });
      const { access_token } = await loginResp.json();
      return { ctx, headers: { Authorization: `Bearer ${access_token}` } };
    } catch (err) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
    }
  }
  throw lastErr;
}

/** Drop a space if it exists (idempotent — 404s are fine). */
export async function dropSpace(spaceId: string): Promise<void> {
  const { ctx, headers } = await authContext();
  await ctx.delete('/api/spaces', { headers, params: { space_id: spaceId } });
  await ctx.dispose();
}

/**
 * Create a pristine isolated space + graph via the space manager.
 *
 * Drops any leftover space of the same name first (a crashed prior run may have
 * skipped its afterAll), so each run starts clean. Safe because the caller owns
 * a name no other suite uses.
 */
export async function createSpace(
  spaceId: string,
  graphUri: string,
  opts: { name?: string; description?: string } = {},
): Promise<void> {
  await dropSpace(spaceId);

  const { ctx, headers } = await authContext();
  const jsonHeaders = { ...headers, 'Content-Type': 'application/json' };

  const createResp = await ctx.post('/api/spaces', {
    headers: jsonHeaders,
    data: {
      space: spaceId,
      space_name: opts.name ?? spaceId,
      space_description: opts.description ?? 'E2E isolated test space',
    },
  });
  if (!createResp.ok()) {
    throw new Error(`create space ${spaceId} failed: ${createResp.status()} ${await createResp.text()}`);
  }

  const graphResp = await ctx.put('/api/graphs/graph', {
    headers,
    params: { space_id: spaceId, graph_uri: graphUri },
  });
  if (!graphResp.ok()) {
    throw new Error(`create graph ${graphUri} failed: ${graphResp.status()} ${await graphResp.text()}`);
  }

  await ctx.dispose();
}
