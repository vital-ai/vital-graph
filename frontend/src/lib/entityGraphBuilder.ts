/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * Entity Graph Builder
 *
 * Converts backend quads into typed VitalSigns graph objects using
 * @vital-ai/vital-kg-model-ts, then walks edges to produce a tree
 * structure suitable for UI rendering.
 *
 * Pipeline:
 *   quads  →  JSON-per-subject  →  convertGraphObjects()  →  EntityGraphTree
 */

import {
  convertGraphObjects,
  isKGEntity,
  isKGFrame,
  isKGSlot,
  isEdgeHasEntityKGFrame,
  isEdgeHasKGSlot,
  lookup_child_frames,
  type GraphObject,
} from '@vital-ai/vital-kg-model-ts';

import type { KGEntity } from '@vital-ai/vital-kg-model-ts';
import type { KGFrame } from '@vital-ai/vital-kg-model-ts';
import type { KGSlot } from '@vital-ai/vital-kg-model-ts';
import type { Edge_hasKGSlot } from '@vital-ai/vital-kg-model-ts';

import {
  type Quad,
  groupQuadsBySubject,
  stripBrackets,
  stripLiteral,
  isUriTerm,
  shortenUri,
  RDF_TYPE,
} from '../utils/QuadUtils';

// ─── Public types ───────────────────────────────────────────────────────────

/** A single frame node in the entity graph tree */
export interface FrameNode {
  frame: KGFrame;
  slots: SlotEntry[];
  childFrames: FrameNode[];
}

/** A slot with its extracted display value */
export interface SlotEntry {
  slot: KGSlot;
  edge: Edge_hasKGSlot | null;
  displayValue: unknown;
  dataType: string;
}

/** The complete entity graph tree */
export interface EntityGraphTree {
  entity: KGEntity;
  graphObjects: GraphObject[];
  frames: FrameNode[];
  totalFrameCount: number;
  totalSlotCount: number;
}

// ─── Quad → JSON-per-subject conversion ─────────────────────────────────────

/**
 * Convert backend quads ({s,p,o,g}) into JSON objects suitable for
 * convertGraphObjects().
 *
 * Each subject becomes one JSON dict with:
 *   - URI: the subject URI
 *   - type: the rdf:type value (vitaltype URI)
 *   - full-URI-keyed properties
 */
export function quadsToJsonObjects(quads: Quad[]): Record<string, unknown>[] {
  const subjectMap = groupQuadsBySubject(quads);
  const jsonObjects: Record<string, unknown>[] = [];

  for (const [uri, preds] of subjectMap) {
    const obj: Record<string, unknown> = { URI: uri };

    // Extract rdf:type → 'type' key (what convertGraphObjects expects)
    const typeVals = preds.get(RDF_TYPE);
    if (typeVals && typeVals.length > 0) {
      const typeUri = isUriTerm(typeVals[0]) ? stripBrackets(typeVals[0]) : typeVals[0];
      obj['type'] = typeUri;
    }

    // Map every predicate → full URI key with parsed value
    for (const [predUri, values] of preds) {
      if (predUri === RDF_TYPE) continue; // already handled

      if (values.length === 1) {
        obj[predUri] = parseQuadValue(values[0]);
      } else if (values.length > 1) {
        // Multi-valued: keep as array (rare, but some properties allow it)
        obj[predUri] = values.map(parseQuadValue);
      }
    }

    jsonObjects.push(obj);
  }

  return jsonObjects;
}

/**
 * Parse a single quad object value: strip brackets from URIs,
 * strip quotes+datatype from literals.
 */
