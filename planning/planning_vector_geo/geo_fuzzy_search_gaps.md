# Geo & Fuzzy Search — Gaps Analysis

## 1. Summary

The VitalGraph search infrastructure supports four modes via SPARQL
`vg:` functions: **keyword**, **FTS**, **vector**, and **hybrid**. Two
additional search capabilities — **geo (spatial)** and **fuzzy search
(near-duplicate matching)** — are now **fully integrated** into the SPARQL
compiler, REST API, Python/TypeScript client libraries, and admin UI.
All previously identified gaps are now **resolved** — client integration
tests, SPARQL function tests, and admin UI are complete.

---

## 2. Current State

### 2.1 Geo Search

| Layer | Status | Details |
|-------|--------|----------|
| Storage | ✅ Implemented | `{space}_geo` PostGIS table, WKT via `ST_GeomFromText`, GiST index |
| Population | ✅ Implemented | `geo_populator.py` — **datatype-driven** detection (June 2026) |
| Auto-sync | ✅ Implemented | `auto_sync.py` — geo populated alongside vectors on CRUD |
| REST endpoint | ✅ Implemented | `GET /api/geo?near_lat=&near_lon=&radius_km=` via `geo_points_endpoint.py` |
| Config endpoint | ✅ Implemented | `geo_config_endpoint.py` — enable/disable, configure datatypes |
| SPARQL function | ✅ Implemented | `vg:withinRadius`, `vg:withinBounds`, `vg:withinPolygon`, `vg:geoDistance` |
| Client library (Python) | ✅ Implemented | `client.geo_points.*` and `client.geo_config.*` methods |
| Client library (TypeScript) | ✅ Implemented | `client.geoPoints.list()`, `client.geoPoints.searchNearby()` |
| Integration test (REST) | ✅ Implemented | `vitalgraph_client_test/test_geo_points_endpoint.py` — full client→REST path |
| Integration test (SPARQL) | ✅ Implemented | `test_geo_sparql_all.py` — withinRadius, geoDistance, withinBounds, combined |
| Semantic test (quality) | ✅ Implemented | 45-location test dataset with known distances |

### 2.2 Fuzzy Search

| Layer | Status | Details |
|-------|--------|---------|
| Storage | ✅ Implemented | PostgreSQL tables for MinHash LSH bands (`entity_fuzzy_storage.py`) |
| Algorithm | ✅ Implemented | MinHash LSH + RapidFuzz + phonetic matching (`entity_fuzzy_pg.py`) |
| Internal API | ✅ Implemented | `find_similar(entity, limit, min_score)` async method |
| REST endpoint | ✅ Implemented | `GET /api/entity-registry/search/similar` via `entity_registry_endpoint.py` |
| SPARQL function | ✅ Implemented | `vg:fuzzyMatch(?entity, "name", threshold)` — MinHash LSH + RapidFuzz via resolve pattern |
| Fuzzy mapping CRUD | ✅ Implemented | `POST/GET/PUT/DELETE /api/fuzzy-mappings` — configure per-space fuzzy indexes |
| Fuzzy populator | ✅ Implemented | `fuzzy_populator.py` — reads RDF quads → MinHash bands |
| Client library (Python) | ✅ Implemented | `client.entity_registry.find_similar()` + `client.fuzzy_mappings.*` |
| Client library (TypeScript) | ✅ Implemented | `client.fuzzyMappings.*` + `client.entityRegistry.findSimilar()` |
| Admin UI | ✅ Implemented | Fuzzy Mappings page — list/create/edit/delete mappings, manage properties, populate, index stats display |
| Index stats endpoint | ✅ Implemented | `GET /api/fuzzy-mappings/stats` — band count, entity count, phonetic band count |
| Integration test (internal) | ✅ Implemented | `test_fuzzy_pg.py` — 5/5 pass, 212 entities indexed |
| Integration test (REST) | ✅ Implemented | `test_fuzzy_mapping_endpoints.py` — CRUD + properties + populate + find_similar via client |
| Integration test (SPARQL) | ✅ Implemented | `test_fuzzy_match_unit.py` + `test_fuzzy_sparql_e2e.py` |

