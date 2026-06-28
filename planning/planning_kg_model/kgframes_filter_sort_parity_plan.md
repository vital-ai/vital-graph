# KGFrames Filtering & Sorting Parity with KGEntities

## Goal

Bring the `/api/kgframes` endpoint's filtering and sorting capabilities to parity with the `/api/kgentities` endpoint, and integrate `hasKGFormType` filtering to distinguish **Assertion** (standalone top-level) frames from **Aspect** (entity-enclosed / child) frames.

---

## Current State

### KGEntities (rich filtering)

**Sort**: Full property URI–based sorting via `_ENTITY_SORT_PROPERTIES` registry.

**Filters**:
| Parameter | Type | Description |
|---|---|---|
| `entity_type_uri` | uri | Filter by rdf:type |
| `search` | string | CONTAINS on `hasName` |
| `status` | uri | Exact match on `hasObjectStatusType` |
| `exclude_status` | uri | Exclude by status |
| `created_after` / `created_before` | dateTime | Range on `hasObjectCreationTime` |
| `modified_after` / `modified_before` | dateTime | Range on `hasObjectModificationDateTime` |
| `action_type` | uri | Has value in `hasKGActionTypeList` |
| `provenance_type` | uri | Exact match on `hasKGProvenanceType` |

**Property Filter Model** (`EntityPropertyFilter`):
- Extensible registry `_FILTERABLE_ENTITY_PROPERTIES` maps property URI → datatype.
- Operators per datatype: `eq`, `ne`, `gt`, `lt`, `gte`, `lte`, `contains`, `in`, `not_in`, `has`, `has_any`, `has_all`, `not_has`, `not_has_any`, `exists`, `not_exists`.

### KGFrames (basic filtering)

**Sort**: Hardcoded labels `("name", "uri", "created_date", "frame_type")`.

**Filters**: Only `search` (text match).

No type filter, no date range, no status, no property filter model.

---

## Design

### 1. Frame Property Registry

Create `_FILTERABLE_FRAME_PROPERTIES` (in a new `kgframes_model.py` or existing model file):

```python
_FILTERABLE_FRAME_PROPERTIES = {
    "http://vital.ai/ontology/vital-core#hasName":                        "string",
    "http://vital.ai/ontology/vital#hasObjectModificationDateTime":       "dateTime",
    "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime":          "dateTime",
    "http://vital.ai/ontology/haley-ai-kg#hasKGFormType":                 "uri",
    "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeURI":             "uri",
}

_FRAME_SORT_PROPERTIES = set(_FILTERABLE_FRAME_PROPERTIES.keys())
```

### 2. Frame Property Filter Model

Reuse or mirror `EntityPropertyFilter`:

```python
class FramePropertyFilter(BaseModel):
    property_uri: str
    operator: str
    value: Optional[Union[str, List[str]]] = None
```

Validate against `_FILTERABLE_FRAME_PROPERTIES` with same operator rules.

### 3. Form Type Integration (`hasKGFormType`)

The `form_type` parameter is the primary mechanism for separating frame scenarios:

| `form_type` value | Full URI | Returns |
|---|---|---|
| `Assertion` | `http://vital.ai/ontology/haley-ai-kg#KGFormType_Assertion` | Standalone top-level frames (independent facts) |
| `Aspect` | `http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect` | Entity-enclosed frames and child frames of Assertions |
| _(omitted)_ | — | All frames regardless of form type |

**SPARQL pattern:**
```sparql
?frame <http://vital.ai/ontology/haley-ai-kg#hasKGFormType> <http://vital.ai/ontology/haley-ai-kg#KGFormType_Assertion> .
```

The endpoint should accept either the short label (`Assertion`, `Aspect`) or the full URI, resolving short labels internally.

### 4. Endpoint Parameter Additions

Add to `GET /kgframes`:

| New Parameter | Type | Maps To |
|---|---|---|
| `form_type` | Optional[str] | Filter by `hasKGFormType` — short label or full URI |
| `frame_type_uri` | Optional[str] | Filter by `hasKGFrameTypeURI` (rdf:type of the frame) |
| `sort_by` | Optional[str] | Property URI (replaces current label-based sort) |
| `status` | Optional[str] | Filter by `hasObjectStatusType` |
| `exclude_status` | Optional[str] | Exclude by status |
| `created_after` | Optional[str] | ISO 8601 datetime range |
| `created_before` | Optional[str] | ISO 8601 datetime range |
| `modified_after` | Optional[str] | ISO 8601 datetime range |
| `modified_before` | Optional[str] | ISO 8601 datetime range |

### 5. SPARQL Query Updates

