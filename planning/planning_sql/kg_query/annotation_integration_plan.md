# VitalSigns Annotation API — VitalGraph Integration Plan

This document tracks the integration of VitalSigns' RDF annotation support
(`rdfs:label`, `rdfs:comment`, etc.) into VitalGraph.  It covers the proposed
API, impact analysis on VitalGraph subsystems, VitalGraph-side action items,
and a gap analysis of the VitalSigns implementation with resolution status.

---

## Summary of VitalSigns annotation API

VitalSigns is adding first-class support for RDF annotations (`rdfs:label`,
`rdfs:comment`, etc.) on GraphObjects.  Key points:

- **Separate storage** — Annotations live in an `_annotations` dict, not
  `_properties`.  They do not collide with domain properties like `hasName`.
- **Multi-value + multi-language** — Each annotation URI (e.g. `rdfs:label`)
  can hold multiple values, each with an optional language tag.
- **Convenience API**:
  ```python
  node.set_rdfs_label("My Node")
  node.set_rdfs_label("Mon Nœud", lang="fr")
  node.get_rdfs_label()              # → "My Node"
  node.get_rdfs_label(lang="fr")     # → "Mon Nœud"
  ```
- **General API**: `set_annotation()`, `add_annotation()`,
  `get_annotation()`, `get_annotations()`, `remove_annotation()` — all
  support language tags.
- **Attribute shorthand**: `node.rdfs_label = "Quick Label"`
- **Serialization**:
  - **RDF/N-Triples**: annotations emit standard triples with language tags:
    ```
    <urn:example:1> <rdfs:label> "My Node" .
    <urn:example:1> <rdfs:label> "Mon Nœud"@fr .
    ```
  - **JSON**: annotations appear under a separate `"annotations"` key:
    ```json
    {
      "URI": "urn:example:1",
      "type": "...",
      "hasName": "MyNode",
      "annotations": {
        "http://www.w3.org/2000/01/rdf-schema#label": [
          {"value": "My Node"},
          {"value": "Mon Nœud", "lang": "fr"}
        ]
      }
    }
    ```
  - **Property maps**: `to_property_map()` / `from_property_map()` include
    `"annotations"` when present.
- **Backward compatible** — Objects without annotations serialize identically
  to before (no `"annotations"` key emitted).
- **Deserialization** — Annotation URIs (`rdfs:label`, `rdfs:comment`, etc.)
  are detected before domain property lookup, so they route to `_annotations`,
  never to `_properties`.

---

## Impact on VitalGraph

### 1. Triplestore write path — annotation triples now emitted

When a GraphObject with annotations is written via `to_rdf()` or
`to_triples()`, `rdfs:label` triples (with language tags) are now included
in the output.  This means:

- **INSERT operations** will insert annotation triples alongside domain
  property triples.
- **DELETE + INSERT updates** (the current entity update path) will diff
  correctly — old annotation triples are deleted, new ones inserted — as
  long as the diff operates on the full triple set (which it does, since
  `to_rdf()` is used for both old and new states).
- **No code change required** if the write path already uses `to_rdf()` or
  `to_triples()` for serialization — the annotation triples come out
  automatically.

**Risk**: If any VitalGraph write path manually constructs triples (bypassing
`to_rdf()`), annotations would be silently dropped.  Verify that all write
paths use the VitalSigns serialization methods.

### 2. Triplestore read path — annotation triples now consumed

When reading from the triplestore, `from_rdf()` now routes annotation
predicates to `_annotations` instead of ignoring them or misrouting them to
`_properties`.

- **Existing data** without `rdfs:label` triples: no change (backward
  compatible).
- **New data** with `rdfs:label` triples: correctly round-trips through
  the triplestore.

**Risk**: If VitalGraph has any SPARQL CONSTRUCT queries that return
`rdfs:label` triples, those triples will now be parsed into annotations
rather than being silently ignored.  This is correct behavior but may
surface in test comparisons.

### 3. JSON / property map serialization — new `"annotations"` key

The `"annotations"` key will appear in JSON and property map output for
objects that have annotations.  Impact on VitalGraph:

- **Client ↔ server communication** (quad serialization): If the wire
  format uses JSON or property maps, annotation data will pass through
  transparently.  The client can set `rdfs:label` and the server will
  store it.
- **Entity graph cache**: Cached serialized forms will include annotation
  data.  Cache entries written before the VitalSigns update lack the
  `"annotations"` key; entries written after may include it.  Both are
  valid — `from_json()` handles the missing key gracefully.
