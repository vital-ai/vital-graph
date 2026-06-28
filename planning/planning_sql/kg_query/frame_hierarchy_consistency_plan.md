# Frame Hierarchy Consistency Plan

## Overview

Both the **entity frames endpoint** (`/kgentities/kgframes`) and the **top-level frames endpoint** (`/kgframes`) must have consistent behavior when operating on frames that participate in parent-child hierarchies via `Edge_hasKGFrame` edges. This document captures the required checks, missing implementations, and needed tests.

---

## 1. Delete: Child-Check and Cascade Logic

### Current State

| Behavior | Entity Frames (`/kgentities/kgframes`) | Top-Level Frames (`/kgframes`) |
|---|---|---|
| `recursive=false` (default): fail if children exist | ✅ Implemented | ✅ Implemented |
| `recursive=true`: cascade-delete all descendants | ✅ Implemented | ✅ Implemented |
| Meaningful error message listing children | ✅ Implemented | ✅ Implemented |
| Client `recursive` parameter | ✅ `delete_entity_frames` | ✅ `delete_kgframe`, `delete_kgframes_batch`, etc. |

### Action Items

- [x] **Verify edge cleanup on cascade delete**: `KGEntityFrameDeleteProcessor` was already correct — it discovers `Edge_hasEntityKGFrame` and `Edge_hasKGFrame` (destination) edges via dedicated methods. **Bug found in `_delete_frame_from_backend`** (top-level endpoint): it was NOT cleaning up `Edge_hasKGFrame` or `Edge_hasEntityKGFrame` edges. **Fixed** — now uses `frameGraphURI`-based deletion (see §6) plus typed structural edge cleanup.
- [x] **Verify slot cleanup on cascade delete**: both paths now use `frameGraphURI` grouping to find and delete all frame graph members (frame, slots, slot edges) in a single pass. Previous `_delete_frame_from_backend` used `Edge_hasKGSlot` join; `_replace_entity_frames` had a **slot orphaning bug** — it deleted edges by source/destination but never touched the slot objects themselves. Both are now fixed.
- [x] **Add test**: delete a frame with grandchildren via top-level `/kgframes` endpoint — `case_kgframe_hierarchy.py::test_recursive_delete`.

---

## 2. Update: Parent Validation

### Current State

| Behavior | Entity Frames | Top-Level Frames |
|---|---|---|
| Ownership validation (frame belongs to entity) | ✅ Including deep hierarchy walk-up | N/A (no entity scoping) |
| Parent-child validation (`parent_frame_uri` → frame has `Edge_hasKGFrame`) | ✅ via `validate_frame_parent_relationship` | ✅ Implemented in `_handle_update_mode` |

### Required: Top-Level Frames Parent Validation

When `POST /kgframes` is called with `parent_uri` and `operation_mode=update`, the endpoint should:

1. Verify that `parent_uri` exists and is a valid `KGFrame`.
2. Verify that each frame being updated is a child of `parent_uri` via an `Edge_hasKGFrame` edge (source=parent, destination=frame).
3. Return a clear error if validation fails.

### Action Items

- [x] **Implement parent validation in `_handle_update_mode`** in `kgframes_endpoint.py`: when `parent_uri` is provided, validate the parent-child relationship before proceeding with the update.
- [x] **Add test**: update a frame via `/kgframes` with `parent_uri` — `case_kgframe_hierarchy.py::test_update_validates_parent`.

---

## 3. Update Modes: Replace-With-Children vs Update-Frame-Only

### Concept

Two distinct update semantics for hierarchical frames:

1. **Replace frame graph** (deep replace): Replace the target frame AND all of its descendant frames/slots with a new frame graph provided in the request body. The old subtree is removed and the new one is inserted. This is a "subtree swap."

2. **Update frame only** (shallow update): Update properties of the target frame itself without affecting any of its children. Children remain unchanged.

### Current State

- The current `operation_mode=update` path updates the frame's own properties and slots but does **not** explicitly address what happens to children.
- ~~There is no explicit `replace` mode that removes the old subtree and inserts a new one.~~ `replace` mode is now implemented on both endpoints.

### Design Proposal

Add a new parameter or operation mode to distinguish the two behaviors:

| Mode | Behavior |
|---|---|
| `update` (existing) | Update the target frame's properties/slots only. Children are untouched. |
| `replace` (new) | Delete the target frame's entire subtree (all descendants + their slots/edges), then insert the new frame graph from the request body. Preserves the parent→target edge. |

### Action Items

- [x] **Audit current `update` behavior**: confirmed via `test_update_preserves_children` — shallow update does NOT affect children.
- [x] **Design `replace` mode**: `operation_mode=replace` preserves the root frame URI. Deletes all descendants + slots + edges, then re-inserts from request body. Parent→frame edge is recreated by the CREATE phase.
- [x] **Implement `replace` mode** for both entity frames (`_replace_entity_frames`) and top-level frames (`_handle_replace_mode`). Added `REPLACE` to both `OperationMode` enums.
- [x] **Add tests for both modes**:
  - `update` mode: `case_kgframe_hierarchy.py::test_update_preserves_children`
  - `replace` mode: `case_kgframe_hierarchy.py::test_replace_mode`

---

## 4. Test Matrix

| # | Test Case | Endpoint | Status |
|---|---|---|---|
| 1 | Delete frame with children fails (recursive=false) | Entity frames | ✅ Exists |
| 2 | Delete frame with children cascades (recursive=true) | Entity frames | ✅ Exists |
| 3 | Delete frame with children fails (recursive=false) | Top-level frames | ✅ `case_kgframe_hierarchy.py::test_delete_fails_if_children` |
| 4 | Delete frame with children cascades (recursive=true) | Top-level frames | ✅ `case_kgframe_hierarchy.py::test_recursive_delete` |
| 5 | Delete frame with grandchildren cascades | Top-level frames | ✅ (covered by test_recursive_delete) |
| 6 | Update frame with parent_uri validates relationship | Entity frames | ✅ Exists |
| 7 | Update frame with parent_uri validates relationship | Top-level frames | ✅ `case_kgframe_hierarchy.py::test_update_validates_parent` |
| 8 | Update grandchild frame passes ownership validation | Entity frames | ✅ Fixed (walk-up in `kgentity_frame_update_impl.py`) |
| 9 | Update frame (shallow) preserves children | Top-level frames | ✅ `case_kgframe_hierarchy.py::test_update_preserves_children` |
| 10 | Replace frame graph (deep) removes old children | Top-level frames | ✅ `case_kgframe_hierarchy.py::test_replace_mode` |
| 11 | Replace with child + grandchild hierarchy | Top-level frames | ✅ `case_kgframe_hierarchy.py::test_replace_with_hierarchy` |
| 12 | Replace flat (removes old children, preserves root) | Entity frames | ✅ `case_kgentity_frame_hierarchical.py::test_replace_flat` |
| 13 | Replace with child + grandchild hierarchy | Entity frames | ✅ `case_kgentity_frame_hierarchical.py::test_replace_with_hierarchy` |

---

## 5. frameGraphURI Grouping Convention

All frame graph members (frame, slots, slot edges) carry `hasFrameGraphURI` pointing to their parent frame's URI. This is the **primary mechanism** for efficient lookups during delete, replace, and retrieval.

### Service responsibility

The service sets **both** grouping URIs on all objects during **create** and **update**. Clients must **never** set `kGGraphURI` or `frameGraphURI` — these are server-enforced.

| Property | Set by | Scope | Purpose |
|---|---|---|---|
| `kGGraphURI` | Server only (entity endpoint) | All objects under an entity | Entity-level graph retrieval |
| `frameGraphURI` | Server only (both endpoints) | All objects under a frame | Frame-level graph retrieval |

| Endpoint | Create path | Update path |
|---|---|---|
| `/kgframes` | `KGFrameCreateProcessor.create_frame()` + `_set_frame_grouping_uris` (frameGraphURI only) | Same processor |
| `/kgentities/kgframes` | `KGEntityFrameCreateProcessor` sets both `kGGraphURI` and `frameGraphURI` | `_update_entity_frames` sets both |

### Delete / replace usage

Both endpoints now use the `frameGraphURI` pattern for deletion:

```sparql
DELETE { GRAPH <G> { ?s ?p ?o } }
WHERE  { GRAPH <G> { ?s haley:hasFrameGraphURI <frame_uri> . ?s ?p ?o } }
```

This single query removes the frame, all its slots, and all slot edges. A follow-up query deletes `<frame_uri> ?p ?o` as a safety fallback (in case the frame itself lacks `hasFrameGraphURI` pointing to itself). Structural edges (`Edge_hasKGFrame`, `Edge_hasEntityKGFrame`) are cleaned up separately by type.

### Bug fixed

`_replace_entity_frames` previously used generic edge source/destination matching which **orphaned slot triples** — edges from the frame were removed but slot objects remained. Now uses `frameGraphURI` grouping consistently.

---

## 6. Files Involved

- **Server endpoints**:
  - `vitalgraph/endpoint/kgentities_endpoint.py` — entity frames CRUD
  - `vitalgraph/endpoint/kgframes_endpoint.py` — top-level frames CRUD
- **Processors**:
  - `vitalgraph/kg_impl/kgframe_create_impl.py` — **new** standalone frame create processor (frameGraphURI only, no entity concepts)
  - `vitalgraph/kg_impl/kgframe_hierarchical_impl.py` — child frame creation (updated: frameGraphURI only, no kGGraphURI)
  - `vitalgraph/kg_impl/kgentity_frame_create_impl.py` — entity-scoped frame create (sets both kGGraphURI + frameGraphURI)
  - `vitalgraph/kg_impl/kgentity_frame_update_impl.py` — entity frame update + ownership validation
  - `vitalgraph/kg_impl/kgentity_frame_delete_impl.py` — entity frame deletion (uses `frameGraphURI` discovery)
  - `vitalgraph/kg_impl/kg_sparql_query.py` — `find_child_frames`, `collect_all_descendants`, `validate_frame_parent_relationship`
- **Grouping URI support**:
  - `vitalgraph/sparql/grouping_uri_queries.py` — `GroupingURIQueryBuilder` (`build_frame_graph_subjects_query`, `build_entity_graph_subjects_query`)
- **Client**:
  - `vitalgraph/client/endpoint/kgentities_endpoint.py` — entity frames client (`operation_mode` added to `create_entity_frames`)
  - `vitalgraph/client/endpoint/kgframes_endpoint.py` — top-level frames client (`entity_uri` removed, `recursive` passthrough on all delete wrappers)
- **Tests**:
  - `vitalgraph_client_test/kgframes/case_kgframe_hierarchy.py` — top-level frames hierarchy tests (new)
  - `vitalgraph_client_test/kgentities/case_kgentity_frame_hierarchical.py` — entity frames hierarchy tests
  - `vitalgraph_client_test/test_kgentities_endpoint.py` — test runner

---

## 7. kGGraphURI Enforcement: Server-Side Only

### Change

`kGGraphURI` is a server-side concept. Clients and tests must **never** set it on objects before sending them to the server. The server assigns it based on context:

- **Entity endpoint** (`/kgentities/kgframes`): server sets `kGGraphURI` = entity URI on all frame graph members.
- **Standalone endpoint** (`/kgframes`): server does **not** set `kGGraphURI` at all — only `frameGraphURI`.

### Files cleaned

| File | Change |
|---|---|
| `vitalgraph/client/endpoint/kgframes_endpoint.py` | Removed `entity_uri` parameter from all methods |
| `vitalgraph_client_test/kgframes/case_kgframe_hierarchy.py` | Removed all `.kGGraphURI =` and `.frameGraphURI =` assignments; removed `entity_uri` from helper signatures |
| `vitalgraph_client_test/kgentities/case_kgentity_frame_hierarchical.py` | Same — removed all grouping URI assignments from test object builders |
| `vitalgraph_client_test/entity_graph_lead/case_entity_server_properties.py` | Removed `frame.kGGraphURI = uri` from 4 test methods |
| `vitalgraph_client_test/multi_kgentity/case_create_relations.py` | Removed `product.kGGraphURI = product.URI` |

### Principle

Clients send **structural data** (URIs, names, types, edge source/destination). The server assigns **grouping metadata** (`kGGraphURI`, `frameGraphURI`) based on the endpoint and operation context. Any client-supplied values for these properties are overwritten by the server.
