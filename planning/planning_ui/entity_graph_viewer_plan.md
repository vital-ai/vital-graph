# KG Entity Graph Viewer — UI Plan

## 1. Overview

Display the complete **entity graph** for a single KG Entity as a structured, interactive tree view. An entity graph consists of the entity itself plus all of its frames, slots, and the edges that connect them. The hierarchy can be arbitrarily deep because frames can contain child frames recursively.

The viewer is reached from the **KGEntityDetail** page (or by direct link) and uses the existing `include_entity_graph=true` API parameter.

---

## 2. Data Model Recap

### Object Types

| Object | Type Property | Type Description Property | Key Value Property |
|--------|--------------|--------------------------|-------------------|
| **KGEntity** | `kGEntityType` (URN) | `kGEntityTypeDescription` | `name` |
| **KGFrame** | `kGFrameType` (URN) | `kGFrameTypeDescription` | `name`, `frameSequence` |
| **KGSlot** (many subtypes) | `kGSlotType` (URN) | `kGSlotTypeDescription` | `name`, `<type>SlotValue` |

### Edge Types (structural)

| Edge Class | Connects | Meaning |
|-----------|----------|---------|
| `Edge_hasEntityKGFrame` | Entity → Frame | Top-level frames of the entity |
| `Edge_hasKGFrame` | Frame → Frame | Child frame (recursive nesting) |
| `Edge_hasKGSlot` | Frame → Slot | Slot belonging to a frame |

All edges use `edgeSource` (parent URI) and `edgeDestination` (child URI).

### Grouping URIs

Every object in the entity graph carries a `kGGraphURI` property pointing to the entity URI, and a `frameGraphURI` property pointing to its containing frame. The backend SPARQL for `include_entity_graph=true` finds all objects whose `kGGraphURI` equals the entity URI.

### Hierarchy

```
KGEntity  (kGEntityType = "urn:PersonEntityType")
 ├── Edge_hasEntityKGFrame ──► KGFrame  (kGFrameType = "urn:EmploymentType")
 │    ├── Edge_hasKGSlot ──► KGTextSlot  (kGSlotType = "urn:EmployerNameSlot")
 │    ├── Edge_hasKGSlot ──► KGDateTimeSlot  (kGSlotType = "urn:StartDateSlot")
 │    └── Edge_hasKGFrame ──► KGFrame  (kGFrameType = "urn:PerformanceReviewType")  ← child frame
 │         ├── Edge_hasKGSlot ──► KGTextSlot  (kGSlotType = "urn:ReviewNotesSlot")
 │         └── Edge_hasKGFrame ──► KGFrame  ← grandchild frame (recursive)
 │              └── ...
 └── Edge_hasEntityKGFrame ──► KGFrame  (kGFrameType = "urn:ContactInfoType")
      ├── Edge_hasKGSlot ──► KGTextSlot  (kGSlotType = "urn:EmailSlot")
      └── Edge_hasKGSlot ──► KGTextSlot  (kGSlotType = "urn:PhoneSlot")
```

Because frames nest recursively, the tree can grow arbitrarily wide and deep. The UI must handle this **vertically** since horizontal space is finite.

---

## 3. API Integration

### Endpoint

```
GET /api/graphs/kgentities?space_id={s}&graph_id={g}&uri={entityUri}&include_entity_graph=true
```

### Response

Returns a flat list of quads for **all** objects in the entity graph:
- The entity itself (all its triples)
- All frames (all their triples)
- All slots (all their triples)
- All structural edges (`Edge_hasEntityKGFrame`, `Edge_hasKGFrame`, `Edge_hasKGSlot`)

### ApiService Change

✅ **Done.** `ApiService.getEntityGraph()` delegates to the typed TS client:

```typescript
async getEntityGraph(spaceId: string, graphId: string, entityUri: string): Promise<QuadResponse> {
  return vgClient.kgentities.get(spaceId, graphId, entityUri, true) as any;
}
```