- **API responses**: Entity data returned to clients will include
  `rdfs:label` values when present.  Clients that don't understand the
  `"annotations"` key will ignore it (standard JSON behavior).

### 4. Search — `rdfs:label` can now be populated

The "Future enhancement" section (Phase 6 in the sorting plan) identified
that `rdfs:label` storage was the blocker for multi-language search.
With the VitalSigns annotation API, that blocker is removed:

- `rdfs:label` values (with language tags) will be stored in the
  triplestore as standard RDF triples.
- The SPARQL search pattern `?entity rdfs:label ?label .
  FILTER(CONTAINS(LCASE(?label), ...))` will now match.
- Language-filtered search is feasible:
  `FILTER(LANG(?label) = "en")`.

**Impact on search alignment decisions (6n, 6o)**:

The earlier decision to **remove** `rdfs:label` from the KG query search
UNION (steps 6n, 6o) was based on the premise that `rdfs:label` is not
populated.  With the annotation API, this premise changes:

- **Option A**: Keep the removal (6n, 6o) as planned.  Re-add
  `rdfs:label` search in a future phase once annotations are actively
  used.  Simpler, avoids searching empty labels on existing data.
- **Option B**: Retain the `rdfs:label` UNION branch.  Entities without
  labels are unaffected (the UNION falls through to `hasName`).  Entities
  with labels get searched.  No extra implementation cost.
- **Option C**: Add a `search_lang` parameter to filter by language tag.
  This is the full multi-language search vision from the future
  enhancement section.

**Recommendation**: Proceed with **Option A** for now (remove `rdfs:label`
from search as planned).  Add it back as a deliberate feature once
annotation usage is established and a `search_lang` parameter is designed.
This avoids changing search behavior as a side effect of the serialization
upgrade.

### 5. `hasName` vs `rdfs:label` — relationship clarified

The annotation API documentation states: "They are independent of
`name` / `hasName` — setting one does not affect the other."  This confirms:

- `hasName` remains the canonical programmatic name (domain property).
- `rdfs:label` is the display label, potentially multilingual (annotation).
- Setting `rdfs:label` does **not** set `hasName` and vice versa.
- Search on `hasName` and search on `rdfs:label` are independent.

### 6. Entity property filtering — no change needed

The `_FILTERABLE_ENTITY_PROPERTIES` registry (Phase 6) operates on domain
properties (`hasName`, timestamps, status, entity type).  `rdfs:label` is
an annotation, not a domain property — it does not belong in the filter
registry.  Multi-value + multi-language semantics don't fit the current
single-value filter model.

Language-aware label filtering would be a separate feature if needed.

### 7. SPARQL UPDATE diff and cache invalidation

When an entity's `rdfs:label` annotations change, the SPARQL UPDATE diff
will include the added/removed `rdfs:label` triples.  Since these triples
have the entity URI as subject, the `collect_invalidation_targets()` change
detection (if working correctly per T0 in the entity timestamp management
plan) should detect the entity as modified and invalidate its cache.

If annotations are changed via a frame-style update (unlikely for
`rdfs:label` on the entity node itself), the modification time would also
need to be touched — but this is already covered by the entity update path.

---

## Action items (VitalGraph side)