---

## 3. Gaps Detail

### 3.1 ~~No SPARQL Functions for Geo~~ ✅ RESOLVED

Four SPARQL geo functions are now implemented in the SPARQL-to-SQL compiler:
`vg:withinRadius`, `vg:withinBounds`, `vg:withinPolygon`, `vg:geoDistance`.
These generate PostGIS SQL (`ST_DWithin`, `ST_MakeEnvelope`, `ST_Contains`,
`ST_Distance`) via `emit_expressions.py` dispatch.

### 3.2 ~~No SPARQL Functions for Fuzzy Search~~ ✅ RESOLVED

`vg:fuzzyMatch(?entity, "name", threshold)` is implemented using the
placeholder + resolve pattern (like vector search). When a fuzzy mapping
exists, resolves via MinHash LSH band lookup + RapidFuzz scoring;
otherwise falls back to pg_trgm `similarity()` via existing GIN index.

### 3.3 ~~No REST Endpoint for Fuzzy Search Queries~~ ✅ RESOLVED

Endpoint: `GET /api/entity-registry/search/similar?name=...&type_key=...&min_score=50`
Also: fuzzy mapping CRUD at `/api/fuzzy-mappings` with populate trigger.

### 3.4 ~~No Python/TypeScript Client Methods for Geo or Fuzzy Search~~ ✅ RESOLVED

- **Python**: `client.geo_points.*`, `client.geo_config.*`, `client.entity_registry.find_similar()`, `client.fuzzy_mappings.*`
- **TypeScript**: `client.geoPoints.*`, `client.geoConfig.*`, `client.entityRegistry.findSimilar()`, `client.fuzzyMappings.*`

### 3.5 ~~Geo REST Endpoint Not Tested via Client~~ ✅ RESOLVED

Client-based integration test: `vitalgraph_client_test/test_geo_points_endpoint.py`
tests the full path: `VitalGraphClient` → REST → endpoint → PostGIS → response.
Covers: list all, spatial radius, graph filter, pagination, error cases.

### 3.6 ~~No Quality/Semantic Tests for Geo~~ ✅ RESOLVED

45-location test dataset with known distances is implemented. Semantic
quality tests validate real-world correctness.

### 3.7 ~~Fuzzy Index Not Rebuilt on Service Restart (PostgreSQL mode)~~ ✅ RESOLVED

The `find_similar()` method now lazy-loads scoring metadata from entity
registry tables on demand. Band hashes persist in PostgreSQL. No startup
rebuild required — band lookup works immediately after restart.

---

## 4. Recommended Actions

### Phase 1: REST & Client ✅ COMPLETE

| Task | Priority | Status |
|------|----------|--------|
| Add `GET /api/entity-registry/search/similar` endpoint | High | ✅ Done |
| Add `client.geo_points.*` and `client.geo_config.*` to Python client | High | ✅ Done |
| Add `client.entity_registry.find_similar()` to Python client | High | ✅ Done |
| Add `client.fuzzy_mappings.*` to Python client | Medium | ✅ Done |
| Mirror in TypeScript client | Medium | ✅ Done |
| Admin UI — Fuzzy Mappings page | Medium | ✅ Done (see `search_ui_plan.md` §9) |
| Write integration tests via client for geo REST | Medium | ✅ Done (`test_geo_points_endpoint.py`) |
| Write integration tests via client for fuzzy search REST | Medium | ✅ Done (`test_fuzzy_mapping_endpoints.py`) |

### Phase 2: SPARQL Functions (Medium effort)

| Task | Priority | Status |
|------|----------|--------|
| Implement `vg:withinRadius(?s, lat, lon, radius_m)` in SPARQL-to-SQL compiler | Medium | ✅ Done |
| Implement `vg:geoDistance(?s, lat, lon)` returning distance in meters | Medium | ✅ Done |
| Implement `vg:withinBounds(?s, minLat, minLon, maxLat, maxLon)` | Medium | ✅ Done |
| Implement `vg:withinPolygon(?s, wktPolygon)` | Medium | ✅ Done |
| Implement `vg:fuzzyMatch(?entity, name, threshold)` in SPARQL-to-SQL compiler | Low | ✅ Done |
| Add SPARQL geo tests to dedicated script | Medium | ✅ Done (`test_geo_sparql_all.py`) |
| Add SPARQL fuzzy tests | Low | ✅ Done (unit + e2e) |

