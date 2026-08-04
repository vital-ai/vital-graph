import { describe, it, expect } from 'vitest';
import {
  hydrateQuads,
  buildEntityGraphTree,
  countTreeNodes,
  humanizeUrn,
  getShortClassName,
  type FrameNode,
} from './entityGraphBuilder';
import type { Quad } from '../utils/QuadUtils';

/**
 * Unit tests for the pure entity-graph logic.
 *
 * Browser behavior is covered by the Playwright suite in `e2e/` (see
 * planning/planning_ui/ui_testing_plan.md). This file covers the non-React
 * logic that is awkward to assert through a browser — chiefly the ORDERING
 * rules — by driving the real pipeline: quads → hydrateQuads →
 * buildEntityGraphTree. Fixtures are quads rather than hand-built objects so
 * the model package's real type resolution is exercised (KGTextSlot must
 * actually resolve as a KGSlot, for instance).
 *
 * These are deliberately CHARACTERIZATION tests. The paging plan
 * (planning/planning_ui/entity_graph_frame_slot_paging_plan.md §5) removes the
 * three client-side sorts here, because a local re-sort of a single page would
 * scramble page boundaries. Pinning today's behavior first means that refactor
 * changes ordering *deliberately* rather than by accident, and these fixtures
 * carry over directly to asserting the server-ordered replacement.
 *
 * Every ordering fixture DECORRELATES sequence order from URI order and from
 * name order. If any two agreed, a dropped sort would still look correct — a
 * trap that hid two real bugs during the server-side work.
 */

const KG = 'http://vital.ai/ontology/haley-ai-kg#';
const VC = 'http://vital.ai/ontology/vital-core#';
const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const XSD_INT = 'http://www.w3.org/2001/XMLSchema#integer';

const q = (s: string, p: string, o: string): Quad => ({ s, p, o } as Quad);
const uri = (u: string) => `<${u}>`;
const int = (n: number) => `"${n}"^^<${XSD_INT}>`;
const str = (v: string) => `"${v}"`;

function entityQuads(u: string, name = 'Test Entity'): Quad[] {
  return [
    q(uri(u), uri(RDF_TYPE), uri(`${KG}KGEntity`)),
    q(uri(u), uri(`${VC}hasName`), str(name)),
  ];
}

function frameQuads(
  u: string, opts: { name?: string; sequence?: number } = {},
): Quad[] {
  const out = [
    q(uri(u), uri(RDF_TYPE), uri(`${KG}KGFrame`)),
    q(uri(u), uri(`${VC}hasName`), str(opts.name ?? u)),
  ];
  if (opts.sequence !== undefined) {
    out.push(q(uri(u), uri(`${KG}hasFrameSequence`), int(opts.sequence)));
  }
  return out;
}

function slotQuads(
  u: string, opts: { name?: string; sequence?: number; value?: string } = {},
): Quad[] {
  const out = [
    q(uri(u), uri(RDF_TYPE), uri(`${KG}KGTextSlot`)),
    q(uri(u), uri(`${VC}hasName`), str(opts.name ?? u)),
    q(uri(u), uri(`${KG}hasTextSlotValue`), str(opts.value ?? 'v')),
  ];
  if (opts.sequence !== undefined) {
    out.push(q(uri(u), uri(`${KG}hasSlotSequence`), int(opts.sequence)));
  }
  return out;
}

function edgeQuads(u: string, type: string, from: string, to: string): Quad[] {
  return [
    q(uri(u), uri(RDF_TYPE), uri(type)),
    q(uri(u), uri(`${VC}hasEdgeSource`), uri(from)),
    q(uri(u), uri(`${VC}hasEdgeDestination`), uri(to)),
  ];
}

const entityFrameEdge = (u: string, from: string, to: string) =>
  edgeQuads(u, `${KG}Edge_hasEntityKGFrame`, from, to);
const slotEdge = (u: string, from: string, to: string) =>
  edgeQuads(u, `${KG}Edge_hasKGSlot`, from, to);

const buildFrom = (quads: Quad[]) => buildEntityGraphTree(hydrateQuads(quads));

/* eslint-disable @typescript-eslint/no-explicit-any */
const short = (u: unknown) => String(u).split(':').pop();
const frameNames = (nodes: FrameNode[]) => nodes.map(n => short((n.frame as any).URI));
const slotNames = (node: FrameNode) => node.slots.map(s => short((s.slot as any).URI));