The `true` fourth argument sets `include_entity_graph=true` on the underlying client call.

---

## 4. Typed Graph Object Library

### 4.1 `@vital-ai/vital-model-utils`

The `vital-model-utils-ts` repo provides a TypeScript library for working with VitalSigns objects:

- **Package**: `@vital-ai/vital-model-utils` (v0.1.7)
- **Location**: `/Users/hadfield/Local/vital-git/vital-model-utils-ts/vital-model-utils-ts/`
- **Core classes**: `VitalSignsObject` (base), `VITAL_Node_Base`, `VITAL_Edge_Base`
- **Hydration**: `fromJSON(data)` and `fromMap(map)` on every object — populates typed properties from URI-keyed JSON or Map
- **Serialization**: `toJSON()` and `toMap()` — full round-trip
- **Property definitions**: `getPropertyDefinitions()` returns `{ propertyURI, tsPropertyName, type }[]` — self-describing, introspectable
- **Graph traversal**: `VitalSignsGraphTraverser` with `findConnectedNodes()`, `getEdgesBetween()`, `findByVitalType()`, etc.
- **Graph container**: `VitalSignsGraphInstance` = `{ nodes: Map<URI, Node>, edges: Map<URI, Edge>, objectsByType: Map<vitaltype, Object[]> }`

### 4.2 Generated Domain Classes

The `haley-ai-kg-0.1.0-schema` generated package provides typed classes for every KG type:

| Class | Key TS Properties |
|-------|------------------|
| `KGEntity` | `kGEntityType`, `kGEntityTypeDescription`, `name` |
| `KGFrame` | `kGFrameType`, `kGFrameTypeDescription`, `frameSequence`, `parentFrameURI` |
| `KGSlot` | `kGSlotType`, `kGSlotTypeDescription`, `slotSequence`, `kGSlotValueType` |
| `KGTextSlot` | `textSlotValue` |
| `KGIntegerSlot` | `integerSlotValue` |
| `KGBooleanSlot` | `booleanSlotValue` |
| `KGDateTimeSlot` | `dateTimeSlotValue` |
| `KGCurrencySlot` | `currencySlotValue` |
| `KGDoubleSlot` | `doubleSlotValue` |
| `KGChoiceSlot` | `choiceSlotValue` |
| `KGEntitySlot` | `entitySlotValue` |
| `KGJSONSlot` | `jsonSlotValue` |
| `KGImageSlot` | `imageSlotValue` |
| (20+ more slot subtypes) | ... |
| `Edge_hasEntityKGFrame` | `edgeSource`, `edgeDestination` |
| `Edge_hasKGFrame` | `edgeSource`, `edgeDestination` |
| `Edge_hasKGSlot` | `edgeSource`, `edgeDestination`, `frameGraphURI`, `kGSlotRoleType` |

All edge classes extend `VITAL_Edge_Base` which provides `edgeSource` and `edgeDestination`.

### 4.3 Dependency Setup

✅ **Done.** Both packages are in `frontend/package.json`:
```json
"@vital-ai/vital-kg-model-ts": "^0.1.0",
"@vital-ai/vital-model-utils": "^0.1.7"
```

The `@vital-ai/vital-kg-model-ts` package provides the generated domain classes (KGEntity, KGFrame, all slot subtypes, edge classes) plus type-guard functions (`isKGEntity`, `isKGFrame`, `isKGSlot`, etc.) and `convertGraphObjects()` for JSON → typed object hydration.

---

## 5. Data Pipeline

### Overview

```
Backend quads  →  grouped JSON  →  typed Graph Objects  →  tree structure  →  React components
     (API)         (QuadUtils)     (vital-model-utils)    (edge walking)       (generic UI)
```

### Step 1 — Fetch quads

`ApiService.getEntityGraph()` returns flat `Quad[]` for the entire entity graph.

### Step 2 — Convert quads to JSON-per-subject

