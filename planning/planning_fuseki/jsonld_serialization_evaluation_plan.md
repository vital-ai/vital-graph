# Evaluation: Should VitalGraph Remove JSON-LD as Primary RDF Serialization Format?

## 1. Problem Statement

JSON-LD was initially chosen as VitalGraph's primary wire format for sending and receiving RDF data through the REST API. While promising in theory — JSON-compatible, W3C standard, familiar to web developers — it has proven difficult in practice and introduces subtle, hard-to-debug problems throughout the codebase.

This document evaluates whether to replace JSON-LD with a simpler RDF serialization format, reviews alternatives, and incorporates broader community experience.

---

## 2. Current JSON-LD Usage in VitalGraph

### 2.1 Scope of Impact

JSON-LD is deeply embedded across the VitalGraph codebase:

- **~700 references** to `JsonLdDocument`, `JsonLdObject`, or `JsonLdRequest` across **47 files**
- **~250 references** to `to_jsonld` / `from_jsonld` across **36 files**
- **Pydantic models**: `JsonLdObject`, `JsonLdDocument`, `JsonLdRequest` discriminated union (`vitalgraph/model/jsonld_model.py`)
- **Every major endpoint**: KGEntities, KGFrames, KGTypes, KGRelations, Objects, Files, Triples
- **Client library**: REST client, mock client, all endpoint adapters
- **Utility layers**: `kg_jsonld_utils.py`, `vitalsigns_helpers.py`, `graphobject_jsonld_utils.py`, `data_format_utils.py`

### 2.2 The Conversion Pipeline

Every request/response currently traverses this chain:

```
Client (VitalSigns objects)
  → to_jsonld() / to_jsonld_list()
  → JSON-LD dict
  → Pydantic model (JsonLdObject or JsonLdDocument)
  → HTTP JSON body
  → Server receives JSON
  → Pydantic model validation (discriminated union)
  → model_dump(by_alias=True)
  → from_jsonld() / from_jsonld_list()
  → VitalSigns GraphObjects
  → to_triples()
  → Backend storage (PostgreSQL/Fuseki)
```

And in reverse for responses. Every step in this chain is a potential failure point.

### 2.3 Specific Problems Encountered

1. **Discriminated union complexity**: The `JsonLdRequest` discriminated union (`JsonLdObject` vs `JsonLdDocument`) requires a `jsonld_type` discriminator field, content-based fallback detection, and special handling for single-vs-multiple objects. The `JsonLdDocument` validator even *rejects* single-element `@graph` arrays, forcing callers to switch between two models.

2. **Field aliasing fragility**: Pydantic `@context`, `@id`, `@type`, `@graph` require `alias`/`serialization_alias` and `by_alias=True` everywhere. Forgetting `by_alias=True` on any `model_dump()` call silently produces `context`/`id`/`type`/`graph` keys instead of `@context`/`@id`/`@type`/`@graph`, breaking downstream parsing.

3. **Context management overhead**: Every response constructs or references a `@context` object. Different endpoints use different context strings. Empty results still need context. Context objects can contain invalid keyword redefinitions that must be stripped (see `fix_jsonld_fields` in `vitalsigns_helpers.py`).