| Item | Plan | Description | Status |
|------|------|-------------|--------|
| A1 | Sorting/Filtering | Proceed with 6n/6o (remove `rdfs:label` from search) as planned. Re-add in a future multi-language search phase. | **Done** — Removed `rdfs:label` UNION branch from `_build_frame_count_query()` in `kgquery_endpoint.py`. |
| A2 | Sorting/Filtering | Fix frame search bug (`vital-core:name` → `vital-core:hasName`) in 6o regardless. | **Done** — Fixed `vital-core:name` → `vital-core:hasName` in same location. Now matches `kg_query_builder.py`. |
| A3 | VitalGraph core | Verify all write paths use VitalSigns `to_rdf()` / `to_triples()` — no manual triple construction that would drop annotations. | **Done** — All write paths use `to_triples_list()` or `to_triples()`. Fast outbound path (`_graphobjects_to_quad_list_fast`) updated to emit annotation triples from `pm['annotations']` with language tags. |
| A4 | VitalGraph core | Verify the SPARQL→GraphObject read path uses `from_rdf()` and correctly handles annotation predicates. | **Done** — Three read paths updated to preserve `xml:lang` for annotation URIs: `kg_graph_retrieval_utils._bindings_to_objects()`, `kgentity_list_impl._bindings_to_graph_objects()`, `quad_format_utils._quad_list_to_graphobjects_fast()`. |
| A5 | VitalGraph core | Test round-trip: create entity with `rdfs:label` (+ language tag) → write to triplestore → read back → annotations preserved. | **Done** — `test_scripts/test_annotation_integration.py` (6 tests: quad round-trip, N-Quads text round-trip, SPARQL bindings path, domain property lang-tag stripping, outbound annotation emission, no-annotation backward compat). |
| A6 | Client | Confirm client serialization (quad format) transparently passes `"annotations"` key through without stripping it. | **Done** — Client uses `graphobjects_to_quad_list()` / `quad_list_to_graphobjects()` which now handle annotations. Both JSON Quads and N-Quads wire formats preserve annotation triples with language tags. |
| A7 | Future | Design multi-language search phase: `search_lang` parameter, `rdfs:label` UNION branch re-added, `LANG()` / `LANGMATCHES()` filters. | Future |

### Implementation details (Apr 30, 2026)

**Files modified:**

1. **`vitalgraph/utils/quad_format_utils.py`** — Three changes:
   - `_graphobjects_to_quad_list_fast()`: Iterates `pm.get('annotations', {})` after domain properties, emitting annotation quads with `"value"@lang` N-Quads encoding.
   - `_parse_nquads_object()`: Now returns `{"value": str, "lang": str}` dicts for language-tagged literals (previously stripped the language tag).
   - `_quad_list_to_graphobjects_fast()`: For non-annotation predicates, unwraps language-tagged dicts back to plain strings. For annotation predicates, keeps the dict so `from_property_maps()` can extract the language tag via `_parse_annotation_value()`.

2. **`vitalgraph/kg_impl/kg_graph_retrieval_utils.py`** — `_bindings_to_objects()`:
   Checks `o_data.get('xml:lang')` on SPARQL JSON bindings. When present and predicate is an annotation URI (`is_annotation_property(p)`), stores value as `{"value": str, "lang": str}` dict.

3. **`vitalgraph/kg_impl/kgentity_list_impl.py`** — `_bindings_to_graph_objects()`:
   Same fix as above. Also changed from first-value-wins (`if p not in props`) to multi-value accumulation (`list` append) so multiple annotations for the same URI are preserved.

4. **`test_scripts/test_annotation_integration.py`** — New test file with 6 test cases covering all code paths.

---

## Gap analysis — VitalGraph integration feedback (VitalSigns side)

The following gaps were identified in the annotation implementation when reviewing
integration with VitalGraph. Each gap is assessed against the current implementation
state and a remediation plan is provided.

### Gap 1 (Critical): Flat annotation keys in `from_property_map()`

**Problem**: VitalGraph builds property maps from SPARQL SELECT `?s ?p ?o` rows. When
the triplestore returns `rdfs:label` triples, the builder puts them as flat keys
(e.g. `properties["http://www.w3.org/2000/01/rdf-schema#label"] = "My Node"`), not
nested under an `"annotations"` key. The current `from_property_map()` only reads the
nested `"annotations"` kwarg — flat annotation keys in `properties` fall through to
`uri_dict.get(prop_uri)`, which returns `None` (since annotation URIs are not domain
properties), and the value is silently dropped.

**Current state**: FIXED.
- `from_property_map()` and `from_property_maps()` now check
  `is_annotation_property(prop_uri)` when `uri_dict` lookup fails, routing the value
  to `_annotations` instead of skipping it.
- Values are parsed via `_parse_annotation_value()` which accepts `str`, `dict`,
  rdflib `Literal`, or `AnnotationValue` (see Gap 2).
- This makes `from_property_map()` consistent with `from_rdf()` and `from_triples()`,
  which already check the annotation registry before domain property lookup.
- 7 tests added in `TestPropertyMapFlatAnnotations`.

### Gap 2 (Critical): Language tag preservation in SPARQL → property map

**Problem**: When VitalGraph's property map builder receives `Literal("Mon Nœud", lang="fr")`
from a SPARQL SELECT result, property maps are currently `str → str` — no slot for
language tags. The language tag is lost before reaching `from_property_map()`.