Use `groupQuadsBySubject()` from `QuadUtils` to produce a `Map<URI, Map<predicate, values[]>>`. Then convert each subject's predicate map into a JSON dict with full URI keys — the format that `VitalSignsObject.fromJSON()` expects.

### Step 3 — Hydrate into typed graph objects

For each subject JSON dict:
1. Read `vitaltype` to find the correct generated class constructor (from a `TYPE_MAP: Record<vitaltypeURI, Constructor>`)
2. Instantiate and call `instance.fromJSON(jsonDict)`
3. Result: a list of typed `VitalSignsObject` instances — `KGEntity`, `KGFrame`, `KGTextSlot`, `Edge_hasEntityKGFrame`, etc.

All property access is now type-safe: `entity.kGEntityType`, `frame.kGFrameType`, `slot.textSlotValue`, `edge.edgeSource`, etc.

### Step 4 — Build entity graph tree

Using the typed graph objects and `VitalSignsGraphTraverser` (or simple edge walking):

```typescript
interface EntityGraphTree {
  entity: KGEntity;
  frames: FrameNode[];
}

interface FrameNode {
  frame: KGFrame;
  slots: KGSlot[];          // all slot subtypes via instanceof
  childFrames: FrameNode[]; // recursive
}
```

Algorithm:
1. Separate objects into: entity, frames (by URI), slots (by URI), edges (by type).
2. Find `Edge_hasEntityKGFrame` edges where `edgeSource === entity.URI` → top-level frames.
3. For each frame, find `Edge_hasKGSlot` edges → attach slots.
4. For each frame, find `Edge_hasKGFrame` edges → **recursively** build child `FrameNode`s.
5. Sort: frames by `frameSequence` then `name`; slots by `slotSequence` then `name`.

### Step 5 — Extract slot values generically

Because every slot subclass has its value in a typed property, we can use `getPropertyDefinitions()` to introspect:

```typescript
function getSlotDisplayValue(slot: KGSlot): { value: unknown; dataType: string } {
  // Use instanceof checks against generated classes
  if (slot instanceof KGTextSlot)     return { value: slot.textSlotValue, dataType: 'text' };
  if (slot instanceof KGIntegerSlot)  return { value: slot.integerSlotValue, dataType: 'number' };
  if (slot instanceof KGBooleanSlot)  return { value: slot.booleanSlotValue, dataType: 'boolean' };
  if (slot instanceof KGDateTimeSlot) return { value: slot.dateTimeSlotValue, dataType: 'datetime' };
  if (slot instanceof KGCurrencySlot) return { value: slot.currencySlotValue, dataType: 'currency' };
  if (slot instanceof KGDoubleSlot)   return { value: slot.doubleSlotValue, dataType: 'number' };
  if (slot instanceof KGChoiceSlot)   return { value: slot.choiceSlotValue, dataType: 'choice' };
  if (slot instanceof KGEntitySlot)   return { value: slot.entitySlotValue, dataType: 'uri' };
  if (slot instanceof KGJSONSlot)     return { value: slot.jsonSlotValue, dataType: 'json' };
  if (slot instanceof KGImageSlot)    return { value: slot.imageSlotValue, dataType: 'image' };
  // ... etc for all slot subtypes
  
  // Fallback: introspect property definitions for any *SlotValue property
  for (const propDef of slot.getAllPropertyDefinitions()) {
    if (propDef.tsPropertyName.endsWith('SlotValue') || propDef.tsPropertyName.endsWith('SlotValues')) {
      const val = (slot as any)[propDef.tsPropertyName];
      if (val !== undefined) return { value: val, dataType: propDef.type };
    }
  }
  return { value: undefined, dataType: 'unknown' };
}
```

The fallback introspection via `getAllPropertyDefinitions()` ensures we handle new slot types without code changes.

---

## 6. UI Design

### 6.1 Layout: Collapsible Vertical Sections

