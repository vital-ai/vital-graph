import { useState, useCallback, useRef } from 'react';
import ApiService from '../services/ApiService';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GraphNode {
  id: string;
  label: string;
  type?: string;
  description?: string;
  expanded?: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
}

export interface GraphState {
  nodes: Map<string, GraphNode>;
  edges: Map<string, GraphEdge>;
}

export interface SearchResult {
  uri: string;
  name: string;
}

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

// ---------------------------------------------------------------------------
// SPARQL helpers
// ---------------------------------------------------------------------------

function buildSearchQuery(term: string): string {
  const escaped = term.replace(/"/g, '\\"');
  return `
    SELECT ?entity ?name WHERE {
      ?entity <${RDF_TYPE}> <${HALEY_KG_ENTITY}> .
      ?entity <${VITAL_NAME}> ?name .
      FILTER(REGEX(?name, "${escaped}", "i"))
    } LIMIT 50
  `;
}

function buildExpandQuery(entityUri: string): string {
  return `
    SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {
      {
        BIND(<${entityUri}> AS ?srcEntity)
        ?srcSlot <${HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
        ?srcSlot <${HALEY_SLOT_VALUE}> ?srcEntity .
        ?srcEdge <${VITAL_EDGE_SRC}> ?frame .
        ?srcEdge <${VITAL_EDGE_DST}> ?srcSlot .

        ?frame <${RDF_TYPE}> <${HALEY_KG_FRAME}> .
        ?frame <${HALEY_FRAME_TYPE_DESC}> ?relationType .

        ?dstSlot <${HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
        ?dstSlot <${HALEY_SLOT_VALUE}> ?dstEntity .
        ?dstEdge <${VITAL_EDGE_SRC}> ?frame .
        ?dstEdge <${VITAL_EDGE_DST}> ?dstSlot .

        ?srcEntity <${VITAL_NAME}> ?srcName .
        ?dstEntity <${VITAL_NAME}> ?dstName .
      }
      UNION
      {
        BIND(<${entityUri}> AS ?dstEntity)
        ?dstSlot <${HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
        ?dstSlot <${HALEY_SLOT_VALUE}> ?dstEntity .
        ?dstEdge <${VITAL_EDGE_SRC}> ?frame .
        ?dstEdge <${VITAL_EDGE_DST}> ?dstSlot .

        ?frame <${RDF_TYPE}> <${HALEY_KG_FRAME}> .
        ?frame <${HALEY_FRAME_TYPE_DESC}> ?relationType .

        ?srcSlot <${HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
        ?srcSlot <${HALEY_SLOT_VALUE}> ?srcEntity .
        ?srcEdge <${VITAL_EDGE_SRC}> ?frame .
        ?srcEdge <${VITAL_EDGE_DST}> ?srcSlot .

        ?srcEntity <${VITAL_NAME}> ?srcName .
        ?dstEntity <${VITAL_NAME}> ?dstName .
      }
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

function shortenRelType(rel: string): string {
  if (rel.startsWith('Edge_Wordnet')) return rel.slice('Edge_Wordnet'.length);
  if (rel.startsWith('Edge_')) return rel.slice('Edge_'.length);
  return rel;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useGraphVisualization(spaceId: string) {
  const [graph, setGraph] = useState<GraphState>({
    nodes: new Map(),
    edges: new Map(),
  });
  const [searching, setSearching] = useState(false);
  const [expanding, setExpanding] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const graphRef = useRef(graph);
  graphRef.current = graph;

  const searchEntities = useCallback(async (term: string) => {
    if (!term.trim()) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const sparql = buildSearchQuery(term);
      const result = await ApiService.executeSparqlQuery(spaceId, sparql);
      const rows = parseResults(result);
      setSearchResults(rows.map(r => ({ uri: r.entity, name: r.name })));
    } catch (e: any) {
      setError(e.message || 'Search failed');
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [spaceId]);

  const addNode = useCallback((uri: string, name: string) => {
    setGraph(prev => {
      if (prev.nodes.has(uri)) return prev;
      const next = {
        nodes: new Map(prev.nodes),
        edges: new Map(prev.edges),
      };
      next.nodes.set(uri, { id: uri, label: name });
      return next;
    });
  }, []);

  const expandNode = useCallback(async (entityUri: string) => {
    setExpanding(true);
    setError(null);
    try {
      const sparql = buildExpandQuery(entityUri);
      const result = await ApiService.executeSparqlQuery(spaceId, sparql);
      // eslint-disable-next-line no-console
      console.log('[GraphViz] expand result:', JSON.stringify(result).slice(0, 500));
      const rows = parseResults(result);
      // eslint-disable-next-line no-console
      console.log('[GraphViz] expand parsed rows:', rows.length, rows.slice(0, 2));

      setGraph(prev => {
        const next = {
          nodes: new Map(prev.nodes),
          edges: new Map(prev.edges),
        };
        // Mark the expanded node
        const existingNode = next.nodes.get(entityUri);
        if (existingNode) {
          next.nodes.set(entityUri, { ...existingNode, expanded: true });
        }

        for (const row of rows) {
          const src = row.srcEntity;
          const dst = row.dstEntity;
          const frame = row.frame;
          const rel = row.relationType || '';

          if (!next.nodes.has(src)) {
            next.nodes.set(src, { id: src, label: row.srcName || src });
          }
          if (!next.nodes.has(dst)) {
            next.nodes.set(dst, { id: dst, label: row.dstName || dst });
          }
          if (!next.edges.has(frame)) {
            next.edges.set(frame, {
              id: frame,
              source: src,
              target: dst,
              label: shortenRelType(rel),
            });
          }
        }
        return next;
      });
    } catch (e: any) {
      setError(e.message || 'Expand failed');
    } finally {
      setExpanding(false);
    }
  }, [spaceId]);

  const collapseNode = useCallback((entityUri: string) => {
    setGraph(prev => {
      const next = {
        nodes: new Map(prev.nodes),
        edges: new Map(prev.edges),
      };
      // Find edges connected to this node
      const connectedEdges = [...next.edges.values()].filter(
        e => e.source === entityUri || e.target === entityUri
      );
      // Find nodes that would be orphaned if we remove these edges
      const connectedNodeIds = new Set<string>();
      for (const e of connectedEdges) {
        connectedNodeIds.add(e.source === entityUri ? e.target : e.source);
      }
      // Remove the edges
      for (const e of connectedEdges) {
        next.edges.delete(e.id);
      }
      // Remove orphaned nodes (nodes with no remaining edges)
      for (const nodeId of connectedNodeIds) {
        const hasEdge = [...next.edges.values()].some(
          e => e.source === nodeId || e.target === nodeId
        );
        if (!hasEdge && nodeId !== entityUri) {
          next.nodes.delete(nodeId);
        }
      }
      // Mark as collapsed
      const node = next.nodes.get(entityUri);
      if (node) {
        next.nodes.set(entityUri, { ...node, expanded: false });
      }
      return next;
    });
  }, []);

  const getNodeDetail = useCallback(async (entityUri: string) => {
    try {
      const sparql = buildDetailQuery(entityUri);
      const result = await ApiService.executeSparqlQuery(spaceId, sparql);
      const rows = parseResults(result);
      if (rows.length > 0) {
        const row = rows[0];
        setGraph(prev => {
          const next = {
            nodes: new Map(prev.nodes),
            edges: new Map(prev.edges),
          };
          const existing = next.nodes.get(entityUri);
          if (existing) {
            next.nodes.set(entityUri, {
              ...existing,
              type: row.entityTypeDesc,
              description: row.description,
            });
          }
          return next;
        });
      }
    } catch {
      // Detail fetch failure is non-critical
    }
  }, [spaceId]);

  const clearGraph = useCallback(() => {
    setGraph({ nodes: new Map(), edges: new Map() });
    setSearchResults([]);
    setError(null);
  }, []);

  const removeNode = useCallback((entityUri: string) => {
    setGraph(prev => {
      const next = {
        nodes: new Map(prev.nodes),
        edges: new Map(prev.edges),
      };
      next.nodes.delete(entityUri);
      // Remove all connected edges
      for (const [id, e] of next.edges) {
        if (e.source === entityUri || e.target === entityUri) {
          next.edges.delete(id);
        }
      }
      return next;
    });
  }, []);

  return {
    graph,
    searching,
    expanding,
    searchResults,
    error,
    searchEntities,
    addNode,
    expandNode,
    collapseNode,
    getNodeDetail,
    clearGraph,
    removeNode,
  };
}