**Current state**: FIXED (VitalSigns side).
- `_parse_annotation_value(v)` helper in `GraphObject.py` accepts:
  - `AnnotationValue` — returned as-is
  - `dict` with `"value"` and optional `"lang"` keys
  - `rdflib.Literal` — extracts `.language`
  - `str` — plain string, no language tag
  - `list` of any of the above — multiple values for the same annotation URI
- The VitalGraph property map builder still needs updating (VitalGraph side) to either:
  (a) pass rdflib `Literal` objects through for annotation URIs, or
  (b) wrap annotation values as `{"value": str, "lang": str}` dicts.

### Gap 3: Annotation predicate registry extensibility

**Problem**: How is the set of annotation URIs defined? Is it extensible?

**Current state**: ALREADY HANDLED.
- `annotation_registry.py` defines `KNOWN_ANNOTATION_URIS` (frozen set of 6 standard
  RDFS/OWL annotation URIs).
- `_custom_annotation_uris` is a mutable set for runtime extensions.
- `register_annotation_property(uri)` / `unregister_annotation_property(uri)` allow
  adding custom annotation URIs (e.g. `skos:prefLabel`, `dcterms:description`).
- `is_annotation_property(uri)` checks both sets.

**Remediation**: None required. Could add documentation noting the extensibility
for VitalGraph consumers.

### Gap 4: Annotations on edges

**Problem**: Can edges carry annotations? The feedback requests that `_annotations`
live on `GraphObject` (the base class).

**Current state**: ALREADY HANDLED.
- `_annotations` is initialized in `GraphObject.__init__()`, which is the base class
  for all graph objects — nodes, edges, hyper-edges, and hyper-nodes.
- All annotation API methods (`get_annotation`, `set_annotation`, `add_annotation`,
  `remove_annotation`, convenience accessors) are defined on `GraphObject`.
- All serialization paths (RDF, triples, JSON, dict, property map) handle annotations
  at the `GraphObject` level.

**Remediation**: None required.

### Gap 5: Multi-value same-URI round-trip without language tags

**Problem**: Multiple annotations with the same URI and no language tag must round-trip
correctly — naïve implementations may take only the last value.

**Current state**: ALREADY HANDLED.
- `add_annotation()` appends to a list per URI — multiple values are preserved.
- `to_rdf()` emits one triple per annotation value.
- `from_rdf()` calls `add_annotation()` for each triple, building the list.
- `to_json()` serializes the list, `from_json()` iterates and calls `add_annotation()`
  for each entry.
- Existing tests (`test_annotation_support.py`) cover this case for RDF, triples,
  JSON, dict, and property map round-trips.

**Remediation**: None required. Could add an explicit test case for the exact scenario
described (two labels with no lang) to strengthen coverage.

### Gap 6: `AnnotationValue` class definition

**Problem**: The feedback requests clarification on `AnnotationValue` fields, equality
semantics, and datatype support.

**Current state**: ALREADY IMPLEMENTED.
- `AnnotationValue(IProperty)` with `value: str` and `lang: str | None` (inherited
  from `IProperty`).
- `__eq__` compares `(value, lang)` — `AnnotationValue("Hello", lang=None)` equals
  `AnnotationValue("Hello")`.
- `__eq__` also supports comparison with plain `str` (compares `self.value == other`).
- `__hash__` uses `(value, lang)`.
- `to_json()` / `from_json()` for serialization.

**Regarding datatype support**: The current implementation is string-only. RDF allows
typed annotations (e.g. `"42"^^xsd:integer` for `owl:deprecated`), but these are rare
for the supported annotation set. Adding a `datatype` field is a low-priority future
enhancement.

**Remediation**: Add a brief note to the `AnnotationValue` docstring about the
datatype limitation. No code change needed now.

### Gap 7: `remove_annotation` — removal modes

**Problem**: The feedback asks about removal by value, by lang, and by value+lang pair.

**Current state**: ALREADY HANDLED.
- `remove_annotation(uri)` — removes all values for that URI.
- `remove_annotation(uri, lang="es")` — removes values matching that language.
- `remove_annotation(uri, value="Hello")` — removes values matching that value (any
  language).
- `remove_annotation(uri, value="Hola", lang="es")` — removes the specific
  value+lang pair.

All four modes are implemented via the filter logic in `GraphObject.remove_annotation()`.

**Remediation**: None required. Could add explicit test cases for value-only and
value+lang removal modes.

### Gap 8: Bulk set with language map