4. **Round-trip data loss**: JSON-LD does not guarantee lossless round-tripping for all RDF constructs. The W3C itself acknowledges this — nested RDF lists, blank node properties, and numeric precision can be lost or corrupted during JSON-LD ↔ RDF conversion (see [w3c/json-ld-bp#13](https://github.com/w3c/json-ld-bp/issues/13), [json-ld/json-ld.org#237](https://github.com/json-ld/json-ld.org/issues/237)).

5. **Single vs. multiple object gymnastics**: Constant branching throughout the codebase:
   ```python
   if isinstance(data, JsonLdObject):
       # Single object - wrap in @graph array
       context = jsonld_data.pop('@context', {})
       jsonld_document = {'@context': context, '@graph': [jsonld_data]}
   else:
       # Already a document with @graph
       jsonld_document = jsonld_data
   ```
   This pattern appears in nearly every endpoint.

6. **VitalSigns conversion overhead**: Converting between VitalSigns GraphObjects and JSON-LD dicts is non-trivial. Property objects must be cast (`str(obj.URI)`), `@type` fields may be arrays or strings, and the `fix_jsonld_fields` function must recursively rewrite `id`→`@id` and `type`→`@type` throughout documents.

7. **Debugging difficulty**: When something goes wrong in the pipeline, it's hard to identify whether the issue is in Pydantic validation, JSON-LD structure, VitalSigns conversion, or the actual data. The intermediate JSON-LD representation obscures the underlying triple data.

---

## 3. Broader Community Opinion on JSON-LD

### 3.1 Manu Sporny (JSON-LD Co-Creator)

The JSON-LD co-creator himself described the motivation as "burning most of the Semantic Web technology stack (TURTLE/SPARQL/Quad Stores) to the ground and starting over." JSON-LD was designed to make RDF palatable to JSON developers who would never touch Turtle or SPARQL. It was *not* designed as an efficient internal transport between RDF-aware systems.

### 3.2 Dr. Chuck Severance (Performance Analysis)

In ["Unconstrained JSON-LD Performance Is Bad for API Specs"](https://www.dr-chuck.com/csev-blog/2016/04/json-ld-performance-sucks-for-api-specs/), Dr. Chuck found:

> "There is over an order of magnitude of performance cost to parse JSON-LD than to parse JSON because of the requirement to transform an infinite number of equivalent forms into a single canonical form."

His conclusion: **"Unconstrained JSON-LD should never be used for non-trivial APIs — period."**

His recommended compromise: if you must use JSON-LD, require a canonical serialized JSON form where the `@context` can be completely ignored and the document parsed as plain JSON.

### 3.3 Ontola (RDF Serialization Format Comparison)

From [ontola.io/blog/rdf-serialization-formats](https://ontola.io/blog/rdf-serialization-formats):

> "JSON-LD is **difficult and costly to parse** if you need the RDF data instead of the JSON object. Parsing JSON-LD often involves requesting data from the internet, and needs clever caching to be performant. This complexity in parsing limits how many (bug-free) JSON-LD parsers are available."

Their recommendation for JSON-LD: **"Use JSON-LD if you already have a RESTful JSON API, and if performant RDF parsing is not crucial."**

Their TL;DR recommendations:
- **N-Triples / N-Quads**: "Decent performance and high compatibility"
- **Turtle**: "Manually read & edit your RDF"
- **HexTuples (NDJSON)**: "High performance in JS with dynamic data"
- **JSON-LD**: "Improve your existing JSON API, and don't need performant RDF parsing"

### 3.4 Hacker News Community

Recurring themes from HN discussions ([14474222](https://news.ycombinator.com/item?id=14474222), [35322889](https://news.ycombinator.com/item?id=35322889)):

- JSON-LD is a **compromise format** — it does JSON okay and RDF okay, but neither well
- N3/Turtle advocates argue JSON-LD "made the same mistake as RDF/XML" by shoehorning graph data into a tree format
- Multiple commenters describe avoiding JSON-LD due to its association with Semantic Web complexity
- The "infinite equivalent forms" problem (any JSON-LD document can be restructured many ways while remaining semantically identical) makes testing and comparison difficult

### 3.5 W3C Round-Tripping Issues

The W3C JSON-LD Best Practices working group explicitly acknowledges that **neither direction of round-tripping is guaranteed**:

- **RDF → JSON-LD → RDF**: Some RDF constructs cannot be serialized (e.g., rdf:List of rdf:Lists)
- **JSON-LD → RDF → JSON-LD**: Some JSON-LD constructs are not valid RDF (e.g., blank node properties)

For an RDF-native system like VitalGraph where data integrity matters, this is a serious concern.

---

## 4. Alternative Formats

### 4.1 N-Quads (.nq)

**The strongest candidate for VitalGraph.**

| Aspect | Assessment |
|--------|-----------|
| **Parsing** | Trivially simple — one line per quad: `<s> <p> <o> <g> .` |
| **Performance** | Fastest to parse/serialize of all text RDF formats |
| **Fidelity** | Lossless — every RDF quad is represented exactly |
| **Named graphs** | Native support (the 4th element) — critical for VitalGraph's graph-based architecture |
| **Streaming** | Line-oriented — supports streaming parse/serialize |
| **Tooling** | Universal support in RDF libraries (RDFLib, Jena, etc.) |
| **Human readability** | Verbose (full URIs, no prefixes) but unambiguous |
| **Compression** | Compresses well with gzip (HTTP Content-Encoding) |

**Why N-Quads fits VitalGraph:**
- VitalGraph already stores data as quads internally (subject, predicate, object, context/graph)
- No @context resolution needed
- No single-vs-document discrimination needed
- No field aliasing needed
- Eliminates the entire Pydantic JsonLd* model layer
- Direct mapping to/from VitalSigns `to_triples()` / `from_triples()`

### 4.2 Turtle / TriG (.ttl / .trig)

| Aspect | Assessment |
|--------|-----------|
| **Parsing** | Moderate complexity — supports prefixes, nesting, lists |
| **Performance** | Slower to parse than N-Quads due to prefix resolution |
| **Fidelity** | Lossless for RDF |
| **Named graphs** | TriG supports named graphs; plain Turtle does not |
| **Readability** | Excellent — best human-readable RDF format |
| **Use case** | Good for debugging, documentation, manual editing |

**Assessment**: Better as an optional output format for debugging, not as a primary transport.

### 4.3 JSON Quads (Proposed for VitalGraph)

**A JSON envelope with metadata and a results array of quad maps using standard RDF term encoding.**

```json
{
  "total_count": 3,
  "page_size": 100,
  "offset": 0,
  "results": [
    {"s": "<http://example.org/person1>", "p": "<http://schema.org/name>", "o": "\"Alice\"", "g": "<http://example.org/graph1>"},
    {"s": "<http://example.org/person1>", "p": "<http://schema.org/age>", "o": "\"30\"^^<http://www.w3.org/2001/XMLSchema#integer>", "g": "<http://example.org/graph1>"},
    {"s": "<http://example.org/person1>", "p": "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>", "o": "<http://schema.org/Person>", "g": "<http://example.org/graph1>"}
  ]
}
```

The envelope carries pagination metadata (or any other response metadata) alongside the quad data. Each quad in the `results` array is a simple `{s, p, o, g}` map. The `g` field may be omitted when the quad belongs to the default graph.

**Term encoding uses standard N-Quads rules inside JSON strings:**
- **URIs**: `<http://example.org/thing>` — angle brackets indicate URI
- **Plain string literals**: `"Alice"` — quoted
- **Typed literals**: `"30"^^<http://www.w3.org/2001/XMLSchema#integer>` — standard `^^` datatype notation
- **Language-tagged literals**: `"hello"@en` — standard `@` language tag
- **Blank nodes**: `_:b1` — standard blank node label

This means each field value is exactly the N-Quads term encoding placed inside a JSON string. Zero ambiguity, trivial to convert to/from N-Quads.

| Aspect | Assessment |
|--------|-----------|
| **Format** | JSON envelope with `results` array of `{s, p, o, g}` maps, N-Quads term encoding |
| **Parsing** | Standard JSON parser + thin RDF term extraction layer |
| **Fidelity** | Lossless — same encoding as N-Quads |
| **Named graphs** | Supported via `g` field |
| **Metadata** | Envelope carries pagination (`total_count`, `page_size`, `offset`) and other response metadata |
| **Tooling** | Custom but trivial — just N-Quads terms wrapped in JSON maps |
| **Human readability** | Better than N-Quads (structured), worse than Turtle |
| **Frontend friendly** | Standard JSON — `fetch()` + `response.json()`, no special parsers needed |

**Why this works well as a secondary format:**
- Frontend/TypeScript clients consume native JSON — no N-Quads parser library needed
- Pydantic models are trivial (see Section 5.5 for request vs response models)
- Conversion to/from N-Quads is mechanical (split/join terms)
- No `@context`, no `@graph`, no field aliasing, no discriminated unions
- Uses standard RDF term encoding — not inventing new semantics

**Prior art:**
- [W3C RDF/JSON](https://www.w3.org/TR/rdf-json/) — groups by subject (nested), more compact but harder to stream
- [HexTuples-NDJSON](https://github.com/ontola/hextuples) — uses positional JSON arrays instead of named maps, limited adoption
- [SPARQL Results JSON](https://www.w3.org/TR/sparql12-results-json/) — similar concept for variable bindings

Our JSON Quads format is simpler than all of these — flat maps with named keys and standard RDF encoding.

### 4.4 RDF Binary (Apache Thrift / Protobuf)

| Aspect | Assessment |
|--------|-----------|
| **Performance** | Highest possible — binary encoding |
| **Fidelity** | Lossless |
| **Readability** | None — requires tooling to inspect |
| **Tooling** | Apache Jena uses RDF Thrift internally |

**Assessment**: Overkill for a REST API. Better for internal sidecar communication.

---

## 5. Recommendation

### 5.1 Dual Wire Format: N-Quads (Default) + JSON Quads (Option)

Replace JSON-LD with two supported formats:

1. **N-Quads** (`application/n-quads`) — default server response format; standard RDF text format
2. **JSON Quads** (`application/json`) — JSON envelope format used by the Python client, frontend, and TypeScript clients

Format selection via `Content-Type` (request) and `Accept` (response) headers. Both formats represent the same quad data — conversion between them is trivial.

**Client default**: The Python client (`VitalGraphClient`) uses **JSON Quads** as its default format, since it needs pagination metadata (`total_count`, `page_size`, `offset`) returned in the response envelope.

**N-Quads pagination**: Since N-Quads is plain text with no envelope, pagination metadata is always conveyed via HTTP response headers (`X-Total-Count`, `X-Page-Size`, `X-Offset`) on N-Quads responses.

**Rationale:**
- Replaces the fragile `JsonLdObject`/`JsonLdDocument`/`JsonLdRequest` Pydantic models with simpler Pydantic models suited to the new formats
- Eliminates `@context` management, field aliasing (`by_alias=True`), and discriminated unions
- Eliminates JSON-LD ↔ VitalSigns conversion overhead and bugs
- Lossless round-tripping guaranteed by definition for both formats
- Direct alignment with VitalGraph's internal quad storage model
- JSON Quads keeps JSON-native clients (frontend, TypeScript) happy without reintroducing JSON-LD complexity
- Both formats share the same RDF term encoding — maintaining two is trivial unlike JSON-LD + anything else

### 5.2 Complete Removal of JSON-LD

JSON-LD will be removed entirely — not retained as an optional output format. Rationale:

- **No half-measures**: Keeping JSON-LD as an optional format means maintaining all the conversion code, Pydantic models, and test coverage for a fundamentally different serialization model. This defeats the purpose of simplification.
- **Maintenance burden**: Every bug fix or feature addition would need to be validated against JSON-LD's `@context` resolution, field aliasing, and discriminated unions.
- **Complexity creep**: Optional formats tend to become required over time as consumers start depending on them.
- **Clean break**: A complete removal allows deleting all JSON-LD-specific conversion code, utilities, and models with no residual maintenance cost.
- **JSON Quads replaces the need**: The JSON Quads format provides JSON-native access without any of JSON-LD's complexity.

Any external consumers needing JSON-LD can convert N-Quads to JSON-LD client-side using standard RDF libraries.

### 5.3 Why Two Formats Is Acceptable Here (Unlike JSON-LD + N-Quads)

Supporting both N-Quads and JSON Quads is fundamentally different from supporting JSON-LD alongside another format:

- **Same data model**: Both are flat lists of quads with identical RDF term encoding. JSON Quads is literally N-Quads terms wrapped in JSON maps.
- **Trivial conversion**: Converting between them is a mechanical string operation — no context resolution, no graph restructuring.
- **Simple Pydantic models**: `Quad`, `QuadRequest`, `QuadResponse` — no aliasing, no discriminated unions. `g` is omitted for default graph quads.
- **No branching logic**: Endpoints produce quads; the serialization layer formats them. No single-vs-document, no `@context`, no discriminated unions.

### 5.4 Pydantic Models: Request vs Response

Requests and responses have different shapes. The request is just quad data; the response includes metadata.

```python
from typing import List, Optional
from pydantic import BaseModel

class Quad(BaseModel):
    """A single RDF quad with N-Quads term encoding."""
    s: str                     # "<http://example.org/person1>"
    p: str                     # "<http://schema.org/name>"
    o: str                     # "\"Alice\"" or "<http://schema.org/Person>"
    g: Optional[str] = None    # "<http://example.org/graph1>" or omitted for default graph

# --- Request models (client → server) ---

class QuadRequest(BaseModel):
    """JSON Quads request body — just a list of quads, no metadata."""
    quads: List[Quad]

# --- Response models (server → client) ---

class QuadResponse(BaseModel):
    """JSON Quads response envelope — metadata + results."""
    total_count: int
    page_size: int
    offset: int
    results: List[Quad]
```

For **N-Quads** format, requests are plain text (`application/n-quads`) and responses are plain text with pagination in HTTP headers. No Pydantic models needed for the N-Quads path — just raw string parsing/serialization.

During the **transition phase**, both the new models and the existing `JsonLdObject`/`JsonLdDocument`/`JsonLdRequest` models coexist. The format detection middleware routes to the appropriate model based on `Content-Type`.

### 5.5 VitalSigns Integration Simplification

With N-Quads / JSON Quads, the conversion pipeline simplifies to:

```
Client (VitalSigns objects)
  → to_triples()
  → List of (s, p, o, g) tuples
  → Serialize as N-Quads text OR JSON Quads envelope
  → HTTP body
  → Server receives body
  → Parse N-Quads text OR JSON Quads envelope → (s, p, o, g) tuples
  → from_triples()
  → VitalSigns GraphObjects
  → Backend storage
```

This eliminates 4+ intermediate conversion steps. Pydantic models still define request/response structure — but they become straightforward models without `@`-prefixed field aliasing, discriminated unions, or context management.

---

## 6. Migration Plan

### Phase 0: Coexistence — Add New Formats Alongside JSON-LD (Low Risk)

JSON-LD remains fully functional. New formats are added in parallel, routed by content type detection. Zero changes to existing JSON-LD code.

1. Create `Quad`, `QuadRequest`, `QuadResponse` Pydantic models (`vitalgraph/model/quad_model.py`)
2. Add N-Quads serialization/deserialization utilities for VitalSigns GraphObjects
3. Add JSON Quads serialization/deserialization (quad list ↔ VitalSigns objects)
4. Implement `Content-Type` / `Accept` header detection middleware:
   - `application/n-quads` → N-Quads path
   - `application/json` with `quads` key in body → JSON Quads path
   - Everything else (including `application/json` with `@context`/`@graph`) → existing JSON-LD path
5. Add format-aware request parsing at each endpoint — thin adapter that converts incoming N-Quads or `QuadRequest` to VitalSigns objects, then calls existing backend logic
6. Add format-aware response serialization — thin adapter that converts VitalSigns objects to `QuadResponse` or N-Quads text based on `Accept` header
7. Verify round-trip fidelity for all KG object types (KGEntity, KGFrame, KGSlot, all Edge types) in both new formats
8. Benchmark N-Quads and JSON Quads vs JSON-LD for typical payloads

**Key point**: During this phase, all three formats work simultaneously. Existing JSON-LD clients are unaffected. New format can be tested endpoint-by-endpoint.

#### Phase 0 Implementation Status ✅

All Phase 0 items are implemented. Files created or modified:

**New files:**
- `vitalgraph/model/quad_model.py` — `Quad`, `QuadRequest`, `QuadResponse` Pydantic models
- `vitalgraph/utils/nquads_utils.py` — N-Quads serialization/deserialization for VitalSigns GraphObjects
- `vitalgraph/utils/json_quads_utils.py` — JSON Quads serialization/deserialization (quad list ↔ VitalSigns objects)
- `vitalgraph/utils/format_negotiation.py` — `WireFormat` enum, `Content-Type`/`Accept` header detection as FastAPI dependencies
- `vitalgraph/utils/format_adapter.py` — `parse_request_body`, `build_response`, `build_graphobjects_response` helpers

**Modified endpoints (format-aware GET + POST routes):**
- `vitalgraph/endpoint/kgentities_endpoint.py` — Full integration: GET routes detect `Accept` header and branch response serialization; POST route detects `Content-Type` and parses N-Quads/JSON Quads or falls back to JSON-LD
- `vitalgraph/endpoint/kgframes_endpoint.py` — Same pattern applied to GET `/kgframes` and POST `/kgframes`
- `vitalgraph/endpoint/kgtypes_endpoint.py` — Same pattern applied to GET `/kgtypes` (list, get-by-uri, get-by-uris)
- `vitalgraph/endpoint/objects_endpoint.py` — Same pattern applied to GET `/objects` and POST `/objects`

**Format negotiation rules:**
- `Accept: application/n-quads` → N-Quads response (pagination in HTTP headers)
- `Accept: application/json` → JSON Quads response (pagination in envelope)
- Default / `Accept: application/ld+json` → existing JSON-LD path (unchanged)
- `Content-Type: application/n-quads` → parse N-Quads request body
- `Content-Type: application/json` with `quads` key → parse JSON Quads request body
- Default → existing JSON-LD parsing (unchanged)

### Phase 1: Client Migration (Medium Risk)

9. Update `VitalGraphClient` to send/receive JSON Quads by default (uses `QuadRequest` for sends, expects `QuadResponse` for receives)
10. Update `MockVitalGraphClient` to match
11. Update all client endpoint classes (remove `model_dump(by_alias=True)` patterns, JSON-LD dict manipulation)
12. Run full test suites against both new and old formats to verify parity

#### Phase 1 Implementation Status ✅

Client default wire format switched to `ClientWireFormat.JSON_QUADS`. All 5 client test suites pass at 100%:

| Suite | Tests | Result |
|-------|------:|--------|
| KGTypes | 16/16 | ✅ |
| KGFrames | 12/12 | ✅ |
| KGEntities | 38/38 | ✅ |
| Objects | all | ✅ |
| KGQueries | 35/35 | ✅ |

**New files:**
- `vitalgraph/client/utils/format_helpers.py` — `ClientWireFormat` enum, `serialize_graphobjects_for_request()`, `deserialize_response_to_graphobjects()`, `is_json_quads_response()`, `extract_pagination_from_json_quads()`

**Modified client files:**
- `vitalgraph/client/vitalgraph_client.py` — Default `wire_format` set to `ClientWireFormat.JSON_QUADS`; `open()` sets `Accept` header based on format
- `vitalgraph/client/utils/client_utils.py` — Added `status_code` attribute to `VitalGraphClientError` for proper error handling
- `vitalgraph/client/endpoint/base_endpoint.py` — Added `wire_format` property, `_get_accept_header()`, format helper imports
- `vitalgraph/client/endpoint/kgentities_endpoint.py` — GET: JSON Quads response detection + deserialization for list and get; POST create/update: format-aware body serialization with headers/content forwarding
- `vitalgraph/client/endpoint/kgtypes_endpoint.py` — GET list/get/by-uris: JSON Quads response path; POST create: sends space_id/graph_id as query params with raw quad body; PUT update: same pattern
- `vitalgraph/client/endpoint/objects_endpoint.py` — GET list/get: JSON Quads response path; new `create_objects_from_graphobjects()` and `update_objects_from_graphobjects()` methods
- `vitalgraph/client/endpoint/kgframes_endpoint.py` — Full JSON Quads return paths for `list_kgframes`, `get_kgframe`, `list_kgframes_with_graphs`, `get_kgframe_graph`; handles single-vs-multiple object branching for `JsonLdObject`/`JsonLdDocument` construction
- `vitalgraph/client/endpoint/kgrelations_endpoint.py` — Fixed `_make_request` to forward headers/content params

**Modified server files (to support JSON Quads on remaining endpoints):**
- `vitalgraph/endpoint/kgtypes_endpoint.py` — Added format negotiation to POST/PUT handlers via `get_request_format` + `parse_request_body`; added `_create_kgtypes_from_objects()` and `_update_kgtypes_from_objects()` for direct GraphObject handling; removed redundant local `GraphObject` import that caused 500 on list
- `vitalgraph/utils/format_adapter.py` — Added `total_count` to `build_graphobjects_response` JSON Quads envelope

**Modified test files:**
- `vitalgraph_client_test/kgtypes/case_kgtype_update.py` — Update verification handles `GraphObject` via `to_jsonld()` in addition to `JsonLdObject`/dict

**Mock client:**
- `vitalgraph/mock/client/mock_vitalgraph_client.py` — Added `wire_format` constructor param for API parity

**Test file:**
- `test_scripts_misc/test_format_helpers_roundtrip.py` — 5/5 round-trip tests passing (JSON Quads, N-Quads, JSON-LD, pagination extraction, envelope detection)

**Backward compatible**: All existing JSON-LD methods preserved. JSON-LD path still reachable via `wire_format=ClientWireFormat.JSONLD`.

### Phase 2: Server Simplification (Medium Risk)

13. Make N-Quads / JSON Quads the only accepted formats — remove JSON-LD detection from middleware
14. Remove `JsonLdObject`/`JsonLdDocument`/`JsonLdRequest` from all endpoint route signatures and response unions
15. Remove all single-vs-document branching, `@context` handling, discriminated unions from endpoint implementations
16. Replace `vitalgraph/model/jsonld_model.py` with `vitalgraph/model/quad_model.py` in all imports

#### Phase 2 Implementation Status ✅

Server format defaults changed to JSON Quads. All JSON-LD conditional branches (`if response_format != WireFormat.JSONLD`) removed from server endpoints. All 5 client test suites pass at 100%:

| Suite | Tests | Result |
|-------|------:|--------|
| KGTypes | 16/16 | ✅ |
| KGFrames | 12/12 | ✅ |
| KGEntities | 38/38 | ✅ |
| Objects | all | ✅ |
| KGRelations | 32/32 | ✅ |

**Format negotiation changes:**
- `vitalgraph/utils/format_negotiation.py` — All defaults changed from `WireFormat.JSONLD` to `WireFormat.JSON_QUADS`; `detect_request_format()`, `detect_response_format()`, `detect_json_body_format()`, and `get_request_format()` all default to JSON Quads; JSON-LD still accepted on input via `application/ld+json` Content-Type or `@context`/`@graph` body keys for backward compatibility
- `vitalgraph/utils/format_adapter.py` — `parse_request_body()` now handles all formats including legacy JSON-LD (converts to GraphObjects); `build_response()` and `build_graphobjects_response()` no longer return `None` for JSONLD — they respond with JSON Quads instead

**Server endpoint changes:**
- `vitalgraph/endpoint/objects_endpoint.py` — Removed JSON-LD fallback from `_list_objects`, `_get_object_by_uri`, `_get_objects_by_uris`; POST/PUT routes now always use `parse_request_body` + `_create_objects_from_graphobjects`; added `_update_objects_from_graphobjects()` method; PUT route changed from `JsonLdRequest` body to `Request` with format negotiation
- `vitalgraph/endpoint/kgtypes_endpoint.py` — Removed JSON-LD fallback from `_list_kgtypes`, `_get_kgtype_by_uri`, `_get_kgtypes_by_uris`; POST/PUT routes simplified to always use `parse_request_body` + `_from_objects` methods; query params changed from `Optional` to required
- `vitalgraph/endpoint/kgentities_endpoint.py` — Removed JSON-LD fallback from `_list_entities`, `_get_entity_by_uri`; refactored `_get_entities_by_uris` to call `KGEntityGetProcessor` directly and collect GraphObjects (instead of going through `_get_entity_by_uri` which now returns JSONResponse); POST route simplified; all error returns use `build_response`/`build_graphobjects_response` instead of `JsonLdDocument(graph=[])`
- `vitalgraph/endpoint/kgframes_endpoint.py` — Removed JSON-LD fallback from `_list_frames`, `_get_frame_by_uri`, `_get_frames_by_uris`; POST route simplified; `_create_frames_from_objects` now returns `FrameUpdateResponse` for `operation_mode=update`; all error returns use build helpers

**Bug fix:**
- `vitalgraph_client_test/test_kgrelations_crud.py` — Added missing `await` on `create_all_relation_data()` async call (was causing `cannot unpack non-iterable coroutine object`)

**Remaining JSON-LD references**: The `JsonLdObject`/`JsonLdDocument`/`JsonLdRequest` imports still exist in endpoint files but are only used by dead code paths (old `_create_or_update_*` methods) and some response model type annotations. These will be cleaned up in Phase 3.

### Phase 3: Complete Removal

#### 3a. Response model cleanup
17. Remove `JsonLdObject`/`JsonLdDocument` field types from all Pydantic response models: `objects_model.py`, `kgentities_model.py`, `kgframes_model.py`, `kgtypes_model.py`, `kgrelations_model.py`, `triples_model.py`, `files_model.py`, `api_model.py`. Replace with `List[dict]` or remove the fields entirely (server already returns JSONResponse, not these models).

#### 3b. Client endpoint cleanup
18. Remove `JsonLdObject`/`JsonLdDocument` construction from all client endpoint classes: `kgentities_endpoint.py`, `kgtypes_endpoint.py`, `kgframes_endpoint.py`, `kgrelations_endpoint.py`, `objects_endpoint.py`, `files_endpoint.py`, `triples_endpoint.py`. Client should deserialize JSON Quads responses directly to GraphObjects without wrapping in JsonLd types.

#### 3c. Mock client cleanup
19. Remove `JsonLdObject`/`JsonLdDocument` construction from all mock endpoint classes: `mock_kgentities_endpoint.py`, `mock_kgtypes_endpoint.py`, `mock_kgframes_endpoint.py`, `mock_kgrelations_endpoint.py`, `mock_objects_endpoint.py`, `mock_files_endpoint.py`, `mock_triples_endpoint.py`.

#### 3d. Remaining server internals
20. Remove `JsonLdDocument`/`JsonLdObject` construction from remaining server methods: `kgrelations_endpoint.py` (list/get/create routes still use JsonLd types), `kgentities_endpoint.py` entity-frames sub-endpoint (`_get_kgentity_frames`, `_get_individual_frame`, `_query_kgentities`), `kgframes_endpoint.py` slots/query methods (`_get_kgframes_with_slots`, `_query_frames`, `_get_frame_slots`, `_frames_to_jsonld_document`).

#### Phase 3 Progress: Dead Server Code Removal ✅

Removed dead JSON-LD methods and cleaned up imports from server endpoints:

- `vitalgraph/endpoint/objects_endpoint.py` — Deleted `_create_objects`, `_update_object`, `create_objects`, `update_object` (old JSON-LD CRUD paths); removed `pyld`/`jsonld`/`JsonLd*` imports; removed `JsonLdDocument` from GET `response_model`
- `vitalgraph/endpoint/kgtypes_endpoint.py` — Deleted `_create_kgtypes`, `_update_kgtypes`, `_jsonld_to_vitalsigns_objects`, `_validate_operation_compatibility`; removed `pyld`/`JsonLd*` imports; set GET `response_model=None`
- `vitalgraph/endpoint/kgentities_endpoint.py` — Deleted `_create_or_update_entities` (150-line old JSON-LD path), `_convert_jsonld_to_graph_objects`; removed `JsonLd*` from GET `response_model` union
- `vitalgraph/endpoint/kgframes_endpoint.py` — Deleted `_create_frames` (old JSON-LD create), `_create_or_update_frames` (150-line old JSON-LD CRUD); removed `JsonLd*` from GET `response_model`
- `vitalgraph/utils/format_adapter.py` — Removed unused `jsonld_model` import

#### Phase 3 Progress: Interface Unification to Quads — In Progress 🔄

The next step is unifying all layer boundaries to use `List[Quad]` as the data exchange type, with `List[GraphObject]` conversion happening internally at each layer.

##### Architecture: Three-Layer Quad Boundary

```
┌─────────────────────────────────────────────────────┐
│  Caller (test scripts, application code)            │
│  Works with: List[GraphObject]                      │
│  Calls: client.create_kgtypes(space, graph, objects)│
└───────────────┬─────────────────────────────────────┘
                │  Public API: List[GraphObject]
                ▼
┌─────────────────────────────────────────────────────┐
│  Client Layer (vitalgraph/client/)                  │
│  Public interface: List[GraphObject]                │
│  Internally converts: GraphObject → Quad → wire     │
│  Uses: serialize_graphobjects_for_request()         │
│    → graphobjects_to_quad_list()                    │
│    → serialize_quads_for_request()                  │
│    → QuadRequest body over HTTP                     │
└───────────────┬─────────────────────────────────────┘
                │  Wire: QuadRequest (JSON Quads) or N-Quads text
                ▼
┌─────────────────────────────────────────────────────┐
│  Server Endpoints (vitalgraph/endpoint/)            │
│  HTTP handlers receive: List[Quad]                  │
│    via parse_request_body_as_quads()                │
│  Internal methods accept: List[Quad]                │
│  Internally convert: Quad → GraphObject → backend   │
│    via quad_list_to_graphobjects()                  │
└───────────────┬─────────────────────────────────────┘
                │  Internal: List[GraphObject]
                ▼
┌─────────────────────────────────────────────────────┐
│  Backend / kg_impl (processors, storage)            │
│  Works with: List[GraphObject] internally           │
│  Stores as: RDF quads in PostgreSQL/Fuseki          │
└─────────────────────────────────────────────────────┘
```

The same pattern applies to the mock client (`vitalgraph/mock/client/endpoint/`):
- Public methods accept `List[GraphObject]` (matching the client interface)
- Internally convert to/from quads for storage in pyoxigraph

##### Pydantic Models: Request and Response Types

All endpoint request/response types are defined using quad-based Pydantic models:

```python
# Base quad models (vitalgraph/model/quad_model.py)
class Quad(BaseModel):
    s: str; p: str; o: str; g: Optional[str] = None

class QuadRequest(BaseModel):
    quads: List[Quad]

class QuadResponse(BaseModel):
    total_count: int; page_size: int; offset: int
    results: List[Quad]

class QuadResultsResponse(BaseModel):
    total_count: int
    results: List[Quad]
```

**Unified response models** — all GET endpoints use `QuadResponse` (paginated lists) or `QuadResultsResponse` (single-item retrieval) directly. Both include `success` and `message` fields:
```python
class QuadResultsResponse(BaseModel):
    success: bool = True; message: str = ""
    total_count: int; results: List[Quad]

class QuadResponse(QuadResultsResponse):
    page_size: int; offset: int
```

Domain-specific subclasses (`KGTypeListResponse`, `EntitiesResponse`, `FramesResponse`, `ObjectsResponse`, `FilesResponse`, `SingleObjectResponse`, `SingleFileResponse`) have been eliminated — all endpoints return `QuadResponse` or `QuadResultsResponse` directly. The empty subclasses still exist in model files but are no longer imported or used outside those files.

**Create/Update/Delete response models** extend base operation models (no quad data needed):
```python
class BaseCreateResponse(BaseModel):
    success: bool; message: str
    created_count: int; created_uris: List[str]

class BaseUpdateResponse(BaseModel):
    success: bool; message: str
    updated_uri: Optional[str]

class BaseDeleteResponse(BaseModel):
    success: bool; message: str
    deleted_count: int; deleted_uris: List[str]
```

##### Server Endpoint Pattern: Quad-In, GraphObject-Internal

Each server endpoint follows this pattern for create/update operations:

```python
# Route handler: parse wire format → List[Quad]
async def create_kgtypes(request: Request, ...):
    quads = await parse_request_body_as_quads(request, request_format)
    return await self._create_kgtypes(space_id, graph_id, quads, current_user)

# Internal method: accept quads, convert to GraphObjects internally
async def _create_kgtypes(self, space_id, graph_id, quads: List[Quad], current_user):
    kgtype_objects = quad_list_to_graphobjects(quads)
    typed_objects = [obj for obj in kgtype_objects if isinstance(obj, KGType)]
    # ... proceed with GraphObject-based backend logic
```

For GET responses, the server converts GraphObjects to quads at the response boundary and returns typed Pydantic models directly:
```python
async def _list_kgtypes(self, ...):
    graph_objects, total = await processor.list_kgtypes(...)
    quads = graphobjects_to_quad_list(graph_objects, graph_id)
    return QuadResponse(results=quads, total_count=total, page_size=page_size, offset=offset)
```

For single-item retrieval:
```python
async def _get_kgtype_by_uri(self, ...):
    graph_objects = await processor.get_by_uri(...)
    quads = graphobjects_to_quad_list(graph_objects, graph_id)
    return QuadResultsResponse(results=quads, total_count=len(graph_objects))
```

##### Completed Work

**Format adapter** (`vitalgraph/utils/format_adapter.py`):
- Added `parse_request_body_as_quads()` — returns `List[Quad]` from any wire format
- Kept `parse_request_body()` as deprecated wrapper (returns `List[GraphObject]`)
- `build_response()` and `build_graphobjects_response()` **fully removed** from all endpoints — replaced with direct `QuadResponse`/`QuadResultsResponse` Pydantic model construction

**Client interface** (`vitalgraph/client/vitalgraph_client_inf.py`):
- All create/update signatures use `objects: List[GraphObject]` (public API)
- All list/get return types use `QuadResponse`/`QuadResultsResponse` directly
- Removed `Quad` from public interface; kept `QuadRequest` only for `add_triples`
- Removed domain-specific response imports (`KGTypeListResponse`, `ObjectsResponse`, `FilesResponse`, etc.)

**Client serialization** (`vitalgraph/client/utils/format_helpers.py`):
- Added `serialize_quads_for_request(quads, wire_format)` — direct quad serialization
- `serialize_graphobjects_for_request()` now delegates to `serialize_quads_for_request()` internally
- All REST client endpoints (`kgtypes_endpoint.py`, `kgframes_endpoint.py`, `objects_endpoint.py`, `kgentities_endpoint.py`, `kgrelations_endpoint.py`, `files_endpoint.py`) accept `List[GraphObject]` and use `serialize_graphobjects_for_request()` which converts internally to quads

**Client endpoint return types** updated to `QuadResponse`/`QuadResultsResponse`:
- `vitalgraph/client/vitalgraph_client.py` — All list/get method return types updated
- `vitalgraph/client/endpoint/kgtypes_endpoint.py` — Removed unused `ServerKGTypeListResponse`/`ServerKGTypeGetResponse` imports
- `vitalgraph/client/endpoint/objects_endpoint.py` — Removed unused `ServerObjectsResponse` import
- `vitalgraph/client/endpoint/kgframes_endpoint.py` — Replaced `FramesResponse` with `QuadResponse` throughout

**Mock client endpoints** (`vitalgraph/mock/client/endpoint/`):
- All create/update methods accept `List[GraphObject]` (matching client interface)
- All list/get methods return `QuadResponse`/`QuadResultsResponse` directly
- Removed domain-specific response imports (`KGTypeListResponse`, `EntitiesResponse`, `FramesResponse`, `ObjectsResponse`, `FilesResponse`)
- Internal storage uses pyoxigraph with quad-based conversion
- Files: `mock_kgtypes_endpoint.py`, `mock_objects_endpoint.py`, `mock_files_endpoint.py`, `mock_kgframes_endpoint.py`, `mock_kgentities_endpoint.py`, `mock_triples_endpoint.py`
- `mock_vitalgraph_client.py` — All list/get return type annotations updated

**Deleted deprecated client files:**
- `vitalgraph/client/endpoint/files_endpoint_old.py`
- `vitalgraph/client/endpoint/graphs_endpoint_old.py`
- `vitalgraph/client/endpoint/spaces_endpoint_old.py`

**Server endpoints — create/update accept `List[Quad]`:**
- `vitalgraph/endpoint/kgtypes_endpoint.py` — `_create_kgtypes()` and `_update_kgtypes()` accept `quads: List[Quad]`, convert internally via `quad_list_to_graphobjects()`
- `vitalgraph/endpoint/objects_endpoint.py` — `_create_objects()` and `_update_objects()` accept `quads: List[Quad]`
- `vitalgraph/endpoint/files_endpoint.py` — `_create_file_node()` and `_update_file_metadata()` accept `quads: List[Quad]`
- `vitalgraph/endpoint/kgentities_endpoint.py` — `_create_or_update_entities()` accepts `quads: List[Quad]`
- `vitalgraph/endpoint/kgrelations_endpoint.py` — `_create_or_update_relations()` accepts `quads: List[Quad]`

**Server endpoints — ALL GET methods return typed Pydantic models:** ✅
- `vitalgraph/endpoint/kgtypes_endpoint.py` — `_list_kgtypes` → `QuadResponse`, `_get_kgtype_by_uri` → `QuadResultsResponse`, `_get_kgtypes_by_uris` → `QuadResultsResponse`
- `vitalgraph/endpoint/objects_endpoint.py` — `_list_objects` → `QuadResponse`, `_get_object_by_uri` → `QuadResultsResponse`, `_get_objects_by_uris` → `QuadResultsResponse`
- `vitalgraph/endpoint/files_endpoint.py` — `_list_files` → `QuadResponse`, `_get_file_by_uri` → `QuadResultsResponse`, `_get_files_by_uris` → `QuadResultsResponse`
- `vitalgraph/endpoint/kgentities_endpoint.py` — `_list_entities` → `QuadResponse`, `_get_entity_by_uri` → `QuadResultsResponse`, `_get_entities_by_uris` → `QuadResponse`, `_get_kgentity_frames` → `QuadResponse`, `_query_kgentities` → `QuadResponse`
- `vitalgraph/endpoint/kgframes_endpoint.py` — `_list_frames` → `QuadResponse`, `_get_frame_by_uri` → `QuadResultsResponse`, `_get_frames_by_uris` → `QuadResponse`, `_get_entity_frames` → `QuadResponse`, `_get_kgframes_with_slots` → `QuadResponse`, `_list_slots` → `QuadResponse`, `_get_slot_by_uri` → `QuadResultsResponse`
- `vitalgraph/endpoint/kgrelations_endpoint.py` — `_list_relations` → `QuadResponse`, `_get_relation` → `QuadResultsResponse`

All `build_response()`/`build_graphobjects_response()` calls eliminated from endpoint files. All `get_response_format` dependencies and `response_format`/`response_obj` parameters removed from GET route handlers.

**kg_impl files updated:**
- `vitalgraph/kg/kgentity_list_endpoint_impl.py` — `EntitiesResponse` → `QuadResponse`
- `vitalgraph/kg_impl/kgentity_get_impl.py` — `EntitiesResponse` → `QuadResponse`
- `vitalgraph/kg/kgframe_list_endpoint_impl.py` — `FramesResponse` → `QuadResponse`

##### Remaining Work

**Server endpoints — quad boundary is complete.** All route handlers call `parse_request_body_as_quads()` and pass `List[Quad]` to the first internal method. Deeper internal methods (e.g. `_update_frames`, `_create_slots`, `_create_child_frames`, `_create_standalone_frames`) correctly accept `List[GraphObject]` because they are called after the quad→GraphObject conversion. No further changes needed.

**Model file cleanup:** ✅ Done. Empty subclasses (`ObjectsResponse`, `SingleObjectResponse`, `FilesResponse`, `SingleFileResponse`, `EntitiesResponse`, `FramesResponse`, `KGTypeListResponse`, `KGTypeGetResponse`) removed from model files.

**Test scripts (`test_script_kg_impl/`):**
- ~38 files reference `JsonLdDocument`, `JsonLdObject`, or `to_jsonld()` / `from_jsonld()`
- Top-level `from vitalgraph.model.jsonld_model import` lines already removed via bulk sed
- Inline `from vitalgraph.model.jsonld_model import` inside functions already removed
- `case_utils.py` fully rewritten: replaced `jsonld_to_kgtypes()`, `kgtypes_to_jsonld_document()`, `kgtype_to_jsonld_object()`, `validate_jsonld_roundtrip()` with quad-based equivalents (`filter_kgtypes()`, `quads_to_kgtypes()`, `validate_graphobject_roundtrip()`)
- **Still pending**: Update test method bodies to pass `List[GraphObject]` directly instead of constructing `JsonLdDocument(**{...})` objects; test assertions that parse JSON-LD responses need to parse quad responses instead; update references to removed `case_utils` functions (`jsonld_to_kgtypes`, `kgtypes_to_jsonld_document`)
- Tests call server-side internal methods (e.g. `self.endpoint._create_kgtypes(...)`) which now accept `List[Quad]`, so tests must convert GraphObjects to quads before calling

**Test scripts (`vitalgraph_client_test/`):**
- These test the client interface which accepts `List[GraphObject]` — likely need fewer changes
- Need audit for any remaining `JsonLdDocument` construction

**Response model alignment — ALL endpoints return typed Pydantic models with quad data ✅**

Every server endpoint that returns quad data now returns `QuadResponse` (paginated lists) or `QuadResultsResponse` (single-item retrieval) directly. Domain-specific wrapper response classes have been eliminated. The `build_response()`/`build_graphobjects_response()` helper functions are no longer called from any endpoint.

The pattern for GET responses:
```python
# Paginated list: return QuadResponse directly
graph_objects, total_count = await processor.list_kgtypes(...)
quads = graphobjects_to_quad_list(graph_objects, graph_id)
return QuadResponse(results=quads, total_count=total_count, page_size=page_size, offset=offset)

# Single-item retrieval: return QuadResultsResponse directly
graph_objects = await processor.get_by_uri(...)
quads = graphobjects_to_quad_list(graph_objects, graph_id)
return QuadResultsResponse(results=quads, total_count=len(graph_objects))
```

All 6 server endpoint files completed: `kgtypes_endpoint.py`, `objects_endpoint.py`, `files_endpoint.py`, `kgentities_endpoint.py`, `kgframes_endpoint.py`, `kgrelations_endpoint.py`.

Create/Update/Delete response models (`BaseCreateResponse`, `BaseUpdateResponse`, `BaseDeleteResponse`) are already correct — they don't carry quad data.

#### 3e. Delete dead files and code
21. Delete `kg_jsonld_utils.py`, `graphobject_jsonld_utils.py`, `fix_jsonld_fields` in `vitalsigns_helpers.py`
22. Remove `to_jsonld()` / `from_jsonld()` calls from all VitalGraph code (methods remain in VitalSigns library but are unused by VitalGraph)
23. Remove `data_format_utils.py` JSON-LD sections
24. Delete `vitalgraph/model/jsonld_model.py`

#### 3f. Documentation and frontend
25. Update all documentation and README files
26. Update frontend to consume JSON Quads format

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| **Large codebase change (~47 files)** | Phased approach with test validation at each phase; server and client can be migrated independently |
| **Frontend compatibility** | Frontend uses JSON Quads format — standard `fetch()` + `response.json()`, metadata and quads in one response |
| **TypeScript client** | JSON Quads is native JSON; N-Quads also available with `@rdfjs/parser-n3` if preferred |
| **Human readability during debugging** | N-Quads is line-oriented and grep-friendly; for richer debugging, pipe through a Turtle serializer locally |
| **External API consumers** | Breaking change — document clearly, version the API. Any consumer needing JSON-LD can convert N-Quads trivially with standard RDF libraries |
| **No backward compatibility** | This is intentional — maintaining two formats defeats the purpose. Clean break with clear migration guide |
| **VitalSigns `to_jsonld()` / `from_jsonld()`** | Methods remain in the VitalSigns library unchanged; VitalGraph simply stops calling them |

---

## 8. Evaluation Criteria for Decision

Before committing to this migration, validate:

- [x] **N-Quads round-trip test**: Verified VitalSigns `to_triples()` output serialized to N-Quads and parsed back with zero data loss for all KG object types (KGEntity, KGFrame, KGSlot, Edge types)
- [x] **JSON Quads round-trip test**: Same verification for JSON Quads format — confirmed lossless
- [x] **Performance benchmark**: N-Quads/JSON Quads are 35–48x faster for serialization and ~7x faster for deserialization vs JSON-LD (see Section 9)
- [x] **Payload size comparison**: JSON-LD ~30% smaller raw, but after gzip all formats compress to similar sizes (see Section 9.3)
- [x] **VitalSigns compatibility**: `GraphObject.to_triples()` and `GraphObject.from_triples()` / `from_triples_list()` confirmed working for all property types
- [ ] **Frontend impact assessment**: Evaluate effort required to update the React frontend to consume JSON Quads
- [x] **RDF term encoding validation**: Verified all RDF term types render correctly in JSON strings (URIs with `<>`, typed literals with `^^`, language tags with `@`, blank nodes with `_:`)

---

## 9. Benchmark Results

Measured on Apple Silicon (M-series), Python 3.12, 50 iterations per measurement. Times in milliseconds (median).

### 9.1 Serialization (GraphObjects → wire format)

| Scenario | N-Quads | JSON Quads | JSON-LD | JSON-LD / N-Quads |
|----------|--------:|-----------:|--------:|------------------:|
| 1 entity | 0.016 ms | 0.020 ms | 0.677 ms | **42x slower** |
| 10 entities | 0.147 ms | 0.158 ms | 6.383 ms | **43x slower** |
| 100 entities | 1.739 ms | 2.258 ms | 61.683 ms | **35x slower** |
| Complex graph (25 objects) | 0.367 ms | 0.400 ms | 17.772 ms | **48x slower** |

### 9.2 Deserialization (wire format → GraphObjects)

| Scenario | N-Quads | JSON Quads | JSON-LD | JSON-LD / N-Quads |
|----------|--------:|-----------:|--------:|------------------:|
| 1 entity | 0.068 ms | 0.064 ms | 0.463 ms | **7x slower** |
| 10 entities | 0.631 ms | 0.599 ms | 4.303 ms | **7x slower** |
| 100 entities | 6.315 ms | 5.922 ms | 43.455 ms | **7x slower** |
| Complex graph (25 objects) | 1.846 ms | 1.616 ms | 12.150 ms | **7x slower** |

### 9.3 Payload Size

| Scenario | N-Quads | JSON Quads | JSON-LD | NQ gzipped | JQ gzipped | JL gzipped |
|----------|--------:|-----------:|--------:|-----------:|-----------:|-----------:|
| 1 entity | 607 B | 760 B | 440 B | 198 B | 251 B | 210 B |
| 10 entities | 6,079 B | 7,116 B | 4,288 B | 363 B | 418 B | 312 B |
| 100 entities | 61,339 B | 71,198 B | 42,898 B | 1,914 B | 1,999 B | 1,151 B |
| Complex graph | 18,175 B | 20,946 B | 11,863 B | 771 B | 846 B | 584 B |

### 9.4 Analysis

**Serialization**: N-Quads and JSON Quads are **35–48x faster** than JSON-LD for serialization. This is the most dramatic difference — JSON-LD's `to_jsonld()` / `to_jsonld_list()` involves property introspection, context construction, and dict building, while N-Quads/JSON Quads use the direct `to_triples()` path.

**Deserialization**: N-Quads and JSON Quads are **~7x faster** than JSON-LD. The deserialization gap is smaller because `from_triples_list()` and `from_jsonld_list()` both ultimately reconstruct GraphObjects, but JSON-LD adds context resolution overhead.

**Payload size**: JSON-LD produces **~30% smaller** raw payloads due to prefix compression and nested structure. However, after gzip compression (standard HTTP `Content-Encoding`), the difference narrows significantly — **all formats compress to similar sizes** because gzip effectively handles the repetitive URI prefixes in N-Quads.

**Conclusion**: The new formats offer a **dramatic speed improvement** (7–48x) with negligible payload size penalty after compression. The speed gains come from eliminating JSON-LD's context resolution, property introspection, and dict manipulation — exactly the overhead documented in Sections 2 and 3.

---

## 10. Refactor: Remove JSON-LD from Server-Side Test Scripts

### Scope
The `test_scripts/fuseki_postgresql/` directory contains server-side endpoint tests that directly import and use JSON-LD models (`JsonLdDocument`, `JsonLdObject`, `@context`, `@graph`). These should be refactored to use VitalSigns GraphObjects and the quad-based wire format, consistent with the client test pattern in `vitalgraph_client_test/`.

### Files Requiring Refactoring (by JSON-LD usage)

| File | JSON-LD refs | Notes |
|------|-------------|-------|
| `test_kgtypes_endpoint_fuseki_postgresql.py` | ~99 | Heaviest JSON-LD usage — imports JsonLdDocument, KGType*Response models, builds JSON-LD manually |
| `test_triples_endpoint_fuseki_postgresql.py` | ~16 | JSON-LD in triple conversion |
| `test_kgframes_endpoint_fuseki_postgresql.py` | ~12 | JSON-LD for frame create/update |
| `test_kgentities_endpoint_fuseki_postgresql.py` | ~9 | JSON-LD for entity create/update |
| `test_files_endpoint_fuseki_postgresql.py` | ~3 | Minor JSON-LD usage |
| `test_objects_endpoint_fuseki_postgresql.py` | ~3 | Minor JSON-LD usage |
| `test_kgrelations_endpoint_fuseki_postgresql.py` | ~2 | Minor JSON-LD usage |
| `test_fuseki_postgresql_endpoint_utils.py` | ~1 | Base test utility |

### Refactoring Pattern
1. **Replace** `JsonLdDocument`/`JsonLdObject` imports and usage with VitalSigns GraphObject creation
2. **Replace** manual `@context`/`@graph` construction with `graphobjects_to_quad_list()` or `vitalsigns.to_jsonld_list()`
3. **Replace** JSON-LD response parsing with `quad_list_to_graphobjects()` or `vitalsigns.from_triples_list()`
4. **Replace** server response model imports (`KGTypeListResponse`, etc.) with client response models where applicable
5. **Ensure** all test data is created via concrete VitalSigns classes (never abstract `GraphObject()`)

### Priority Order
1. `test_kgtypes_endpoint_fuseki_postgresql.py` — largest impact, most JSON-LD debt
2. `test_kgframes_endpoint_fuseki_postgresql.py`
3. `test_kgentities_endpoint_fuseki_postgresql.py`
4. Remaining files (minimal changes needed)

---

## 11. Complete JSON-LD Reference Inventory (by directory)

All `.py` files containing `jsonld`/`JsonLd`/`json_ld`/`JSONLD` references, grouped by directory. **100 files total.**

### `vitalgraph/utils/` (7 files)

| File | Refs | Notes |
|------|-----:|-------|
| `vitalsigns_helpers.py` | 55 | Heaviest — `fix_jsonld_fields`, `strip_grouping_uris_from_document`, conversion helpers |
| `graphobject_jsonld_utils.py` | 47 | GraphObject ↔ JSON-LD conversion utilities |
| `data_format_utils.py` | 17 | Format detection and data conversion |
| `vitalsigns_conversion_utils.py` | 11 | VitalSigns ↔ JSON-LD conversion |
| `format_negotiation.py` | 10 | WireFormat enum, content-type detection |
| `file_utils.py` | 4 | File I/O with JSON-LD |
| `format_adapter.py` | 3 | Request/response format adaptation |

### `vitalgraph/mock/client/endpoint/` (5 files)

| File | Refs | Notes |
|------|-----:|-------|
| `mock_base_endpoint.py` | 42 | Base mock endpoint with JSON-LD helpers |
| `mock_kgentities_endpoint.py` | 13 | Mock KGEntities CRUD |
| `mock_export_endpoint.py` | 1 | Export mock |
| `mock_import_endpoint.py` | 1 | Import mock |

### `vitalgraph/mock/client/` (2 files, excluding endpoint/)

| File | Refs | Notes |
|------|-----:|-------|
| `space/mock_space.py` | 3 | Mock space with JSON-LD storage |
| `mock_vitalgraph_client.py` | 1 | Client factory |

### `vitalgraph/model/` (3 files)

| File | Refs | Notes |
|------|-----:|-------|
| `jsonld_model.py` | 16 | Core JSON-LD Pydantic models (`JsonLdObject`, `JsonLdDocument`, `JsonLdRequest`) |
| `export_model.py` | 1 | Export model references |
| `import_model.py` | 1 | Import model references |

### `vitalgraph/endpoint/` (5 files)

| File | Refs | Notes |
|------|-----:|-------|
| `triples_endpoint.py` | 6 | Triples endpoint JSON-LD handling |
| `impl/impl_utils.py` | 4 | Implementation utility helpers |
| `kgentities_endpoint.py` | 2 | Residual JSON-LD references |
| `export_endpoint.py` | 1 | Export endpoint |
| `import_endpoint.py` | 1 | Import endpoint |

### `vitalgraph/client/` (5 files)

| File | Refs | Notes |
|------|-----:|-------|
| `endpoint/kgentities_endpoint.py` | 13 | Client KGEntities with JSON-LD fallback paths |
| `response/response_builder.py` | 9 | Response deserialization |
| `utils/format_helpers.py` | 9 | ClientWireFormat, serialization helpers |
| `vitalgraph_client.py` | 2 | Client wire format config |
| `endpoint/base_endpoint.py` | 1 | Base endpoint |

### `vitalgraph/kg_impl/` (2 files)

| File | Refs | Notes |
|------|-----:|-------|
| `kg_jsonld_utils.py` | 24 | KG-specific JSON-LD utilities |
| `kgentity_list_impl.py` | 1 | Entity list implementation |

### `vitalgraph/db/` (2 files)

| File | Refs | Notes |
|------|-----:|-------|
| `postgresql/space/postgresql_space_db_objects.py` | 18 | PostgreSQL space objects |
| `fuseki_postgresql/fuseki_query_utils.py` | 5 | Fuseki query utilities |

### `vitalgraph/sparql/` (2 files)

| File | Refs | Notes |
|------|-----:|-------|
| `graph_validation.py` | 4 | Graph validation |
| `triple_store.py` | 3 | Triple store |

### `vitalgraph/rdf/` (1 file)

| File | Refs | Notes |
|------|-----:|-------|
| `rdf_utils.py` | 3 | RDF utilities |

### `vitalgraph/transfer/` (1 file)

| File | Refs | Notes |
|------|-----:|-------|
| `transfer_utils.py` | 5 | Data transfer utilities |

### `vitalgraph/admin_cmd/` (1 file)

| File | Refs | Notes |
|------|-----:|-------|
| `vitalgraphdb_admin_cmd.py` | 1 | Admin command |

### `test_scripts/fuseki_postgresql/` (8 files)

| File | Refs | Notes |
|------|-----:|-------|
| `test_kgtypes_endpoint_fuseki_postgresql.py` | 71 | Heaviest test file — manual JSON-LD construction |
| `test_kgframes_endpoint_fuseki_postgresql.py` | 9 | Frame create/update |
| `test_kgentities_endpoint_fuseki_postgresql.py` | 6 | Entity create/update |
| `test_triples_endpoint_fuseki_postgresql.py` | 5 | Triple conversion |
| `test_files_endpoint_fuseki_postgresql.py` | 1 | Minor |
| `test_objects_endpoint_fuseki_postgresql.py` | 1 | Minor |
| `test_kgrelations_endpoint_fuseki_postgresql.py` | 1 | Minor |
| `test_fuseki_postgresql_endpoint_utils.py` | 1 | Base utility |

### `test_scripts/kg_endpoint_fuseki/` (3 files)

| File | Refs | Notes |
|------|-----:|-------|
| `test_kgentities_frames_endpoint.py` | 12 | Entity-frames endpoint test |
| `test_kgentities_endpoint.py` | 7 | KGEntities endpoint test |
| `test_kg_endpoint_utils.py` | 4 | Test utilities |

### `test_scripts/endpoint/` (1 file)

| File | Refs | Notes |
|------|-----:|-------|
| `test_triples_endpoint.py` | 7 | Triples endpoint test |

### `vitalgraph_mock_client_test/` (26 files)

| File | Refs | Notes |
|------|-----:|-------|
| `mock_client_example.py` | 40 | Example script — heavy JSON-LD |
| `test_mock_kgtypes_vitalsigns.py` | 37 | KGTypes VitalSigns test |
| `test_mock_kgentities_vitalsigns.py` | 31 | KGEntities VitalSigns test |
| `test_mock_triples_endpoint.py` | 24 | Triples endpoint test |
| `test_data_lifecycle_management.py` | 17 | Data lifecycle test |
| `test_mock_kgframes_integration.py` | 17 | KGFrames integration test |
| `test_mock_objects_endpoint.py` | 16 | Objects endpoint test |
| `test_mock_client_kgentities.py` | 13 | Client KGEntities test |
| `test_mock_client_kgframes.py` | 13 | Client KGFrames test |
| `test_mock_client_kgtypes.py` | 13 | Client KGTypes test |
| `test_kg_endpoint_enhancements.py` | 11 | Endpoint enhancements test |
| `test_mock_kgentities_enhanced.py` | 10 | Enhanced KGEntities test |
| `test_entity_lifecycle_management.py` | 9 | Entity lifecycle test |
| `test_mock_files_endpoint.py` | 9 | Files endpoint test |
| `test_vitalsigns_objects.py` | 9 | VitalSigns objects test |
| `test_vitalsigns_pyoxigraph_integration.py` | 8 | Pyoxigraph integration test |
| `test_mock_kgframes_vitalsigns.py` | 7 | KGFrames VitalSigns test |
| `test_mock_client_files.py` | 6 | Client files test |
| `test_mock_kgentities_endpoint.py` | 6 | KGEntities endpoint test |
| `test_mock_kgframes_endpoint.py` | 6 | KGFrames endpoint test |
| `test_mock_kgtypes_endpoint.py` | 6 | KGTypes endpoint test |
| `test_dual_grouping_uris.py` | 5 | Dual grouping URIs test |
| `test_mock_client_objects.py` | 5 | Client objects test |
| `test_graph_level_retrieval.py` | 3 | Graph level retrieval test |
| `test_mock_client_graphs.py` | 2 | Client graphs test |
| `test_mock_sparql_endpoint.py` | 1 | SPARQL endpoint test |

### `test_scripts_misc/` (17 files)

| File | Refs | Notes |
|------|-----:|-------|
| `test_pure_vitalsigns_jsonld.py` | 43 | Pure VitalSigns JSON-LD test |
| `test_mock_client_jsonld_issue.py` | 25 | Mock client JSON-LD issue reproduction |
| `test_entity_frame_crud.py` | 22 | Entity frame CRUD |
| `test_kg_relations.py` | 22 | KG relations test |
| `test_jsonld_loading.py` | 14 | JSON-LD loading test |
| `benchmark_serialization_formats.py` | 11 | Serialization benchmark |
| `test_vitalsigns_conversion.py` | 10 | VitalSigns conversion test |
| `test_vitalsigns_simple.py` | 8 | VitalSigns simple test |
| `test_vitalsigns_query_functionality.py` | 7 | Query functionality test |
| `discover_kg_properties.py` | 6 | KG property discovery |
| `test_entity_graph_client.py` | 6 | Entity graph client test |
| `test_format_helpers_roundtrip.py` | 4 | Format helpers round-trip test |
| `test_simple_query.py` | 3 | Simple query test |
| `test_vitalsigns_methods.py` | 2 | VitalSigns methods test |
| `test_vitalsigns_rdf.py` | 2 | VitalSigns RDF test |
| `test_kg_relations_phase1.py` | 1 | KG relations phase 1 |
| `test_comprehensive_query_functionality.py` | 1 | Comprehensive query test |

### `vitalsigns_test_scripts/` (6 files)

| File | Refs | Notes |
|------|-----:|-------|
| `test_jsonld_basic.py` | 45 | Basic JSON-LD test |
| `test_jsonld_data_format_utils.py` | 33 | Data format utils test |
| `test_rdf_type_roundtrip.py` | 19 | RDF type round-trip test |
| `test_rdf_type_check.py` | 18 | RDF type check test |
| `test_rdf_triples_comparison.py` | 6 | RDF triples comparison |
| `kgentity_serialization_test.py` | 4 | KGEntity serialization test |

### `test_sparql/` (2 files)

| File | Refs | Notes |
|------|-----:|-------|
| `test_triple_store.py` | 15 | Triple store test |
| `utils/test_helpers.py` | 2 | Test helper utilities |

### `test_client_api/` (1 file)

| File | Refs | Notes |
|------|-----:|-------|
| `test_grouping_uri_functionality.py` | 2 | Grouping URI test |

### Root-level (1 file)

| File | Refs | Notes |
|------|-----:|-------|
| `test_vitalsigns_jsonld.py` | 49 | VitalSigns JSON-LD integration test |

---

## 12. Phase 3 Progress: Test Script JSON-LD Cleanup

### Grep Scope
Full project grep for `jsonld`, `@graph`, `@type`, `@id`, `from_jsonld`, `to_jsonld`, `model_dump(by_alias=True)`, `JsonLdDocument`, `JsonLdObject`.

### Completed Files

| File | Action | Status |
|------|--------|--------|
| `test_vitalsigns_jsonld.py` (root) | Deleted — entirely JSON-LD test | ✅ |
| `test_scripts_misc/test_simple_query.py` | Refactored to GraphObject + N-Quads | ✅ |
| `test_scripts_misc/test_jsonld_loading.py` | Rewritten to N-Quads loading | ✅ |
| `test_scripts_misc/benchmark_serialization_formats.py` | Removed JSON-LD benchmarks | ✅ |
| `test_scripts_misc/test_vitalsigns_simple.py` | Replaced JSON-LD round-trip with quad round-trip | ✅ |
| `test_scripts_misc/test_comprehensive_query_functionality.py` | Replaced JSON-LD dict construction with GraphObjects + N-Quads | ✅ |
| `test_scripts_misc/discover_kg_properties.py` | Replaced JSON-LD code examples in generated docs | ✅ |
| `test_scripts_misc/test_entity_graph_client.py` | Cleaned | ✅ |
| `test_scripts_misc/test_mock_client_jsonld_issue.py` | Cleaned | ✅ |
| `test_scripts_misc/test_vitalsigns_conversion.py` | Cleaned | ✅ |
| `test_scripts/fuseki_postgresql/test_kgtypes_endpoint_fuseki_postgresql.py` | Deep cleaned | ✅ |
| `test_scripts/fuseki_postgresql/test_kgentities_endpoint_fuseki_postgresql.py` | Verified clean | ✅ |
| `vitalgraph_mock_client_test/test_mock_triples_endpoint.py` | Replaced all `response.data.model_dump(by_alias=True)` + `@graph` with `quad_list_to_graphobjects(response.results)` | ✅ |
| `vitalgraph_mock_client_test/test_dual_grouping_uris.py` | Replaced `from_jsonld_list` with `quad_list_to_graphobjects` | ✅ |
| `vitalgraph_mock_client_test/test_graph_level_retrieval.py` | Replaced `model_dump()` + `@graph` with `quad_list_to_graphobjects` | ✅ |
| `vitalgraph_mock_client_test/mock_client_example.py` | Replaced all `to_jsonld_list()` and `from_jsonld()`/`from_jsonld_list()` with direct GraphObject passing and `quad_list_to_graphobjects` | ✅ |

### Additional Completed Files (Phase 3 continued)

| File | Action | Status |
|------|--------|--------|
| `test_mock_kgframes_integration.py` | Replaced `test_vitalsigns_native_jsonld_conversion` with quad round-trip test | ✅ |
| `test_scripts_misc/test_entity_frame_crud.py` | Replaced `model_dump(by_alias=True)` + `@graph` with `quad_list_to_graphobjects` | ✅ |
| `test_sparql/fixtures/sample_entity_graphs.py` | Deleted — unused JSON-LD fixture data | ✅ |
| `test_sparql/fixtures/sample_frame_graphs.py` | Deleted — unused JSON-LD fixture data | ✅ |
| `test_sparql/test_triple_store.py` | Deleted — imported deleted fixtures, all tests used `load_jsonld_document` | ✅ |
| `test_scripts_misc/test_pure_vitalsigns_jsonld.py` | Deleted — entirely JSON-LD testing | ✅ |
| `vitalgraph_client_test/test_entity_graph_debug.py` | Replaced `@graph` response parsing with `results` quad parsing | ✅ |
| `test_kgframes_endpoint_fuseki_postgresql.py` | Replaced `from_jsonld_list` with `quad_list_to_graphobjects`; replaced `to_jsonld_list()` with direct list passing; fixed broken `test_invalid_jsonld_validation` import → `test_invalid_input_validation` | ✅ |
| `case_frame_operations.py` | Replaced `model_dump(by_alias=True)` + `@graph` with `quad_list_to_graphobjects` | ✅ |
| `case_entity_graph_operations.py` | Replaced `model_dump(by_alias=True)` + `@graph` with `quad_list_to_graphobjects` | ✅ |
| `case_query_lead_graph.py` | Removed stale `model_dump` fallback | ✅ |
| `vitalgraph/endpoint/kgtypes_endpoint.py` | Updated error messages to remove `@graph` terminology | ✅ |
| `test_kg_endpoint_enhancements.py` | Replaced JSON-LD conversion test with quad round-trip; removed `jsonld_keys` | ✅ |
| `test_mock_kgtypes_vitalsigns.py` | Replaced `@graph` assertion with `results` assertion | ✅ |
| `test_mock_kgentities_vitalsigns.py` | Replaced `@graph` assertion with `results` assertion | ✅ |
| `case_kgentity_delete.py` | Removed dead JSON-LD dict literal | ✅ |
| `case_kgentity_create.py` | Removed dead JSON-LD dict literal | ✅ |
| `test_sparql/utils/test_helpers.py` | Removed `create_test_store_with_data` (used `load_jsonld_document`); replaced `extract_uris_by_type` with GraphObject-based version | ✅ |
| `test_scripts/endpoint/test_triples_endpoint.py` | Renamed `test_jsonld_conversion` → `test_graphobjects_to_quads_conversion` | ✅ |
| `test_script_kg_impl/kgframes/case_frame_create.py` | Removed JSON-LD reference from import comment | ✅ |

### Intentionally Retained References

| File | Reason |
|------|--------|
| `vitalgraph/utils/file_utils.py` | `'@context' in content_lower` — legitimate file format detection |
| `vitalgraph/client/endpoint/kgentities_endpoint.py` | `model_dump(by_alias=True)` — legitimate Pydantic serialization for JSON Quads wire format |
| `test_scripts_misc/test_format_helpers_roundtrip.py` | Tests `ClientWireFormat.JSONLD` — still a supported client wire format |
| `test_scripts_misc/test_vitalsigns_methods.py` | Checks upstream VitalSigns library API method existence (`from_jsonld`, etc.) |
| `test_scripts_misc/test_vitalsigns_rdf.py` | Educational print statements comparing RDF vs JSON-LD formats |

### Final Verification

Production code (`vitalgraph/`) has **zero** remaining calls to `to_jsonld_list`, `from_jsonld_list`, `from_jsonld`, `to_jsonld`, `JsonLdDocument`, `JsonLdObject`, or `load_jsonld_document`.

**Phase 3 Status: COMPLETE** ✅

---

## 13. References

- [Ontola: What's the best RDF serialization format?](https://ontola.io/blog/rdf-serialization-formats)
- [Dr. Chuck: Unconstrained JSON-LD Performance Is Bad for API Specs](https://www.dr-chuck.com/csev-blog/2016/04/json-ld-performance-sucks-for-api-specs/)
- [W3C JSON-LD Best Practices: Round Tripping](https://github.com/w3c/json-ld-bp/issues/13)
- [W3C JSON-LD: Data Round Tripping](https://github.com/json-ld/json-ld.org/issues/237)
- [HN: JSON-LD and Why I Hate the Semantic Web](https://news.ycombinator.com/item?id=14474222)
- [W3C N-Quads Specification](https://www.w3.org/TR/n-quads/)
- [W3C RDF/JSON Alternate Serialization](https://www.w3.org/TR/rdf-json/)
- [HexTuples-NDJSON (Ontola)](https://github.com/ontola/hextuples)
- [Manu Sporny: JSON-LD Origins](http://manu.sporny.org/2014/json-ld-origins-2/)
