import { useState, useCallback, useRef, useMemo, useEffect } from 'react';
import ApiService from '../services/ApiService';
import type { DataGraph, ViewGraph, SearchResult } from './graphTypes';
import { createEmptyDataGraph } from './graphTypes';
import { buildViewGraph } from './buildViewGraph';

export type { SearchResult };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const VITAL_NAME = 'http://vital.ai/ontology/vital-core#hasName';
const VITAL_EDGE_SRC = 'http://vital.ai/ontology/vital-core#hasEdgeSource';
const VITAL_EDGE_DST = 'http://vital.ai/ontology/vital-core#hasEdgeDestination';
const HALEY_KG_ENTITY = 'http://vital.ai/ontology/haley-ai-kg#KGEntity';
const HALEY_KG_FRAME = 'http://vital.ai/ontology/haley-ai-kg#KGFrame';
const HALEY_FRAME_TYPE_DESC = 'http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription';
const HALEY_KG_DESC = 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription';
const HALEY_SLOT_TYPE = 'http://vital.ai/ontology/haley-ai-kg#hasKGSlotType';
const HALEY_SLOT_VALUE = 'http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue';
const HALEY_ENTITY_TYPE_DESC = 'http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription';
const HALEY_KG_RELATION = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation';
const HALEY_REL_TYPE_DESC = 'http://vital.ai/ontology/haley-ai-kg#hasKGRelationTypeDescription';
const HALEY_KG_SLOT = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot';
const HALEY_ENTITY_KG_FRAME = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame';
const HALEY_DATETIME_SLOT_VALUE = 'http://vital.ai/ontology/haley-ai-kg#hasDateTimeSlotValue';
const HALEY_FRAME_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI';
const HALEY_KG_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI';

const MAX_VISUALIZATION_ITEMS = 10000;

// ---------------------------------------------------------------------------
// SPARQL helpers
// ---------------------------------------------------------------------------

const SP_KG_TYPES = 'sp_kg_types';

const KGTYPE_CLASSES = [
  'http://vital.ai/ontology/haley-ai-kg#KGType',
  'http://vital.ai/ontology/haley-ai-kg#KGEntityType',
  'http://vital.ai/ontology/haley-ai-kg#KGFrameType',
  'http://vital.ai/ontology/haley-ai-kg#KGRelationType',
  'http://vital.ai/ontology/haley-ai-kg#KGSlotType',
  'http://vital.ai/ontology/haley-ai-kg#KGSlotRoleType',
  'http://vital.ai/ontology/haley-ai-kg#KGEntityProtoType',
  'http://vital.ai/ontology/haley-ai-kg#KGFrameProtoType',
  'http://vital.ai/ontology/haley-ai-kg#KGSlotProtoType',
];

