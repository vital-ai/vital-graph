# Graph Visualization Plan — Cytoscape.js

## 1. Overview

Add a top-level **Visualization** sidebar menu item that opens an interactive graph exploration screen. The core interaction loop:

1. **Search** for an entity by name/keyword
2. **Add** the entity node to the Cytoscape.js canvas
3. **Expand** (right-click → context menu) to fetch and display neighbors
4. **Collapse** to remove expanded neighbors

**Frames are rendered as their own nodes** in the graph. Each frame node connects to its associated entity nodes via edges labeled with the slot type. This faithfully represents N-ary relationships where a single frame may connect to any number of entities (see §2 for detailed scenarios).

---

## 2. Data Model & Visualization Mapping

### 2.1 KGNode Class Hierarchy

All knowledge graph objects extend **KGNode** (which extends VITAL_Node).
The key subclasses relevant to visualization:

```
KGNode
├── KGEntity              — People, places, things, concepts
│   ├── KGNewsEntity
│   ├── KGProductEntity
│   └── KGWebEntity
├── KGFrame               — Relationship/context groupings (N-ary)
├── KGSlot                — Individual values/facts within a frame
│   ├── KGEntitySlot      — Slot pointing to an entity URI
│   ├── KGTextSlot        — Slot with text value
│   ├── KGDateTimeSlot    — Slot with datetime value
│   ├── KGIntegerSlot     — Slot with integer value
│   ├── KGDoubleSlot      — Slot with double value
│   ├── KGBooleanSlot     — Slot with boolean value
│   ├── KGURISlot         — Slot with URI value
│   ├── KGImageSlot       — Slot with image reference
│   ├── KGChoiceSlot      — Slot with choice selection
│   └── ... (20+ slot subtypes)
├── KGDocument            — Documents (text, HTML, summaries)
├── KGAnnotation          — Annotations on entities/frames
├── KGMedia               — Media objects
│   ├── KGImage
│   ├── KGAudio
│   └── KGVideo
├── KGGraph               — Named graph containers
├── KGStatement           — Assertions/claims
└── ... (60+ total subclasses)
```

### 2.2 Edge Types (Structural Relationships)

Key edge types that define the KG structure:

| Edge Type | From → To | Purpose |
|-----------|-----------|---------|
| `Edge_hasEntityKGFrame` | Entity → Frame | Entity owns a frame |
| `Edge_hasKGFrame` | Frame → Frame | Subframe (parent → child) |
| `Edge_hasKGSlot` | Frame → Slot | Frame contains a slot |
| `Edge_hasKGEntity` | Slot → Entity | Slot references an entity |
| `Edge_hasKGDocument` | Slot/Entity → Document | References a document |
| `Edge_hasKGRelation` | KGNode → KGNode | **Direct relation edge** between any two nodes |

**Edge_hasKGRelation** is particularly important — it connects **any two
KGNodes directly** (not just entities), with properties:
- `kGRelationType` — URI of the relation type
- `kGRelationTypeDescription` — Human-readable relation label

### 2.3 Data Patterns

#### Pattern 1: Entity → Frame → Slots (the core structure)

An entity owns frames, each frame contains slots. Slots hold either data values
or URI references to other entities/documents.

```
KGEntity "John Doe"
 └─[Edge_hasEntityKGFrame]─→ KGFrame "Employment_Frame"
                               ├─[Edge_hasKGSlot]─→ KGEntitySlot (urn:hasEmployer → "ACME Corp")
                               ├─[Edge_hasKGSlot]─→ KGTextSlot (urn:hasPosition → "Engineer")
                               ├─[Edge_hasKGSlot]─→ KGDateTimeSlot (urn:hasStartDate → "2023-01-15")
                               └─[Edge_hasKGSlot]─→ KGEntitySlot (urn:hasLocation → "NYC Office")
```

#### Pattern 2: Frame → Subframes (hierarchical)

Frames can contain child frames via `Edge_hasKGFrame`, with `parentFrameURI`
on the child pointing back to the parent.

```
KGFrame "Purchase_Transaction"
 ├─[Edge_hasKGSlot]─→ KGEntitySlot (urn:hasBuyer → "Alice")
 ├─[Edge_hasKGSlot]─→ KGEntitySlot (urn:hasSeller → "Bob")
 └─[Edge_hasKGFrame]─→ KGFrame "Shipping_Details" (subframe)
                         ├─[Edge_hasKGSlot]─→ KGTextSlot (urn:hasAddress → "123 Main St")
                         └─[Edge_hasKGSlot]─→ KGDateTimeSlot (urn:hasDeliveryDate → "2024-03-01")
```

#### Pattern 3: KG Relation edges (direct node-to-node)

`Edge_hasKGRelation` connects any two KGNodes directly — not mediated by
frames. These are simpler binary relationships.

```
KGEntity "Alice" ──[Edge_hasKGRelation: "knows"]──→ KGEntity "Bob"
KGEntity "Alice" ──[Edge_hasKGRelation: "works_at"]──→ KGEntity "ACME Corp"
KGDocument "Report" ──[Edge_hasKGRelation: "cites"]──→ KGDocument "Paper"
```

#### Pattern 4: WordNet (binary frames)

The WordNet dataset uses frames with exactly two entity slots (source +
destination). This is a specific case of Pattern 1.

```
KGEntity "happy"
 └─[slot]─← KGFrame "Edge_WordnetHyponym" ─[slot]─→ KGEntity "feeling"
```

#### Pattern 5: Slots referencing documents

Slots can point to KGDocuments instead of KGEntities.

