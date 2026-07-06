# Graph Session Architecture Plan

## 1. Overview

The graph visualization needs a **multi-layer data structure** that separates
raw KG data from the Cytoscape rendering representation, supports multiple
concurrent graph sessions, and provides a natural home for visualization
metadata like frame arity classification.

### Design Goals

1. **Cache** — hold fetched entities/frames/edges so expansions don't re-query
2. **Data/view separation** — raw graph objects (with full properties) vs.
   Cytoscape-specific shape/position/style representation
3. **Visualization metadata** — arity registry, frame collapse decisions,
   style overrides organized per-session
4. **Multi-session** — hold multiple investigation graphs in memory, switch
   between them without losing state or requiring re-fetch

---

## 2. Architecture

```
┌────────────────────────────────────────────────────────┐
│  GraphSessionStore                                     │
│  ├── sessions: Map<sessionId, GraphSession>            │
│  ├── activeSessionId: string | null                    │
│  ├── createSession(name, spaceId): GraphSession        │
│  ├── deleteSession(sessionId): void                    │
│  ├── duplicateSession(sessionId): GraphSession         │
│  └── switchSession(sessionId): void                    │
├────────────────────────────────────────────────────────┤
│  GraphSession                                          │
│  ├── id: string (uuid)                                 │
│  ├── name: string                                      │
│  ├── spaceId: string                                   │
│  ├── createdAt: Date                                   │
│  ├── updatedAt: Date                                   │
│  ├── dataGraph: DataGraph           ← raw KG data      │
│  ├── viewGraph: ViewGraph           ← cytoscape repr   │
│  └── vizConfig: SessionVizConfig    ← arity, styles    │
├────────────────────────────────────────────────────────┤
│  DataGraph (cache + structural truth)                  │
│  ├── entities: Map<uri, KGEntityData>                  │
│  ├── frames: Map<uri, KGFrameData>                     │
│  ├── slots: Map<uri, KGSlotData>                       │
│  ├── documents: Map<uri, KGDocumentData>               │
│  ├── edges: Map<uri, EdgeData>                         │
│  ├── fetchedExpansions: Set<uri>                       │
│  └── lastFetchedAt: Map<uri, Date>                     │
├────────────────────────────────────────────────────────┤
│  ViewGraph (derived from DataGraph + VizConfig)        │
│  ├── cyNodes: Map<id, CyNode>                          │
│  ├── cyEdges: Map<id, CyEdge>                          │
│  ├── layout: LayoutState                               │
│  └── selection: SelectionState                         │
├────────────────────────────────────────────────────────┤
│  SessionVizConfig (per-session, initialized from DB)   │
│  ├── frameArity: Map<frameTypeUri, ArityInfo>          │
│  ├── nodeStyles: Map<typeUri, NodeStyle>               │
│  ├── edgeStyles: Map<relTypeUri, EdgeStyle>            │
│  ├── collapsedFrameTypes: Set<frameTypeUri>            │
│  ├── labelConfig: Map<typeUri, LabelConfig>            │
│  └── overrides: Map<uri, InstanceOverride>             │
└────────────────────────────────────────────────────────┘
```

---

## 3. Layer Responsibilities

### 3.1 DataGraph — Raw KG Data Cache

The DataGraph holds graph objects exactly as they exist in the database.
It is populated by SPARQL queries and API calls and acts as a local cache.

```typescript
interface KGEntityData {
  uri: string;
  name: string;
  typeDescription?: string;
  description?: string;
  properties: Record<string, unknown>;  // all RDF properties
  fetchedAt: Date;
}

interface KGFrameData {
  uri: string;
  frameType: string;            // frame type description / URI
  parentFrameUri?: string;
  slots: string[];              // slot URIs belonging to this frame
  fetchedAt: Date;
}

interface KGSlotData {
  uri: string;
  slotType: string;             // slot type URI (e.g. urn:hasSourceEntity)
  slotTypeDescription?: string;
  value: string;                // entity URI, document URI, or literal
  valueType: 'entity' | 'document' | 'literal';
}

interface KGDocumentData {
  uri: string;
  name: string;
  description?: string;
  properties: Record<string, unknown>;
  fetchedAt: Date;
}

interface EdgeData {
  uri: string;
  edgeType: string;             // e.g. Edge_hasKGRelation, Edge_hasKGSlot
  source: string;               // source URI
  destination: string;          // destination URI
  properties: Record<string, unknown>;
}
```

**Key behaviors:**
- **Deduplication**: Adding an entity that already exists updates it (merge)
- **Expansion tracking**: `fetchedExpansions` records which nodes have been
  fully expanded, preventing redundant queries