/** Entity with N top-level frames, each described by opts. */
function entityWithFrames(
  frames: { uri: string; name?: string; sequence?: number }[],
): Quad[] {
  const quads: Quad[] = [...entityQuads('urn:e')];
  frames.forEach((f, i) => {
    quads.push(...frameQuads(f.uri, { name: f.name, sequence: f.sequence }));
    quads.push(...entityFrameEdge(`urn:ef${i}`, 'urn:e', f.uri));
  });
  return quads;
}

/** One frame carrying the given slots. */
function frameWithSlots(
  slots: { uri: string; name?: string; sequence?: number }[],
): Quad[] {
  const quads: Quad[] = [
    ...entityQuads('urn:e'),
    ...frameQuads('urn:f1', { sequence: 0 }),
    ...entityFrameEdge('urn:ef0', 'urn:e', 'urn:f1'),
  ];
  slots.forEach((s, i) => {
    quads.push(...slotQuads(s.uri, { name: s.name, sequence: s.sequence }));
    quads.push(...slotEdge(`urn:se${i}`, 'urn:f1', s.uri));
  });
  return quads;
}

describe('buildEntityGraphTree — top-level frame ordering', () => {
  it('orders frames by frameSequence, not by URI or name', () => {
    // URI order f1,f2,f3 ; sequence 3,1,2 ; names C,A,B — all three differ.
    const tree = buildFrom(entityWithFrames([
      { uri: 'urn:f1', sequence: 3, name: 'C' },
      { uri: 'urn:f2', sequence: 1, name: 'A' },
      { uri: 'urn:f3', sequence: 2, name: 'B' },
    ]))!;
    expect(frameNames(tree.frames)).toEqual(['f2', 'f3', 'f1']);
  });

  it('sorts sequences numerically across the 10 boundary', () => {
    // A lexical sort would give 1,10,11,2 — the exact bug found server-side.
    const tree = buildFrom(entityWithFrames([
      { uri: 'urn:f11', sequence: 11 },
      { uri: 'urn:f2', sequence: 2 },
      { uri: 'urn:f10', sequence: 10 },
      { uri: 'urn:f1', sequence: 1 },
    ]))!;
    expect(frameNames(tree.frames)).toEqual(['f1', 'f2', 'f10', 'f11']);
  });

  it('places frames without a sequence last, ordered by name', () => {
    const tree = buildFrom(entityWithFrames([
      { uri: 'urn:f1', name: 'Zulu' },
      { uri: 'urn:f2', sequence: 5, name: 'Q' },
      { uri: 'urn:f3', name: 'Alpha' },
    ]))!;
    expect(frameNames(tree.frames)).toEqual(['f2', 'f3', 'f1']);
  });

  it('treats sequence 0 as a real value, not as missing', () => {
    // Singletons are commonly written with sequence 0; a falsy check would
    // push them to the end.
    const tree = buildFrom(entityWithFrames([
      { uri: 'urn:f1', sequence: 7 },
      { uri: 'urn:f2', sequence: 0 },
    ]))!;
    expect(frameNames(tree.frames)).toEqual(['f2', 'f1']);
  });

  it('breaks ties on name when sequences are equal', () => {
    const tree = buildFrom(entityWithFrames([
      { uri: 'urn:f1', sequence: 1, name: 'Bravo' },
      { uri: 'urn:f2', sequence: 1, name: 'Alpha' },
    ]))!;
    expect(frameNames(tree.frames)).toEqual(['f2', 'f1']);
  });
});