```
KGFrame "Research_Frame"
 ├─[Edge_hasKGSlot]─→ KGEntitySlot (urn:hasResearcher → KGEntity "Dr. Smith")
 └─[Edge_hasKGSlot]─→ KGURISlot (urn:hasPublication → KGDocument "Paper.pdf")
```

### 2.4 Visualization Philosophy

**The goal is to show entity-to-entity and entity-to-document relationships.**
Frames, slots, and slot edges are internal KG plumbing — they should NOT be
visible as nodes in the default visualization. Instead:

- **Binary frames** (e.g. WordNet source/dest) are **collapsed into a single
  edge** between the two entities, labeled with the frame type.
- **N-ary frames** (3+ entity/document references) are shown as a **hub node**
  connecting to all referenced entities/documents.
- **KG Relation edges** (`Edge_hasKGRelation`) are rendered directly as edges
  between entities.
- **Entity/URI slots** that reference other entities or KGDocuments create
  visible connections. Data-value slots are hidden (shown only in detail panel).

### 2.5 Frame Type Registry (Binary vs N-ary) via Prototypes

The KG type system includes a **prototype hierarchy** that describes the
structure of each frame type — what slot roles it has, what types those slots
hold, and in what order. This is the registry that determines whether a frame
should be collapsed (binary) or shown as a hub (N-ary).

#### 2.5.1 Prototype Classes

| Class | Extends | Key Properties | Purpose |
|-------|---------|---------------|---------|
| **KGFrameProtoType** | KGNode | `kGFrameType` (URI) | Template for a frame type — defines what slots it has |
| **KGSlotProtoType** | KGNode | `kGSlotType` (URI) | Template for a slot role within a frame |
| **KGEntityProtoType** | KGNode | `kGEntityType` (URI) | Template for an entity type |

#### 2.5.2 Prototype Edges

| Edge | From → To | Properties | Purpose |
|------|-----------|-----------|---------|
| **Edge_hasKGFrameProtoType** | EntityProtoType → FrameProtoType | — | Entity type owns this frame type |
| **Edge_hasKGSlotProtoType** | FrameProtoType → SlotProtoType | `kGSlotRoleSequence` (int), `kGSlotRoleType` (URI) | Frame type has this slot role at this position |

#### 2.5.3 How the Prototype Graph Works

```
KGEntityProtoType "PersonType"
 └─[Edge_hasKGFrameProtoType]─→ KGFrameProtoType "EmploymentFrameType"
                                   ├─[Edge_hasKGSlotProtoType seq=1]─→ KGSlotProtoType "EmployeeSlot"
                                   ├─[Edge_hasKGSlotProtoType seq=2]─→ KGSlotProtoType "EmployerSlot"
                                   ├─[Edge_hasKGSlotProtoType seq=3]─→ KGSlotProtoType "PositionSlot"
                                   └─[Edge_hasKGSlotProtoType seq=4]─→ KGSlotProtoType "StartDateSlot"
```

Each `Edge_hasKGSlotProtoType` carries:
- `kGSlotRoleSequence` — ordering of the slot within the frame
- `kGSlotRoleType` — the role URI (e.g. `urn:hasEmployeeEntity`, `urn:hasPositionText`)

The `KGSlotProtoType.kGSlotType` property points to the corresponding
`KGSlotType` instance, which in turn defines the slot value type (entity
reference, text, date, URI, etc.).

#### 2.5.4 Arity Classification from Prototypes

By querying the prototype graph, the visualization can determine arity:

1. **Query**: For a given `KGFrameType`, find its `KGFrameProtoType`, then
   follow `Edge_hasKGSlotProtoType` edges to get all `KGSlotProtoType`s.
2. **Classify each slot**: Is it an entity-referencing slot (KGEntitySlot,
   KGURISlot pointing to entities/documents) or a data-value slot (KGTextSlot,
   KGDateTimeSlot, etc.)? The `kGSlotRoleType` URI and the slot's value type
   determine this.
3. **Count entity-referencing slots**:

| Count | Classification | Visualization |
|-------|---------------|---------------|
| 2 | `binary` | Collapsed to edge: `entity ──[type]──→ entity` |
| 3+ | `n-ary` | Hub node: `entity ── [frame] ── entity ── ...` |
| 0–1 | `unary` | Badge or small annotation on entity |

4. **Cache** the classification per frame type for the session.

#### 2.5.5 Binary Frame Collapse

When a binary frame type is encountered during expansion:
- The two entity-referencing slot prototypes identify the **source** and
  **destination** roles (by `kGSlotRoleSequence` or by slot role URI convention)
- The frame + its two slots are collapsed into a single directed edge
  `source entity ──[frame type label]──→ destination entity`
- Clicking the edge opens the detail panel showing the frame's data-value
  slots and metadata

Example (WordNet): `Edge_WordnetHyponym` prototype has 2 entity slots
(source + destination) → classified as **binary** → collapsed to
`[happy] ──Hyponym──→ [feeling]`.

#### 2.5.6 Fallback (No Prototype Data)

If no `KGFrameProtoType` is found for a frame type (e.g. imported data without
prototype definitions), fall back to counting actual entity-referencing slots
at query time. Default: treat as binary if exactly 2 entity slots are present.

#### 2.5.7 VitalSigns API for Prototype Queries

The VitalSigns library provides utilities to navigate the class/property
hierarchy:

- **`GraphObject.get_allowed_domain_properties()`** — walks the class
  hierarchy via `ClassUtils.get_class_hierarchy()` and collects all domain
  properties for a class
