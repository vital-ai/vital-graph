# Knowledge Graph Model — Planning & Task Tracker

## 1. Knowledge Representation Patterns

### 1.1 KGEntity with Enclosed Frames

A **KGEntity** encloses a hierarchy of frames and subframes:

```
KGEntity
 ├── Edge_hasEntityKGFrame → KGFrame (top-level frame within entity)
 │    ├── Edge_hasKGSlot → KGSlot (slot on this frame)
 │    │    └── slot value: base datatype | URI ref to another KGEntity | URI ref to KGDocument
 │    └── Edge_hasKGFrame → KGFrame (subframe)
 │         └── Edge_hasKGSlot → KGSlot ...
 └── Edge_hasEntityKGFrame → KGFrame ...
```

- **Grouping URIs**: `kGGraphURI` = owning entity URI; `frameGraphURI` = immediate owning frame URI.
- Slots may reference other KGEntities, KGDocuments, or hold base data types (string, integer, double, boolean, dateTime, URI).

### 1.2 KGRelation (Entity-to-Entity Edge)

A **KGRelation** is an edge object linking one KGEntity to another:

```
KGEntity (source) ← Edge_hasKGRelation → KGEntity (destination)
```

- Queried by direction (incoming, outgoing, all) and relation type URI.
- Endpoint: `/api/kgrelations`

### 1.3 Top-Level KGFrame (Standalone)

A **top-level KGFrame** is NOT enclosed by a KGEntity. It has its own subframe/slot hierarchy:

```
KGFrame (top-level, standalone)
 ├── Edge_hasKGSlot → KGSlot
 │    └── slot value: base datatype | URI ref to KGEntity | URI ref to KGDocument
 └── Edge_hasKGFrame → KGFrame (subframe)
      └── ...
```

- No `kGGraphURI` (entity-scoped concept does not apply).
- Uses only `frameGraphURI` for grouping.
- Endpoint: `/api/kgframes` (standalone frame operations via `KGFrameCreateProcessor`).

---

## 2. KGEntity Properties Used for UI Filtering & Sorting

From `vitalgraph/model/kgentities_model.py` — `_FILTERABLE_ENTITY_PROPERTIES`:

| Property URI | Datatype | UI Label |
|---|---|---|
| `http://vital.ai/ontology/vital-core#hasName` | string | Name |
| `http://vital.ai/ontology/vital#hasObjectModificationDateTime` | dateTime | Modified |
| `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime` | dateTime | Created |
| `http://vital.ai/ontology/haley-ai-kg#hasKGEntityType` | uri | Entity Type |
| `http://vital.ai/ontology/vital-aimp#hasObjectStatusType` | uri | Status |
| `http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList` | uri_list | Action Types |
| `http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType` | uri | Provenance Type |

**Frontend sort options** (from `KGEntities.tsx`):
- Name (`vital-core#hasName`)
- Modified (`vital#hasObjectModificationDateTime`)
- Created (`vital-aimp#hasObjectCreationTime`)

**Frontend filters**:
- Text search (CONTAINS on `hasName`)
- Entity type URI (`hasKGEntityType`)
- Status / exclude-status (`hasObjectStatusType`)
- Date range (created_after/before, modified_after/before)
- Provenance type
- Action type

---

## 3. Separating Scenarios via `hasKGFormType`

### Approach

Use the property `http://vital.ai/ontology/haley-ai-kg#hasKGFormType` (range: URIs of `KGFormType`) on both KGEntity and KGFrame to classify each object's role in the knowledge graph.

### URI Constants

| Constant | Full URI | Applied To | Meaning |
|---|---|---|---|
| `KGFormType_Assertion` | `http://vital.ai/ontology/haley-ai-kg#KGFormType_Assertion` | KGFrame | Standalone top-level frame — an independent fact, not enclosed by an entity |
| `KGFormType_Aspect` | `http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect` | KGFrame | Entity-enclosed frame, or child frame of an Assertion — a particular dimension/feature of its parent |
| `KGFormType_Entity` | `http://vital.ai/ontology/haley-ai-kg#KGFormType_Entity` | KGEntity | The entity node itself |

### Rationale