Update `_build_list_frames_query` and `_build_count_frames_query` to:
- Accept filter parameters.
- Generate FILTER clauses for date ranges, status, type URIs.
- Use property URI–based `ORDER BY` instead of label-based.

---

## Tasks

- [x] **1.** Create `_FILTERABLE_FRAME_PROPERTIES` and `_FRAME_SORT_PROPERTIES` registry.
- [x] **2.** Create `FramePropertyFilter` model (or reuse a shared base with `EntityPropertyFilter`).
- [x] **3.** Add `form_type` parameter to `/kgframes` endpoint with short-label resolution (`Assertion` → full URI).
- [x] **4.** Add remaining filter parameters (`frame_type_uri`, `status`, `exclude_status`, date ranges) to endpoint.
- [x] **5.** Migrate `sort_by` from label-based (`"name"`, `"uri"`, etc.) to property URI–based (matching entity pattern).
- [x] **6.** Update `_build_list_frames_query` SPARQL generation to handle `form_type` and all new filters.
- [x] **7.** Update `_build_count_frames_query` to match filter logic.
- [x] **8.** Set `hasKGFormType` automatically during frame creation:
  - `kgframe_create_impl.py` → `KGFormType_Assertion` on standalone frames.
  - `kgentity_create_impl.py` → `KGFormType_Aspect` on entity-enclosed frames (mixed payload path).
  - `kgentity_frame_create_impl.py` → `KGFormType_Aspect` on entity-enclosed frames (frame sub-endpoint path).
  - `kgframe_hierarchical_impl.py` → `KGFormType_Aspect` on child frames.
- [x] **9.** Update frontend KGFrames page to expose form-type filter (tabs: Assertions / Aspects / All).
- [x] **10.** Update mock endpoint (`mock_kgframes_endpoint.py`) to support new parameters.
- [x] **11.** Update TypeScript client (`kgframes_endpoint.ts`) and Python client (`client/endpoint/kgframes_endpoint.py`) to pass new parameters.
- [x] **12.** Add integration tests for form-type filtering and new filter/sort combinations.
- [ ] **13.** Backfill script: classify existing frames based on `kGGraphURI` presence.

---

## Implementation Notes (June 2026)

**Status: ✅ IMPLEMENTED (tasks 1–12) — 10/10 integration tests passing**

### Key files modified:
| File | Changes |
|---|---|
| `vitalgraph/model/kgframes_model.py` | Added `_FILTERABLE_FRAME_PROPERTIES`, `_FRAME_SORT_PROPERTIES`, `FramePropertyFilter`, `resolve_form_type` |
| `vitalgraph/endpoint/kgframes_endpoint.py` | Added filter/sort params to route, `_build_frame_filter_clauses` helper, property URI sorting |
| `vitalgraph/kg_impl/kgframe_create_impl.py` | Auto-set `KGFormType_Assertion` on standalone frames |
| `vitalgraph/kg_impl/kgentity_create_impl.py` | Auto-set `KGFormType_Aspect` on entity-enclosed frames (step 4b) |
| `vitalgraph/kg_impl/kgentity_frame_create_impl.py` | Auto-set `KGFormType_Aspect` in `assign_grouping_uris` |
| `vitalgraph/kg_impl/kgframe_hierarchical_impl.py` | Auto-set `KGFormType_Aspect` on child frames |
| `vitalgraph/client/endpoint/kgframes_endpoint.py` | Python client accepts all new filter/sort params |
| `vitalgraph/client/vitalgraph_client.py` | Delegating method updated with `**kwargs` |
| `vitalgraph/client/vitalgraph_client_inf.py` | Abstract interface updated |
| `vitalgraph/mock/client/endpoint/mock_kgframes_endpoint.py` | Signature updated |
| `vitalgraph/mock/client/mock_vitalgraph_client.py` | Delegate updated |
| `vitalgraph-client-ts/src/endpoint/KGFramesEndpoint.ts` | TS client accepts new params |
| `frontend/src/pages/KGFrames.tsx` | Form-type tabs, property URI sorting |
| `frontend/src/services/ApiService.ts` | Passes new params to client |

### Integration test:
`vitalgraph_client_test/test_kgframes_filter_sort.py` — 10 tests covering creation, form-type filtering, sorting, search, combined filters, and validation rejection.

---

## Reference Files

| File | Purpose |
|---|---|
| `vitalgraph/model/kgentities_model.py` | Entity property registry pattern to follow |
| `vitalgraph/endpoint/kgframes_endpoint.py` | Endpoint to update |
| `vitalgraph/kg_impl/kgentity_list_impl.py` | Entity SPARQL query pattern to mirror |
| `vitalgraph/mock/client/endpoint/mock_kgframes_endpoint.py` | Mock to update |
| `frontend/src/pages/KGFrames.tsx` | UI to update |