function parseQuadValue(raw: string): unknown {
  if (isUriTerm(raw)) {
    return stripBrackets(raw);
  }
  const stripped = stripLiteral(raw);

  // Detect typed literals for numeric/boolean coercion
  if (raw.includes('^^<http://www.w3.org/2001/XMLSchema#integer>') ||
      raw.includes('^^<http://www.w3.org/2001/XMLSchema#int>') ||
      raw.includes('^^<http://www.w3.org/2001/XMLSchema#long>')) {
    const n = parseInt(stripped, 10);
    return isNaN(n) ? stripped : n;
  }
  if (raw.includes('^^<http://www.w3.org/2001/XMLSchema#double>') ||
      raw.includes('^^<http://www.w3.org/2001/XMLSchema#float>') ||
      raw.includes('^^<http://www.w3.org/2001/XMLSchema#decimal>')) {
    const n = parseFloat(stripped);
    return isNaN(n) ? stripped : n;
  }
  if (raw.includes('^^<http://www.w3.org/2001/XMLSchema#boolean>')) {
    return stripped === 'true';
  }

  return stripped;
}

// ─── Graph object conversion ────────────────────────────────────────────────

/**
 * Convert quads to typed VitalSigns graph objects.
 *
 * This is the main entry point for the quad-to-object pipeline:
 *   quads → JSON dicts → convertGraphObjects() → GraphObject[]
 */
export function hydrateQuads(quads: Quad[]): GraphObject[] {
  const jsonObjects = quadsToJsonObjects(quads);
  return convertGraphObjects(jsonObjects as Record<string, any>[]);
}

// ─── Tree builder ───────────────────────────────────────────────────────────

/**
 * Build an EntityGraphTree from a flat list of typed graph objects.
 *
 * Walks Edge_hasEntityKGFrame, Edge_hasKGFrame, and Edge_hasKGSlot
 * to reconstruct the entity → frame → slot hierarchy.
 */
export function buildEntityGraphTree(graphObjects: GraphObject[]): EntityGraphTree | null {
  // Find entity
  const entity = graphObjects.find(isKGEntity) as KGEntity | undefined;
  if (!entity || !entity.URI) return null;

  // Index slot edges by source frame URI for quick lookup
  const slotEdgesByFrame = new Map<string, Edge_hasKGSlot[]>();
  for (const obj of graphObjects) {
    if (isEdgeHasKGSlot(obj) && obj.edgeSource) {
      const existing = slotEdgesByFrame.get(obj.edgeSource) || [];
      existing.push(obj as Edge_hasKGSlot);
      slotEdgesByFrame.set(obj.edgeSource, existing);
    }
  }

  // Index all slots by URI
  const slotsByUri = new Map<string, KGSlot>();
  for (const obj of graphObjects) {
    if (isKGSlot(obj) && obj.URI) {
      slotsByUri.set(obj.URI, obj as KGSlot);
    }
  }

  // Counters
  let totalFrameCount = 0;
  let totalSlotCount = 0;

  // Recursive frame builder
  function buildFrame(frame: KGFrame): FrameNode {
    totalFrameCount++;
    const frameUri = frame.URI!;

    // Find slots for this frame
    const slotEdges = slotEdgesByFrame.get(frameUri) || [];
    const slots: SlotEntry[] = [];
    for (const edge of slotEdges) {
      if (!edge.edgeDestination) continue;
      const slot = slotsByUri.get(edge.edgeDestination);
      if (slot) {
        totalSlotCount++;
        const { value, dataType } = getSlotDisplayValue(slot);
        slots.push({
          slot,
          edge,
          displayValue: value,
          dataType,
        });
      }
    }

    // Sort slots by slotSequence then name
    slots.sort((a, b) => {
      const seqA = (a.slot as any).slotSequence ?? Infinity;
      const seqB = (b.slot as any).slotSequence ?? Infinity;
      if (seqA !== seqB) return seqA - seqB;
      const nameA = (a.slot as any).name ?? '';
      const nameB = (b.slot as any).name ?? '';
      return nameA.localeCompare(nameB);
    });

    // Find child frames
    const childFrameObjects = lookup_child_frames(graphObjects, frame);

    // Sort child frames by frameSequence then name
    childFrameObjects.sort((a, b) => {
      const seqA = a.frameSequence ?? Infinity;
      const seqB = b.frameSequence ?? Infinity;
      if (seqA !== seqB) return seqA - seqB;
      const nameA = (a as any).name ?? '';
      const nameB = (b as any).name ?? '';
      return nameA.localeCompare(nameB);
    });

    const childFrames = childFrameObjects.map(buildFrame);

    return { frame, slots, childFrames };
  }

  // Find top-level frames (entity → frame via Edge_hasEntityKGFrame)
  const topFrameUris = new Set<string>();
  for (const obj of graphObjects) {
    if (isEdgeHasEntityKGFrame(obj) && obj.edgeSource === entity.URI && obj.edgeDestination) {
      topFrameUris.add(obj.edgeDestination);
    }
  }

  const topFrames: KGFrame[] = [];
  for (const obj of graphObjects) {
    if (isKGFrame(obj) && obj.URI && topFrameUris.has(obj.URI)) {
      topFrames.push(obj as KGFrame);
    }
  }

  // Sort top-level frames by frameSequence then name
  topFrames.sort((a, b) => {
    const seqA = a.frameSequence ?? Infinity;
    const seqB = b.frameSequence ?? Infinity;
    if (seqA !== seqB) return seqA - seqB;
    const nameA = (a as any).name ?? '';
    const nameB = (b as any).name ?? '';
    return nameA.localeCompare(nameB);
  });

  const frames = topFrames.map(buildFrame);

  return {
    entity,
    graphObjects,
    frames,
    totalFrameCount,
    totalSlotCount,
  };
}