- **Assertion**: Standard knowledge-representation term for a standalone statement of fact that exists independently — not subordinate to or dependent on another structure.
- **Aspect**: A particular dimension or feature of its parent (entity or assertion). Child frames of an Assertion are also Aspects — they elaborate on a specific facet of the assertion.
- Filtering by `hasKGFormType` is a simple single-property check, faster than checking edge connectivity or absence of `kGGraphURI`.

### Structural Reinforcement (Existing)

The `hasKGFormType` classification is **in addition to** the existing structural signals:
- `kGGraphURI` present → frame belongs to an entity graph
- `Edge_hasEntityKGFrame` incoming → frame is directly linked to an entity
- Absence of both → standalone/assertion frame

### Tasks

- [ ] **3.1** _(deferred)_ Add `KGFormType_Assertion`, `KGFormType_Aspect`, `KGFormType_Entity` to the domain schema as `KGFormType` instances.
- [x] **3.2** Set `hasKGFormType` automatically during create operations:
  - ✅ `kgframe_create_impl.py` → set `KGFormType_Assertion` on standalone top-level frames.
  - ✅ `kgentity_create_impl.py` → set `KGFormType_Aspect` on entity-enclosed frames (mixed payload path).
  - ✅ `kgentity_frame_create_impl.py` → set `KGFormType_Aspect` on entity-enclosed frames (frame sub-endpoint path).
  - ✅ `kgframe_hierarchical_impl.py` → set `KGFormType_Aspect` on child frames.
  - [ ] Entity create → set `KGFormType_Entity`.
- [x] **3.3** Add `form_type` query parameter to `/api/kgframes` endpoint to filter by `hasKGFormType` URI.
- [x] **3.4** Update UI KGFrames page to expose form-type filter (tabs: Assertions / Aspects / All).
- [ ] **3.5** Backfill existing frames: script to classify existing frames based on `kGGraphURI` presence.
- [ ] **3.6** Add `hasKGFormType` to `_FILTERABLE_ENTITY_PROPERTIES` if entity-level filtering by form type is needed.
- [x] **3.7** Document the classification in API docs / OpenAPI schema descriptions.

> **Implementation status (June 2026):** Tasks 3.2–3.4 fully implemented and verified with 10/10 integration tests passing. See `planning_kg_model/kgframes_filter_sort_parity_plan.md` for details.

---

## 4. Additional Model & UI Tasks

- [x] **4.1** Add KGFrame type filtering to the standalone frames list (analogous to `entity_type_uri` on entities).
  - ✅ Added `frame_type_uri` parameter + `form_type` filter to `/api/kgframes` endpoint.
- [x] **4.2** Add sorting support to the standalone frames list — now property URI–based (matching entity pattern).
  - ✅ `sort_by` accepts full property URI; validated against `_FRAME_SORT_PROPERTIES` registry.
- [x] **4.3** Improve KGRelation UI page to show source/destination entity names (not just URIs).
  - ✅ Batch-resolves entity names via `getEntity()` after relations load; displays name with URI tooltip.
- [x] **4.4** Add slot type/value summary columns to frame detail views.
  - ✅ `KGFrameDetail.tsx` now fetches frame graph and renders a Slot Summary table with Name, Type (badge), and Value columns.
- [x] **4.5** Add cross-reference navigation in UI: slot value → linked entity or document.
  - ✅ `SlotFieldRow.tsx` detects internal URIs (`urn:` / `vital.ai/`) and renders in-app navigation buttons; external URIs still open in new tab.

---

## 5. Reference: Key Backend Files

| Concern | File |
|---|---|
| Entity list/sort/filter | `vitalgraph/kg_impl/kgentity_list_impl.py` |
| Entity property registry | `vitalgraph/model/kgentities_model.py` |
| Entity endpoint | `vitalgraph/endpoint/kgentities_endpoint.py` |
| Entity-enclosed frame create | `vitalgraph/kg_impl/kgentity_frame_create_impl.py` |
| Standalone frame create | `vitalgraph/kg_impl/kgframe_create_impl.py` |
| Standalone frames endpoint | `vitalgraph/endpoint/kgframes_endpoint.py` |
| KGRelations endpoint | `vitalgraph/endpoint/kgrelations_endpoint.py` |
| Frontend entities page | `frontend/src/pages/KGEntities.tsx` |
