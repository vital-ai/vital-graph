import { describe, it, expect, vi, afterEach } from 'vitest';
import { VitalGraphClient } from '../../src/VitalGraphClient.js';

/**
 * `kgentities.batchCount` must send the body the server's batch-count route
 * validates: `{ space_id, graph_id, count_requests: [{ label, entity_type_uri }] }`.
 * It sent `{ entity_type_uris }`, which the server rejects before counting.
 */
describe('kgentities.batchCount', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends space_id, graph_id and one labelled count request per type', async () => {
    let body: any = null;
    let url = '';
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (u, init) => {
      const s = typeof u === 'string' ? u : u.toString();
      if (!s.includes('/api/login')) {
        url = s;
        body = init?.body ? JSON.parse(String(init.body)) : null;
      }
      return new Response(JSON.stringify({ status: 'found', counts: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    const client = new VitalGraphClient({ serverUrl: 'http://localhost:8001', apiKey: 'vg_test_key' });
    await client.open();

    await client.kgentities.batchCount('sp', 'urn:g', ['urn:t:A', 'urn:t:B']);

    expect(url).toContain('/api/graphs/kgentities/counts');
    expect(body).toEqual({
      space_id: 'sp',
      graph_id: 'urn:g',
      count_requests: [
        { label: 'urn:t:A', entity_type_uri: 'urn:t:A' },
        { label: 'urn:t:B', entity_type_uri: 'urn:t:B' },
      ],
    });
  });
});
