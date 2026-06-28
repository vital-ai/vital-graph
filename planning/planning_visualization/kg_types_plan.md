# KG Types — UI & Data Model Enhancements Plan

## 1. Overview

The existing KG Types page shows all type instances in a flat, undifferentiated
list. This plan covers enhancements to the KG Types UI and backend to surface
type relationships, documentation, and search — making the type catalog a
first-class browsing and editing experience.

This plan is implemented **before** the prototype layer (see
`planning_visualization/prototype_kg_types_plan.md`), which builds on top of
these type-level enhancements.

This plan covers:
1. **Type data model** — type classes, type-level edges, and supporting types
2. **KG Types UI** — tabbed browsing, type relationships, search, documentation
3. **Backend enhancements** — type-aware queries, documentation endpoints

---

## 2. Type Data Model

### 2.1 Primary Type Classes

All type classes extend `KGType` (which extends `VITAL_Node`) and share
inherited properties: `name`, `kGraphDescription`, `kGModelVersion`,
`kGTypeVersion`.

| Type Class | URI | Key Properties |
|-----------|-----|---------------|
| `KGFrameType` | `haley-ai-kg#KGFrameType` | `kGFrameTypeExternIdentifier` |
| `KGSlotType` | `haley-ai-kg#KGSlotType` | `kGSlotTypeExternIdentifier`, `kGSlotTypeName`, `kGSlotTypeLabel` |
| `KGEntityType` | `haley-ai-kg#KGEntityType` | `kGEntityTypeExternIdentifier` |
| `KGRelationType` | `haley-ai-kg#KGRelationType` | `kGRelationTypeSymmetric` |

### 2.2 Supporting Type Classes

| Type Class | URI | Purpose | Management |
|-----------|-----|----------|------------|
| `KGSlotRoleType` | `haley-ai-kg#KGSlotRoleType` | Classifies slot role (e.g. core vs non-core) | UI-managed (see §3.2) |
| `KGSlotValueType` | `haley-ai-kg#KGSlotValueType` | Classifies data type a slot holds (entity, text, currency, etc.) | Constants (ontology-defined) |
| `KGSlotConstraintType` | `haley-ai-kg#KGSlotConstraintType` | Constraints on slot values (e.g. semantic type restrictions) | Constants (ontology-defined) |

`KGSlotValueType` and `KGSlotConstraintType` are fixed constant sets defined
in the ontology — they are not user-editable. `KGSlotRoleType` instances are
user-managed and should be editable in the UI (e.g. creating custom role
classifications beyond the default core/non-core).

**Role types for slot disambiguation:** `KGSlotRoleType` can be used to
distinguish different roles when a frame has multiple slots of the same type.
For example, a Commerce frame might have two slots both typed as
`BusinessEntity` — one with role type "Buyer" and the other "Seller". Without
role types, the modeler would need distinct slot types like `BuyerEntity` and
`SellerEntity`, which duplicates what is essentially the same underlying type.

This is ultimately a **modeling choice**:
- **Role-based** — reuse a single slot type (e.g. `BusinessEntity`) and
  differentiate via `KGSlotRoleType` on the prototype edge. Cleaner type
  catalog, more flexible.
- **Type-based** — create distinct slot types (e.g. `BuyerEntity`,
  `SellerEntity`). Simpler prototype structure, but more types to manage.

Both approaches are valid and commonly used. The system supports either.

### 2.3 Type-Level Edges

These edges relate KG types to each other as part of the type definitions.
Source and destination classes are declared via `vital-core:hasEdgeSrcDomain`
and `vital-core:hasEdgeDestDomain` OWL annotations (queryable via VitalSigns
`ont_manager.get_domain_graph()`). Comments are from `rdfs:comment` annotations.