- **Staleness**: `lastFetchedAt` allows optional cache invalidation
- **Space-scoped**: Each DataGraph belongs to one space

### 3.2 ViewGraph — Cytoscape Representation

The ViewGraph is a **derived projection** of the DataGraph, computed by
applying VizConfig rules. It contains only what Cytoscape needs to render.

```typescript
interface CyNode {
  id: string;                   // URI
  label: string;                // display name
  nodeType: 'entity' | 'document' | 'frame_hub';
  classes: string[];            // CSS classes for styling
  position?: { x: number; y: number };
  data: {
    entityType?: string;
    frameType?: string;
    expanded?: boolean;
    pinned?: boolean;
  };
}

interface CyEdge {
  id: string;                   // composite key
  source: string;               // source node id
  target: string;               // target node id
  label: string;                // shortened relation type
  classes: string[];            // CSS classes for styling
  data: {
    edgeType: 'collapsed_frame' | 'hub_spoke' | 'relation' | 'document_link';
    frameUri?: string;          // underlying frame (for collapsed edges)
    slotType?: string;          // original slot type URI
  };
}

interface LayoutState {
  algorithm: string;            // 'cose-bilkent' | 'dagre' | 'manual'
  positions: Map<string, { x: number; y: number }>;
  zoom: number;
  pan: { x: number; y: number };
}

interface SelectionState {
  selectedNodes: Set<string>;
  selectedEdges: Set<string>;
  hoveredNode: string | null;
}
```

**Key behaviors:**
- **Recomputable**: ViewGraph can be fully regenerated from DataGraph +
  VizConfig without any network calls
- **Layout preservation**: Node positions persist across recomputation
  (only new nodes get auto-positioned)
- **No raw data**: ViewGraph never stores full property maps — only what's
  needed for rendering and interaction

### 3.3 SessionVizConfig — Visualization Metadata

The SessionVizConfig holds all rendering decisions. It is initialized from
database-stored defaults (the planned `kgtype_frame_arity`, `kgtype_node_style`
etc. tables from `visualization_config_plan.md`) but can be overridden
per-session by the user.

```typescript
interface ArityInfo {
  arity: 'binary' | 'n_ary' | 'unary';
  source: 'prototype' | 'database' | 'user_override' | 'runtime_inferred';
  entitySlotCount: number;      // how many entity-referencing slots
  sourceSlotUri?: string;       // which slot is "source" (binary only)
  destSlotUri?: string;         // which slot is "destination" (binary only)
}

interface NodeStyle {
  color: string;
  shape: 'ellipse' | 'rectangle' | 'diamond' | 'hexagon';
  size: number;
  icon?: string;
  borderColor?: string;
  borderWidth?: number;
}

interface EdgeStyle {
  color: string;
  width: number;
  lineStyle: 'solid' | 'dashed' | 'dotted';
  arrowShape: 'triangle' | 'circle' | 'none';
  curveStyle: 'bezier' | 'straight' | 'taxi';
}

interface LabelConfig {
  primaryProperty: string;      // URI of property to use as label
  secondaryProperty?: string;   // optional subtitle
  tooltipProperties: string[];  // properties shown on hover
  maxLabelLength: number;
}

interface InstanceOverride {
  // Per-instance overrides (e.g. user pins a specific node color)
  nodeStyle?: Partial<NodeStyle>;
  label?: string;
  pinned?: boolean;
  hidden?: boolean;
}
```

**Key behaviors:**
- **Layered defaults**: DB config → prototype-derived arity → runtime
  inference → user override (last wins)
- **Arity classification**: When a frame type is first encountered, check
  `frameArity` map; if missing, query prototypes or count entity-referencing
  slots at runtime, then cache the result
- **Serializable**: The entire VizConfig can be JSON-serialized for
  save/restore of sessions

---

## 4. DataGraph → ViewGraph Transformation

The core transformation logic converts raw graph data into Cytoscape elements
by applying arity classification and style rules:

```typescript
function buildViewGraph(data: DataGraph, config: SessionVizConfig): ViewGraph {
  const cyNodes = new Map<string, CyNode>();
  const cyEdges = new Map<string, CyEdge>();

  // 1. Add all entities as nodes
  for (const [uri, entity] of data.entities) {
    cyNodes.set(uri, {
      id: uri,
      label: entity.name,
      nodeType: 'entity',
      classes: getEntityClasses(entity, config),
      data: { entityType: entity.typeDescription, expanded: data.fetchedExpansions.has(uri) },
    });
  }

  // 2. Add all documents as nodes
  for (const [uri, doc] of data.documents) {
    cyNodes.set(uri, {
      id: uri,
      label: doc.name,
      nodeType: 'document',
      classes: ['document'],
      data: {},
    });
  }

  // 3. Process frames according to arity
  for (const [frameUri, frame] of data.frames) {
    const arity = resolveArity(frame.frameType, frame, data, config);

    if (arity.arity === 'binary') {
      // Collapse frame into a single edge between two entities
      const { sourceEntity, destEntity } = resolveBinaryEndpoints(frame, data, arity);
      if (sourceEntity && destEntity) {
        cyEdges.set(frameUri, {
          id: frameUri,
          source: sourceEntity,
          target: destEntity,
          label: shortenFrameType(frame.frameType),
          classes: ['collapsed-frame'],
          data: { edgeType: 'collapsed_frame', frameUri },
        });
      }
    } else if (arity.arity === 'n_ary') {
      // Show frame as hub node with spokes to entities
      cyNodes.set(frameUri, {
        id: frameUri,
        label: shortenFrameType(frame.frameType),
        nodeType: 'frame_hub',
        classes: ['frame-hub'],
        data: { frameType: frame.frameType },
      });
      // Add spoke edges from hub to each entity/document slot
      for (const slotUri of frame.slots) {
        const slot = data.slots.get(slotUri);
        if (slot && (slot.valueType === 'entity' || slot.valueType === 'document')) {
          const edgeId = `${frameUri}::${slot.value}`;
          cyEdges.set(edgeId, {
            id: edgeId,
            source: frameUri,
            target: slot.value,
            label: shortenSlotType(slot.slotType),
            classes: ['hub-spoke'],
            data: { edgeType: 'hub_spoke', slotType: slot.slotType },
          });
        }
      }
    }
    // 'unary' frames: not rendered (shown only in detail panel)
  }

  // 4. Process direct relation edges (Edge_hasKGRelation)
  for (const [edgeUri, edge] of data.edges) {
    if (edge.edgeType === 'Edge_hasKGRelation') {
      cyEdges.set(edgeUri, {
        id: edgeUri,
        source: edge.source,
        target: edge.destination,
        label: shortenRelationType(edge.properties),
        classes: ['relation'],
        data: { edgeType: 'relation' },
      });
    }
  }

  return { cyNodes, cyEdges, layout: preserveLayout(), selection: emptySelection() };
}
```

### 4.1 Arity Resolution

```typescript
function resolveArity(
  frameTypeUri: string,
  frame: KGFrameData,
  data: DataGraph,
  config: SessionVizConfig,
): ArityInfo {
  // 1. Check user override
  if (config.collapsedFrameTypes.has(frameTypeUri)) {
    return { arity: 'binary', source: 'user_override', entitySlotCount: 2 };
  }

  // 2. Check cached classification
  const cached = config.frameArity.get(frameTypeUri);
  if (cached) return cached;

  // 3. Runtime inference: count entity-referencing slots
  let entitySlotCount = 0;
  for (const slotUri of frame.slots) {
    const slot = data.slots.get(slotUri);
    if (slot && (slot.valueType === 'entity' || slot.valueType === 'document')) {
      entitySlotCount++;
    }
  }

  const arity: ArityInfo = {
    arity: entitySlotCount <= 2 ? 'binary' : 'n_ary',
    source: 'runtime_inferred',
    entitySlotCount,
  };

  // Cache for future use in this session
  config.frameArity.set(frameTypeUri, arity);
  return arity;
}
```

---

## 5. Multi-Session Management

### 5.1 Session Lifecycle

```typescript
interface GraphSessionStore {
  sessions: Map<string, GraphSession>;
  activeSessionId: string | null;

  createSession(name: string, spaceId: string): GraphSession;
  deleteSession(sessionId: string): void;
  duplicateSession(sessionId: string): GraphSession;
  renameSession(sessionId: string, name: string): void;
  switchSession(sessionId: string): void;

  getActiveSession(): GraphSession | null;
  getSessionList(): SessionSummary[];
}

interface SessionSummary {
  id: string;
  name: string;
  spaceId: string;
  nodeCount: number;
  edgeCount: number;
  updatedAt: Date;
}
```

### 5.2 Session Persistence

Sessions can be persisted to allow resumption across page reloads:

| Storage | Scope | Data |
|---------|-------|------|
| **localStorage** | Browser-local | Session list + DataGraph + ViewGraph positions |
| **Backend (future)** | Per-user | Named sessions stored as JSON in a `graph_sessions` table |

For Phase 1, localStorage is sufficient. The serialization format:

```typescript
interface SerializedSession {
  id: string;
  name: string;
  spaceId: string;
  createdAt: string;
  updatedAt: string;
  dataGraph: {
    entities: [string, KGEntityData][];
    frames: [string, KGFrameData][];
    slots: [string, KGSlotData][];
    documents: [string, KGDocumentData][];
    edges: [string, EdgeData][];
    fetchedExpansions: string[];
  };
  layout: {
    positions: [string, { x: number; y: number }][];
    zoom: number;
    pan: { x: number; y: number };
  };
  vizConfig: {
    frameArity: [string, ArityInfo][];
    collapsedFrameTypes: string[];
    overrides: [string, InstanceOverride][];
  };
}
```

### 5.3 Cross-Session Cache Sharing (Optional)

Multiple sessions on the same space can share a read-through cache layer
to avoid redundant fetches:

```
SpaceCache (per spaceId)
├── entities: Map<uri, KGEntityData>   ← shared across sessions
├── frames: Map<uri, KGFrameData>
└── slots: Map<uri, KGSlotData>

Session.dataGraph reads from SpaceCache first, then fetches on miss.
```

This avoids fetching the same entity twice when it appears in multiple
investigation sessions within the same space.

---

## 6. UI Integration

### 6.1 Session Tab Bar

```
┌──────────────────────────────────────────────────────────────┐
│ [+ New] │ Investigation A │ Investigation B* │ WordNet Test │ │
├──────────────────────────────────────────────────────────────┤
│  ... Cytoscape canvas ...                                    │
└──────────────────────────────────────────────────────────────┘
```

- Tabs show session name + dirty indicator (*)
- Right-click tab → Rename / Duplicate / Delete / Export
- `+ New` creates a blank session (prompts for space selection)

### 6.2 Session Panel (alternative to tabs)

For many sessions, a collapsible left panel with search/filter:

```
┌─────────────┬────────────────────────────────────┐
│ Sessions    │                                    │
│ ┌─────────┐ │  Cytoscape canvas                  │
│ │ 🔍 ...  │ │                                    │
│ ├─────────┤ │                                    │
│ │▶ Inv A  │ │                                    │
│ │  5n 8e  │ │                                    │
│ │● Inv B  │ │                                    │
│ │  12n 15e│ │                                    │
│ │▶ Test   │ │                                    │
│ │  3n 2e  │ │                                    │
│ └─────────┘ │                                    │
└─────────────┴────────────────────────────────────┘
```

---

## 7. Relationship to Existing Plans

| Plan | Relationship |
|------|-------------|
| `graph_visualization_plan.md` | Current hook becomes a thin wrapper; DataGraph replaces the flat `GraphState` |
| `visualization_config_plan.md` | DB-stored configs populate `SessionVizConfig` defaults on session creation |
| `prototype_kg_types_plan.md` | Prototype queries feed arity classification (source = 'prototype') |
| `kg_types_plan.md` | KGType metadata (descriptions, relationships) cached in DataGraph for tooltips |

### Migration from Current Implementation

The existing `useGraphVisualization.ts` hook maps to this architecture:

| Current | New |
|---------|-----|
| `GraphState.nodes` | `ViewGraph.cyNodes` (derived) |
| `GraphState.edges` | `ViewGraph.cyEdges` (derived) |
| `searchResults` | Stays as UI state (not persisted) |
| `expandNode()` | Populates `DataGraph`, then rebuilds `ViewGraph` |
| `clearGraph()` | Resets `DataGraph` + `ViewGraph` (or deletes session) |

---

## 8. Implementation Phases

### Phase 1 — DataGraph + ViewGraph Split
- Extract `DataGraph` interface from current flat state
- Implement `buildViewGraph()` transformation (binary collapse only)
- Single session (no multi-session yet)
- Verify existing expand/collapse/search still works

### Phase 2 — Multi-Session
- Add `GraphSessionStore` with create/switch/delete
- Tab bar UI
- localStorage persistence

### Phase 3 — VizConfig Integration
- Load defaults from backend (`kgtype_frame_arity` etc. when implemented)
- Arity resolution with prototype fallback
- Per-session style overrides

### Phase 4 — Shared Cache + Performance
- Space-level cache sharing across sessions
- Cache invalidation on data mutations
- Lazy loading of full properties (fetch on detail panel open)

---

## 9. Related Documents

- `planning_visualization/graph_visualization_plan.md` — Core visualization plan (current implementation)
- `planning_visualization/visualization_config_plan.md` — DB-stored visualization config (not yet implemented)
- `planning_visualization/prototype_kg_types_plan.md` — Prototype model for arity classification
- `planning_visualization/kg_types_plan.md` — KG Types system (implemented)
