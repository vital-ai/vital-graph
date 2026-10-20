import { describe, it, expect, vi, afterEach } from 'vitest';
import { VitalGraphClient } from '../../src/VitalGraphClient.js';

/**
 * The KG document options server 0.0.48 reads: `document_type` and `vectorize`
 * on the upload form, `vectorize` as a query parameter on create and in the
 * segment body (vital-graph issues/284, issues/285).
 */
describe('kgdocuments vectorize and document type', () => {
  afterEach(() => vi.restoreAllMocks());

  async function capture() {
    const sent: { url: string; init?: RequestInit } = { url: '' };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (u, init) => {
      const s = typeof u === 'string' ? u : u.toString();
      if (!s.includes('/api/login')) {
        sent.url = s;
        sent.init = init;
      }
      return new Response(JSON.stringify({ success: true, status: 'created' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    const client = new VitalGraphClient({ serverUrl: 'http://localhost:8001', apiKey: 'vg_test_key' });
    await client.open();
    return { client, sent };
  }

  it('upload sends document_type and vectorize as form fields', async () => {
    const { client, sent } = await capture();
    await client.kgdocuments.upload('sp', 'urn:g', new Blob(['# T\n\ntext']), {
      filename: 'r.md', storeOriginal: true,
      documentType: 'urn:kgdoctype:research', vectorize: false,
    });
    expect(sent.url).toContain('/api/graphs/kgdocuments/upload');
    const form = sent.init?.body as FormData;
    expect(form.get('document_type')).toBe('urn:kgdoctype:research');
    expect(form.get('vectorize')).toBe('false');
    expect(form.get('store_original')).toBe('true');
  });

  it('upload omits both when not given', async () => {
    const { client, sent } = await capture();
    await client.kgdocuments.upload('sp', 'urn:g', new Blob(['x']), { filename: 'n.txt' });
    const form = sent.init?.body as FormData;
    expect(form.has('document_type')).toBe(false);
    expect(form.has('vectorize')).toBe(false);
  });

  it('create sends vectorize as a query parameter only when given', async () => {
    const { client, sent } = await capture();
    await client.kgdocuments.create('sp', 'urn:g', { quads: [] }, { vectorize: true });
    expect(new URL(sent.url).searchParams.get('vectorize')).toBe('true');
    await client.kgdocuments.create('sp', 'urn:g', { quads: [] });
    expect(new URL(sent.url).searchParams.has('vectorize')).toBe(false);
  });

  it('segment carries vectorize in its body', async () => {
    const { client, sent } = await capture();
    await client.kgdocuments.segment('sp', 'urn:g', { document_uri: 'urn:d', vectorize: false });
    expect(JSON.parse(String(sent.init?.body))).toEqual({ document_uri: 'urn:d', vectorize: false });
  });
});
