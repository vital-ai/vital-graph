import { describe, it, expect, vi, afterEach } from 'vitest';
import { VitalGraphClient } from '../../src/VitalGraphClient.js';

/**
 * Sort/paging query parameters for frames, slots and relations.
 *
 * These assert on the URL actually sent. That matters because the failure mode
 * here is silent: a param that is accepted by the method signature but never
 * forwarded produces a perfectly successful, unsorted response. Three real
 * bugs of exactly that shape were found while adding these endpoints
 * (ApiService dropping relation_type_uri/direction/sort_by, and the Python
 * facade passing page_size positionally into frame_uris).
 *
 * Sort keys must match the server allow-lists — an unlisted URI comes back as
 * an INVALID_REQUEST body with HTTP 200, not an error.
 */

const FRAME_SEQUENCE = 'http://vital.ai/ontology/haley-ai-kg#hasFrameSequence';
const SLOT_SEQUENCE = 'http://vital.ai/ontology/haley-ai-kg#hasSlotSequence';
const LIST_INDEX = 'http://vital.ai/ontology/vital-core#hasListIndex';

/** Capture the URL of the first non-login request. */
function captureRequestUrl(): { getUrl: () => string } {
  let captured = '';
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
    const urlStr = typeof url === 'string' ? url : url.toString();
    if (!urlStr.includes('/api/login')) captured = urlStr;
    return new Response(
      JSON.stringify({ results: [], total_count: 0, page_size: 10, offset: 0 }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    );
  });
  return { getUrl: () => captured };
}

async function connectedClient(): Promise<VitalGraphClient> {
  const client = new VitalGraphClient({
    serverUrl: 'http://localhost:8001',
    apiKey: 'vg_test_key',
  });
  await client.open();
  return client;
}

function paramsOf(url: string): URLSearchParams {
  return new URL(url).searchParams;
}

describe('sort and paging query params', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('kgentities.getFrames', () => {
    it('sends paging and sort params for an entity frame list', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgentities.getFrames('sp', 'urn:g', 'urn:e', {
        pageSize: 25,
        offset: 50,
        sortBy: FRAME_SEQUENCE,
        sortOrder: 'desc',
      });

      const p = paramsOf(cap.getUrl());
      expect(cap.getUrl()).toContain('/api/graphs/kgentities/kgframes');
      expect(p.get('entity_uri')).toBe('urn:e');
      expect(p.get('page_size')).toBe('25');
      expect(p.get('offset')).toBe('50');
      expect(p.get('sort_by')).toBe(FRAME_SEQUENCE);
      expect(p.get('sort_order')).toBe('desc');
    });

    it('forwards parent_frame_uri for the child-frame hierarchy', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgentities.getFrames('sp', 'urn:g', 'urn:e', {
        parentFrameUri: 'urn:frame:parent',
      });

      expect(paramsOf(cap.getUrl()).get('parent_frame_uri')).toBe('urn:frame:parent');
    });

    it('sends include_slot_counts when the caller asks for counts', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgentities.getFrames('sp', 'urn:g', 'urn:e', {
        includeSlotCounts: true,
      });

      expect(paramsOf(cap.getUrl()).get('include_slot_counts')).toBe('true');
    });

    it('omits include_slot_counts unless requested (it costs an extra query)', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgentities.getFrames('sp', 'urn:g', 'urn:e');

      expect(paramsOf(cap.getUrl()).has('include_slot_counts')).toBe(false);
    });

    it('omits sort params entirely when not requested', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgentities.getFrames('sp', 'urn:g', 'urn:e');

      const p = paramsOf(cap.getUrl());
      expect(p.has('sort_by')).toBe(false);
      expect(p.has('sort_order')).toBe(false);
    });
  });

  describe('kgframes.getEntityFrameSlots', () => {
    it('sends frame_uri, paging and slot sort params', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgframes.getEntityFrameSlots('sp', 'urn:g', 'urn:frame:1', {
        entityUri: 'urn:e',
        pageSize: 20,
        offset: 40,
        sortBy: SLOT_SEQUENCE,
        sortOrder: 'asc',
      });

      const p = paramsOf(cap.getUrl());
      expect(cap.getUrl()).toContain('/api/graphs/kgentities/kgframes/kgslots');
      expect(p.get('frame_uri')).toBe('urn:frame:1');
      expect(p.get('entity_uri')).toBe('urn:e');
      expect(p.get('page_size')).toBe('20');
      expect(p.get('offset')).toBe('40');
      expect(p.get('sort_by')).toBe(SLOT_SEQUENCE);
      expect(p.get('sort_order')).toBe('asc');
    });

    it('sends the slot type filter under the server param name', async () => {
      // The server declares this as kGSlotType; a mismatched name is silently
      // ignored, which is how the Python client's slot_type filter was dead.
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgframes.getEntityFrameSlots('sp', 'urn:g', 'urn:frame:1', {
        kgSlotType: 'urn:slot-type:text',
      });

      expect(paramsOf(cap.getUrl()).get('kGSlotType')).toBe('urn:slot-type:text');
    });

    it('requires a frame uri', async () => {
      captureRequestUrl();
      const client = await connectedClient();

      await expect(
        client.kgframes.getEntityFrameSlots('sp', 'urn:g', ''),
      ).rejects.toThrow();
    });
  });

  describe('kgframes.getSlots', () => {
    it('forwards paging to the mixed frames+slots endpoint', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgframes.getSlots('sp', 'urn:g', 'urn:frame:1', {
        pageSize: 50,
        offset: 100,
      });

      const p = paramsOf(cap.getUrl());
      expect(cap.getUrl()).toContain('/api/graphs/kgframes/kgslots');
      expect(p.get('page_size')).toBe('50');
      expect(p.get('offset')).toBe('100');
    });
  });

  describe('kgrelations.list', () => {
    it('sends list-index sort params', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgrelations.list('sp', 'urn:g', 25, 50, undefined, undefined, undefined, {
        sortBy: LIST_INDEX,
        sortOrder: 'desc',
      });

      const p = paramsOf(cap.getUrl());
      expect(cap.getUrl()).toContain('/api/graphs/kgrelations');
      expect(p.get('page_size')).toBe('25');
      expect(p.get('offset')).toBe('50');
      expect(p.get('sort_by')).toBe(LIST_INDEX);
      expect(p.get('sort_order')).toBe('desc');
    });

    it('forwards relation_type_uri and direction', async () => {
      // Both were previously accepted by callers but never reached the server.
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgrelations.list('sp', 'urn:g', 10, 0, undefined, undefined, undefined, {
        relationTypeUri: 'urn:reltype:knows',
        direction: 'incoming',
      });

      const p = paramsOf(cap.getUrl());
      expect(p.get('relation_type_uri')).toBe('urn:reltype:knows');
      expect(p.get('direction')).toBe('incoming');
    });

    it('still forwards the source/destination filters positionally', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgrelations.list(
        'sp', 'urn:g', 10, 0, undefined, 'urn:e:src', 'urn:e:dst',
      );

      const p = paramsOf(cap.getUrl());
      expect(p.get('entity_source_uri')).toBe('urn:e:src');
      expect(p.get('entity_destination_uri')).toBe('urn:e:dst');
    });

    it('omits sort params when no options object is passed', async () => {
      const cap = captureRequestUrl();
      const client = await connectedClient();

      await client.kgrelations.list('sp', 'urn:g');

      const p = paramsOf(cap.getUrl());
      expect(p.has('sort_by')).toBe(false);
      expect(p.has('relation_type_uri')).toBe(false);
    });
  });
});
