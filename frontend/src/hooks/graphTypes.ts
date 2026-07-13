// ---------------------------------------------------------------------------
// Graph Session Architecture — Type Definitions (Phase 1)
//
// Separates raw KG data (DataGraph) from Cytoscape rendering (ViewGraph).
// See: planning/planning_visualization/graph_session_architecture_plan.md
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// DataGraph — Raw KG Data Cache
// ---------------------------------------------------------------------------

export interface KGEntityData {
  uri: string;
  name: string;
  typeDescription?: string;
  description?: string;
  properties: Record<string, unknown>;
  fetchedAt: Date;
}

export interface KGFrameData {
  uri: string;
  name?: string;
  frameType: string;
  frameTypeDescription?: string;
  formType?: 'Assertion' | 'Aspect';
  ownerEntityUri?: string;
  parentFrameUri?: string;
  slots: string[];
  fetchedAt: Date;
}

export interface KGSlotData {
  uri: string;
  slotType: string;
  slotTypeDescription?: string;
  value: string;
  valueType: 'entity' | 'document' | 'literal';
  graphUri?: string;
}

export interface KGDocumentData {
  uri: string;
  name: string;
  description?: string;
  properties: Record<string, unknown>;
  fetchedAt: Date;
}

export interface EdgeData {
  uri: string;
  edgeType: string;
  source: string;
  destination: string;
  properties: Record<string, unknown>;
}

export interface DataGraph {
  entities: Map<string, KGEntityData>;
  frames: Map<string, KGFrameData>;
  slots: Map<string, KGSlotData>;
  documents: Map<string, KGDocumentData>;
  edges: Map<string, EdgeData>;
  fetchedExpansions: Set<string>;
}

export function createEmptyDataGraph(): DataGraph {
  return {
    entities: new Map(),
    frames: new Map(),
    slots: new Map(),
    documents: new Map(),
    edges: new Map(),
    fetchedExpansions: new Set(),
  };
}

// ---------------------------------------------------------------------------
// ViewGraph — Cytoscape Representation (derived from DataGraph)
// ---------------------------------------------------------------------------

export interface CyNode {
  id: string;
  label: string;
  nodeType: 'entity' | 'document' | 'frame_hub' | 'kgtype';
  classes: string[];
  data: {
    entityType?: string;
    frameType?: string;
    expanded?: boolean;
    pinned?: boolean;
  };
}

export interface CyEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  classes: string[];
  data: {
    edgeType: 'collapsed_frame' | 'hub_spoke' | 'relation' | 'document_link';
    frameUri?: string;
    slotType?: string;
  };
}

export interface ViewGraph {
  cyNodes: Map<string, CyNode>;
  cyEdges: Map<string, CyEdge>;
}

export function createEmptyViewGraph(): ViewGraph {
  return {
    cyNodes: new Map(),
    cyEdges: new Map(),
  };
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export type LayoutAlgorithm =
  | 'cose-bilkent'
  | 'fcose'
  | 'dagre'
  | 'cola'
  | 'elk-stress'
  | 'elk-layered'
  | 'breadthfirst'
  | 'circle'
  | 'concentric'
  | 'grid'
  | 'event-timeline';

export interface LayoutConfig {
  algorithm: LayoutAlgorithm;
  animate: boolean;
  animationDuration: number;
  autoLayoutOnChange: boolean;
  params: Record<string, unknown>;
}

export const DEFAULT_LAYOUT_CONFIG: LayoutConfig = {
  algorithm: 'cose-bilkent',
  animate: true,
  animationDuration: 500,
  autoLayoutOnChange: true,
  params: {},
};

export const LAYOUT_OPTIONS: { value: LayoutAlgorithm; label: string }[] = [
  { value: 'cose-bilkent', label: 'CoSE-Bilkent' },
  { value: 'fcose', label: 'fCoSE' },
  { value: 'dagre', label: 'Dagre (Hierarchical)' },
  { value: 'cola', label: 'Cola (Constraint)' },
  { value: 'elk-stress', label: 'ELK Stress' },
  { value: 'elk-layered', label: 'ELK Layered' },
  { value: 'breadthfirst', label: 'Breadthfirst (Tree)' },
  { value: 'circle', label: 'Circle' },
  { value: 'concentric', label: 'Concentric' },
  { value: 'grid', label: 'Grid' },
  { value: 'event-timeline', label: 'Event Timeline (L\u2192R)' },
];

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export interface SearchResult {
  uri: string;
  name: string;
  typeDescription?: string;
}