// ─── Slot value extraction ──────────────────────────────────────────────────

/**
 * Extract the display value and data type from a slot object.
 *
 * Uses instanceof-style checks via vitaltype string matching against known
 * slot subtypes. Falls back to property introspection via
 * getAllPropertyDefinitions() for unknown slot types.
 */
export function getSlotDisplayValue(slot: KGSlot): { value: unknown; dataType: string } {
  const s = slot as any;
  const vt = slot.vitaltype ?? '';

  // Check known slot types by vitaltype suffix
  if (vt.includes('KGTextSlot') && !vt.includes('KGLongTextSlot')) {
    return { value: s.textSlotValue, dataType: 'text' };
  }
  if (vt.includes('KGLongTextSlot')) {
    return { value: s.longTextSlotValue, dataType: 'longtext' };
  }
  if (vt.includes('KGIntegerSlot')) {
    return { value: s.integerSlotValue, dataType: 'integer' };
  }
  if (vt.includes('KGLongSlot') && !vt.includes('KGLongTextSlot')) {
    return { value: s.longSlotValue, dataType: 'long' };
  }
  if (vt.includes('KGDoubleSlot')) {
    return { value: s.doubleSlotValue, dataType: 'double' };
  }
  if (vt.includes('KGCurrencySlot')) {
    return { value: s.currencySlotValue, dataType: 'currency' };
  }
  if (vt.includes('KGBooleanSlot')) {
    return { value: s.booleanSlotValue, dataType: 'boolean' };
  }
  if (vt.includes('KGDateTimeSlot')) {
    return { value: s.dateTimeSlotValue, dataType: 'datetime' };
  }
  if (vt.includes('KGChoiceSlot') && !vt.includes('KGMultiChoiceSlot')) {
    return { value: s.choiceSlotValue, dataType: 'choice' };
  }
  if (vt.includes('KGMultiChoiceSlot')) {
    return { value: s.multiChoiceSlotValue ?? s.multiChoiceSlotValues, dataType: 'multichoice' };
  }
  if (vt.includes('KGEntitySlot')) {
    return { value: s.entitySlotValue, dataType: 'uri' };
  }
  if (vt.includes('KGURISlot')) {
    return { value: s.uriSlotValue, dataType: 'uri' };
  }
  if (vt.includes('KGJSONSlot')) {
    return { value: s.jsonSlotValue, dataType: 'json' };
  }
  if (vt.includes('KGImageSlot')) {
    return { value: s.imageSlotValue, dataType: 'image' };
  }
  if (vt.includes('KGVideoSlot')) {
    return { value: s.videoSlotValue, dataType: 'video' };
  }
  if (vt.includes('KGAudioSlot')) {
    return { value: s.audioSlotValue, dataType: 'audio' };
  }
  if (vt.includes('KGCodeSlot')) {
    return { value: s.codeSlotValue, dataType: 'code' };
  }
  if (vt.includes('KGFileUploadSlot')) {
    return { value: s.fileUploadSlotValue, dataType: 'file' };
  }
  if (vt.includes('KGGeoLocationSlot')) {
    return { value: s.geoLocationSlotValue, dataType: 'geolocation' };
  }
  if (vt.includes('KGPropertySlot')) {
    return { value: s.propertySlotValue, dataType: 'property' };
  }
  if (vt.includes('KGTaxonomySlot') && !vt.includes('KGMultiTaxonomySlot')) {
    return { value: s.taxonomySlotValue, dataType: 'taxonomy' };
  }
  if (vt.includes('KGMultiTaxonomySlot')) {
    return { value: s.multiTaxonomySlotValue ?? s.multiTaxonomySlotValues, dataType: 'multitaxonomy' };
  }
  if (vt.includes('KGRunSlot')) {
    return { value: s.runSlotValue, dataType: 'run' };
  }

  // Fallback: introspect property definitions for any *SlotValue property
  if (typeof slot.getAllPropertyDefinitions === 'function') {
    for (const propDef of slot.getAllPropertyDefinitions()) {
      const propName = propDef.tsPropertyName;
      if (propName && (propName.endsWith('SlotValue') || propName.endsWith('SlotValues'))) {
        const val = s[propName];
        if (val !== undefined) {
          return { value: val, dataType: propDef.type || 'unknown' };
        }
      }
    }
  }

  return { value: undefined, dataType: 'unknown' };
}

