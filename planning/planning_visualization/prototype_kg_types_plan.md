# KG Prototypes — Data Model & Editor Plan

## 1. Overview

**Prerequisite:** This plan builds on `planning_visualization/kg_types_plan.md`,
which covers the KG type classes, type-level edges, tabbed UI, search, and
documentation features. Implement the KG Types plan first.

The KG type system includes **prototype objects** (`KGFrameProtoType`,
`KGSlotProtoType`, `KGEntityProtoType`) that describe the *structure* of each
frame type — what slot roles it has, what types those slots hold, and in what
order. Prototypes reference KG Type instances (defined in the KG Types plan)
for their semantic meaning; the prototype layer is purely structural.

This plan covers:
1. **Prototype data model** — classes, edges, and properties
2. **Prototype editor UI** — screens added to the KG Types detail views
3. **Backend endpoints** specific to prototype CRUD
4. **Prototype search** — finding prototypes via type description search

---

## 2. Prototype Data Model

### 2.1 Prototype Classes

| Class | URI | Purpose |
|-------|-----|---------|
| `KGFrameProtoType` | `haley-ai-kg#KGFrameProtoType` | Template for a frame type — defines slot composition |
| `KGSlotProtoType` | `haley-ai-kg#KGSlotProtoType` | Template for a slot role within a frame |
| `KGEntityProtoType` | `haley-ai-kg#KGEntityProtoType` | Template for an entity type — defines which frame types it owns |

### 2.2 Prototype Edges

| Edge | From → To | Properties |
|------|-----------|-----------|
| `Edge_hasKGFrameProtoType` | EntityProtoType → FrameProtoType | `kGEntityTypeExternIdentifier` |
| `Edge_hasKGSlotProtoType` | FrameProtoType → SlotProtoType | `kGSlotRoleSequence` (int), `kGSlotRoleType` (URI), `kGSlotTypeExternIdentifier` |
| `Edge_hasKGSlotType` | SlotProtoType → KGSlotType | `kGSlotRoleType` (URI), `kGSlotTypeExternIdentifier` |

### 2.3 Relationship: KG Types vs Prototypes

The **KG Type classes** (`KGFrameType`, `KGSlotType`, `KGEntityType`,
`KGRelationType`) are the authoritative semantic definitions (see
`kg_types_plan.md` §2). Each type instance carries the concept's name,
description, and identity — it defines *what something is*.

**Prototypes do not redefine or re-specify the semantic concept.** They
*reference* existing KG Type instances to describe grouping and structure:

- A `KGFrameProtoType` references a `KGFrameType` via `hasKGFrameType` — it
  says "this frame type is composed of these slots in this order"
- A `KGSlotProtoType` references a `KGSlotType` via `hasKGSlotType` — it
  says "this slot position uses this slot type definition"
- A `KGEntityProtoType` references a `KGEntityType` — it says "this entity
  type participates in these frame types"

The prototype layer is purely structural (composition, ordering, role
assignment). All semantic meaning — names, descriptions, labels — lives on the
KG Type instances themselves and is not duplicated into the prototype objects.

### 2.4 Prototype Graph Structure

A complete prototype graph for an entity type looks like:

```
KGEntityProtoType ("Person")
  ├── Edge_hasKGFrameProtoType → KGFrameProtoType ("Employment")
  │     ├── Edge_hasKGSlotProtoType [seq=1, role=Core] → KGSlotProtoType
  │     │     └── Edge_hasKGSlotType → KGSlotType "Employee"
  │     └── Edge_hasKGSlotProtoType [seq=2, role=Core] → KGSlotProtoType
  │           └── Edge_hasKGSlotType → KGSlotType "Employer"
  ├── Edge_hasKGFrameProtoType → KGFrameProtoType ("Education")
  │     ├── Edge_hasKGSlotProtoType [seq=1, role=Core] → KGSlotProtoType
  │     │     └── Edge_hasKGSlotType → KGSlotType "Student"
  │     ├── Edge_hasKGSlotProtoType [seq=2, role=Core] → KGSlotProtoType
  │     │     └── Edge_hasKGSlotType → KGSlotType "School"
  │     └── Edge_hasKGSlotProtoType [seq=3, role=Non-Core] → KGSlotProtoType
  │           └── Edge_hasKGSlotType → KGSlotType "Degree"
  └── Edge_hasKGFrameProtoType → KGFrameProtoType ("Address")
        └── Edge_hasKGSlotProtoType [seq=1, role=Core] → KGSlotProtoType
              └── Edge_hasKGSlotType → KGSlotType "Location"
```

