// ---------------------------------------------------------------------------
// buildViewGraph — Transforms DataGraph into ViewGraph for Cytoscape
//
// Phase 1: Binary frame collapse + direct relation edges + N-ary hub rendering.
// See: planning/planning_visualization/graph_session_architecture_plan.md §4
// ---------------------------------------------------------------------------

import type {
  DataGraph,
  KGFrameData,
  ViewGraph,
  CyNode,
  CyEdge,
} from './graphTypes';
import { createEmptyViewGraph } from './graphTypes';

// ---------------------------------------------------------------------------
// Arity classification (runtime-inferred from slots)
// ---------------------------------------------------------------------------

interface ArityResult {
  arity: 'binary' | 'n_ary' | 'unary';
  entitySlotUris: string[];
}

function classifyFrameArity(frame: KGFrameData, dataGraph: DataGraph): ArityResult {
  const entitySlotUris: string[] = [];
  for (const slotUri of frame.slots) {
    const slot = dataGraph.slots.get(slotUri);
    if (slot && slot.valueType === 'entity') {
      entitySlotUris.push(slotUri);
    }
  }
  const count = entitySlotUris.length;
  if (count === 0) return { arity: 'unary', entitySlotUris };
  if (count <= 2) return { arity: 'binary', entitySlotUris };
  return { arity: 'n_ary', entitySlotUris };
}

// ---------------------------------------------------------------------------
// Core transformation
// ---------------------------------------------------------------------------

export function buildViewGraph(dataGraph: DataGraph, spaceId?: string): ViewGraph {
  const view = createEmptyViewGraph();
  const isKGTypesSpace = spaceId === 'sp_kg_types';

  // Step 1: Add entity nodes for all known entities
  for (const [uri, entity] of dataGraph.entities) {
    const node: CyNode = {
      id: uri,
      label: entity.name,
      nodeType: isKGTypesSpace ? 'kgtype' : 'entity',
      classes: [isKGTypesSpace ? 'kgtype' : 'entity'],
      data: {
        entityType: entity.typeDescription,
        expanded: dataGraph.fetchedExpansions.has(uri),
      },
    };
    view.cyNodes.set(uri, node);
  }

  // Step 2: Add document nodes
  for (const [uri, doc] of dataGraph.documents) {
    const node: CyNode = {
      id: uri,
      label: doc.name,
      nodeType: 'document',
      classes: ['document'],
      data: {},
    };
    view.cyNodes.set(uri, node);
  }

  // Step 3: Process frames (collapse binary, render N-ary as hubs, skip unary)
  for (const [frameUri, frame] of dataGraph.frames) {
    const { arity, entitySlotUris } = classifyFrameArity(frame, dataGraph);

    if (arity === 'binary') {
      // Collapse binary frame into a direct edge between the two entities
      const entities: string[] = [];
      for (const slotUri of entitySlotUris) {
        const slot = dataGraph.slots.get(slotUri);
        if (slot) entities.push(slot.value);
      }
      if (entities.length >= 2) {
        const edgeId = `collapsed:${frameUri}`;
        const label = frame.frameTypeDescription || frame.frameType || '';
        const cyEdge: CyEdge = {
          id: edgeId,
          source: entities[0],
          target: entities[1],
          label: shortenLabel(label),
          classes: ['collapsed-frame'],
          data: {
            edgeType: 'collapsed_frame',
            frameUri,
          },
        };
        view.cyEdges.set(edgeId, cyEdge);
      }
    } else if (arity === 'n_ary') {
      // Render N-ary frame as a hub node with spoke edges to each entity/doc
      const hubNode: CyNode = {
        id: frameUri,
        label: frame.frameTypeDescription || frame.name || frame.frameType || '',
        nodeType: 'frame_hub',
        classes: ['frame-hub'],
        data: {
          frameType: frame.frameType,
        },
      };
      view.cyNodes.set(frameUri, hubNode);

      // Create spoke edges from hub to each entity slot target
      for (const slotUri of frame.slots) {
        const slot = dataGraph.slots.get(slotUri);
        if (!slot) continue;

        if (slot.valueType === 'entity' || slot.valueType === 'document') {
          const spokeId = `spoke:${frameUri}:${slotUri}`;
          const cyEdge: CyEdge = {
            id: spokeId,
            source: frameUri,
            target: slot.value,
            label: slot.slotTypeDescription || shortenSlotType(slot.slotType),
            classes: ['hub-spoke'],
            data: {
              edgeType: 'hub_spoke',
              frameUri,
              slotType: slot.slotType,
            },
          };
          view.cyEdges.set(spokeId, cyEdge);
        }
      }
    }
    // arity === 'unary': skip — shown in detail panel only
  }

  // Step 4: Add direct edges (Edge_hasKGRelation, type-level edges, etc.)
  for (const [edgeUri, edge] of dataGraph.edges) {
    const relType = (edge.properties?.relationType as string) || '';
    const relTypeDesc = (edge.properties?.relationTypeDescription as string) || relType;
    const cyEdge: CyEdge = {
      id: `relation:${edgeUri}`,
      source: edge.source,
      target: edge.destination,
      label: shortenLabel(relTypeDesc),
      classes: ['relation'],
      data: {
        edgeType: 'relation',
      },
    };
    view.cyEdges.set(cyEdge.id, cyEdge);
  }

  // Step 5: Remove edges whose source or target node is not in the view
  for (const [id, edge] of view.cyEdges) {
    if (!view.cyNodes.has(edge.source) || !view.cyNodes.has(edge.target)) {
      view.cyEdges.delete(id);
    }
  }

  return view;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function shortenLabel(label: string): string {
  // Extract local name from full URI (e.g. "http://...#Edge_hasSubKGEntityType" → "Edge_hasSubKGEntityType")
  const hashIdx = label.lastIndexOf('#');
  if (hashIdx >= 0) label = label.slice(hashIdx + 1);
  const slashIdx = label.lastIndexOf('/');
  if (slashIdx >= 0) label = label.slice(slashIdx + 1);
  if (label.startsWith('Edge_Wordnet')) return label.slice('Edge_Wordnet'.length);
  if (label.startsWith('Edge_')) return label.slice('Edge_'.length);
  return label;
}

function shortenSlotType(slotType: string): string {
  // "urn:hasResearcher" → "hasResearcher"
  const lastColon = slotType.lastIndexOf(':');
  if (lastColon >= 0) return slotType.slice(lastColon + 1);
  const lastHash = slotType.lastIndexOf('#');
  if (lastHash >= 0) return slotType.slice(lastHash + 1);
  return slotType;
}