Each top-level frame is a **collapsible card section**. Child frames nest **vertically inside** with an indented left border. This is the only way to handle arbitrary recursive depth on a finite screen.

```
┌─────────────────────────────────────────────────────────────────┐
│  Entity Header                                                   │
│  Name: John Doe                                                  │
│  Type: urn:PersonEntityType  •  12 frames  •  47 slots          │
│  URI: http://vital.ai/...  [copy]      [Expand All] [Collapse All]│
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ▼  Employment  [urn:EmploymentType]        3/5 complete  │    │
│  ├──────────────────────────────────────────────────────────┤    │
│  │  Employer Name   [urn:EmployerNameSlot]   "Acme Corp"    │    │
│  │  Start Date      [urn:StartDateSlot]      2020-01-15     │    │
│  │  Position        [urn:PositionSlot]       "Engineer"     │    │
│  │                                                          │    │
│  │  ┃ ▼ Performance Review  [urn:ReviewType]                │    │
│  │  ┃   Review Notes  [urn:NotesSlot]       "Good"          │    │
│  │  ┃   Rating        [urn:RatingSlot]      4               │    │
│  │  ┃                                                       │    │
│  │  ┃   ┃ ▼ Sub-Review  [urn:SubReviewType]                │    │
│  │  ┃   ┃   Detail    [urn:DetailSlot]      "..."           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ▼  Contact Info  [urn:ContactInfoType]     2/2 complete  │    │
│  ├──────────────────────────────────────────────────────────┤    │
│  │  Email  [urn:EmailSlot]   "john@example.com"             │    │
│  │  Phone  [urn:PhoneSlot]   "+1-555-0100"                  │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

Layout rules:
- **Top-level frames** = white card with border, collapsible header
- **Child frames** = nested inside parent card with `border-l-2 border-blue-300 pl-3`
- **Slots** = 2-column grid of label + value rows
- **Depth** grows vertically; left-borders stack to indicate nesting

### 6.2 Visual Elements

| Element | Icon | Color | Badge |
|---------|------|-------|-------|
| Entity (root) | `HiUser` | green | Entity type URN |
| Frame (section) | `HiViewBoards` | blue | Frame type URN |
| Slot (field row) | — | gray label + value | Slot type as label |
| Expand/Collapse | chevron `▶`/`▼` | gray | — |
| Child frame nesting | — | `border-l-2 border-blue-300` | — |

### 6.3 Frame Section Header

1. **Expand/collapse chevron** — rotates 90° when expanded
2. **Frame name** — `frame.name` or humanized `kGFrameType` (strip `Frame` suffix, split CamelCase)
3. **Frame type badge** — shortened URN
4. **Slot completion** — `X of Y slots have values`
5. **Instance badge** — if multiple sibling frames share the same `kGFrameType`, show `#1`, `#2`, etc.

### 6.4 Slot Field Row

All slots rendered uniformly (this is a **generic** viewer for arbitrary entities):
1. **Label** — `slot.name` or humanized `kGSlotType`
2. **Type badge** — small muted slot type URN
3. **Value** — type-aware rendering (see §8)
4. **VitalSigns class** — tiny muted label: `KGTextSlot`, `KGIntegerSlot`, etc.

### 6.5 Interactions

- **Click section header** → expand/collapse frame section
- **Expand All / Collapse All** — toolbar buttons in entity header
- **Click slot value URI** → navigate to linked entity (if `KGEntitySlot`)
- **Copy URI** — hover button on entity and frame headers
- **Default expansion**: expand all for shallow graphs (≤3 top-level frames); auto-collapse depth > 2 for deep graphs

### 6.6 Entity Header Card

| Field | Source |
|-------|--------|
| Entity Name | `entity.name` |
| Entity URI | `entity.URI` (with copy button) |
| Entity Type | `entity.kGEntityType` + `entity.kGEntityTypeDescription` |
| Frame Count | recursive frame count |
| Slot Count | recursive slot count |
| Graph URI | `entity.kGGraphURI` |

