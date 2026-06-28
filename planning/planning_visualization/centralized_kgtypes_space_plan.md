# Centralized KG Types Space Plan

> **Created**: Jun 17, 2026
> **Updated**: Jun 18, 2026 (all phases complete)
> **Related**: `kg_types_plan.md`, `kg_types_search_plan.md`, `semantic_search_ui_plan.md`

## 1. Goal

Move KG Type data (KGEntityType, KGFrameType, KGSlotType, KGRelationType, etc.)
out of per-space storage into a single **system-defined KG Types space**
(`sp_kg_types`), analogous to how `entity_registry` is a global facility.

Consumers in other spaces (e.g. vector populators building search text for
KGEntities/KGFrames/KGDocuments) will **look up** type descriptions from this
central space rather than expecting the types to be co-located.

---

## 2. Current Architecture (per-space)

| Component | How it works today |
|---|---|
| **Storage** | Each space has a well-known graph `urn:vitalgraph:{space_id}:kg_types` containing all KGType objects as RDF quads. |
| **REST API** | `GET/POST/PUT/DELETE /api/graphs/kgtypes?space_id=X` — all operations scoped to one space (`kgtypes_endpoint.py` → `_types_graph(space_id)`). |
| **KGType index setup** | `kgtype_index_setup.py` runs during `create_space` and creates per-space `kgtype_default` vector index, FTS index, and search mappings in `{space_id}_vector_index`, `{space_id}_search_mapping`, etc. |
| **Vector text builder** | `search_text_builder.py` accepts an optional `type_description` param. However, `vector_populator.py` currently calls `build_search_text()` **without** `type_description` — so type descriptions are not yet injected into entity/frame/doc vectors. |
| **Frontend** | KG Types page (`KGTypes.tsx`) takes a `space_id` from the URL or selector. Type URI pickers (`TypeURIPicker.tsx`) call `GET /api/graphs/kgtypes?space_id=X&type_uri=...`. |
| **UI sidebar** | KG Types appears under the per-space navigation (like Graphs, Objects, etc.). |

### Key observation

Type descriptions are **not yet flowing** into entity/frame vectors because
`vector_populator.py` never passes `type_description` to `build_search_text()`.
This is the right time to redesign, since the lookup path doesn't exist yet
anyway.

---

## 3. Target Architecture

### 3.1 System Space: `sp_kg_types`

A system-defined space created at startup (like entity_registry tables), with:

- **Space ID**: `sp_kg_types`
- **Default graph**: `urn:vitalgraph:sp_kg_types:kg_types`
- **Owner**: system (not user-deletable)
- Bootstrapped during `SpaceManager.initialize_from_database()` → `_ensure_system_spaces()`
- Schema creation via `SparqlSQLSchema.create_space()` (same as any space)
- KGType search infrastructure (`kgtype_default` vector + FTS + mappings) set up once

### 3.2 Type Description Lookup Service

A new async utility that other spaces' vector populators can call:

```python
class KGTypeDescriptionLookup:
    """Look up KGType descriptions from the centralized sp_kg_types space."""

    SPACE_ID = "sp_kg_types"
    GRAPH_ID = "urn:vitalgraph:sp_kg_types:kg_types"

    async def get_description(self, conn, type_uri: str) -> Optional[str]:
        """Fetch hasKGraphDescription for a KGType URI."""
        ...

    async def get_descriptions_batch(self, conn, type_uris: List[str]) -> Dict[str, str]:
        """Batch fetch descriptions. Returns {type_uri: description}."""
        ...
```

The populator calls this for `type_description` or `properties_type` source
modes, passing the entity's `hasKGEntityType` (or frame's `hasKGFrameType`)
value to look up the type-specific description field:

| Subject class | Type URI property | Description field on KGType |
|---|---|---|
| KGEntity | `hasKGEntityType` | `hasKGEntityTypeDescription` |
| KGFrame | `hasKGFrameType` | `hasKGFrameTypeDescription` |
| KGDocument | `hasKGDocumentType` | `hasKGDocumentTypeDescription` |
| KGSlot | `hasKGSlotType` | `hasKGSlotTypeDescription` |

If the subject has no type URI set, it is **skipped** for `type_description`
mode, or indexed without the type portion for `properties_type` mode.

### 3.3 Search Text Source Modes

The `source_type` column on `search_mapping` controls what text is built for
vectorization/FTS. Replace the current `source_type` + `include_type_desc`
pair with a single enum:

```python
class SearchTextSource(str, Enum):
    """What goes into the indexed search text for a mapping."""
    type_description = "type_description"    # KGType description only (typical)
    properties      = "properties"           # Subject's own properties only (typical)
    properties_type = "properties_type"      # Properties + type description (rare)
    default         = "default"              # All literals on subject (legacy)
```

| Mode | What gets indexed | Typical use case |
|------|-------------------|------------------|
| `type_description` | Just the KGType description from `sp_kg_types` | "What kind of thing is this?" — semantic type search |
| `properties` | Subject's own property values (from mapping child table) | Entity/document content search |
| `properties_type` | Subject properties + type description appended | Rare — when both content and type context matter |
| `default` | All literal triples on the subject | Legacy/fallback |

**DB change**: ~~Drop `include_type_desc` boolean column~~ **DONE** (Jun 18).
The `source_type` column now carries this information. `type_description` and
`properties_type` imply a type description lookup; `properties` and `default`
do not. Migration script: `migrate_drop_include_type_desc.py`.

### 3.4 Vector Populator Integration

When building search text for a subject in space X:

1. Resolve the mapping rule (existing logic).
2. Based on `rule.source_type`:
   - `type_description` → read subject's type URI (e.g. `hasKGEntityType`),
     look up description from `sp_kg_types`, use **only** that text.
   - `properties` → build text from mapped properties (no type lookup).
   - `properties_type` → build text from properties, **then** append the
     type description.
   - `default` → all literals (existing behavior).
3. For modes that need the type description, call
   `KGTypeDescriptionLookup.get_description(conn, type_uri)` to fetch from
   `sp_kg_types`.

This is a **cross-space read** — the populator's connection reads from the
`sp_kg_types` tables while operating on space X's vector tables.

### 3.5 REST API Changes

| Route | Change |
|---|---|
| `GET /api/graphs/kgtypes` | Default to `space_id=sp_kg_types` when no space_id provided. Continue to accept explicit space_id for backward compat during migration. |
| `POST/PUT/DELETE /api/graphs/kgtypes` | Write to `sp_kg_types` by default. Reject writes to other spaces once migration is complete (or keep as admin-only override). |
| New: `GET /api/kgtypes/description?type_uri=...` | Lightweight endpoint returning just the description text for a type URI (used by populators and UI). |

### 3.6 Frontend Changes

| Component | Change |
|---|---|
| **KG Types page** | Remove space selector; always operate on `sp_kg_types`. |
| **TypeURIPicker** | Remove `spaceId` prop; hardcode `sp_kg_types` in API call. |
| **Sidebar** | Move "KG Types" from per-space section to top-level (alongside Entity Registry, Agent Registry). |
| **KG Type Detail** | Same — no space selector needed. |

---

## 4. Implementation Strategy

> **No migration needed** — there are no existing per-space types to migrate.
> The system starts fresh with `sp_kg_types` as the sole location for KG Types.

### Phase 1: Bootstrap system space

1. **Create `sp_kg_types` at startup** — add to `startup_event()` alongside
   entity_registry init. Call `space_manager.create_space_with_tables()` if
   the space doesn't exist.
2. **Bootstrap KGType search infra** on `sp_kg_types` via existing
   `setup_kgtype_search()`.
3. **Mark as protected** — prevent user deletion of this system space.
4. **Route all KGType writes** to `sp_kg_types` exclusively.
5. **Stop bootstrapping per-space KGType indexes** — remove
   `setup_kgtype_search()` from `create_space`.

### Phase 2: Cross-space type description lookup

6. **Implement `KGTypeDescriptionLookup`** utility class.
7. **Wire into `vector_populator.py`** — handle `source_type` enum;
   `type_description` and `properties_type` modes look up from `sp_kg_types`.
8. **Wire into FTS populator** — same pattern for FTS text building.

### Phase 3: Frontend

9. **KG Types page** — remove space selector, always operate on `sp_kg_types`.
10. **TypeURIPicker** — remove `spaceId` prop, always fetch from `sp_kg_types`
    (shows all types regardless of which space the mapping is for).
11. **Sidebar** — move "KG Types" to top-level (alongside Entity Registry,
    Agent Registry).
12. **Create Mapping UI** — expose `source_type` enum as a clear selector
    so users understand what text goes into the index.

---

## 5. Detailed Task List

### 5.1 Backend — System Space Bootstrap

- [x] Add `SP_KG_TYPES = "sp_kg_types"` constant to `vitalgraph/constants.py`
- [x] `SpaceManager.initialize_from_database()` calls `_ensure_system_spaces()`:
  - [x] Check if `sp_kg_types` exists in SpaceManager
  - [x] If not, call `space_manager.create_space_with_tables("sp_kg_types", "KG Types", ...)`
  - [x] Call `setup_kgtype_search(conn, "sp_kg_types")` to bootstrap indexes