Each `Edge_hasKGSlotProtoType` carries:
- **`kGSlotRoleSequence`** (int) — ordering within the frame
- **`kGSlotRoleType`** (URI) — the semantic role of this slot (core vs non-core)
- **`kGSlotTypeExternIdentifier`** (string) — external identifier

Each `Edge_hasKGSlotType` links the slot prototype to its `KGSlotType`
definition, which carries the slot's name, description, and label.

### 2.5 Slot Type Reusability and Core/Non-Core Roles

**Slot types are reusable across frame prototypes.** A `KGSlotType` like
"Place" or "Time" is defined once and referenced by `KGSlotProtoType`
instances in many different frame prototypes. The prototype binds a slot
type into a specific frame structure with a sequence position and role —
the slot type itself is shared.

**Core vs non-core roles:** The `kGSlotRoleType` on `Edge_hasKGSlotProtoType`
distinguishes between:
- **Core slots** — essential to the frame's meaning (e.g. Buyer, Seller,
  Goods in Commerce_buy). These roles must be filled for the frame to be
  semantically complete.
- **Non-core slots** — optional modifiers (e.g. Place, Time, Manner).
  These provide additional context but are not required.

This distinction is important for the prototype editor (core slots are
prominent, non-core are secondary) and for instance validation (core slots
should be encouraged during extraction).

### 2.6 Instance Layer (downstream consumer)

The prototype layer defines structural templates that the **instance layer**
consumes. When data is extracted from text or other sources:
- A `KGFrame` instance is created, referencing a `KGFrameType`
- `KGSlot` instances (typed subclasses like `KGEntitySlot`, `KGTextSlot`,
  `KGCurrencySlot`, `KGDateTimeSlot`, etc.) are created as children via
  `Edge_hasKGSlot`, each referencing a `KGSlotType`
- `KGEntity` instances are linked to frames via `Edge_hasEntityKGFrame`

Not all slots defined in the prototype are necessarily filled in every
instance — the prototype defines the full template; instances are partial
fills based on what was extracted. There are 23 typed `KGSlot` subclasses
covering entity references, text, currency, datetime, integer, boolean,
geolocation, URI, and more.

### 2.7 `hasKGJSON` Property

All prototype classes inherit from `KGNode`, which provides the property
`hasKGJSON` (string) — a serialized JSON map for additional metadata.

The underlying data (e.g. arity classification) may be stored in dedicated
database tables for efficient querying. When prototype objects are retrieved
for the frontend, the server can populate `hasKGJSON` on each object with
relevant computed/table-stored data before returning it. This way the frontend
receives enriched graph objects in standard quad format without needing
separate API calls — the delivery mechanism is the existing property on the
graph object, even though the source of truth may be a table.

---

## 3. UI Plan — Prototype Screens

Prototypes have their own **top-level sidebar menu item** ("Prototypes") and
dedicated screens, separate from the KG Types pages. The two areas cross-link
to each other: a KG Type detail can link to its prototype, and a prototype
detail links back to its referenced KG Types.

### 3.1 Top-Level Navigation

Add a **Prototypes** entry to the sidebar navigation (e.g. with a
`HiTemplate` or `HiCubeTransparent` icon), alongside the existing KG Types
entry. This gives prototypes equal visibility in the UI.

### 3.2 Prototypes List Page

The prototypes list page shows all prototype objects in the current graph,
organized by tabs:

| Tab | Content |
|-----|---------|
| **Frame Prototypes** | All `KGFrameProtoType` instances, with arity badge, slot count, linked frame type name |
| **Entity Prototypes** | All `KGEntityProtoType` instances, with linked entity type name, frame prototype count |

Each row in the Frame Prototypes tab shows:

| Column | Content |
|--------|---------|
| Frame Type | Linked `KGFrameType` name (clickable → KG Types detail) |
| Arity | Badge: `Binary` (green), `N-ary` (blue), `Unary` (gray), `Unknown` (yellow) |
| Slots | Count of slot prototypes (e.g. "4 slots") |
| Entity Slots | Count of entity-referencing slots |
| Actions | View, Edit, Delete |

Each row in the Entity Prototypes tab shows:

| Column | Content |
|--------|---------|
| Entity Type | Linked `KGEntityType` name (clickable → KG Types detail) |
| Frame Prototypes | Count of associated frame prototypes |
| Actions | View, Edit, Delete |

### 3.3 Prototype Search

Prototype search queries KG Type information (names, descriptions) but
surfaces the related prototype objects. Internally this uses SPARQL queries
that leverage the vector and full-text search constructs (see
`kg_types_plan.md` §3.3) — e.g. finding `KGFrameType` instances by
description similarity, then following `hasKGFrameType` links to return the
associated `KGFrameProtoType` and its slot prototypes.