function buildSearchQuery(term: string, spaceId: string): string {
  const escaped = term.replace(/"/g, '\\"');
  if (spaceId === SP_KG_TYPES) {
    const values = KGTYPE_CLASSES.map(c => `<${c}>`).join(' ');
    return `
      SELECT ?entity ?name ?entityTypeDesc WHERE {
        VALUES ?entityTypeDesc { ${values} }
        ?entity <${RDF_TYPE}> ?entityTypeDesc .
        ?entity <${VITAL_NAME}> ?name .
        FILTER(REGEX(?name, "${escaped}", "i"))
      } LIMIT 50
    `;
  }
  return `
    SELECT ?entity ?name WHERE {
      ?entity <${RDF_TYPE}> <${HALEY_KG_ENTITY}> .
      ?entity <${VITAL_NAME}> ?name .
      FILTER(REGEX(?name, "${escaped}", "i"))
    } LIMIT 50
  `;
}

const VITAL_TYPE = 'http://vital.ai/ontology/vital-core#vitaltype';

const KGTYPE_EDGE_CLASSES = [
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasPartOfKGFrameType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityTypePartOfKGFrameType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasSameAsKGType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelationType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasOutgoingKGRelationType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasIncomingKGRelationType',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGAnnotation',
  'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlotType',
];

function buildExpandQuery(entityUri: string, spaceId: string): string {
  if (spaceId === SP_KG_TYPES) {
    const edgeValues = KGTYPE_EDGE_CLASSES.map(c => `<${c}>`).join(' ');
    const typeValues = KGTYPE_CLASSES.map(c => `<${c}>`).join(' ');
    return `
      SELECT ?srcEntity ?srcName ?srcType ?dstEntity ?dstName ?dstType ?frame ?relationType WHERE {
        {
          BIND(<${entityUri}> AS ?srcEntity)
          ?frame <${VITAL_TYPE}> ?relationType .
          ?frame <${VITAL_EDGE_SRC}> ?srcEntity .
          ?frame <${VITAL_EDGE_DST}> ?dstEntity .
          ?dstEntity <${VITAL_NAME}> ?dstName .
          ?srcEntity <${VITAL_NAME}> ?srcName .
          VALUES ?relationType { ${edgeValues} }
          ?srcEntity <${RDF_TYPE}> ?srcType . VALUES ?srcType { ${typeValues} }
          ?dstEntity <${RDF_TYPE}> ?dstType . VALUES ?dstType { ${typeValues} }
        }
        UNION
        {
          BIND(<${entityUri}> AS ?dstEntity)
          ?frame <${VITAL_TYPE}> ?relationType .
          ?frame <${VITAL_EDGE_SRC}> ?srcEntity .
          ?frame <${VITAL_EDGE_DST}> ?dstEntity .
          ?srcEntity <${VITAL_NAME}> ?srcName .
          ?dstEntity <${VITAL_NAME}> ?dstName .
          VALUES ?relationType { ${edgeValues} }
          ?srcEntity <${RDF_TYPE}> ?srcType . VALUES ?srcType { ${typeValues} }
          ?dstEntity <${RDF_TYPE}> ?dstType . VALUES ?dstType { ${typeValues} }
        }
      }
    `;
  }
  return `
    SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {
      {
        BIND(<${entityUri}> AS ?srcEntity)
        ?mySlot <${HALEY_SLOT_VALUE}> ?srcEntity .
        ?mySlot <${HALEY_FRAME_GRAPH_URI}> ?frame .
        ?frame <${HALEY_FRAME_TYPE_DESC}> ?relationType .
        ?otherSlot <${HALEY_FRAME_GRAPH_URI}> ?frame .
        ?otherSlot <${HALEY_SLOT_VALUE}> ?dstEntity .
        FILTER(?otherSlot != ?mySlot)
        ?srcEntity <${VITAL_NAME}> ?srcName .
        ?dstEntity <${VITAL_NAME}> ?dstName .
      }
      UNION
      {
        BIND(<${entityUri}> AS ?srcEntity)
        ?frame <${HALEY_KG_GRAPH_URI}> ?srcEntity .
        ?frame <${HALEY_FRAME_TYPE_DESC}> ?relationType .
        ?slot <${HALEY_FRAME_GRAPH_URI}> ?frame .
        ?slot <${HALEY_SLOT_VALUE}> ?dstEntity .
        FILTER(?dstEntity != ?srcEntity)
        ?srcEntity <${VITAL_NAME}> ?srcName .
        ?dstEntity <${VITAL_NAME}> ?dstName .
      }
      UNION
      {
        BIND(<${entityUri}> AS ?srcEntity)
        ?rel <${VITAL_EDGE_SRC}> ?srcEntity .
        ?rel <${VITAL_EDGE_DST}> ?dstEntity .
        ?rel <${HALEY_REL_TYPE_DESC}> ?relationType .
        BIND(?rel AS ?frame)
        ?srcEntity <${VITAL_NAME}> ?srcName .
        ?dstEntity <${VITAL_NAME}> ?dstName .
      }
      UNION
      {
        BIND(<${entityUri}> AS ?dstEntity)
        ?rel <${VITAL_EDGE_DST}> ?dstEntity .
        ?rel <${VITAL_EDGE_SRC}> ?srcEntity .
        ?rel <${HALEY_REL_TYPE_DESC}> ?relationType .
        BIND(?rel AS ?frame)
        ?srcEntity <${VITAL_NAME}> ?srcName .
        ?dstEntity <${VITAL_NAME}> ?dstName .
      }
      UNION
      {
        BIND(<${entityUri}> AS ?srcEntity)
        ?slot <${HALEY_FRAME_GRAPH_URI}> <${entityUri}> .
        ?slot <${HALEY_SLOT_VALUE}> ?dstEntity .
        ?slot <${HALEY_SLOT_TYPE}> ?relationType .
        BIND(?slot AS ?frame)
        <${entityUri}> <${VITAL_NAME}> ?srcName .
        ?dstEntity <${VITAL_NAME}> ?dstName .
      }
    }
  `;
}

function buildEntityCountQuery(spaceId: string): string {
  if (spaceId === SP_KG_TYPES) {
    const values = KGTYPE_CLASSES.map(c => `<${c}>`).join(' ');
    return `SELECT (COUNT(?ent) AS ?cnt) WHERE { VALUES ?type { ${values} } ?ent <${RDF_TYPE}> ?type }`;
  }
  return `SELECT (COUNT(?ent) AS ?cnt) WHERE { ?ent <${RDF_TYPE}> <${HALEY_KG_ENTITY}> }`;
}

function buildFrameCountQuery(spaceId: string): string {
  if (spaceId === SP_KG_TYPES) {
    return `SELECT (0 AS ?cnt) WHERE {}`;
  }
  return `SELECT (COUNT(?frame) AS ?cnt) WHERE { ?frame <${RDF_TYPE}> <${HALEY_KG_FRAME}> }`;
}

function buildRelationCountQuery(spaceId: string): string {
  if (spaceId === SP_KG_TYPES) {
    const edgeValues = KGTYPE_EDGE_CLASSES.map(c => `<${c}>`).join(' ');
    return `SELECT (COUNT(?rel) AS ?cnt) WHERE { VALUES ?type { ${edgeValues} } ?rel <${VITAL_TYPE}> ?type }`;
  }
  return `SELECT (COUNT(?rel) AS ?cnt) WHERE { ?rel <${RDF_TYPE}> <${HALEY_KG_RELATION}> }`;
}

function buildAllEntitiesQuery(spaceId: string): string {
  if (spaceId === SP_KG_TYPES) {
    const values = KGTYPE_CLASSES.map(c => `<${c}>`).join(' ');
    return `
      SELECT ?entity ?name ?entityTypeDesc WHERE {
        VALUES ?entityTypeDesc { ${values} }
        ?entity <${RDF_TYPE}> ?entityTypeDesc .
        ?entity <${VITAL_NAME}> ?name .
      }
    `;
  }
  return `
    SELECT ?entity ?name ?entityTypeDesc WHERE {
      ?entity <${RDF_TYPE}> <${HALEY_KG_ENTITY}> .
      ?entity <${VITAL_NAME}> ?name .
      OPTIONAL { ?entity <${HALEY_ENTITY_TYPE_DESC}> ?entityTypeDesc }
    }
  `;
}

function buildAllFramesQuery(spaceId: string): string {
  if (spaceId === SP_KG_TYPES) {
    // KG Types space has no KGFrame objects; return empty result
    return `SELECT ?frame ?frameTypeDesc ?slot ?slotType ?slotValue WHERE { FILTER(false) }`;
  }
  return `
    SELECT ?frame ?frameTypeDesc ?slot ?slotType ?slotValue ?slotGraphUri WHERE {
      ?frame <${RDF_TYPE}> <${HALEY_KG_FRAME}> .
      OPTIONAL { ?frame <${HALEY_FRAME_TYPE_DESC}> ?frameTypeDesc }
      ?slotEdge <${VITAL_EDGE_SRC}> ?frame .
      ?slotEdge <${VITAL_EDGE_DST}> ?slot .
      ?slotEdge <${RDF_TYPE}> <${HALEY_KG_SLOT}> .
      ?slot <${HALEY_SLOT_TYPE}> ?slotType .
      ?slot <${HALEY_SLOT_VALUE}> ?slotValue .
      OPTIONAL { ?slot <${HALEY_KG_GRAPH_URI}> ?slotGraphUri }
    }
  `;
}

function buildAllRelationsQuery(spaceId: string): string {
  if (spaceId === SP_KG_TYPES) {
    const edgeValues = KGTYPE_EDGE_CLASSES.map(c => `<${c}>`).join(' ');
    return `
      SELECT ?edge ?src ?dst ?relTypeDesc WHERE {
        VALUES ?edgeType { ${edgeValues} }
        ?edge <${VITAL_TYPE}> ?edgeType .
        ?edge <${VITAL_EDGE_SRC}> ?src .
        ?edge <${VITAL_EDGE_DST}> ?dst .
        BIND(?edgeType AS ?relTypeDesc)
      }
    `;
  }
  return `
    SELECT ?edge ?src ?dst ?relTypeDesc WHERE {
      ?edge <${RDF_TYPE}> <${HALEY_KG_RELATION}> .
      ?edge <${VITAL_EDGE_SRC}> ?src .
      ?edge <${VITAL_EDGE_DST}> ?dst .
      OPTIONAL { ?edge <${HALEY_REL_TYPE_DESC}> ?relTypeDesc }
    }
  `;
}

/**
 * Traverses entity graph: entity → Edge_hasEntityKGFrame → frame → Edge_hasKGSlot → slot
 * to extract datetime slot values based on a specific slot type URI.
 */
function buildEventTimestampsQuery(slotTypeUri: string): string {
  return `
    SELECT ?entity ?timestamp WHERE {
      ?frameEdge <${RDF_TYPE}> <${HALEY_ENTITY_KG_FRAME}> .
      ?frameEdge <${VITAL_EDGE_SRC}> ?entity .
      ?frameEdge <${VITAL_EDGE_DST}> ?frame .
      ?slotEdge <${RDF_TYPE}> <${HALEY_KG_SLOT}> .
      ?slotEdge <${VITAL_EDGE_SRC}> ?frame .
      ?slotEdge <${VITAL_EDGE_DST}> ?slot .
      ?slot <${HALEY_SLOT_TYPE}> <${slotTypeUri}> .
      ?slot <${HALEY_DATETIME_SLOT_VALUE}> ?timestamp .
    }
  `;
}

function buildDetailQuery(entityUri: string): string {
  return `
    SELECT ?name ?entityTypeDesc ?description WHERE {
      <${entityUri}> <${VITAL_NAME}> ?name .
      OPTIONAL { <${entityUri}> <${HALEY_ENTITY_TYPE_DESC}> ?entityTypeDesc }
      OPTIONAL { <${entityUri}> <${HALEY_KG_DESC}> ?description }
    }
  `;
}

// ---------------------------------------------------------------------------
// Row remapping
// ---------------------------------------------------------------------------

function parseResults(result: Record<string, unknown>): Record<string, string>[] {
  // Standard SPARQL Results JSON: { head: { vars }, results: { bindings: [{ var: { type, value } }] } }
  const bindings = (result.results as Record<string, unknown>)?.bindings as Record<string, { type: string; value: string }>[] | undefined;
  if (bindings && bindings.length > 0) {
    return bindings.map(binding => {
      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(binding)) {
        out[k] = v?.value ?? '';
      }
      return out;
    });
  }
  return [];
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useGraphVisualization(spaceId: string) {
  // -----------------------------------------------------------------------
  // Internal state: DataGraph is the source of truth
  // -----------------------------------------------------------------------
  const [dataGraph, setDataGraph] = useState<DataGraph>(createEmptyDataGraph);
  const [eventTimestamps, setEventTimestamps] = useState<Map<string, string>>(new Map());
  const [searching, setSearching] = useState(false);
  const [expanding, setExpanding] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const viewGraph: ViewGraph = useMemo(() => buildViewGraph(dataGraph, spaceId), [dataGraph, spaceId]);

  const viewGraphRef = useRef(viewGraph);
  viewGraphRef.current = viewGraph;

  // -----------------------------------------------------------------------
  // Space size check (for Load All gating)
  // -----------------------------------------------------------------------
  const [spaceItemCount, setSpaceItemCount] = useState<number | null>(null);

  useEffect(() => {
    if (!spaceId) { setSpaceItemCount(null); return; }
    let cancelled = false;
    Promise.all([
      ApiService.executeSparqlQuery(spaceId, buildEntityCountQuery(spaceId)),
      ApiService.executeSparqlQuery(spaceId, buildFrameCountQuery(spaceId)),
      ApiService.executeSparqlQuery(spaceId, buildRelationCountQuery(spaceId)),
    ])
      .then(([entResult, frameResult, relResult]) => {
        if (cancelled) return;
        const entRows = parseResults(entResult);
        const frameRows = parseResults(frameResult);
        const relRows = parseResults(relResult);
        const entities = entRows.length > 0 ? parseInt(entRows[0].cnt || '0', 10) : 0;
        const frames = frameRows.length > 0 ? parseInt(frameRows[0].cnt || '0', 10) : 0;
        const relations = relRows.length > 0 ? parseInt(relRows[0].cnt || '0', 10) : 0;
        const total = entities + frames + relations;
        console.log('[LoadAll] Space count:', { entities, frames, relations, total });
        setSpaceItemCount(total);
      })
      .catch((err) => { console.error('[LoadAll] Space count error:', err); if (!cancelled) setSpaceItemCount(null); });
    return () => { cancelled = true; };
  }, [spaceId]);

  const canLoadFullSpace = spaceItemCount !== null && spaceItemCount <= MAX_VISUALIZATION_ITEMS;

  // -----------------------------------------------------------------------
  // Search
  // -----------------------------------------------------------------------

  const searchEntities = useCallback(async (term: string) => {
    if (!term.trim()) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const sparql = buildSearchQuery(term, spaceId);
      const result = await ApiService.executeSparqlQuery(spaceId, sparql);
      const rows = parseResults(result);
      setSearchResults(rows.map(r => ({ uri: r.entity, name: r.name, typeDescription: r.entityTypeDesc || undefined })));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Search failed';
      setError(msg);
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [spaceId]);

  // -----------------------------------------------------------------------
  // Load full space: fetch all entities, frames, slots, edges
  // -----------------------------------------------------------------------

  const loadFullSpace = useCallback(async () => {
    if (!spaceId) return;
    setLoading(true);
    setError(null);
    try {
      console.log('[LoadAll] Starting for space:', spaceId);
      const [entResult, frameResult, relResult, tsResult] = await Promise.all([
        ApiService.executeSparqlQuery(spaceId, buildAllEntitiesQuery(spaceId)),
        ApiService.executeSparqlQuery(spaceId, buildAllFramesQuery(spaceId)),
        ApiService.executeSparqlQuery(spaceId, buildAllRelationsQuery(spaceId)),
        ApiService.executeSparqlQuery(spaceId, buildEventTimestampsQuery('urn:slot_type:EventTimestampSlot')),
      ]);
      console.log('[LoadAll] Raw results:', { entResult, frameResult, relResult });

      const entRows = parseResults(entResult);
      const frameRows = parseResults(frameResult);
      const relRows = parseResults(relResult);
      console.log('[LoadAll] Parsed rows:', entRows.length, 'ent,', frameRows.length, 'frame,', relRows.length, 'rel');
      if (entRows.length > 0) {
        console.log('[LoadAll] First ent row keys:', Object.keys(entRows[0]));
        console.log('[LoadAll] First 3 ent rows entityTypeDesc:', entRows.slice(0, 3).map(r => r.entityTypeDesc));
      }

      setDataGraph(() => {
        const next = createEmptyDataGraph();

        for (const row of entRows) {
          next.entities.set(row.entity, {
            uri: row.entity,
            name: row.name || row.entity,
            typeDescription: row.entityTypeDesc || undefined,
            properties: {},
            fetchedAt: new Date(),
          });
          next.fetchedExpansions.add(row.entity);
        }

        const frameSlots = new Map<string, { frameTypeDesc: string; slots: string[] }>();
        for (const row of frameRows) {
          const fUri = row.frame;
          const slotUri = row.slot;
          const slotType = row.slotType;
          const slotValue = row.slotValue;

          if (!frameSlots.has(fUri)) {
            frameSlots.set(fUri, { frameTypeDesc: row.frameTypeDesc || '', slots: [] });
          }
          frameSlots.get(fUri)!.slots.push(slotUri);

          if (!next.slots.has(slotUri)) {
            const isEntity = next.entities.has(slotValue);
            next.slots.set(slotUri, {
              uri: slotUri,
              slotType,
              value: slotValue,
              valueType: isEntity ? 'entity' : 'literal',
              graphUri: row.slotGraphUri || undefined,
            });
          }
        }

        for (const [fUri, info] of frameSlots) {
          const uniqueSlots = [...new Set(info.slots)];
          next.frames.set(fUri, {
            uri: fUri,
            frameType: info.frameTypeDesc,
            frameTypeDescription: info.frameTypeDesc,
            slots: uniqueSlots,
            fetchedAt: new Date(),
          });
        }

        for (const row of relRows) {
          next.edges.set(row.edge, {
            uri: row.edge,
            edgeType: row.relTypeDesc || 'Edge_hasKGRelation',
            source: row.src,
            destination: row.dst,
            properties: {
              relationTypeDescription: row.relTypeDesc || '',
            },
          });
        }

        return next;
      });

      // Parse event timestamps (entity graph traversal result)
      const tsRows = parseResults(tsResult);
      const tsMap = new Map<string, string>();
      for (const row of tsRows) {
        if (row.entity && row.timestamp) {
          tsMap.set(row.entity, row.timestamp);
        }
      }
      setEventTimestamps(tsMap);
      console.log('[LoadAll] Event timestamps:', tsMap.size);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Load failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [spaceId]);

  // -----------------------------------------------------------------------
  // Re-fetch event timestamps when dataGraph is restored but timestamps lost
  // (e.g. navigating away and returning — session restores dataGraph but
  // eventTimestamps is local hook state that resets to empty)
  // -----------------------------------------------------------------------

  useEffect(() => {
    if (!spaceId || dataGraph.entities.size === 0) return;
    if (eventTimestamps.size > 0) return;
    let cancelled = false;
    ApiService.executeSparqlQuery(spaceId, buildEventTimestampsQuery('urn:slot_type:EventTimestampSlot'))
      .then(tsResult => {
        if (cancelled) return;
        const tsRows = parseResults(tsResult);
        const tsMap = new Map<string, string>();
        for (const row of tsRows) {
          if (row.entity && row.timestamp) {
            tsMap.set(row.entity, row.timestamp);
          }
        }
        if (tsMap.size > 0) {
          setEventTimestamps(tsMap);
          console.log('[Timeline] Re-fetched event timestamps:', tsMap.size);
        }
      })
      .catch(() => { /* non-critical — timeline just won't show */ });
    return () => { cancelled = true; };
  }, [spaceId, dataGraph.entities.size, eventTimestamps.size]);

  // -----------------------------------------------------------------------
  // Add entity to DataGraph
  // -----------------------------------------------------------------------

  const addNode = useCallback((uri: string, name: string, typeDescription?: string) => {
    setDataGraph(prev => {
      if (prev.entities.has(uri)) return prev;
      const next = cloneDataGraph(prev);
      next.entities.set(uri, {
        uri,
        name,
        typeDescription,
        properties: {},
        fetchedAt: new Date(),
      });
      return next;
    });
  }, []);

  // -----------------------------------------------------------------------
  // Expand: fetch neighbors via SPARQL, populate DataGraph
  // -----------------------------------------------------------------------

  const expandNode = useCallback(async (entityUri: string) => {
    setExpanding(true);
    setError(null);
    try {
      const sparql = buildExpandQuery(entityUri, spaceId);
      const result = await ApiService.executeSparqlQuery(spaceId, sparql);
      console.log('[GraphViz] expand result:', JSON.stringify(result).slice(0, 500));
      const rows = parseResults(result);
      console.log('[GraphViz] expand parsed rows:', rows.length, rows.slice(0, 2));

      setDataGraph(prev => {
        const next = cloneDataGraph(prev);
        next.fetchedExpansions.add(entityUri);

        for (const row of rows) {
          const src = row.srcEntity;
          const dst = row.dstEntity;
          const frameUri = row.frame;
          const rel = row.relationType || '';

          // Ensure both entities exist in cache (and update names if better data available)
          if (!next.entities.has(src)) {
            next.entities.set(src, {
              uri: src,
              name: row.srcName || src,
              typeDescription: row.srcType || undefined,
              properties: {},
              fetchedAt: new Date(),
            });
          } else if (row.srcName) {
            const existing = next.entities.get(src)!;
            if (!existing.name || existing.name === src) {
              next.entities.set(src, { ...existing, name: row.srcName });
            }
            if (row.srcType && !existing.typeDescription) {
              next.entities.set(src, { ...next.entities.get(src)!, typeDescription: row.srcType });
            }
          }
          if (!next.entities.has(dst)) {
            next.entities.set(dst, {
              uri: dst,
              name: row.dstName || dst,
              typeDescription: row.dstType || undefined,
              properties: {},
              fetchedAt: new Date(),
            });
          } else if (row.dstName) {
            const existing = next.entities.get(dst)!;
            if (!existing.name || existing.name === dst) {
              next.entities.set(dst, { ...existing, name: row.dstName });
            }
            if (row.dstType && !existing.typeDescription) {
              next.entities.set(dst, { ...next.entities.get(dst)!, typeDescription: row.dstType });
            }
          }

          // Model the frame + 2 entity slots (binary pattern)
          if (!next.frames.has(frameUri)) {
            const srcSlotUri = `${frameUri}:slot:src`;
            const dstSlotUri = `${frameUri}:slot:dst`;

            next.frames.set(frameUri, {
              uri: frameUri,
              frameType: rel,
              frameTypeDescription: rel,
              slots: [srcSlotUri, dstSlotUri],
              fetchedAt: new Date(),
            });

            next.slots.set(srcSlotUri, {
              uri: srcSlotUri,
              slotType: 'urn:hasSourceEntity',
              value: src,
              valueType: 'entity',
            });
            next.slots.set(dstSlotUri, {
              uri: dstSlotUri,
              slotType: 'urn:hasDestinationEntity',
              value: dst,
              valueType: 'entity',
            });
          }
        }
        return next;
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Expand failed';
      setError(msg);
    } finally {
      setExpanding(false);
    }
  }, [spaceId]);

  // -----------------------------------------------------------------------
  // Collapse: remove expansion data for a node
  // -----------------------------------------------------------------------

  const collapseNode = useCallback((entityUri: string) => {
    setDataGraph(prev => {
      const next = cloneDataGraph(prev);
      next.fetchedExpansions.delete(entityUri);

      // Find frames owned by / connected to this entity via slots
      const framesToRemove = new Set<string>();
      for (const [frameUri, frame] of next.frames) {
        for (const slotUri of frame.slots) {
          const slot = next.slots.get(slotUri);
          if (slot && slot.value === entityUri) {
            framesToRemove.add(frameUri);
          }
        }
      }

      // Remove those frames and their slots
      for (const frameUri of framesToRemove) {
        const frame = next.frames.get(frameUri);
        if (frame) {
          for (const slotUri of frame.slots) {
            next.slots.delete(slotUri);
          }
          next.frames.delete(frameUri);
        }
      }

      // Remove orphaned entities (no remaining frame references)
      const referencedEntities = new Set<string>();
      for (const slot of next.slots.values()) {
        if (slot.valueType === 'entity') {
          referencedEntities.add(slot.value);
        }
      }
      for (const edge of next.edges.values()) {
        referencedEntities.add(edge.source);
        referencedEntities.add(edge.destination);
      }

      for (const uri of [...next.entities.keys()]) {
        if (uri !== entityUri && !referencedEntities.has(uri) && !next.fetchedExpansions.has(uri)) {
          next.entities.delete(uri);
        }
      }

      return next;
    });
  }, []);

  // -----------------------------------------------------------------------
  // Detail fetch: enrich an entity with type/description
  // -----------------------------------------------------------------------

  const getNodeDetail = useCallback(async (entityUri: string): Promise<{ name?: string; typeDescription?: string; description?: string } | null> => {
    try {
      const sparql = buildDetailQuery(entityUri);
      const result = await ApiService.executeSparqlQuery(spaceId, sparql);
      const rows = parseResults(result);
      if (rows.length > 0) {
        const row = rows[0];
        // Mutate entity in-place — no DataGraph clone needed for display metadata
        const existing = dataGraph.entities.get(entityUri);
        if (existing) {
          if (row.name) existing.name = row.name;
          if (row.entityTypeDesc) existing.typeDescription = row.entityTypeDesc;
          if (row.description) existing.description = row.description;
        }
        return { name: row.name, typeDescription: row.entityTypeDesc, description: row.description };
      }
    } catch {
      // Detail fetch failure is non-critical
    }
    return null;
  }, [spaceId, dataGraph]);

  // -----------------------------------------------------------------------
  // Clear / remove
  // -----------------------------------------------------------------------

  const clearGraph = useCallback(() => {
    setDataGraph(createEmptyDataGraph());
    setSearchResults([]);
    setError(null);
  }, []);

  const restoreDataGraph = useCallback((dg: DataGraph) => {
    setDataGraph(dg);
    setSearchResults([]);
    setError(null);
  }, []);

  const removeNode = useCallback((entityUri: string) => {
    setDataGraph(prev => {
      const next = cloneDataGraph(prev);
      next.entities.delete(entityUri);
      next.fetchedExpansions.delete(entityUri);

      // Remove frames that reference this entity via slots
      for (const [frameUri, frame] of next.frames) {
        for (const slotUri of frame.slots) {
          const slot = next.slots.get(slotUri);
          if (slot && slot.value === entityUri) {
            // Remove entire frame and its slots
            for (const s of frame.slots) next.slots.delete(s);
            next.frames.delete(frameUri);
            break;
          }
        }
      }

      // Remove direct relation edges involving this entity
      for (const [edgeUri, edge] of next.edges) {
        if (edge.source === entityUri || edge.destination === entityUri) {
          next.edges.delete(edgeUri);
        }
      }

      return next;
    });
  }, []);

  return {
    viewGraph,
    dataGraph,
    eventTimestamps,
    searching,
    expanding,
    loading,
    canLoadFullSpace,
    searchResults,
    error,
    searchEntities,
    loadFullSpace,
    addNode,
    expandNode,
    collapseNode,
    getNodeDetail,
    clearGraph,
    restoreDataGraph,
    removeNode,
  };
}

// ---------------------------------------------------------------------------
// DataGraph cloning helper (shallow clone of Maps/Sets for immutable updates)
// ---------------------------------------------------------------------------

function cloneDataGraph(dg: DataGraph): DataGraph {
  return {
    entities: new Map(dg.entities),
    frames: new Map(dg.frames),
    slots: new Map(dg.slots),
    documents: new Map(dg.documents),
    edges: new Map(dg.edges),
    fetchedExpansions: new Set(dg.fetchedExpansions),
  };
}