- [x] Add `sp_kg_types` to `PROTECTED_SPACES` frozenset (prevent deletion)
- [x] Migration script: `migrate_create_sp_kg_types.py` for existing databases

### 5.2 Backend — Remove Per-Space KGType Infrastructure

- [x] `setup_kgtype_search()` NOT called from `sparql_sql_schema.py` `create_space()`
  (comment in place: "kgtype_default search infra is NOT bootstrapped per-space")
- [x] KGType search infra only created in `sp_kg_types` system space

### 5.3 Backend — API Changes

- [x] `kgtypes_endpoint.py`: `space_id` defaults to `sp_kg_types` in all routes
- [x] `_types_graph()`: Returns `SP_KG_TYPES_GRAPH` when space_id is `sp_kg_types`
- [x] Endpoint: `GET /api/graphs/kgtypes/description?type_uri=X` — returns type description text
- [x] Auth: `require_space_read(current_user, SP_KG_TYPES)` on description endpoint
- [ ] Auth: system space write restricted to admin role (deferred)

### 5.4 Backend — Type Description Lookup

- [x] Created `vitalgraph/vectorization/kgtype_description_lookup.py`:
  - [x] `KGTypeDescriptionLookup` class with `mapping_type` constructor
  - [x] `get_description(conn, type_uri)` — SQL query against `sp_kg_types` tables
  - [x] `get_descriptions_batch(conn, type_uris)` — batch version
  - [x] `get_subject_type_uri(conn, space_id, subject_uuid, context_uuid)`
  - [x] `get_subject_type_uris_batch(conn, space_id, subject_uuids, context_uuid)`
  - [x] In-memory cache with 10-minute TTL + `invalidate_cache()` function
- [x] Type URI property mapping via `TYPE_URI_PROPERTIES` in constants:
  - [x] KGEntity: `hasKGEntityType`
  - [x] KGFrame: `hasKGFrameType`
  - [x] KGDocument: `hasKGDocumentType`
- [x] Update `search_mapping_manager.py`:
  - [x] Replace `include_type_desc` boolean with `source_type` enum values
  - [x] Update `create_mapping()` and `update_mapping()` to accept new values
  - [x] Update `MappingRule` dataclass: remove `include_type_desc`, `source_type`
    now carries `type_description` / `properties_type` variants
- [x] Update `search_text_builder.py`:
  - [x] Remove legacy `resolve_mapping()` + SQL (vector_mapping backward compat)
  - [x] Only `resolve_search_mapping()` remains (reads `search_mapping` tables)
  - [x] Handle `type_description` mode (return only type desc text)
  - [x] Handle `properties_type` mode (existing properties + type desc appended)
  - [x] `properties` and `default` unchanged
- [x] Wired into `vector_populator.py`:
  - [x] Batch path: `_needs_type_desc` flag, `KGTypeDescriptionLookup`, batch fetch
  - [x] Single-subject path: same lookup for incremental sync
  - [x] `type_description` mode: skip subjects without type desc
  - [x] `build_search_text(props, mapping_rule, type_description=type_desc)`
- [x] Wired into `fts_populator.py` (same pattern)
- [x] DB migration: `ALTER TABLE search_mapping DROP COLUMN include_type_desc`
  (migration script: `migrate_drop_include_type_desc.py`, executed Jun 18)
- [x] DB migration: `ALTER TABLE vector_mapping DROP COLUMN include_type_desc`
  (17 legacy vector_mapping tables cleaned up)

### 5.5 Backend — Cross-Space Re-Sync on Type Update

- [x] When a KGType is updated/created in `sp_kg_types`:
  - [x] Identify all spaces + indexes that have mappings with `source_type` in
    (`type_description`, `properties_type`)
  - [x] For each such space, find subjects whose type URI matches the updated type
  - [x] Schedule vector re-sync for those subjects (via `auto_sync.schedule_sync()`)
- [x] This can be async/background — type description changes are infrequent
- [x] Implementation: `vitalgraph/vectorization/kgtype_cross_space_sync.py`
  - `schedule_cross_space_sync()` — fire-and-forget background asyncio task
  - Iterates all spaces (except `sp_kg_types`), queries `search_mapping` for
    `source_type IN ('type_description', 'properties_type')`, finds affected
    subjects via `rdf_quad` join on type URI property, delegates to `schedule_sync()`
  - Wired into `kgtypes_endpoint.py` `_create_kgtypes` and `_update_kgtypes`