This allows users to find prototypes by the semantic meaning of the types
they reference, without requiring prototypes themselves to carry searchable
text.

### 3.4 Frame Prototype Detail — Slot Editor

The frame prototype detail page is a dedicated screen showing the full
prototype structure with slot editing:

```
┌─────────────────────────────────────────────────────┐
│ Frame Prototype: Employment                         │
│ Frame Type: Employment → (link to KG Types detail)  │
│ Arity: [Binary ▾]  (auto-computed / manual)         │
│                                                     │
│ ── Slot Prototypes ──────────────────────────────── │
│ #  Slot Type            Role Type        Value Type  │
│ 1  EmployeeSlot         hasEmployee      Entity      │
│ 2  EmployerSlot         hasEmployer      Entity      │
│ 3  PositionSlot         hasPosition      Text        │
│ 4  StartDateSlot        hasStartDate     DateTime    │
│                                                     │
│ [+ Add Slot]                        [Auto-classify] │
└─────────────────────────────────────────────────────┘
```

- **Frame Type link** — clickable link to the KG Types detail page for the
  referenced `KGFrameType`
- **Arity dropdown** — shows current classification, allows manual override
- **Auto-classify button** — re-computes arity from slot prototypes
- **Slot list** — ordered by `kGSlotRoleSequence`, shows role type and value type
- **Slot Type links** — each slot type name is clickable → KG Types detail
- **Add/remove/reorder** — CRUD for `KGSlotProtoType` + `Edge_hasKGSlotProtoType`
- **For binary frames** — highlights which slot is source vs destination

### 3.5 Entity Prototype Detail — Frame Associations

The entity prototype detail page shows which frame prototypes are associated:

```
┌─────────────────────────────────────────────────────┐
│ Entity Prototype: Person                            │
│ Entity Type: Person → (link to KG Types detail)     │
│                                                     │
│ ── Frame Prototypes ─────────────────────────────── │
│ Frame Type          Arity     Slots                  │
│ Employment          Binary    Employee, Employer      │
│ Education           N-ary     Student, School, Degree │
│ Address             Unary     Location                │
│                                                     │
│ [+ Associate Frame Prototype]                        │
└─────────────────────────────────────────────────────┘
```

- **Entity Type link** — clickable link to the KG Types detail page
- **Frame Prototype rows** — clickable → Frame Prototype detail (§3.4)
- **Associate** — creates `Edge_hasKGFrameProtoType` linking entity prototype
  to an existing frame prototype

### 3.6 Cross-Links with KG Types

The KG Types detail views (from `kg_types_plan.md`) include links into the
Prototypes screens:

- **Frame Type detail** — shows a "View Prototype" link/button if a
  `KGFrameProtoType` exists for this frame type (navigates to §3.4)
- **Entity Type detail** — shows a "View Entity Prototype" link/button if a
  `KGEntityProtoType` exists (navigates to §3.5)
- **Slot Type detail** — shows a "Used in Prototypes" section listing which
  frame prototypes reference this slot type (each row links to §3.4)

Conversely, prototype detail pages link back to KG Type detail pages for
the referenced types (frame type, entity type, slot types).

---

## 4. Routes

| Route | Component | Purpose |
|-------|-----------|---------|
| `/prototypes?space_id=...&graph_id=...` | PrototypesList | Top-level prototypes list (tabbed: frame, entity) |
| `/prototypes/frame?space_id=...&graph_id=...&id=...` | FramePrototypeDetail | Frame prototype detail with slot editor |
| `/prototypes/entity?space_id=...&graph_id=...&id=...` | EntityPrototypeDetail | Entity prototype detail with frame associations |

KG Types routes are defined in `kg_types_plan.md` §4. Cross-links between
the two route hierarchies use standard navigation (e.g. clicking a frame type
name in the prototype detail navigates to `/kg_types?space_id=...&id=...`).

---

## 5. Backend API

### 5.1 Existing Prototype CRUD (no changes needed)

Prototype objects (`KGFrameProtoType`, `KGSlotProtoType`, `KGEntityProtoType`)
are stored as regular graph objects and can be managed via the existing
objects/triples endpoints. The `Edge_hasKGSlotProtoType` and
`Edge_hasKGFrameProtoType` edges are also managed via standard edge CRUD.

### 5.2 Prototype Query Endpoints (new convenience endpoints)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/prototypes/frame?space_id=...&frame_type_uri=...` | GET | Get frame prototype + all slot prototypes + edges for a frame type |
| `GET /api/prototypes/entity?space_id=...&entity_type_uri=...` | GET | Get entity prototype + linked frame prototypes |
| `POST /api/prototypes/frame?space_id=...` | POST | Create/update full frame prototype (prototype + slots + edges in one call) |
| `DELETE /api/prototypes/frame?space_id=...&frame_type_uri=...` | DELETE | Delete frame prototype and all associated slot prototypes/edges |