### 6.7 Responsive Behavior

- Single-column vertical layout — no horizontal scrolling needed
- On narrow screens, truncate long URNs and values with ellipsis + tooltip
- Left-border stacking caps visually at ~6 levels

---

## 7. Component Architecture

```
ApiService.getEntityGraph()          ← fetch quads
    ↓
quadsToGraphObjects()                ← hydrate into typed VitalSigns objects
    ↓
buildEntityGraphTree()               ← edge-walk into EntityGraphTree
    ↓
EntityGraphViewer.tsx                ← page shell: header, toolbar, loading/error
    ↓
FrameSection.tsx                     ← collapsible card per frame (recursive)
    ↓
SlotFieldRow.tsx                     ← single slot: label + typed value
```

### New Files (all ✅ Done)

| File | Purpose | Status |
|------|---------|--------|
| `lib/entityGraphBuilder.ts` | `hydrateQuads()` — convert quads to typed graph objects via `convertGraphObjects()`. `buildEntityGraphTree()` — walk edges to build `EntityGraphTree`. Slot value extraction via `SlotEntry`. | ✅ Done |
| `components/entity-graph/EntityGraphViewer.tsx` | Inline component: fetch, hydrate, build tree, render. Loading/error/empty states. Expand All / Collapse All. | ✅ Done |
| `components/entity-graph/FrameSection.tsx` | Collapsible card for a frame. Renders slots + recursively renders child `FrameSection`s. | ✅ Done |
| `components/entity-graph/SlotFieldRow.tsx` | Single slot field: label, type badge, typed value display. | ✅ Done |
| `components/entity-graph/EntityGraphHeader.tsx` | Entity summary header card with frame/slot counts, expand/collapse buttons. | ✅ Done |

### Reused

- `@vital-ai/vital-model-utils` + generated domain classes — typed graph objects
- `QuadUtils` — `groupQuadsBySubject`, `shortenUri`
- Flowbite `Badge`, `Spinner`, `Alert`

---

## 8. Navigation & Routing

### Option A: Inline Tab on KGEntityDetail

Add an **"Entity Graph"** tab to the existing `KGEntityDetail.tsx` page. When active, fetches the entity graph and renders the frame/slot tree.

Pros: No new route, integrated, discoverable.
Cons: KGEntityDetail gets heavier.

### Option B: Separate Route

New route: `/space/:spaceId/graph/:graphId/kgentities/:entityUri/graph`

Pros: Clean separation, shareable URL.
Cons: Extra route, less discoverable.

**Recommendation**: **Option A** — inline tab. The entity detail page gets a tab bar: "Properties" (existing) | "Entity Graph" (new). This keeps the entity as the focal point.

### Sidebar

No new sidebar entry — accessed via entity detail page tab.

---

## 9. Slot Value Rendering

Slots carry typed values. The renderer should display them appropriately:

| Slot VitalType | Value Property | Display |
|---------------|---------------|---------|
| `KGTextSlot` | `textSlotValue` | Plain text (truncated) |
| `KGLongTextSlot` | `longTextSlotValue` | Plain text (truncated, expandable) |
| `KGIntegerSlot` | `integerSlotValue` | Number |
| `KGDoubleSlot` / `KGCurrencySlot` | `doubleSlotValue` / `currencySlotValue` | Number (formatted) |
| `KGBooleanSlot` | `booleanSlotValue` | ✅ / ❌ icon |
| `KGDateTimeSlot` | `dateTimeSlotValue` | Formatted date/time |
| `KGChoiceSlot` | `choiceSlotValue` | Badge |
| `KGMultiChoiceSlot` | `multiChoiceSlotValues` | Multiple badges |
| `KGEntitySlot` | `entitySlotValue` | Clickable URI link |
| `KGImageSlot` | `imageSlotValue` | Thumbnail or URI |
| `KGJSONSlot` | `jsonSlotValue` | Code block (collapsible) |
| Other URI-valued slots | Various | URI link |