| Edge | Source → Destination | Comment |
|------|----------------------|---------|
| `Edge_hasSubKGFrameType` | KGFrameType → KGFrameType | A subframe in the sense of one frame extending another to be more specific. E.g. Description → Physical Description |
| `Edge_hasPartOfKGFrameType` | KGFrameType → KGFrameType | Case of a frame being part of a parent frame |
| `Edge_hasEntityTypePartOfKGFrameType` | KGEntityType → KGFrameType | An entity type has a component represented by the frame type. E.g. a person entity type might have a physical description frame type |
| `Edge_hasSubKGEntityType` | KGEntityType → KGEntityType | Entity type hierarchy (inheritance) |
| `Edge_hasSubKGType` | KGType → KGType | General type hierarchy (any KGType subclass to any KGType subclass) |
| `Edge_hasSameAsKGType` | KGType → KGType | Equivalence link between two type definitions |
| `Edge_hasOutgoingKGRelationType` | KGEntityType, KGEntityProtoType → KGRelationType | Which relation types an entity type can be the source of |
| `Edge_hasIncomingKGRelationType` | KGEntityType, KGEntityProtoType → KGRelationType | Which relation types an entity type can be the destination of |
| `Edge_hasKGEdge` | KGNode, KGType → KGNode, KGType | General-purpose edge linking any KG nodes/types (see §2.4) |

### 2.4 Linking KG Types to KGDocuments

`Edge_hasKGEdge` can be used to link a KG type (e.g. `KGFrameType`,
`KGEntityType`) to a `KGDocument` containing longer-form documentation.
The KGDocument can hold markdown content describing the type's intended
usage, examples, constraints, and design rationale — information that is
too detailed for the `kGraphDescription` property but valuable for users
browsing the type catalog.

- At most **one** documentation KGDocument per KG type
- The KGDocument is **optional** — types without documentation have no linked document
- Linked via `Edge_hasKGEdge` from the KG type to the KGDocument
- Since `Edge_hasKGEdge` has broad domains, documentation queries must filter
  by the destination object's `rdf:type` being `KGDocument` (i.e. the SPARQL
  query follows the edge and checks that the destination is a KGDocument)

### 2.5 Type Relationship Graph

Type-level edges create a rich relationship graph between types:

```
KGEntityType ("Person")
  ├── Edge_hasSubKGEntityType → KGEntityType ("Employee")
  ├── Edge_hasSubKGEntityType → KGEntityType ("Student")
  ├── Edge_hasEntityTypePartOfKGFrameType → KGFrameType ("Employment")
  ├── Edge_hasEntityTypePartOfKGFrameType → KGFrameType ("Education")
  ├── Edge_hasOutgoingKGRelationType → KGRelationType ("KnowsPerson")
  ├── Edge_hasIncomingKGRelationType → KGRelationType ("ManagedBy")
  └── Edge_hasKGEdge → KGDocument ("Person type documentation")

KGFrameType ("Employment")
  ├── Edge_hasSubKGFrameType → KGFrameType ("FullTimeEmployment")
  ├── Edge_hasPartOfKGFrameType → KGFrameType ("CompensationPackage")
  └── Edge_hasSameAsKGType → KGFrameType ("WorkEngagement")
```

These relationships are surfaced in the UI (§3) to help users understand
how types relate to each other.

### 2.6 Types Graph — Space-Wide Storage

KG types are **space-wide** — they apply across all data graphs in a space,
not to a single graph. To support this, all KG type objects, type-level edges,
and linked KGDocuments are stored in a **standard types graph** with a
well-known URI per space:

```
urn:vitalgraph:{space_id}:kg_types
```

This graph is created automatically when the first KG type is written to a
space. All type CRUD operations (create, read, update, delete) target this
graph. The types graph is not listed alongside user data graphs — it is an
internal system graph. No migration is needed — there is no existing type
data in production.

Benefits:
- Types are shared across all data graphs without duplication
- Type queries do not need a `graph_id` parameter
- Data graphs can reference type URIs without storing the type objects
- Vector and full-text indexes on types are scoped to this single graph

---

## 3. UI Plan — KG Types Enhancements

### 3.1 Current State

The existing KG Types page (`/kg_types`) shows a flat list of all KGType
subclass instances in a graph:

- **Route**: `/kg_types?space_id=...`
- **Detail**: `/kg_types?space_id=...&id=...`
- **Page**: `frontend/src/pages/KGTypes.tsx` — list with search, pagination
- **Detail**: `frontend/src/pages/KGTypeDetail.tsx` — generic quad-based CRUD
- **Backend**: `vitalgraph/endpoint/kgtypes_endpoint.py` → `kgtypes_*_impl.py`
- **Client**: `vitalgraph-client-ts/src/endpoint/KGTypesEndpoint.ts`

The list shows all KGType subclasses mixed together (KGEntityType, KGFrameType,
KGSlotType, KGRelationType, etc.) without distinguishing between them or
showing their relationships.

### 3.2 Tab Structure on KG Types Page

Add tabs to the existing KG Types page to separate concerns:

| Tab | Content |
|-----|---------|
| **All Types** | Current flat list (unchanged) |
| **Frame Types** | Filtered to KGFrameType only |
| **Entity Types** | Filtered to KGEntityType, with linked frame types and subtypes |
| **Slot Types** | Filtered to KGSlotType |
| **Relation Types** | Filtered to KGRelationType, with symmetry flag |
| **Role Types** | Filtered to KGSlotRoleType — user-managed role classifications |

### 3.3 Search

The UI supports searching for types via:

- **Keyword / full-text search** — matches against type names, descriptions,
  and labels on KG Type instances
- **Vector search** — semantic similarity search against type descriptions

Search internally uses SPARQL queries that leverage the vector and full-text
search constructs — e.g. finding `KGFrameType` instances by description
similarity.

### 3.4 KG Type Documentation

Each KG type detail view includes an optional **Documentation** panel. This
provides longer-form markdown documentation beyond the short `kGraphDescription`
property — covering usage guidance, examples, constraints, and design rationale.

**Data model:**
- Documentation is stored in a `KGDocument` linked to the KG type via
  `Edge_hasKGEdge` (see §2.4)
- At most one documentation KGDocument per KG type
- The KGDocument is optional — types without documentation simply show no panel

**UI behavior:**

```
┌─────────────────────────────────────────────────────┐
│ Frame Type: Commerce_buy                            │
│ Description: A Buyer wants Goods and pays Money...  │
│                                                     │
│ ── Documentation ──────────────────────── [Edit ✎] │
│                                                     │
│  ## Usage                                           │
│  This frame covers all commercial purchase events.  │
│  The **Buyer** and **Goods** slots are always       │
│  required; Money and Seller are often present.      │
│                                                     │
│  ## Examples                                        │
│  - "John bought a car for $5,000"                   │
│  - "She purchased three tickets online"             │
│                                                     │
└─────────────────────────────────────────────────────┘
```

- **View mode** (default) — markdown is rendered via a markdown renderer
  component; the raw markdown is not shown
- **Edit mode** — clicking [Edit] switches to a markdown text editor with a
  live preview panel alongside it; the user edits the raw markdown and sees
  the rendered output updating in real time
- **Save** — clicking [Save] persists the content and reverts to rendered
  view mode; clicking [Cancel] discards changes and reverts to view mode

**Backend behavior:**
- When documentation text is first added to a KG type that has none, the
  server creates a new `KGDocument` and an `Edge_hasKGEdge` linking the
  type to the document
- Subsequent saves update the existing `KGDocument` content
- The type detail endpoints include the linked KGDocument in the returned
  graph objects (if present)

**Frontend library:** Use a React markdown renderer (e.g. `react-markdown`
or `@uiw/react-md-editor`) for both rendering and editing.

### 3.5 Entity Type Detail — Type Relationships

When viewing a `KGEntityType` detail, show sections for its type-level
relationships:

```
┌─────────────────────────────────────────────────────┐
│ Entity Type: Person                                 │
│ Description: A human individual...                  │
│                                                     │
│ ── Subtypes ───────────────────────────────────── │
│ Employee, Student, Customer                         │
│ [+ Add Subtype]                                     │
│                                                     │
│ ── Part-of Frame Types ───────────────────────── │
│ Employment, Education, Address, PhysicalDescription │
│ [+ Link Frame Type]                                 │
│                                                     │
│ ── Relation Types ─────────────────────────────── │
│ Outgoing: KnowsPerson, WorksFor                     │
│ Incoming: ManagedBy, MentoredBy                     │
│ [+ Link Relation Type]                              │
│                                                     │
│ ── Documentation ──────────────────────── [Edit ✎] │
│ (rendered markdown content)                         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

Each section shows the linked types via the corresponding edges:
- **Subtypes** — `Edge_hasSubKGEntityType` children
- **Part-of Frame Types** — `Edge_hasEntityTypePartOfKGFrameType` destinations
- **Relation Types** — `Edge_hasOutgoingKGRelationType` / `Edge_hasIncomingKGRelationType`

Users can add/remove these links via the UI, which creates/deletes the
corresponding edge objects.

### 3.6 Frame Type Detail — Type Relationships

When viewing a `KGFrameType` detail, show:

```
┌─────────────────────────────────────────────────────┐
│ Frame Type: Employment                              │
│ Description: An employer employs an employee...     │
│                                                     │
│ ── Parent Frame Types ─────────────────────────── │
│ (frames this inherits from via Edge_hasSubKGFrameType) │
│ EconomicActivity                                    │
│                                                     │
│ ── Sub Frame Types ────────────────────────────── │
│ FullTimeEmployment, ContractWork                    │
│                                                     │
│ ── Part-of Frame Types ───────────────────────── │
│ (composite frames via Edge_hasPartOfKGFrameType)    │
│ CompensationPackage                                 │
│                                                     │
│ ── Entity Types ───────────────────────────────── │
│ (entities that participate via Edge_hasEntityTypePartOfKGFrameType) │
│ Person, Organization                                │
│                                                     │
│ ── Same-As ────────────────────────────────────── │
│ WorkEngagement (via Edge_hasSameAsKGType)            │
│                                                     │
│ ── Documentation ──────────────────────── [Edit ✎] │
│ (rendered markdown content)                         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 3.7 Slot Type Detail — Referencing Frames

When viewing a `KGSlotType` detail, show which frames and prototypes
reference this slot type:

```
┌─────────────────────────────────────────────────────┐
│ Slot Type: Agent                                    │
│ Description: The entity that intentionally performs  │
│   the action...                                     │
│                                                     │
│ ── Used in Frames ─────────────────────────────── │
│ Frame Type          Role       Sequence              │
│ Intentionally_act   Core       1                     │
│ Collaboration       Core       1                     │
│ Crime               Core       1                     │
│ Leadership          Non-Core   3                     │
│                                                     │
│ ── Documentation ──────────────────────── [Edit ✎] │
│ (rendered markdown content)                         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

The "Used in Frames" section is derived by querying `Edge_hasKGSlotType`
edges that point to this slot type, then following back to the parent
`KGFrameProtoType` via `Edge_hasKGSlotProtoType`. Each row links to the
corresponding frame prototype detail (in the Prototypes screens) and the
frame type detail (in the KG Types screens).

**Note:** This section depends on prototype data and should be implemented
as part of the prototype plan (`prototype_kg_types_plan.md`), not in this
plan's phases. The slot type detail view ships initially with just the
type properties and documentation panel.

### 3.8 Relation Type Detail

When viewing a `KGRelationType`, show which entity types can be source
and destination:

```
┌─────────────────────────────────────────────────────┐
│ Relation Type: KnowsPerson                          │
│ Symmetric: true                                     │
│                                                     │
│ ── Source Entity Types ──────────────────────────── │
│ (via Edge_hasOutgoingKGRelationType pointing here)   │
│ Person                                              │
│                                                     │
│ ── Destination Entity Types ─────────────────────── │
│ (via Edge_hasIncomingKGRelationType pointing here)   │
│ Person                                              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 4. Routes

| Route | Component | Purpose |
|-------|-----------|---------|
| `/kg_types?space_id=...` | KGTypes (tabbed) | List all types with tabs |
| `/kg_types?space_id=...&id=...` | KGTypeDetail | Enhanced detail view with relationships + documentation |