### Phase 3: Quality Validation (Low effort)

| Task | Priority | Status |
|------|----------|--------|
| Create test dataset with known lat/long entities | Medium | ✅ Done (45 locations, WKT format) |
| Write geo semantic tests: "within 5km of X" → expected entities | Medium | ✅ Done |
| Write fuzzy search semantic tests: name → expected matches | Medium | ✅ Done (test_fuzzy_sparql_e2e.py) |

---

## 5. Unified Geo Datatype Design (June 2026)

### 5.1 Problem

The geo system was built around **hardcoded predicate URIs** (wgs84:lat/long,
haleyKG:hasLatitude/hasLongitude) with a custom string format (`"lat,lon"`).
This is non-standard and limits geo queries to entities that happen to use
those specific predicates.

The VitalSigns ontology defines `GEO_LOCATION` as a first-class datatype
(`http://vital.ai/ontology/vital#VitalOntDataType_GEO_LOCATION`). The
`KGGeoLocationSlot` uses `hasGeoLocationSlotValue` with this type. Any
property in the ontology can be typed as `geoLocation`.

### 5.2 Solution: WKT Literal Format for Both Datatypes

Adopt WKT (Well-Known Text) as the canonical format for geo values.
Support two equivalent datatype URIs:

```
"POINT(-73.9855 40.7580)"^^<http://www.opengis.net/ont/geosparql#wktLiteral>
"POINT(-73.9855 40.7580)"^^<http://vital.ai/ontology/vital-core#geoLocation>
```

Both are treated identically. WKT format: `POINT(longitude latitude)`.

**Recognized datatype URIs**:
```python
GEO_DATATYPE_URIS = {
    "http://www.opengis.net/ont/geosparql#wktLiteral",
    "http://vital.ai/ontology/vital-core#geoLocation",
}
```

### 5.3 Architecture Changes

| Component | Before | After |
|-----------|--------|-------|
| Geo value format | `"40.7580,-73.9855"` (custom lat,lon) | `"POINT(-73.9855 40.7580)"` (WKT) |
| Populator detection | Hardcoded predicate URI list | Detect any quad whose object has a geo datatype |
| Parsing | Custom comma/space/JSON parser | `ST_GeomFromText(value, 4326)` — PostGIS native |
| Side-table column | `geography(Point, 4326)` | `geography(Geometry, 4326)` — supports Point, Polygon, etc. |
| Config | `lat_predicates` / `lon_predicates` lists | `geo_datatype_uris` set (extensible) |
| Backward compat | N/A | Parse old `"lat,lon"` format as fallback during migration |

### 5.4 Benefits

- **Datatype-driven**: Geo populator watches for geo-typed literals on ANY
  triple, regardless of predicate URI. No predicate lists to maintain.
- **PostGIS-native parsing**: No custom parser — `ST_GeomFromText` handles WKT.
- **Supports complex geometries**: WKT can represent `POLYGON((...))`,
  `LINESTRING(...)`, `MULTIPOINT(...)` — not just points.
- **Standard-compatible**: `geo:wktLiteral` is the OGC GeoSPARQL standard.
  Tools that speak GeoSPARQL can interop directly.
- **Unified**: The Vital `geoLocation` type and the OGC `wktLiteral` type
  use the same format and are handled identically.

### 5.5 Implementation Files (COMPLETED June 2026)