- **`VitalSignsOntologyManager.get_domain_property_list(clazz)`** — resolves
  domain properties for a class using the ontology property maps
- **`VitalSignsOntologyManager.get_subclass_uri_list(class_uri)`** — SPARQL
  `rdfs:subClassOf*` traversal to find all subclasses of a given class
- **`VitalSignsOntologyManager.build_domain_property_map()`** — builds the
  domain→property and range→property maps from OWL data/object properties

These can be used server-side to resolve prototype structures, or the
visualization can query the stored prototype instances directly via SPARQL.

### 2.6 Visualization Rules

| What's visible | Rendered as | Shape | Color | Label |
|----------------|------------|-------|-------|-------|
| KGEntity | Node | Circle | Blue (#6366f1) | entity name |
| KGDocument | Node | Rectangle | Teal (#14b8a6) | document name |
| Binary frame | Collapsed edge | — | Gray (#9ca3af) | frame type (shortened) |
| N-ary frame | Hub node | Diamond | Gray (#9ca3af) | frame type (shortened) |
| Edge_hasKGRelation | Direct edge | — | Orange (#f97316) | relation type |

**Hidden (internal plumbing):**
- KGSlot nodes — never shown
- Edge_hasKGSlot edges — never shown
- Edge_hasEntityKGFrame edges — never shown
- Slot edge internals — never shown
- Data-value slots — shown only in detail panel when entity/frame selected

### 2.7 Visualization Scenarios

#### Scenario A — Binary frame collapsed to edge (WordNet)

Frame type `Edge_WordnetHyponym` is registered as **binary** (2 entity slots:
source + destination). Collapsed to a single edge:

```
[happy] ──Hyponym──→ [feeling]
```

No frame node visible. Clicking the edge shows frame details in the side panel.

#### Scenario B — N-ary frame as hub node (Employment)

Frame type `Employment` is registered as **n-ary** (3+ entity slots). Shown
as a hub node:

```
[John Doe] ──Employee── [Employment] ──Employer── [ACME Corp]
                              |
                          Location
                              |
                         [NYC Office]
```

Data slots (Position, StartDate) shown in detail panel when frame node is
selected.

#### Scenario C — KG Relation edges (direct)

```
[Alice] ──knows──→ [Bob]
   └──works_at──→ [ACME Corp]
```

`Edge_hasKGRelation` edges rendered directly. No frames involved.

#### Scenario D — Slots referencing documents

An entity slot or URI slot points to a KGDocument:

```
[Dr. Smith] ──Researcher── [Research] ──Publication── [Paper.pdf]
```

If `Research` frame type is binary (researcher + publication), collapsed:

```
[Dr. Smith] ──Research──→ [Paper.pdf]
```

#### Scenario E — Mixed connections

```
[Alice] ──knows──→ [Bob]           (KG Relation, direct edge)
[Alice] ──Manages──→ [Bob]         (binary frame, collapsed edge)
[Alice] ── [Project_X] ── [Bob]    (N-ary frame hub, also connects to [Widget])
                |
             [Widget]
```

### 2.8 Expansion Behavior

When expanding an **entity** node:
1. Query all **KG Relation edges** (`Edge_hasKGRelation`) from/to this entity
   → add target entities as nodes with direct edges
2. Query all **frames** connected to this entity (via entity slots)
3. For each frame, check the **frame type registry**:
   - **Binary**: query the other entity → add entity node + collapsed edge
   - **N-ary**: add frame as hub node, query all entity/document slots →
     add those as nodes with edges to the hub
4. Query entity/URI slots that reference **KGDocuments** → add document nodes

When expanding a **hub (N-ary frame)** node:
1. Query all entity/document slots → add as nodes
2. Query subframes → optionally add as child hubs

**Detail panel** (on entity or frame selection):
- Show all data-value slots (text, dates, numbers)
- Show frame type, description
- Show entity type, description

### Ontology Constants

**Core properties:**

| Property | URI |
|---|---|
| rdf:type | `http://www.w3.org/1999/02/22-rdf-syntax-ns#type` |
| hasName | `http://vital.ai/ontology/vital-core#hasName` |
| hasEdgeSource | `http://vital.ai/ontology/vital-core#hasEdgeSource` |
| hasEdgeDestination | `http://vital.ai/ontology/vital-core#hasEdgeDestination` |

**KGNode classes:**

| Class | URI |
|---|---|
| KGNode | `http://vital.ai/ontology/haley-ai-kg#KGNode` |
| KGEntity | `http://vital.ai/ontology/haley-ai-kg#KGEntity` |
| KGFrame | `http://vital.ai/ontology/haley-ai-kg#KGFrame` |
| KGSlot | `http://vital.ai/ontology/haley-ai-kg#KGSlot` |
| KGDocument | `http://vital.ai/ontology/haley-ai-kg#KGDocument` |

**KGNode properties (visualization-relevant):**

| Property | URI | On |
|---|---|---|
| hasKGEntityTypeDescription | `http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription` | KGEntity |
| hasKGFrameTypeDescription | `http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription` | KGFrame |
| parentFrameURI | `http://vital.ai/ontology/haley-ai-kg#parentFrameURI` | KGFrame |
| hasKGSlotType | `http://vital.ai/ontology/haley-ai-kg#hasKGSlotType` | KGSlot |
| hasKGSlotTypeDescription | `http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeDescription` | KGSlot |
| hasEntitySlotValue | `http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue` | KGSlot |
| hasKGraphDescription | `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription` | KGNode |

**Edge types:**

| Edge | URI | Src → Dst |
|---|---|---|
| Edge_hasEntityKGFrame | `http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame` | Entity → Frame |
| Edge_hasKGFrame | `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame` | Frame → Subframe |
| Edge_hasKGSlot | `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot` | Frame → Slot |
| Edge_hasKGEntity | `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGEntity` | Slot → Entity |
| Edge_hasKGDocument | `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGDocument` | Node → Document |
| Edge_hasKGRelation | `http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation` | Node → Node |

**Edge_hasKGRelation properties:**

| Property | URI |
|---|---|
| hasKGRelationType | `http://vital.ai/ontology/haley-ai-kg#hasKGRelationType` |
| hasKGRelationTypeDescription | `http://vital.ai/ontology/haley-ai-kg#hasKGRelationTypeDescription` |

---

## 3. SPARQL Queries

### 3.1 Entity Search (by name substring, case-insensitive)

Uses `REGEX(?var, "term", "i")` which triggers the v2 filter pushdown into
a `term_text ~* 'term'` semi-join on the term table, leveraging the **GIN trigram
index**. Entity type is fetched on-demand via the detail query (§3.4).

**Avoid `LCASE()`** — wrapping the variable prevents pushdown matching (first arg
must be a plain `ExprVar`), falling through to a full-scan `WHERE LOWER(text) LIKE ...`
(**227× slower**). Also avoid `OPTIONAL` LEFT JOINs in search results (~1.8s overhead).

```sparql
SELECT ?entity ?name WHERE {
    ?entity <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
            <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
    ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
    FILTER(REGEX(?name, "SEARCH_TERM", "i"))
} LIMIT 50
```

**Benchmark**: 16 rows in **~35ms** (WordNet, "happy").

### 3.2 Expand Node — Get Connected Frames and Their Entities

For a given entity, find **all frames** connected to it (via any slot), and for
each frame, find **all entities** connected to that frame (via any slot). This
supports the N-ary frame-as-node visualization model.

**Step 1**: Find frames connected to the target entity and all slots of those frames.

```sparql
SELECT ?frame ?frameType ?slotType ?entity ?entityName WHERE {
    # Find slots that point to our target entity
    ?anchorSlot <http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue> <ENTITY_URI> .
    ?anchorEdge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame .
    ?anchorEdge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?anchorSlot .

    # Frame metadata
    ?frame <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
           <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
    ?frame <http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription> ?frameType .

    # All slots of this frame (including the anchor)
    ?slot <http://vital.ai/ontology/haley-ai-kg#hasKGSlotType> ?slotType .
    ?slot <http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue> ?entity .
    ?slotEdge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame .
    ?slotEdge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?slot .

    ?entity <http://vital.ai/ontology/vital-core#hasName> ?entityName .
}
```

Each result row gives one (frame, slot_type, entity) triple. Client-side
processing groups by frame to build the visualization:

- **Frame node** — one per unique `?frame` URI, labeled with `?frameType`
- **Entity node** — one per unique `?entity` URI, labeled with `?entityName`
- **Edge** — from frame to entity, labeled with shortened `?slotType`

**Benchmark**: ~29 rows in ~73ms for "happy" in WordNet.

### 3.2.1 Slot Type Shortening

Slot URIs like `urn:hasSourceEntity` are shortened for edge labels:
- `urn:hasSourceEntity` → `Source`
- `urn:hasDestinationEntity` → `Destination`
- `urn:hasBuyer` → `Buyer`
- General rule: strip `urn:has` prefix, or take last segment

### 3.3 Expand with Frame Type Filter

Same query as 3.2 with an additional filter on frame type:

```sparql
    FILTER(?frameType = "Edge_WordnetHyponym")
```

### 3.4 Entity Details (tooltip/panel)

```sparql
SELECT ?name ?entityTypeDesc ?description WHERE {
    <ENTITY_URI> <http://vital.ai/ontology/vital-core#hasName> ?name .
    OPTIONAL { <ENTITY_URI> <http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription> ?entityTypeDesc }
    OPTIONAL { <ENTITY_URI> <http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription> ?description }
}
```

---

## 4. Frontend Architecture

### 4.1 New Files

| File | Purpose |
|---|---|
| `frontend/src/pages/Visualization.tsx` | Main page component |
| `frontend/src/components/visualization/CytoscapeGraph.tsx` | Cytoscape.js wrapper |
| `frontend/src/components/visualization/NodeSearchPanel.tsx` | Search panel |
| `frontend/src/components/visualization/GraphContextMenu.tsx` | Right-click context menu |
| `frontend/src/components/visualization/GraphToolbar.tsx` | Layout / filter controls |
| `frontend/src/hooks/useGraphVisualization.ts` | State management hook |
| `frontend/src/types/visualization.ts` | TypeScript types |

### 4.2 Dependencies

```
npm install cytoscape cytoscape-cose-bilkent
npm install --save-dev @types/cytoscape
```

- **cytoscape** — core graph library
- **cytoscape-cose-bilkent** — force-directed layout (better than default cose)

### 4.3 Sidebar Integration

Add to `Layout.tsx` between "Data Management" and "Vector & Geo" groups (or as a new group):

```tsx
import { HiChartBar } from 'react-icons/hi';  // or a graph-specific icon

<SidebarItemGroup>
  <span className="px-3 pt-2 pb-1 text-xs font-semibold uppercase text-gray-500 dark:text-gray-400">
    Visualization
  </span>
  <Link to="/visualization" style={{display: 'block'}}>
    <SidebarItem icon={HiChartBar} active={location.pathname === '/visualization'} as="div">
      Graph Explorer
    </SidebarItem>
  </Link>
</SidebarItemGroup>
```

Add to `App.tsx`:

```tsx
const Visualization = lazy(() => import('./pages/Visualization'));
// In routes:
<Route path="/visualization" element={<Visualization />} />
```

### 4.4 Page Layout

```
┌─────────────────────────────────────────────────────────────┐
│ [Toolbar: Layout | Fit | Clear | Filter by Rel Type]        │
├──────────────┬──────────────────────────────────────────────┤
│ Search Panel │  Cytoscape.js Canvas                         │
│              │                                              │
│ [search box] │  ┌───┐                                      │
│              │  │ A │──edge──┐                              │
│ Results:     │  └───┘        │    ┌───┐                    │
│ • entity1    │               ├───>│ C │                    │
│ • entity2    │  ┌───┐        │    └───┘                    │
│ • entity3    │  │ B │──edge──┘                              │
│              │  └───┘                                       │
│ [+ Add]      │                                              │
│              │  Right-click node → Expand / Collapse / Info  │
├──────────────┴──────────────────────────────────────────────┤
│ [Status bar: nodes=N, edges=M, selected=X]                  │
└─────────────────────────────────────────────────────────────┘
```

- **Search panel** — left sidebar (~280px wide), collapsible
- **Canvas** — fills remaining space
- **Toolbar** — top bar with layout/filter controls
- **Status bar** — bottom, shows graph stats

### 4.5 Context Menu (Right-Click)

On **node** right-click:
- **Expand** — fetch neighbors via SPARQL (§3.2), add to graph
- **Expand by Type...** — submenu with available relationship types
- **Collapse** — remove all nodes added by expanding this node
- **Show Details** — open detail side-panel or tooltip
- **Remove** — remove node and its edges from canvas
- **Center on Node** — fit view to this node

On **edge** right-click:
- **Show Frame Details** — show the underlying KGFrame info
- **Remove Edge** — remove from canvas

On **canvas** right-click:
- **Fit All** — zoom to fit all nodes
- **Clear All** — remove all nodes/edges
- **Re-layout** — re-run layout algorithm

### 4.6 Cytoscape.js Configuration

```typescript
// Node styling
{
  selector: 'node',
  style: {
    'label': 'data(label)',
    'background-color': '#3b82f6',  // blue-500
    'color': '#1f2937',
    'text-valign': 'bottom',
    'text-halign': 'center',
    'font-size': '12px',
    'width': 40,
    'height': 40,
  }
},
// Expanded node (different color)
{
  selector: 'node.expanded',
  style: {
    'background-color': '#10b981',  // emerald-500
    'border-width': 2,
    'border-color': '#059669',
  }
},
// Search-result/seed node
{
  selector: 'node.seed',
  style: {
    'background-color': '#f59e0b',  // amber-500
    'width': 50,
    'height': 50,
  }
},
// Edge styling
{
  selector: 'edge',
  style: {
    'label': 'data(label)',
    'curve-style': 'bezier',
    'target-arrow-shape': 'triangle',
    'font-size': '10px',
    'color': '#6b7280',
    'line-color': '#9ca3af',
    'target-arrow-color': '#9ca3af',
    'width': 2,
  }
}
```

**Layout**: `cose-bilkent` with animated transitions on expand/collapse.

### 4.7 State Model

```typescript
interface GraphState {
  // Canvas data — both entity nodes and frame nodes live here
  nodes: Map<string, CyNode>;       // URI → node data
  edges: Map<string, CyEdge>;       // composite key → edge data

  // Expansion tracking
  expansions: Map<string, string[]>; // node URI → [added node/edge URIs]

  // UI state
  selectedNode: string | null;
  searchResults: SearchResult[];
  searchQuery: string;
  loading: boolean;
  frameTypeFilter: string | null;
}

interface CyNode {
  id: string;           // entity or frame URI
  label: string;        // entity name or frame type (shortened)
  nodeType: 'entity' | 'frame';
  entityType?: string;  // entity type description (entities only)
  frameType?: string;   // full frame type string (frames only)
  expanded?: boolean;   // has been expanded?
}

interface CyEdge {
  id: string;           // composite: `${frameUri}::${entityUri}`
  source: string;       // frame URI
  target: string;       // entity URI
  label: string;        // shortened slot type (e.g. "Source", "Destination")
  slotType: string;     // full slot type URI
}

interface SearchResult {
  uri: string;
  name: string;
}
```

### 4.8 Client-Side Expansion Processing

The SPARQL results (§3.2) return one row per (frame, slot, entity) tuple.
Client-side processing groups them into frame nodes and entity nodes:

```typescript
function processExpandResults(
  rows: Record<string, string>[],
  expandedEntityUri: string
): { nodes: CyNode[], edges: CyEdge[] } {
  const nodes = new Map<string, CyNode>();
  const edges = new Map<string, CyEdge>();

  for (const row of rows) {
    const frameUri = row.frame;
    const frameType = row.frameType || '';
    const slotType = row.slotType || '';
    const entityUri = row.entity;
    const entityName = row.entityName || lastSegment(entityUri);

    // Add frame node (diamond shape, gray)
    if (frameUri && !nodes.has(frameUri)) {
      nodes.set(frameUri, {
        id: frameUri,
        label: shortenFrameType(frameType),
        nodeType: 'frame',
        frameType,
      });
    }

    // Add entity node (circle, blue)
    if (entityUri && !nodes.has(entityUri)) {
      nodes.set(entityUri, {
        id: entityUri,
        label: entityName,
        nodeType: 'entity',
      });
    }

    // Add edge: frame → entity, labeled with slot type
    const edgeId = `${frameUri}::${entityUri}`;
    if (frameUri && entityUri && !edges.has(edgeId)) {
      edges.set(edgeId, {
        id: edgeId,
        source: frameUri,
        target: entityUri,
        label: shortenSlotType(slotType),
        slotType,
      });
    }
  }

  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

function shortenFrameType(frameType: string): string {
  if (frameType.startsWith('Edge_Wordnet')) return frameType.slice('Edge_Wordnet'.length);
  if (frameType.startsWith('Edge_')) return frameType.slice('Edge_'.length);
  return frameType;
}

function shortenSlotType(slotType: string): string {
  // "urn:hasSourceEntity" → "Source"
  if (slotType.startsWith('urn:has')) {
    let name = slotType.slice('urn:has'.length);
    // Remove trailing "Entity" if present: "SourceEntity" → "Source"
    if (name.endsWith('Entity')) name = name.slice(0, -'Entity'.length);
    return name || slotType;
  }
  // Fallback: last segment
  const idx = Math.max(slotType.lastIndexOf('/'), slotType.lastIndexOf('#'));
  return idx >= 0 ? slotType.slice(idx + 1) : slotType;
}
```

---

## 5. Implementation Phases

### Phase 1 — Backend Query Validation (test scripts)
- [ ] Create `test_scripts/visualization/test_viz_queries.py` — validate all SPARQL queries from §3 against WordNet data
- [ ] Verify result shapes and performance
- [ ] Document expected row counts

### Phase 2 — Basic Visualization Page
- [ ] Install `cytoscape` + `cytoscape-cose-bilkent`
- [ ] Create `Visualization.tsx` page with space/graph selector
- [ ] Create `CytoscapeGraph.tsx` wrapper component
- [ ] Add sidebar menu item and route
- [ ] Basic node rendering from hardcoded data

### Phase 3 — Search & Add
- [ ] Create `NodeSearchPanel.tsx` with search input
- [ ] Wire search to SPARQL API (`executeSparqlQuery`)
- [ ] Parse results, display in search panel
- [ ] "Add to graph" button adds node to canvas

### Phase 4 — Expand/Collapse via Context Menu
- [ ] Implement right-click context menu on nodes
- [ ] "Expand" fires neighbor query (§3.2), adds results
- [ ] Track expansion state per node
- [ ] "Collapse" removes previously expanded nodes
- [ ] Animated layout transitions

### Phase 5 — Polish
- [ ] Toolbar: layout selector, fit-all, clear, relationship filter
- [ ] Dark mode support (match existing theme)
- [ ] Node tooltips with entity details
- [ ] Edge labels with frame type
- [ ] Status bar
- [ ] Performance: limit max expansion depth, warn on large expansions

---

## 6. Test Scripts

### 6.1 `test_scripts/visualization/test_viz_queries.py` (created)

Validates all visualization SPARQL queries against the WordNet data.
Uses async `SparqlOrchestrator` (the current interface).

Run with:
```bash
/opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/visualization/test_viz_queries.py
```

```python
#!/usr/bin/env python3
"""
test_viz_queries.py — Validate SPARQL queries for graph visualization.

Tests the queries that the frontend will use:
  1. Entity search by name
  2. Neighbor expansion (both directions)
  3. Neighbor expansion with relation type filter
  4. Entity detail lookup

Requires:
  - Jena sidecar running at localhost:7070
  - PostgreSQL with WordNet data in wordnet_exp_* tables

Usage:
    python test_scripts/visualization/test_viz_queries.py
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

logger = logging.getLogger("test_viz_queries")

SPACE_ID = "wordnet_exp"

# Ontology constants
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_KG_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
HALEY_ENTITY_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription"


def _remap_rows(result) -> list:
    vm = getattr(result, 'var_map', None) or {}
    if not vm or not result.rows:
        return result.rows or []
    remap = {opaque: sparql.lower() for opaque, sparql in vm.items()}
    return [{remap.get(k, k): v for k, v in row.items()} for row in result.rows]


def test_entity_search(orch: SparqlOrchestrator) -> bool:
    """Test 1: Search for entities by name substring."""
    print("\n" + "=" * 70)
    print("Test 1: Entity Search (name contains 'happy')")
    print("=" * 70)

    sparql = f"""
        SELECT ?entity ?name ?entityTypeDesc WHERE {{
            ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
            ?entity <{VITAL_NAME}> ?name .
            OPTIONAL {{ ?entity <{HALEY_ENTITY_TYPE_DESC}> ?entityTypeDesc }}
            FILTER(CONTAINS(LCASE(?name), "happy"))
        }} LIMIT 50
    """

    t0 = time.monotonic()
    result = orch.execute(sparql)
    wall_ms = (time.monotonic() - t0) * 1000

    if not result.ok:
        print(f"  FAIL: {result.error}")
        return False

    rows = _remap_rows(result)
    print(f"  Rows: {len(rows)}, Wall: {wall_ms:.0f}ms")

    if not rows:
        print("  FAIL: No results (expected at least 1 entity named 'happy')")
        return False

    print(f"  Results:")
    for row in rows[:10]:
        print(f"    {row.get('name', '?')} ({row.get('entitytypedesc', 'unknown type')})")
        print(f"      URI: {row.get('entity', '?')}")

    # Capture a URI for subsequent tests
    global SAMPLE_ENTITY_URI, SAMPLE_ENTITY_NAME
    SAMPLE_ENTITY_URI = rows[0].get('entity')
    SAMPLE_ENTITY_NAME = rows[0].get('name', '?')
    print(f"\n  Using entity for expansion tests: {SAMPLE_ENTITY_NAME} ({SAMPLE_ENTITY_URI})")

    print(f"  PASS ({len(rows)} entities found)")
    return True


def test_expand_neighbors(orch: SparqlOrchestrator) -> bool:
    """Test 2: Expand a node to find all neighbors via frames."""
    print("\n" + "=" * 70)
    print(f"Test 2: Expand Neighbors of '{SAMPLE_ENTITY_NAME}'")
    print("=" * 70)

    sparql = f"""
        SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {{
            ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
            ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .

            ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
            ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
            ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
            ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

            ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
            ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
            ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
            ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

            ?srcEntity <{VITAL_NAME}> ?srcName .
            ?dstEntity <{VITAL_NAME}> ?dstName .

            FILTER(?srcEntity = <{SAMPLE_ENTITY_URI}> || ?dstEntity = <{SAMPLE_ENTITY_URI}>)
        }}
    """

    t0 = time.monotonic()
    result = orch.execute(sparql)
    wall_ms = (time.monotonic() - t0) * 1000

    if not result.ok:
        print(f"  FAIL: {result.error}")
        return False

    rows = _remap_rows(result)
    print(f"  Rows: {len(rows)}, Wall: {wall_ms:.0f}ms")

    if not rows:
        print("  FAIL: No neighbors found")
        return False

    # Count unique neighbors and relation types
    neighbors = set()
    rel_types = set()
    for row in rows:
        src = row.get('srcentity')
        dst = row.get('dstentity')
        rel = row.get('relationtype', '')
        if src != SAMPLE_ENTITY_URI:
            neighbors.add(src)
        if dst != SAMPLE_ENTITY_URI:
            neighbors.add(dst)
        rel_types.add(rel)

    print(f"  Unique neighbors: {len(neighbors)}")
    print(f"  Relation types: {sorted(rel_types)}")

    # Show sample relationships
    print(f"\n  Sample relationships:")
    for row in rows[:10]:
        src_name = row.get('srcname', '?')
        dst_name = row.get('dstname', '?')
        rel = row.get('relationtype', '?')
        # Shorten
        if rel.startswith('Edge_Wordnet'):
            rel = rel[len('Edge_Wordnet'):]
        elif rel.startswith('Edge_'):
            rel = rel[len('Edge_'):]
        print(f"    {src_name} --({rel})--> {dst_name}")

    # Save a relation type for filter test
    global SAMPLE_REL_TYPE
    SAMPLE_REL_TYPE = sorted(rel_types)[0] if rel_types else None

    print(f"\n  PASS ({len(neighbors)} neighbors, {len(rel_types)} rel types)")
    return True


def test_expand_filtered(orch: SparqlOrchestrator) -> bool:
    """Test 3: Expand with a specific relationship type filter."""
    print("\n" + "=" * 70)
    print(f"Test 3: Expand with Relation Type Filter ('{SAMPLE_REL_TYPE}')")
    print("=" * 70)

    if not SAMPLE_REL_TYPE:
        print("  SKIP: No relation type available from Test 2")
        return True

    sparql = f"""
        SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {{
            ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
            ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .
            FILTER(?relationType = "{SAMPLE_REL_TYPE}")

            ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
            ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
            ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
            ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

            ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
            ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
            ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
            ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

            ?srcEntity <{VITAL_NAME}> ?srcName .
            ?dstEntity <{VITAL_NAME}> ?dstName .

            FILTER(?srcEntity = <{SAMPLE_ENTITY_URI}> || ?dstEntity = <{SAMPLE_ENTITY_URI}>)
        }}
    """

    t0 = time.monotonic()
    result = orch.execute(sparql)
    wall_ms = (time.monotonic() - t0) * 1000

    if not result.ok:
        print(f"  FAIL: {result.error}")
        return False

    rows = _remap_rows(result)
    print(f"  Rows: {len(rows)}, Wall: {wall_ms:.0f}ms")

    # Verify all rows have the expected relation type
    wrong_types = [r for r in rows if r.get('relationtype') != SAMPLE_REL_TYPE]
    if wrong_types:
        print(f"  FAIL: {len(wrong_types)} rows have wrong relation type")
        return False

    for row in rows[:5]:
        src_name = row.get('srcname', '?')
        dst_name = row.get('dstname', '?')
        print(f"    {src_name} --> {dst_name}")

    print(f"\n  PASS ({len(rows)} rows, all match filter)")
    return True


def test_entity_detail(orch: SparqlOrchestrator) -> bool:
    """Test 4: Get entity detail for tooltip/panel."""
    print("\n" + "=" * 70)
    print(f"Test 4: Entity Detail for '{SAMPLE_ENTITY_NAME}'")
    print("=" * 70)

    sparql = f"""
        SELECT ?name ?entityTypeDesc ?description WHERE {{
            <{SAMPLE_ENTITY_URI}> <{VITAL_NAME}> ?name .
            OPTIONAL {{ <{SAMPLE_ENTITY_URI}> <{HALEY_ENTITY_TYPE_DESC}> ?entityTypeDesc }}
            OPTIONAL {{ <{SAMPLE_ENTITY_URI}> <{HALEY_KG_DESC}> ?description }}
        }}
    """

    t0 = time.monotonic()
    result = orch.execute(sparql)
    wall_ms = (time.monotonic() - t0) * 1000

    if not result.ok:
        print(f"  FAIL: {result.error}")
        return False

    rows = _remap_rows(result)
    print(f"  Rows: {len(rows)}, Wall: {wall_ms:.0f}ms")

    if not rows:
        print("  FAIL: No detail found for entity")
        return False

    row = rows[0]
    print(f"  Name: {row.get('name', '?')}")
    print(f"  Type: {row.get('entitytypedesc', 'unknown')}")
    desc = row.get('description', '')
    if desc:
        print(f"  Description: {desc[:200]}{'...' if len(desc) > 200 else ''}")

    print(f"\n  PASS")
    return True


def test_graph_simplification() -> bool:
    """Test 5: Verify client-side frame simplification logic."""
    print("\n" + "=" * 70)
    print("Test 5: Client-Side Frame Simplification (mock data)")
    print("=" * 70)

    # Simulate SPARQL result rows
    mock_rows = [
        {'srcentity': 'urn:entity:happy', 'srcname': 'happy',
         'dstentity': 'urn:entity:glad', 'dstname': 'glad',
         'frame': 'urn:frame:1', 'relationtype': 'Edge_WordnetSimilar'},
        {'srcentity': 'urn:entity:happy', 'srcname': 'happy',
         'dstentity': 'urn:entity:feeling', 'dstname': 'feeling',
         'frame': 'urn:frame:2', 'relationtype': 'Edge_WordnetHypernym'},
        {'srcentity': 'urn:entity:blissful', 'srcname': 'blissful',
         'dstentity': 'urn:entity:happy', 'dstname': 'happy',
         'frame': 'urn:frame:3', 'relationtype': 'Edge_WordnetSimilar'},
        # Duplicate frame URI should be deduplicated
        {'srcentity': 'urn:entity:happy', 'srcname': 'happy',
         'dstentity': 'urn:entity:glad', 'dstname': 'glad',
         'frame': 'urn:frame:1', 'relationtype': 'Edge_WordnetSimilar'},
    ]

    nodes = {}
    edges = {}
    for row in mock_rows:
        src = row['srcentity']
        dst = row['dstentity']
        frame = row['frame']
        rel = row['relationtype']

        if src not in nodes:
            nodes[src] = {'id': src, 'label': row['srcname']}
        if dst not in nodes:
            nodes[dst] = {'id': dst, 'label': row['dstname']}
        if frame not in edges:
            short_rel = rel
            if short_rel.startswith('Edge_Wordnet'):
                short_rel = short_rel[len('Edge_Wordnet'):]
            elif short_rel.startswith('Edge_'):
                short_rel = short_rel[len('Edge_'):]
            edges[frame] = {'id': frame, 'source': src, 'target': dst, 'label': short_rel}

    print(f"  Input rows: {len(mock_rows)}")
    print(f"  Unique nodes: {len(nodes)} (expected 4)")
    print(f"  Unique edges: {len(edges)} (expected 3, deduped from 4)")

    for nid, n in nodes.items():
        print(f"    Node: {n['label']} ({nid})")
    for eid, e in edges.items():
        print(f"    Edge: {nodes[e['source']]['label']} --({e['label']})--> {nodes[e['target']]['label']}")

    ok = len(nodes) == 4 and len(edges) == 3
    print(f"\n  {'PASS' if ok else 'FAIL'}")
    return ok


# Globals set by test_entity_search
SAMPLE_ENTITY_URI = None
SAMPLE_ENTITY_NAME = None
SAMPLE_REL_TYPE = None


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    print("=" * 70)
    print("Graph Visualization — SPARQL Query Validation")
    print(f"Space: {SPACE_ID}")
    print("=" * 70)

    results = {}

    # Tests 1-4 use the orchestrator (require sidecar + DB)
    with SparqlOrchestrator(space_id=SPACE_ID) as orch:
        results['search'] = test_entity_search(orch)

        if SAMPLE_ENTITY_URI:
            results['expand'] = test_expand_neighbors(orch)
            results['expand_filtered'] = test_expand_filtered(orch)
            results['detail'] = test_entity_detail(orch)
        else:
            print("\n  SKIP: Tests 2-4 require entity URI from Test 1")
            results['expand'] = False
            results['expand_filtered'] = False
            results['detail'] = False

    # Test 5: client-side logic (no DB needed)
    results['simplification'] = test_graph_simplification()

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {status}: {name}")
    print(f"\n  {passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
```

---

## 7. API Usage

The frontend uses the existing SPARQL endpoint in `ApiService.ts`:

```typescript
// Execute visualization queries through existing API
const result = await apiService.executeSparqlQuery(spaceId, sparqlQuery);
// result.results.bindings contains the rows
```

No new backend endpoints are needed for Phase 1. All graph exploration is done via SPARQL queries sent through the existing `/api/graphs/sparql/{space_id}/query` endpoint.

---

## 8. Performance Considerations

- **Expansion limit**: Default max 100 neighbors per expansion (adjustable)
- **Depth limit**: Warn user at depth > 3 (graph grows exponentially)
- **Deduplication**: Nodes/edges already on canvas skip re-adding
- **Layout**: Use `cose-bilkent` with `animate: true` for smooth transitions
- **Batch queries**: Search uses single SPARQL query; expansion uses single query per node
- **WordNet performance**: happy_words.py shows ~45 relationships in ~35ms (very fast)

---

## 9. Future Enhancements (Out of Scope)

- Save/load graph layouts
- Export as image (PNG/SVG)
- Multiple layout algorithms (hierarchical, circular, grid)
- Graph analytics (shortest path, centrality)
- Custom node/edge styling per entity type
- Collaborative real-time graph exploration
- Integration with vector search (find similar entities)