The `GET /api/prototypes/frame` endpoint returns graph objects in standard
quad format (same as all other graph endpoints), plus optional convenience
metadata. The authoritative data lives solely in the graph objects — the
metadata section is derived/summary information for UI convenience:

```json
{
  "objects": [
    {
      "URI": "urn:proto:employment",
      "type": "http://vital.ai/ontology/haley-ai-kg#KGFrameProtoType",
      "http://vital.ai/ontology/haley-ai-kg#hasKGFrameType": "http://example.org/EmploymentFrameType",
      ...
    },
    {
      "URI": "urn:proto:employee-slot",
      "type": "http://vital.ai/ontology/haley-ai-kg#KGSlotProtoType",
      ...
    },
    {
      "URI": "urn:proto:employer-slot",
      "type": "http://vital.ai/ontology/haley-ai-kg#KGSlotProtoType",
      ...
    },
    {
      "URI": "urn:edge:frame-to-employee-slot",
      "type": "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlotProtoType",
      "http://vital.ai/ontology/vital-core#hasEdgeSource": "urn:proto:employment",
      "http://vital.ai/ontology/vital-core#hasEdgeDestination": "urn:proto:employee-slot",
      "http://vital.ai/ontology/haley-ai-kg#kGSlotRoleSequence": 1,
      "http://vital.ai/ontology/haley-ai-kg#kGSlotRoleType": "http://example.org/hasEmployee",
      ...
    },
    {
      "URI": "urn:edge:frame-to-employer-slot",
      "type": "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlotProtoType",
      "http://vital.ai/ontology/vital-core#hasEdgeSource": "urn:proto:employment",
      "http://vital.ai/ontology/vital-core#hasEdgeDestination": "urn:proto:employer-slot",
      "http://vital.ai/ontology/haley-ai-kg#kGSlotRoleSequence": 2,
      "http://vital.ai/ontology/haley-ai-kg#kGSlotRoleType": "http://example.org/hasEmployer",
      ...
    }
  ],
  "metadata": {
    "frame_type_uri": "http://example.org/EmploymentFrameType",
    "entity_slot_count": 2,
    "total_slot_count": 2
  }
}
```

The `metadata` section is optional convenience data derived from the graph
objects — it does not contain information not already present in the quads.

---

## 6. Implementation Phases

### Phase 1 — Prototype Query Endpoints
- Implement `GET /api/prototypes/frame` (fetch full frame prototype graph)
- Implement `GET /api/prototypes/entity` (fetch entity prototype + frames)
- These use existing objects/triples infrastructure under the hood

### Phase 2 — Prototype Editor UI
- Build Frame Type Prototype editor (slot list with CRUD) within the
  Frame Type detail view (from `kg_types_plan.md`)
- Build Entity Type frame prototype associations within the Entity Type
  detail view
- Auto-classify button re-computes arity from slot prototypes
- Display arity badge on Frame Types list tab

### Phase 3 — Bulk Prototype Management
- Implement `POST /api/prototypes/frame` (create/update full prototype in one call)
- Implement `DELETE /api/prototypes/frame` (cascade delete prototype + slots + edges)
- Import/export prototype definitions (e.g. from domain schema JSON)

### Phase 4 — Prototype Search
- Implement prototype search via type description queries
- SPARQL queries search KGFrameType descriptions, then follow graph links
  to surface related prototypes

---

## 7. Testing with FrameNet Dataset

See `planning_visualization/framenet_testing_plan.md` for the full FrameNet
testing plan. The loader generates ~12,600 prototype objects and ~24,000
connecting edges in addition to type objects. Key prototype-specific test:
vector/FTS search finds types by description, then SPARQL traverses prototype
edges to return the full prototype graph — validating end-to-end search +
graph traversal integration.

---

## 8. Related Documents

- `planning_visualization/kg_types_plan.md` — KG Types enhancements (prerequisite, implement first)
- `planning_visualization/framenet_testing_plan.md` — FrameNet test dataset, loader, and search testing
- `planning_vector_geo/vector_geo_plan.md` — Vector & geo integration plan (pgvector, HNSW, full-text search)
- `planning_vector_geo/vector_geo_ui_plan.md` — Vector & geo UI integration
- `kgraphgen/planning/framenet_guide.md` — FrameNet mapping onto the three-tier Type/Prototype/Instance architecture
- `docs/object-impl-plan.md` — KG type hierarchy and semantic relationships
- `planning_kgdocument/kgdocument_plan.md` — KGDocument structure