### 5.6 Frontend — Search Text Source Selector

- [x] Remove `include_type_desc` toggle from Create/Edit Mapping modals
  (`SearchMappings.tsx`, `SearchMappingDetail.tsx`, `IndexMappings.tsx`)
- [x] Remove `include_type_desc` from TypeScript types (`searchFts.ts`)
- [x] `source_type` selector in Create Mapping modal (`SearchMappings.tsx`):
  - Type Description only (from KG Types)
  - Properties only (specific URIs)
  - Properties + Type Description
  - Default (hasKGraphDescription + type desc)
  - Slots (slot content)
- [x] `source_type` selector in Edit Mapping detail (`SearchMappingDetail.tsx`)
- [x] `source_type` displayed in mapping list table column

### 5.7 Frontend — KG Types UI

- [x] `KGTypes.tsx`: Top-level at `/kg-types`, hardcoded `sp_kg_types`, no space redirect
- [x] `KGTypeDetail.tsx`: `spaceIdOverride: 'sp_kg_types'` — works without `:spaceId` in URL
- [x] `AbsObjectDetail.tsx`: Added `spaceIdOverride` to `ObjectDetailConfig` interface
- [x] `TypeURIPicker.tsx`: `spaceId` prop deprecated, hardcoded `sp_kg_types`
- [x] `Layout.tsx` sidebar: KG Types in "Knowledge Graph" section, links to `/kg-types`
- [x] `App.tsx` routes: `/kg-types`, `/kg-types/new`, `/kg-types/:kgTypeId` (top-level)
- [x] Legacy `/space/:spaceId/kg-types` routes kept for backward compat

---

## 6. Data Model

### Types graph in `sp_kg_types`

```
Graph: urn:vitalgraph:sp_kg_types:kg_types

<urn:kgtype:RestaurantEntity>
    vital:vitaltype    haley:KGEntityType ;
    vital:hasName      "RestaurantEntity" ;
    haley:hasKGraphDescription         "A restaurant business entity" ;
    haley:hasKGEntityTypeDescription   "Restaurants, cafes, and dining establishments" .
```

### Cross-space reference

An entity in `sp_my_data`:
```
<urn:entity:123>
    vital:vitaltype        haley:KGEntity ;
    haley:hasKGEntityType  <urn:kgtype:RestaurantEntity> ;
    haley:hasKGraphDescription "Joe's Pizza on Main Street" .
```

When vectorizing `urn:entity:123`, the populator:
1. Reads `hasKGEntityType` → `urn:kgtype:RestaurantEntity`
2. Calls `KGTypeDescriptionLookup.get_description("urn:kgtype:RestaurantEntity")`
   which queries `sp_kg_types` → returns `"Restaurants, cafes, and dining establishments"`