describe('buildEntityGraphTree — slot ordering within a frame', () => {
  it('orders slots by slotSequence, not by URI or name', () => {
    const tree = buildFrom(frameWithSlots([
      { uri: 'urn:s1', sequence: 3, name: 'C' },
      { uri: 'urn:s2', sequence: 1, name: 'A' },
      { uri: 'urn:s3', sequence: 2, name: 'B' },
    ]))!;
    expect(slotNames(tree.frames[0])).toEqual(['s2', 's3', 's1']);
  });

  it('sorts slot sequences numerically across the 10 boundary', () => {
    const tree = buildFrom(frameWithSlots([
      { uri: 'urn:s11', sequence: 11 },
      { uri: 'urn:s2', sequence: 2 },
      { uri: 'urn:s10', sequence: 10 },
    ]))!;
    expect(slotNames(tree.frames[0])).toEqual(['s2', 's10', 's11']);
  });

  it('places slots without a sequence last, ordered by name', () => {
    const tree = buildFrom(frameWithSlots([
      { uri: 'urn:s1', name: 'Zulu' },
      { uri: 'urn:s2', sequence: 4, name: 'Q' },
      { uri: 'urn:s3', name: 'Alpha' },
    ]))!;
    expect(slotNames(tree.frames[0])).toEqual(['s2', 's3', 's1']);
  });

  it('treats slot sequence 0 as a real value', () => {
    const tree = buildFrom(frameWithSlots([
      { uri: 'urn:s1', sequence: 9 },
      { uri: 'urn:s2', sequence: 0 },
    ]))!;
    expect(slotNames(tree.frames[0])).toEqual(['s2', 's1']);
  });

  it('resolves a KGTextSlot as a slot of the frame', () => {
    // Guards are subtype-aware only after hydration — this is why the fixtures
    // go through hydrateQuads rather than using hand-built objects.
    const tree = buildFrom(frameWithSlots([{ uri: 'urn:s1', sequence: 0 }]))!;
    expect(tree.frames[0].slots).toHaveLength(1);
    expect(tree.totalSlotCount).toBe(1);
  });
});

describe('buildEntityGraphTree — tree shape and counts', () => {
  it('returns null when no KGEntity is present', () => {
    expect(buildFrom(frameQuads('urn:f1'))).toBeNull();
  });

  it('counts every frame and slot', () => {
    const tree = buildFrom(frameWithSlots([
      { uri: 'urn:s1', sequence: 0 },
      { uri: 'urn:s2', sequence: 1 },
    ]))!;
    expect(tree.totalFrameCount).toBe(1);
    expect(tree.totalSlotCount).toBe(2);
    expect(countTreeNodes(tree.frames)).toEqual({ frames: 1, slots: 2 });
  });

  it('ignores slot edges pointing at a missing slot object', () => {
    const quads: Quad[] = [
      ...entityQuads('urn:e'),
      ...frameQuads('urn:f1', { sequence: 0 }),
      ...entityFrameEdge('urn:ef0', 'urn:e', 'urn:f1'),
      ...slotEdge('urn:se0', 'urn:f1', 'urn:missing'),
    ];
    const tree = buildFrom(quads)!;
    expect(tree.frames[0].slots).toEqual([]);
    expect(tree.totalSlotCount).toBe(0);
  });

  it('excludes frames not linked to the entity', () => {
    const quads: Quad[] = [
      ...entityWithFrames([{ uri: 'urn:f1', sequence: 0 }]),
      ...frameQuads('urn:orphan', { sequence: 0 }),
    ];
    const tree = buildFrom(quads)!;
    expect(frameNames(tree.frames)).toEqual(['f1']);
  });

  it('handles an entity with no frames at all', () => {
    const tree = buildFrom(entityQuads('urn:e'))!;
    expect(tree.frames).toEqual([]);
    expect(tree.totalFrameCount).toBe(0);
    expect(tree.totalSlotCount).toBe(0);
  });
});

describe('countTreeNodes', () => {
  it('returns zeros for an empty list', () => {
    expect(countTreeNodes([])).toEqual({ frames: 0, slots: 0 });
  });

  it('walks nested child frames', () => {
    const leaf = { frame: {}, slots: [{}, {}], childFrames: [] } as unknown as FrameNode;
    const mid = { frame: {}, slots: [{}], childFrames: [leaf] } as unknown as FrameNode;
    expect(countTreeNodes([mid])).toEqual({ frames: 2, slots: 3 });
  });
});

describe('humanizeUrn', () => {
  it('splits CamelCase after a urn: prefix', () => {
    expect(humanizeUrn('urn:EmploymentFrameType')).toBe('Employment Frame Type');
  });

  it('uses the fragment of a hash URI', () => {
    expect(humanizeUrn(`${KG}EmploymentFrameType`)).toBe('Employment Frame Type');
  });

  it('uses the last path segment when there is no fragment', () => {
    expect(humanizeUrn('http://example.org/types/SomeThing')).toBe('Some Thing');
  });

  it('converts underscores and hyphens to spaces', () => {
    expect(humanizeUrn('urn:some_frame-type')).toBe('Some Frame Type');
  });
});

describe('getShortClassName', () => {
  it('returns an empty string for undefined', () => {
    expect(getShortClassName(undefined)).toBe('');
  });

  it('shortens a full class URI', () => {
    expect(getShortClassName(`${KG}KGFrame`)).toContain('KGFrame');
  });
});
