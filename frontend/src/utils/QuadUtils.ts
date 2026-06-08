/**
 * QuadUtils — Centralized utilities for parsing, building, and grouping
 * N-Quads/N-Triples term values used throughout the frontend.
 *
 * Backend wire format:
 *   { s: "<uri>", p: "<uri>", o: "<uri>" | "\"literal\"" | "\"lit\"^^<type>", g?: "<uri>" }
 */

// ─── Types ──────────────────────────────────────────────────────────────────

/** A single quad as returned by the backend API */
export interface Quad {
  s: string;
  p: string;
  o: string;
  g?: string;
}

/** A quad ready to send to the backend (create/update/delete) */
export interface QuadRequest {
  s: string;
  p: string;
  o: string;
  o_type?: 'uri' | 'literal';
  g?: string;
}

/** Standard paginated quad response from the backend */
export interface QuadResponse {
  results: Quad[];
  total_count: number;
  page_size?: number;
  offset?: number;
}

/** A parsed property (predicate + object with type) */
export interface ParsedProperty {
  predicate: string;
  object: string;
  object_type: 'uri' | 'literal';
}

/** An entity grouped by subject URI with all its properties */
export interface GroupedEntity {
  uri: string;
  rdf_type: string;
  name: string;
  properties: Map<string, string[]>;
  properties_count: number;
}

// ─── Constants ──────────────────────────────────────────────────────────────

export const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
export const HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName';

// ─── Term Parsing ───────────────────────────────────────────────────────────

/** Strip angle brackets from a URI term: `<http://ex.org/a>` → `http://ex.org/a` */
export const stripBrackets = (v: string): string => v.replace(/^<|>$/g, '');

/** Strip quotes and optional lang-tag / datatype from a literal term:
 *  `"hello"` → `hello`
 *  `"42"^^<http://www.w3.org/2001/XMLSchema#integer>` → `42`
 *  `"bonjour"@fr` → `bonjour`
 */
export const stripLiteral = (v: string): string =>
  v.replace(/^"/, '').replace(/"(@[a-z-]+|\^\^<[^>]+>)?$/, '');

/** Test whether a raw term value is a URI (wrapped in angle brackets) */
export const isUriTerm = (v: string): boolean => v.startsWith('<') && v.endsWith('>');

/** Parse a raw object term into its value and type */
export const parseObjectTerm = (raw: string): { value: string; type: 'uri' | 'literal' } => {
  if (isUriTerm(raw)) {
    return { value: stripBrackets(raw), type: 'uri' };
  }
  return { value: stripLiteral(raw), type: 'literal' };
};

/** Shorten a full URI to its local name (after last `/` or `#`) */
export const shortenUri = (uri: string): string => uri.split(/[/#]/).pop() || uri;

/** Extract a human-readable graph name from a graph URI or encoded ID */
export const extractGraphName = (graphUri: string): string => {
  if (!graphUri) return 'Unknown Graph';
  const decoded = decodeURIComponent(graphUri);
  if (/^\d+$/.test(decoded)) return `Graph ${decoded}`;
  const name = decoded.split(/[/#]/).pop();
  if (!name) return decoded.includes('global') ? 'Global' : 'Graph';
  return name.replace(/[-_]/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

// ─── Quad Building (for API requests) ───────────────────────────────────────

/** Wrap a bare URI in angle brackets for the wire format */
export const wrapUri = (uri: string): string =>
  uri.startsWith('<') ? uri : `<${uri}>`;

/** Wrap a bare literal in quotes for the wire format */
export const wrapLiteral = (value: string): string =>
  value.startsWith('"') ? value : `"${value}"`;

/** Build a single quad object for API submission */
export const buildQuad = (
  subject: string,
  predicate: string,
  object: string,
  objectType: 'uri' | 'literal',
  graph?: string
): QuadRequest => ({
  s: wrapUri(subject),
  p: wrapUri(predicate),
  o: objectType === 'uri' ? wrapUri(object) : wrapLiteral(object),
  ...(graph ? { g: wrapUri(graph) } : {}),
});

/** Build a quads request payload from an array of properties */
export const buildQuadsPayload = (
  subjectUri: string,
  properties: Array<{ predicate: string; object: string; object_type: 'uri' | 'literal' }>,
  graph?: string
): { quads: QuadRequest[] } => ({
  quads: properties
    .filter(p => p.predicate && p.object)
    .map(p => buildQuad(subjectUri, p.predicate, p.object, p.object_type, graph)),
});

/** Build a wildcard delete payload (delete all triples for a subject) */
export const buildDeleteAllPayload = (
  subjectUri: string,
  graph: string
): { quads: Array<{ s: string; p: string; o: string; g: string }> } => ({
  quads: [{ s: wrapUri(subjectUri), p: '*', o: '*', g: wrapUri(graph) }],
});

// ─── Quad Grouping (parse response into structured entities) ────────────────

/** Group an array of quads by subject URI into a Map of predicate→values */
export const groupQuadsBySubject = (
  quads: Quad[]
): Map<string, Map<string, string[]>> => {
  const subjectMap = new Map<string, Map<string, string[]>>();
  for (const quad of quads) {
    const subj = stripBrackets(quad.s);
    if (!subjectMap.has(subj)) subjectMap.set(subj, new Map());
    const preds = subjectMap.get(subj)!;
    const pred = stripBrackets(quad.p);
    if (!preds.has(pred)) preds.set(pred, []);
    preds.get(pred)!.push(quad.o);
  }
  return subjectMap;
};

/** Convert grouped quads into a list of GroupedEntity objects */
export const parseEntitiesFromQuads = (
  quads: Quad[]
): GroupedEntity[] => {
  const subjectMap = groupQuadsBySubject(quads);
  const entities: GroupedEntity[] = [];

  for (const [uri, preds] of subjectMap) {
    const typeVals = preds.get(RDF_TYPE) || [];
    const rdf_type = typeVals.length > 0 ? stripBrackets(typeVals[0]) : 'Unknown';

    const nameVals = preds.get(HAS_NAME) || [];
    const name = nameVals.length > 0 ? stripLiteral(nameVals[0]) : shortenUri(uri);

    entities.push({ uri, rdf_type, name, properties: preds, properties_count: preds.size });
  }

  return entities;
};

/** Convert an array of quads (all same subject) into parsed properties */
export const quadsToProperties = (quads: Quad[]): ParsedProperty[] =>
  quads.map(q => {
    const { value, type } = parseObjectTerm(q.o);
    return {
      predicate: stripBrackets(q.p),
      object: value,
      object_type: type,
    };
  });

/** Get the first value for a predicate from a predicate→values map, stripped */
export const getFirstValue = (
  preds: Map<string, string[]>,
  predicate: string,
  fallback = ''
): string => {
  const vals = preds.get(predicate);
  if (!vals || vals.length === 0) return fallback;
  const raw = vals[0];
  return isUriTerm(raw) ? stripBrackets(raw) : stripLiteral(raw);
};