3. Calls `build_search_text(props, rule, type_description="Restaurants, cafes, ...")``

---

## 7. Design Decisions (Resolved)

| # | Decision | Resolution |
|---|----------|------------|
| 1 | **Cross-space read pattern** | Confirmed: populators will read from `sp_kg_types` quad tables. This establishes cross-space reads as a supported pattern. |
| 2 | **Search text source modes** | Replaced `include_type_desc` boolean with `source_type` enum: `type_description` (typical), `properties` (typical), `properties_type` (rare), `default` (legacy). UI must clearly present these modes. |
| 3 | **No migration needed** | There are no existing per-space KG Types to migrate. Start fresh with `sp_kg_types`. |
| 4 | **Single flat graph** | All types in one graph: `urn:vitalgraph:sp_kg_types:kg_types`. No multi-graph or provenance dimension. |
| 5 | **Type URIs are global** | No space-specific URI patterns to worry about. URIs are already space-agnostic. |
| 6 | **Fan-out re-sync** | Not needed initially. Existing indexes will use current descriptions; re-population on next scheduled rebuild picks up changes. |
| 7 | **Cache staleness** | Acceptable. LRU with TTL is sufficient; no event-driven invalidation needed. Descriptions change infrequently. |
| 8 | **TypeURIPicker** | Shows all types from `sp_kg_types` regardless of which space the mapping belongs to. |
| 9 | **KG Types as top-level** | Yes — KG Types becomes a global admin screen, not per-space. |

### Additional decisions (resolved Jun 18)

| # | Decision | Resolution |
|---|----------|------------|
| 10 | **Which description field** | Use the **type-specific** description property: `hasKGEntityTypeDescription` for entity types, `hasKGFrameTypeDescription` for frame types, etc. NOT `hasKGraphDescription`. |
| 11 | **Missing type URI fallback** | If a subject has no type URI set and `source_type=type_description`, skip indexing that subject (no text to index). For `properties_type`, index properties only (omit type desc portion). |
| 12 | **Existing `source_type` values** | Current values (`default`, `properties`, `concat_properties`) can be adjusted/renamed as needed during implementation. No hard backward compat constraint. |
| 13 | **Fuzzy mappings** | Separate from this enum. Fuzzy uses its own `fuzzy_mapping` table with property roles. Almost always uses the name property. `SearchTextSource` applies only to vector/FTS search mappings. |
| 14 | **KGType-indexing-KGTypes** | The `kgtype_default` mappings on `sp_kg_types` use `source_type=properties` — they index the type's own name + description. Not `type_description` (that would be circular). |

### Decisions (resolved Jun 18, continued)

| # | Decision | Resolution |
|---|----------|------------|
| 15 | **Legacy `vector_mapping` tables** | Dropped. Schema no longer creates them. `vector_mappings_endpoint.py` rewired to use `SearchMappingManager` (reads `search_mapping` tables). Legacy `mapping_manager.py` deleted. |
| 16 | **Legacy `resolve_mapping()` in `search_text_builder.py`** | Removed. Only `resolve_search_mapping()` (reads `search_mapping`) remains. |
| 17 | **`include_type_desc` column** | Fully removed from: DB schema, Pydantic models, REST endpoints, client endpoints, setup scripts, lifecycle helpers, frontend types, and all UI toggles. Migration script preserved as historical artifact. |

### Remaining open items

| # | Item | Notes |
|---|------|-------|
| 1 | **Batch pipeline integration** | For `type_description` and `properties_type` modes: batch-read type URIs from subjects, call `get_descriptions_batch()`, zip results. Only these two modes trigger cross-space reads. To be finalized during implementation. |
| 2 | **Cross-space read permissions** | Simplest approach: exempt `sp_kg_types` reads from space-level auth. Populators run server-side so no user auth involved. |
| 3 | **Performance** | Batch queries + LRU cache should keep overhead minimal. Profile during implementation. |

---

## 8. Implementation Status

### ✅ Phase 1 — Foundation (complete)

- [x] `SP_KG_TYPES` constant + `PROTECTED_SPACES`
- [x] `_ensure_system_spaces()` in `SpaceManager.initialize_from_database()`
- [x] Migration: `migrate_create_sp_kg_types.py` (idempotent, tested)
- [x] Per-space kgtype infra removed from `create_space()`
- [x] API defaults to `sp_kg_types`

### ✅ Phase 2 — Value Delivery (complete)

- [x] `KGTypeDescriptionLookup` with batch, single, and cache support
- [x] `vector_populator.py` wired for `type_description` and `properties_type` modes
- [x] `fts_populator.py` wired (same pattern)
- [x] `build_search_text()` handles all 4 source modes
- [x] Cache invalidation on KGType create/update/delete

### ✅ Phase 3 — Frontend (complete)

- [x] `KGTypes.tsx` — top-level `/kg-types`, no space redirect
- [x] `KGTypeDetail.tsx` — `spaceIdOverride: 'sp_kg_types'`
- [x] `AbsObjectDetail.tsx` — `spaceIdOverride` field added to config interface
- [x] `TypeURIPicker.tsx` — `spaceId` prop deprecated, hardcoded `sp_kg_types`
- [x] `Layout.tsx` — KG Types in Knowledge Graph sidebar section
- [x] `App.tsx` — top-level routes `/kg-types`, `/kg-types/new`, `/kg-types/:kgTypeId`
- [x] `source_type` selector in Create/Edit Mapping modals

### Completed pre-work (Jun 18)

- [x] **DB cleanup**: Dropped `include_type_desc` from all `search_mapping` and
  `vector_mapping` tables (migration + manual cleanup for 18+17 tables)
- [x] **Backend cleanup**: Removed `include_type_desc` from all models, endpoints,
  managers, schema, setup scripts, lifecycle helpers
- [x] **Legacy removal**: Deleted `mapping_manager.py` (dead code), removed
  `resolve_mapping()` from `search_text_builder.py`, rewired
  `vector_mappings_endpoint.py` to use `SearchMappingManager`
- [x] **Frontend cleanup**: Removed `include_type_desc` from TypeScript types
  and all UI toggles (SearchMappings, SearchMappingDetail, IndexMappings)

### Remaining (deferred)

- [x] Auth: restrict `sp_kg_types` writes to admin role
- [x] Cross-space re-sync on type update (Phase 2c — background job)