**Problem**: The feedback requests a convenience method for setting labels for multiple
languages at once:
```python
node.set_rdfs_labels({"en": "Cat", "fr": "Chat", "de": "Katze"})
```

**Current state**: FIXED.
- `set_rdfs_labels(lang_map)` — replaces all `rdfs:label` annotations with a
  `{lang: value}` dict (use `None` key for no language tag).
- `set_rdfs_comments(lang_map)` — same for `rdfs:comment`.
- `set_annotations_by_lang(uri, lang_map)` — general version for any annotation URI.
- 6 tests added in `TestBulkSetAnnotations`.

### Gap 9: Annotation ordering not preserved through RDF

**Problem**: RDF triples are unordered, but `get_annotations()` returns a Python list.
After round-tripping through a triplestore, order may change.

**Current state**: The implementation does return a list and insertion order is
preserved within a single process. However, no ordering guarantee exists after
RDF/triplestore round-trip.

**Remediation plan**:
- Add a documentation note to `get_annotations()` stating that annotation order is
  not guaranteed after serialization/deserialization.
- No code change needed — this is inherent to RDF semantics.

**Priority**: Low — documentation only.

### Gap 10: Text indexing for search on annotations

**Problem**: If VitalGraph searches `rdfs:label` values, the triplestore may need a
text index on annotation predicates.

**Current state**: This is a VitalGraph/deployment concern, not a VitalSigns code
issue.

**Remediation**: No VitalSigns code change. Document that text search on annotations
may require backend index configuration. This aligns with action item A7
(future multi-language search phase).

### Gap resolution summary

| Gap | Status | Action | Priority |
|-----|--------|--------|----------|
| 1 | **Fixed** | Route flat annotation keys in `from_property_map()` via `is_annotation_property()` | High |
| 2 | **Fixed** | Accept `str`, `dict`, `Literal`, and `list` annotation values in property map path | High |
| 3 | Already handled | Registry is extensible via `register_annotation_property()` | — |
| 4 | Already handled | `_annotations` is on `GraphObject` base class | — |
| 5 | Already handled | Multi-value round-trip works; strengthen test coverage | Low |
| 6 | Already handled | Add docstring note about datatype limitation | Low |
| 7 | Already handled | All removal modes work; strengthen test coverage | Low |
| 8 | **Fixed** | Add `set_rdfs_labels(lang_map)` convenience method | Low |
| 9 | Documentation | Note that ordering is not guaranteed after round-trip | Low |
| 10 | N/A (VitalGraph) | No VitalSigns change; document index requirements | — |

### Implementation details for Gap 1 + Gap 2

These were the only code changes required. They were done together since Gap 2
extends the Gap 1 fix.

**Step 1**: In `from_property_map()`, after the `uri_dict.get(prop_uri)` lookup fails
and before `continue`, add an `is_annotation_property(prop_uri)` check:

```python
from vital_ai_vitalsigns.impl.annotation_registry import is_annotation_property

for prop_uri, value in properties.items():
    if value is None:
        continue
    entry = uri_dict.get(prop_uri)
    if entry:
        # ... existing domain property handling ...
    elif is_annotation_property(prop_uri):
        # Route to annotations — accept multiple value formats
        if isinstance(value, list):
            for v in value:
                graph_object.add_annotation(prop_uri, _parse_annotation_value(v))
        else:
            graph_object.add_annotation(prop_uri, _parse_annotation_value(value))
    # else: skip unknown predicate
```

**Step 2**: Add a helper `_parse_annotation_value(v)` that handles the formats from
Gap 2:

```python
def _parse_annotation_value(v):
    """Convert various value formats to AnnotationValue."""
    if isinstance(v, AnnotationValue):
        return v
    if isinstance(v, dict):
        return AnnotationValue(v["value"], lang=v.get("lang"))
    # rdflib Literal
    if hasattr(v, 'language'):
        return AnnotationValue(str(v), lang=v.language)
    return AnnotationValue(str(v))
```

**Step 3**: Apply same changes to `from_property_maps()`.

**Step 4**: Tests covering:
- Flat `rdfs:label` key in property map (string value, no lang)
- Flat `rdfs:label` key with `{"value": ..., "lang": ...}` dict value
- Flat `rdfs:label` key with rdflib `Literal` value preserving language
- Flat `rdfs:label` key with list of values (multi-value)
- Mixed: flat annotation keys + nested `"annotations"` kwarg (both present)