// ─── Display helpers ────────────────────────────────────────────────────────

/** Get a human-readable label for a frame */
export function getFrameLabel(frame: KGFrame): string {
  const name = (frame as any).name;
  if (name) return name;
  if (frame.kGFrameType) return humanizeUrn(frame.kGFrameType);
  return 'Frame';
}

/** Get a human-readable label for a slot */
export function getSlotLabel(slot: KGSlot): string {
  const name = (slot as any).name;
  if (name) return name;
  if (slot.kGSlotType) return humanizeUrn(slot.kGSlotType);
  return 'Slot';
}

/** Get a human-readable label for the entity */
export function getEntityLabel(entity: KGEntity): string {
  const name = (entity as any).name;
  if (name) return name;
  if (entity.URI) return shortenUri(entity.URI);
  return 'Entity';
}

/** Get the short class name from a vitaltype URI */
export function getShortClassName(vitaltype: string | undefined): string {
  if (!vitaltype) return '';
  return shortenUri(vitaltype);
}

/**
 * Humanize a URN like "urn:EmploymentFrameType" → "Employment Frame Type"
 * or a URI like "http://vital.ai/...#EmploymentFrameType" → "Employment Frame Type"
 */
export function humanizeUrn(urn: string): string {
  // Get the last segment
  const segment = urn.includes('#') ? urn.split('#').pop()!
                 : urn.includes('/') ? urn.split('/').pop()!
                 : urn.startsWith('urn:') ? urn.slice(4)
                 : urn;

  // Split CamelCase and underscores
  return segment
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, l => l.toUpperCase());
}

/**
 * Count frames and slots recursively in a FrameNode tree.
 */
export function countTreeNodes(frames: FrameNode[]): { frames: number; slots: number } {
  let frameCount = 0;
  let slotCount = 0;

  function walk(node: FrameNode) {
    frameCount++;
    slotCount += node.slots.length;
    for (const child of node.childFrames) {
      walk(child);
    }
  }

  for (const f of frames) walk(f);
  return { frames: frameCount, slots: slotCount };
}
