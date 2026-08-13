import { describe, it, expect } from 'vitest';

/**
 * The frame-details view selects its object by URI, never by position.
 *
 * `getFrame` with `include_frame_graph` returns a SUBGRAPH — the frame plus its
 * slot edges and slots — because the Slot Summary needs it. The detail header
 * consumes the same payload and must still describe the frame. It once took the
 * first subject and let the last rdf:type win, which showed a KGFrame as
 * "Edge / Edge_hasKGSlot" with 32 properties.
 *
 * These mirror the selection logic in AbsObjectDetail.convertQuadsToObject so
 * the property can be asserted without mounting the page: the SAME object is
 * chosen whatever order the server returns.
 */

type Quad = { s: string; p: string; o: string; g?: string };

const strip = (v: string) => v.replace(/^<|>$/g, '');

function selectOwnQuads(quads: Quad[], objectId: string | null): Quad[] {
  const wanted = objectId ? strip(objectId) : null;
  const own = wanted ? quads.filter(q => strip(q.s) === wanted) : [];
  if (own.length > 0) return own;
  const fallback = strip(quads[0].s);
  return quads.filter(q => strip(q.s) === fallback);
}

const FRAME = 'http://vital.ai/haley.ai/app/KGFrame/1716488391362_692038076';
const SLOT = 'urn:slot:a';
const EDGE = 'urn:edge:a';
const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';

const frameQuads: Quad[] = [
  { s: `<${FRAME}>`, p: `<${RDF_TYPE}>`, o: '<http://vital.ai/ontology/haley-ai-kg#KGFrame>' },
  { s: `<${FRAME}>`, p: '<urn:hasKGFrameType>', o: '<urn:Edge_WordnetHypernym>' },
];
const slotQuads: Quad[] = [
  { s: `<${SLOT}>`, p: `<${RDF_TYPE}>`, o: '<http://vital.ai/ontology/haley-ai-kg#KGEntitySlot>' },
];
const edgeQuads: Quad[] = [
  { s: `<${EDGE}>`, p: `<${RDF_TYPE}>`, o: '<http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot>' },
];

describe('detail-view object selection', () => {
  it('picks the frame when it comes first', () => {
    const out = selectOwnQuads([...frameQuads, ...slotQuads, ...edgeQuads], FRAME);
    expect(out).toHaveLength(2);
    expect(out.every(q => strip(q.s) === FRAME)).toBe(true);
  });

  it('picks the frame when it comes LAST', () => {
    const out = selectOwnQuads([...edgeQuads, ...slotQuads, ...frameQuads], FRAME);
    expect(out).toHaveLength(2);
    expect(out.every(q => strip(q.s) === FRAME)).toBe(true);
  });

  it('gives the same answer for every ordering', () => {
    const orders: Quad[][] = [
      [...frameQuads, ...slotQuads, ...edgeQuads],
      [...slotQuads, ...frameQuads, ...edgeQuads],
      [...edgeQuads, ...frameQuads, ...slotQuads],
      [...slotQuads, ...edgeQuads, ...frameQuads],
    ];
    const answers = orders.map(o => JSON.stringify(selectOwnQuads(o, FRAME)));
    expect(new Set(answers).size).toBe(1);
  });

  it('never merges subjects, so rdf:type cannot come from another object', () => {
    const out = selectOwnQuads([...frameQuads, ...edgeQuads], FRAME);
    const types = out.filter(q => strip(q.p) === RDF_TYPE).map(q => strip(q.o));
    expect(types).toEqual(['http://vital.ai/ontology/haley-ai-kg#KGFrame']);
  });

  it('falls back to ONE subject when the requested URI is absent', () => {
    // An encoding mismatch must not reinstate the merge.
    const out = selectOwnQuads([...frameQuads, ...edgeQuads], 'urn:not:here');
    const subjects = new Set(out.map(q => strip(q.s)));
    expect(subjects.size).toBe(1);
  });
});