No `graph_id` is needed in routes — types are space-wide (see §2.6).

---

## 5. Backend API

### 5.1 Type-Filtered List Endpoints

The existing `GET /api/kg_types` endpoint already supports type filtering.
The tabbed UI uses the `type_uri` parameter to filter by subclass:

| Tab | Filter |
|-----|--------|
| Frame Types | `type_uri=haley-ai-kg#KGFrameType` |
| Entity Types | `type_uri=haley-ai-kg#KGEntityType` |
| Slot Types | `type_uri=haley-ai-kg#KGSlotType` |
| Relation Types | `type_uri=haley-ai-kg#KGRelationType` |

### 5.2 Type Relationship Queries

New convenience endpoints to fetch type relationships:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/kg_types/relationships?space_id=...&id=...` | GET | Get all type-level edges for a type (subtypes, part-of, relations, same-as) |
| `POST /api/kg_types/relationships?space_id=...&id=...` | POST | Create a type-level edge (specify edge type and target type URI) |
| `DELETE /api/kg_types/relationships?space_id=...&id=...&edge_uri=...` | DELETE | Remove a type-level edge |

The `GET` endpoint returns all connected types as graph objects in standard
quad format — the type objects, edge objects, and optionally the linked
KGDocument.

### 5.3 Documentation Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/kg_types/documentation?space_id=...&id=...` | GET | Get linked KGDocument (if any) |
| `PUT /api/kg_types/documentation?space_id=...&id=...` | PUT | Create or update the documentation KGDocument |
| `DELETE /api/kg_types/documentation?space_id=...&id=...` | DELETE | Remove the documentation KGDocument and its edge |

The `PUT` endpoint:
- If no KGDocument exists: creates a new `KGDocument` + `Edge_hasKGEdge`
- If KGDocument exists: updates the existing document content
- Request body: `{ "content": "# Markdown content..." }`

### 5.4 Search Endpoints