---

## 10. Performance Considerations

- **Entity graph cache**: The backend already caches entity graphs per entity URI. First fetch may be slower; subsequent fetches are fast.
- **Large entity graphs**: Some entities may have 50+ frames with hundreds of slots. The tree should:
  - Auto-collapse frames beyond depth 2 by default
  - Virtualize the list if >500 visible nodes (e.g. `react-window`)
  - Show a count summary: "42 frames, 187 slots"
- **Hydration**: `quadsToGraphObjects()` + `buildEntityGraphTree()` should be wrapped in `useMemo` to avoid re-computation on every render.
- **Typed objects**: Using `@vital-ai/vital-model-utils` with `instanceof` checks is fast — no string comparisons needed for slot type dispatch.

---

## 11. Implementation Steps

### Step 1: Dependency Setup ✅ Done
- ✅ Added `@vital-ai/vital-model-utils` and `@vital-ai/vital-kg-model-ts` to `frontend/package.json`
- ✅ Domain classes provided via published `@vital-ai/vital-kg-model-ts` npm package (not copied into src/lib/)
- ✅ Imports verified with Vite bundler

### Step 2: Entity Graph Builder (`lib/entityGraphBuilder.ts`) ✅ Done
- ✅ `hydrateQuads(quads)` — groups quads by subject, constructs JSON dicts, hydrates via `convertGraphObjects()` from `@vital-ai/vital-kg-model-ts`
- ✅ `buildEntityGraphTree(objects)` — separates entity/frames/slots/edges, walks edges recursively to build `FrameNode[]`
- ✅ `SlotEntry` type with extracted display value
- ✅ Uses type-guard functions (`isKGEntity`, `isKGFrame`, `isKGSlot`, `isEdgeHasEntityKGFrame`, `isEdgeHasKGSlot`) and `lookup_child_frames()` from the model library

### Step 3: ApiService Method ✅ Done
- ✅ `getEntityGraph(spaceId, graphId, entityUri)` delegates to `vgClient.kgentities.get(spaceId, graphId, entityUri, true)`
- ✅ The `true` fourth argument sets `include_entity_graph=true`

### Step 4: SlotFieldRow Component (`components/entity-graph/SlotFieldRow.tsx`) ✅ Done
- ✅ Single slot: label + type badge + typed value display
- ✅ Type-aware formatting (text, number, currency, boolean icon, datetime, URI link, JSON code block)
- ✅ Generic — works for any slot subclass

### Step 5: FrameSection Component (`components/entity-graph/FrameSection.tsx`) ✅ Done
- ✅ Collapsible card with section header (chevron, name, type badge, slot completion count)
- ✅ Grid of `SlotFieldRow` for slots
- ✅ Recursive `<FrameSection>` for child frames with indented left border
- ✅ Instance badges for repeatable sibling frames of same `kGFrameType`

### Step 6: EntityGraphHeader (`components/entity-graph/EntityGraphHeader.tsx`) ✅ Done
- ✅ Entity name, type badge, URI with copy, frame/slot counts
- ✅ Expand All / Collapse All buttons

### Step 7: EntityGraphViewer (`components/entity-graph/EntityGraphViewer.tsx`) ✅ Done
- ✅ Inline component on KGEntityDetail page (not a separate page/tab — rendered directly below properties)
- ✅ Fetch → `hydrateQuads()` → `buildEntityGraphTree()` → render
- ✅ Loading spinner, error alert with retry button, empty state
- ✅ Expand All / Collapse All via key-based re-render

### Step 8: Navigation Integration ✅ Done
- ✅ `EntityGraphViewer` embedded directly in `KGEntityDetail.tsx` below the properties section
- ✅ Rendered automatically when entity is loaded (no separate tab needed)
- ✅ Also shows `EntityGeoMiniMap` below the graph viewer