| File | Change | Status |
|------|--------|--------|
| `vitalgraph/vectorization/geo_populator.py` | Detect by object datatype; parse WKT; `GEO_DATATYPE_URIS` | ✅ Done |
| `vitalgraph/vectorization/geo_slot_handler.py` | Parse WKT format; delegates to `parse_geo_wkt()` | ✅ Done |
| `vitalgraph/vectorization/geo_config_manager.py` | Added `geo_datatype_uris` field; `DEFAULT_GEO_DATATYPE_URIS` | ✅ Done |
| `vitalgraph/db/sparql_sql/sparql_sql_schema.py` | Seeded geo datatypes; `geo_datatype_uris` column in config | ✅ Done |
| `vitalgraph/db/migrations/migrate_vector_geo_schema.py` | Migration adds column + seeds datatypes | ✅ Done |
| `vitalgraph/db/sparql_sql/vg_functions.py` | No change — already uses PostGIS functions | ✅ N/A |
| `test_scripts/data/generate_geo_test_data.py` | Emit `"POINT(lon lat)"^^geoLocation` typed literals | ✅ Done |

### 5.6 SPARQL Query Examples

```sparql
# Any entity with a geo-typed property within a radius
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?entity ?name WHERE {
  ?entity vc:hasName ?name .
  FILTER(vg:withinRadius(?entity, 40.7580, -73.9855, 5000))
}

# Bounding box
FILTER(vg:withinBounds(?entity, 40.70, -74.02, 40.83, -73.93))

# Polygon (WKT)
FILTER(vg:withinPolygon(?entity, "POLYGON((-74.05 40.70, ...))"))
```

The SPARQL functions operate on the **subject** (entity) by joining to the
geo side-table via `subject_uuid`. The populator ensures that any subject
which has a geo-typed property value gets indexed in the side-table.

---

## 6. Relationship to Existing Plans

- **`vector_geo_plan.md`** — Covers storage design and population; does
  not address SPARQL function integration or REST testing gaps.
- **`fuzzy_redis_to_postgresql_plan.md`** — Covers fuzzy search backend
  migration (complete); does not address REST exposure or SPARQL integration.
- **`framenet_testing_plan.md`** — Covers keyword/FTS/vector/hybrid
  search testing; geo and fuzzy search are out of scope for that plan.

---

## 7. Files Referenced

| File | Purpose |
|------|---------|
| `vitalgraph/vectorization/geo_populator.py` | PostGIS geo population |
| `vitalgraph/vectorization/geo_config_manager.py` | Geo config CRUD |
| `vitalgraph/vectorization/geo_slot_handler.py` | Geo slot extraction |
| `vitalgraph/endpoint/geo_points_endpoint.py` | REST geo listing/search |
| `vitalgraph/endpoint/geo_config_endpoint.py` | REST geo config |
| `vitalgraph/entity_registry/entity_fuzzy_pg.py` | PG-backed fuzzy search index |
| `vitalgraph/entity_registry/entity_fuzzy_storage.py` | Band storage CRUD |
| `vitalgraph/entity_registry/entity_fuzzy.py` | Redis/memory fuzzy search index |
| `vitalgraph/endpoint/entity_registry_endpoint.py` | Entity CRUD + `GET /search/similar` fuzzy search |
| `vitalgraph/endpoint/fuzzy_mapping_endpoint.py` | Fuzzy mapping CRUD + populate |
| `vitalgraph/vectorization/fuzzy_populator.py` | RDF quad → MinHash band population |
| `vitalgraph/vectorization/fuzzy_mapping_manager.py` | Fuzzy mapping configuration CRUD |
| `vitalgraph/vectorization/fuzzy_core.py` | Shared: shingles, MinHash, band hash, RapidFuzz scoring |
| `vitalgraph/db/sparql_sql/vg_resolve.py` | Fuzzy + vector placeholder resolve |
| `frontend/src/pages/FuzzyMappings.tsx` | Admin UI — fuzzy mapping list/create/delete |
| `frontend/src/pages/FuzzyMappingDetail.tsx` | Admin UI — fuzzy mapping detail/edit/populate |
| `test_scripts/test_geo_points_endpoint.py` | Direct geo endpoint test |
| `test_scripts/test_geo_sparql_all.py` | Comprehensive SPARQL geo tests (7/7 pass) |
| `vitalgraph_client_test/test_geo_points_endpoint.py` | Client-based geo integration test (9/9 pass) |
| `test_scripts/entity_registry/test_fuzzy_pg.py` | PG fuzzy search unit test |