Search uses the existing SPARQL infrastructure with vector and full-text
constructs:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/kg_types/search?space_id=...&q=...&type=...` | GET | Search types by keyword or vector similarity |

Parameters:
- `q` — search query string
- `space_id` — required (types are space-wide; the search targets the
  standard types graph `urn:vitalgraph:{space_id}:kg_types`)
- `type` — optional filter (`frame`, `entity`, `slot`, `relation`, `role`)
- `search_mode` — `keyword` (default) or `vector`

No `graph_id` parameter is needed — types are stored in a single
space-wide types graph (see §2.6).

---

## 6. Implementation Phases

### Phase 1 — Tabbed KG Types List ✅
- ✅ Tab navigation added to KG Types page (All, Frame, Entity, Slot, Relation, Role)
- ✅ Type-filtered queries via `type_uri` parameter
- ✅ Backend `list_kgtypes` updated to accept optional `type_uri` filter
- ✅ TypeScript client and ApiService updated with `type_uri` support
- ✅ FrameNet test dataset generated and loaded (3,287 objects in `framenet_kgtypes_test` space)

### Phase 1b — Client Library Updates ✅

All client methods for Phases 2–5 added in source. Frontend uses a `_kgtypes`
cast getter so it compiles without Docker rebuild (`tsc --noEmit` = 0 errors).

**TypeScript client (`@vital-ai/vitalgraph-client`):**

| Method | HTTP | Phase | Status |
|--------|------|-------|--------|
| `list(…, typeUri?)` | GET | 1 | ✅ |
| `getRelationships(spaceId, graphId, typeUri)` | GET | 2 | ✅ |
| `createRelationship(spaceId, graphId, typeUri, edgeType, targetUri)` | POST | 5 | ✅ |
| `deleteRelationship(spaceId, graphId, typeUri, edgeUri)` | DELETE | 5 | ✅ |
| `getDocumentation(spaceId, graphId, typeUri)` | GET | 3 | ✅ |
| `updateDocumentation(spaceId, graphId, typeUri, content)` | PUT | 3 | ✅ |
| `deleteDocumentation(spaceId, graphId, typeUri)` | DELETE | 3 | ✅ |
| `search(spaceId, graphId, query, options?)` | GET | 4 | ✅ |

Response types added: `KGTypeRelationshipsResponse`,
`KGTypeRelationshipCreateResponse`, `KGTypeRelationshipDeleteResponse`,
`KGTypeDocumentationResponse`, `KGTypeDocumentationUpdateResponse`,
`KGTypeDocumentationDeleteResponse`, `KGTypeSearchResponse`.

Tasks:
- ✅ All TS client methods and response types implemented
- ✅ Package builds successfully
- ✅ All Python client methods and response types implemented
- ✅ Frontend compiles via `_kgtypes` any-cast getter (no stale type errors)
- Publish to npm after end-to-end verification (Docker rebuild installs latest)

**Python client (`vitalgraph/client/endpoint/kgtypes_endpoint.py`):**

| Method | HTTP | Phase | Status |
|--------|------|-------|--------|
| `list_kgtypes(…, type_uri=None)` | GET | 1 | ✅ `type_uri` param added |
| `get_type_relationships(space_id, graph_id, type_uri)` | GET | 2 | ✅ added |
| `create_type_relationship(space_id, graph_id, type_uri, edge_type, target_uri)` | POST | 5 | ✅ added |
| `delete_type_relationship(space_id, graph_id, type_uri, edge_uri)` | DELETE | 5 | ✅ added |
| `get_type_documentation(space_id, graph_id, type_uri)` | GET | 3 | ✅ added |
| `update_type_documentation(space_id, graph_id, type_uri, content)` | PUT | 3 | ✅ added |
| `delete_type_documentation(space_id, graph_id, type_uri)` | DELETE | 3 | ✅ added |
| `search_types(space_id, graph_id, query, type=None, search_mode=None)` | GET | 4 | ✅ added |

Response types added to `client_response.py`: `KGTypeRelationshipsResponse`,
`KGTypeRelationshipCreateResponse`, `KGTypeRelationshipDeleteResponse`,
`KGTypeDocumentationResponse`, `KGTypeDocumentationUpdateResponse`,
`KGTypeDocumentationDeleteResponse`, `KGTypeSearchResponse`.

**Frontend `ApiService.ts`:**

All KG Types methods route through a private `_kgtypes` getter (cast to `any`)
so the frontend compiles even when the local `node_modules` TS client is stale.
`tsc --noEmit` passes with zero errors.

| Method | Delegates to | Status |
|--------|-------------|--------|
| `getKGTypes(…, { type_uri })` | `_kgtypes.list()` | ✅ |
| `getKGTypeRelationships(…)` | `_kgtypes.getRelationships()` | ✅ |
| `createKGTypeRelationship(…)` | `_kgtypes.createRelationship()` | ✅ |
| `deleteKGTypeRelationship(…)` | `_kgtypes.deleteRelationship()` | ✅ |
| `getKGTypeDocumentation(…)` | `_kgtypes.getDocumentation()` | ✅ |
| `updateKGTypeDocumentation(…)` | `_kgtypes.updateDocumentation()` | ✅ |
| `deleteKGTypeDocumentation(…)` | `_kgtypes.deleteDocumentation()` | ✅ |
| `searchKGTypes(…)` | `_kgtypes.search()` | ✅ |

**REST endpoints (`vitalgraph/endpoint/kgtypes_endpoint.py`):**

| Endpoint | Method | Phase | Status |
|----------|--------|-------|--------|
| `GET /api/graphs/kgtypes` (with `type_uri`) | GET | 1 | ✅ implemented |
| `GET /api/graphs/kgtypes/relationships` | GET | 2 | ✅ implemented |
| `POST /api/graphs/kgtypes/relationships` | POST | 5 | ✅ implemented |
| `DELETE /api/graphs/kgtypes/relationships` | DELETE | 5 | ✅ implemented |
| `GET /api/graphs/kgtypes/documentation` | GET | 3 | ✅ implemented |
| `PUT /api/graphs/kgtypes/documentation` | PUT | 3 | ✅ implemented |
| `DELETE /api/graphs/kgtypes/documentation` | DELETE | 3 | ✅ implemented |
| `GET /api/graphs/kgtypes/search` | GET | 4 | ✅ implemented |

Backend implementation in `kgtypes_read_impl.py` with Pydantic models in `kgtypes_model.py`.

### Phase 2 — Type Detail Enhancements ✅
- ✅ Backend `GET /api/graphs/kgtypes/relationships` endpoint implemented
- ✅ SPARQL query logic for type relationships in `kgtypes_read_impl.py`
- ✅ Response model `KGTypeRelationshipsResponse` defined
- ✅ `TypeRelationshipsPanel` component with type-adaptive sections + add/delete buttons
- ✅ `KGTypeDetail.tsx` integrated — shows relationships + documentation below properties
- ✅ Frame Type detail: parent/sub frames, part-of, entity types, same-as sections
- ✅ Entity Type detail: subtypes, parents, part-of frames, outgoing/incoming relations
- ✅ Relation Type detail: source/destination entity types
- ✅ Slot Type detail: properties only via ObjectDetailRenderer (no relationships panel)

### Phase 3 — Documentation ✅
- ✅ REST endpoints implemented: `GET/PUT/DELETE /api/graphs/kgtypes/documentation`
- ✅ Python client methods added: `get_type_documentation`, `update_type_documentation`, `delete_type_documentation`
- ✅ `ApiService` wrappers: `getKGTypeDocumentation`, `updateKGTypeDocumentation`, `deleteKGTypeDocumentation`
- ✅ `TypeDocumentationPanel` component with inline markdown editor + live preview
- ✅ Documentation panel integrated into `KGTypeDetail.tsx` (all type classes)

### Phase 4 — Search ✅
- ✅ REST endpoint implemented: `GET /api/graphs/kgtypes/search` with keyword, FTS, vector, hybrid modes
- ✅ Python client method added: `search_types(search_mode=keyword|fts|vector|hybrid)`
- ✅ SPARQL pipeline: `vg:textSearch`, `vg:vectorSimilarity`, `vg:hybridSearch` all working
- ✅ VitalSigns vector search validated: 24/24 FrameNet tests pass (`test_kgtype_search_framenet.py`)
- ✅ OpenAI vector search validated: 9/9 provider swap tests pass (`test_kgtype_search_openai.py`)
- ✅ Auto-sync (create → FTS+vector indexing) verified end-to-end
- ✅ `ApiService` wrapper: `searchKGTypes` with mode + alpha params
- ✅ Search mode selector in KG Types list (client filter / keyword / FTS / vector / hybrid)

### Phase 5 — Type Relationship Editing ✅
- ✅ REST endpoints implemented: `POST/DELETE /api/graphs/kgtypes/relationships`
- ✅ Python client methods added: `create_type_relationship`, `delete_type_relationship`
- ✅ `ApiService` wrappers: `createKGTypeRelationship`, `deleteKGTypeRelationship`
- ✅ Add [+] buttons per relationship section with inline URI input
- ✅ Delete (×) buttons on each linked type (hover-reveal, with spinner)
- ✅ Panel renders add buttons even when no relationships exist yet
- ⬜ Server-side validation of edge source/destination types (Phase 6 prerequisite)

### Phase 6 — OWL-Based Domain Filtering (pending)
- ⬜ Use OWL annotation properties (`hasEdgeSrcDomain`, `hasEdgeDestDomain`)
  to drive UI type picker filtering — requires knowledge of the class
  hierarchy from VitalSigns
- ⬜ E.g. when adding a subtype to an entity type, the picker only shows
  KGEntityType instances; when linking a relation type, only shows
  KGRelationType instances
- This is a refinement — basic relationship editing (Phase 5) works without
  it by relying on server-side validation

---

## 7. Testing with FrameNet Dataset

See `planning_visualization/framenet_testing_plan.md` for the full FrameNet
testing plan, including the generator script, block file output, verified
object counts, and loading via `vitalgraphimport`.

**Current test space:** `framenet_kgtypes_test` with 1,221 KGFrameType,
1,285 KGSlotType, and 781 Edge_hasSubKGFrameType loaded into
`urn:vitalgraph:framenet_kgtypes_test:kg_types`.

This dataset is ideal for testing Phase 2 Frame Type detail views since
it includes a real hierarchy of frame inheritance edges.

---

## 8. Backend Client Integration Tests

End-to-end tests exercising the new REST endpoints via the Python client,
integrated into the existing `test_kgtypes_endpoint.py` orchestrator.

**Test orchestrator:** `vitalgraph_client_test/test_kgtypes_endpoint.py`

**New modular test cases (in `vitalgraph_client_test/kgtypes/`):**

| File | Tester Class | Exercises | Tests | Status |
|------|-------------|-----------|-------|--------|
| `case_kgtype_relationships.py` | `KGTypeRelationshipsTester` | `get_type_relationships`, `create_type_relationship`, `delete_type_relationship` | 5 (get empty, create, get with edge, delete, verify empty) | ✅ written |
| `case_kgtype_documentation.py` | `KGTypeDocumentationTester` | `get_type_documentation`, `update_type_documentation`, `delete_type_documentation` | 7 (get empty, create, get exists, update, verify update, delete, verify deleted) | ✅ written |
| `case_kgtype_search.py` | `KGTypeSearchTester` | `search_types`, `list_kgtypes(type_uri=...)` | 4 (basic keyword, type filter, no matches, list with type_uri) | ✅ written |

**Test flow** (steps 7–9 added between existing update and delete steps):
1. Create test space + 20 KGType objects (5 base, 5 entity, 4 frame, 3 relation, 3 slot)
2. CRUD tests (create, list, get, update)
3. **Step 7 — Relationships:** get (empty) → create Edge_hasSubKGEntityType → get (verify) → delete → get (verify empty)
4. **Step 8 — Documentation:** get (empty) → create markdown → get → update → verify content → delete → verify deleted
5. **Step 9 — Search:** keyword search, type-filtered search, zero-result search, list with `type_uri` filter
6. Delete tests + cleanup

**Run command:**
```bash
/opt/homebrew/anaconda3/envs/vital-graph/bin/python -m vitalgraph_client_test.test_kgtypes_endpoint
```

**Status:** ✅ All 32 tests PASSED (Jun 14, 2026) against running server.

---

## 10. Search Infrastructure — Fully Validated (Jun 2026)

All search modes (keyword, FTS, vector, hybrid) are fully implemented and
tested end-to-end via the SPARQL pipeline. See
`planning_visualization/kg_types_search_plan.md` for full details.

| Test Suite | Tests | Provider | Status |
|------------|-------|----------|--------|
| `test_kgtype_search_framenet.py` | 24/24 | VitalSigns (384d) | ✅ |
| `test_kgtype_search_openai.py` | 9/9 | OpenAI swap (1536d) | ✅ |

Key capabilities validated:
- **Provider swap**: VitalSigns → OpenAI → VitalSigns round-trip with dimension changes (384d ↔ 1536d)
- **Auto-sync**: Create KGType → FTS + vector indexed within ~1s
- **Hybrid search**: FTS candidate retrieval + vector re-ranking with configurable `alpha`

---

## 9. Related Documents

- `planning_visualization/prototype_kg_types_plan.md` — Prototype layer (builds on this plan)
- `planning_visualization/framenet_testing_plan.md` — FrameNet test dataset, generator, and search testing
- `planning_visualization/btree_term_index_plan.md` — Btree index limit on long literals (affects import)
- `planning_vector_geo/vector_geo_plan.md` — Vector & geo integration plan (pgvector, HNSW, full-text search)
- `planning_vector_geo/vector_geo_ui_plan.md` — Vector & geo UI integration
- `kgraphgen/planning/framenet_guide.md` — FrameNet mapping onto the three-tier Type/Prototype/Instance architecture
- `planning_kgdocument/kgdocument_plan.md` — KGDocument structure
- `docs/object-impl-plan.md` — KG type hierarchy and semantic relationships