### Step 9: Polish ✅ Done
- ✅ Default expansion for all frames on initial load; collapse all via button
- ✅ Empty state for entities with no frames
- ✅ Loading spinner with descriptive text
- ✅ Error handling with retry button

---

## 12. Open Questions — Resolved

1. ~~**Read-only vs editable**~~ **Decision: Read-only.** The viewer is read-only. Editing can be added later with `onChange` callbacks on `SlotFieldRow`.
2. ~~**Edge objects in UI**~~ **Decision: Not displayed.** Edges are structural metadata used only to build the tree — not displayed in the UI.
3. ~~**Tab vs separate route**~~ **Decision: Inline section.** The `EntityGraphViewer` is rendered directly below the properties section on `KGEntityDetail.tsx` — no separate tab or route needed. It's always visible when the entity is loaded.
4. ~~**Slot ordering**~~ **Decision: `slotSequence` → `name` fallback.** All ordering is dynamic/discovered from the graph data since this is a generic viewer.
5. ~~**Search within graph**~~ **Decision: Deferred.** Not implemented in initial version. Can be added later for large entity graphs.
6. ~~**Domain classes packaging**~~ **Decision: Published npm package.** The generated domain classes are published as `@vital-ai/vital-kg-model-ts` (^0.1.0) — a separate npm package, not bundled into `src/lib/`.

---

## 13. Implementation Status — COMPLETE ✓

All planned components have been implemented and integrated.

| # | Component | File | Status |
|---|-----------|------|--------|
| 1 | Entity graph builder | `frontend/src/lib/entityGraphBuilder.ts` | ✅ Done |
| 2 | Entity graph viewer | `frontend/src/components/entity-graph/EntityGraphViewer.tsx` | ✅ Done |
| 3 | Frame section | `frontend/src/components/entity-graph/FrameSection.tsx` | ✅ Done |
| 4 | Slot field row | `frontend/src/components/entity-graph/SlotFieldRow.tsx` | ✅ Done |
| 5 | Entity graph header | `frontend/src/components/entity-graph/EntityGraphHeader.tsx` | ✅ Done |
| 6 | KGEntityDetail integration | `frontend/src/pages/KGEntityDetail.tsx` | ✅ Done |
| 7 | ApiService method | `frontend/src/services/ApiService.ts` (`getEntityGraph`) | ✅ Done |
| 8 | Dependencies | `@vital-ai/vital-kg-model-ts` + `@vital-ai/vital-model-utils` | ✅ Done |

### Architecture as Implemented

```
vgClient.kgentities.get(…, true)    ← fetch quads via TS client
    ↓
hydrateQuads()                       ← group by subject → convertGraphObjects()
    ↓
buildEntityGraphTree()               ← edge-walk into EntityGraphTree
    ↓
EntityGraphViewer.tsx                ← inline on KGEntityDetail: header, toolbar, loading/error
    ↓
FrameSection.tsx                     ← collapsible card per frame (recursive)
    ↓
SlotFieldRow.tsx                     ← single slot: label + typed value
```

### Key Differences from Original Plan

| Aspect | Planned | Implemented |
|--------|---------|-------------|
| **Integration** | Tab on KGEntityDetail | Inline section below properties (always visible) |
| **Hydration** | `quadsToGraphObjects()` + `TYPE_MAP` + `fromJSON()` | `hydrateQuads()` → `convertGraphObjects()` from `@vital-ai/vital-kg-model-ts` |
| **ApiService** | Raw `fetch` with URLSearchParams | Delegates to `vgClient.kgentities.get(…, true)` via typed TS client |
| **Domain classes** | Copy into `src/lib/` or link | Published npm package `@vital-ai/vital-kg-model-ts` |
| **Type dispatch** | `instanceof` switch + `getAllPropertyDefinitions()` fallback | Type-guard functions from model library (`isKGEntity`, `isKGFrame`, etc.) |
