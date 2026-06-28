# VitalGraph Client — REST API Sync Plan

## Goal

Synchronize the Python client (`vitalgraph/client/`) with the current server REST API surface after recent refactoring. Detect new endpoints, missing client coverage, mounting-point changes, and Pydantic model gaps.

---

## 1. Server REST API Endpoint Inventory

Below is the full list of server-side endpoints, derived from `vitalgraphapp_impl.py` `_setup_all_endpoints()` and the individual endpoint files. Mount prefixes shown as the **effective URL** (router prefix + route path).

### 1.1 Health / Auth (no prefix or `/api`)

| Method | Effective URL | Server Endpoint | Models |
|--------|--------------|-----------------|--------|
| GET | `/health` | `vitalgraphapp_impl.py` | — (dict) |
| GET | `/health/cache` | `vitalgraphapp_impl.py` | — (dict) |
| POST | `/api/login` | `vitalgraphapp_impl.py` | OAuth2 form |
| POST | `/api/logout` | `vitalgraphapp_impl.py` | — |
| POST | `/api/refresh` | `vitalgraphapp_impl.py` | — |
| WS | `/api/ws` | `vitalgraphapp_impl.py` | WebSocket |

### 1.2 Spaces (`/api/spaces`) — REFACTORED

All identifiers moved from path parameters to query parameters.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| GET | `/api/spaces` | — | `spaces_endpoint.py` | `SpacesListResponse` |
| POST | `/api/spaces` | — | `spaces_endpoint.py` | `SpaceCreateResponse` |
| GET | `/api/spaces/space` | `space_id` | `spaces_endpoint.py` | `SpaceResponse` |
| GET | `/api/spaces/info` | `space_id` | `spaces_endpoint.py` | `SpaceInfoResponse` |
| GET | `/api/spaces/analytics` | `space_id`, `refresh?`, `graph_uri?` | `spaces_endpoint.py` | `SpaceAnalyticsResponse` |
| PUT | `/api/spaces` | `space_id` | `spaces_endpoint.py` | `SpaceUpdateResponse` |
| DELETE | `/api/spaces` | `space_id` | `spaces_endpoint.py` | `SpaceDeleteResponse` |
| GET | `/api/spaces/filter` | `space_id` | `spaces_endpoint.py` | `SpacesListResponse` |

### 1.3 Users (`/api/users`) — REFACTORED

All identifiers moved from path parameters to query parameters.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| GET | `/api/users` | — | `users_endpoint.py` | `UsersListResponse` |
| POST | `/api/users` | — | `users_endpoint.py` | `UserCreateResponse` |
| GET | `/api/users/user` | `user_id` | `users_endpoint.py` | `User` |
| PUT | `/api/users` | `user_id` | `users_endpoint.py` | `UserUpdateResponse` |
| DELETE | `/api/users` | `user_id` | `users_endpoint.py` | `UserDeleteResponse` |
| GET | `/api/users/spaces` | `user_id` | `users_endpoint.py` | — (dict) |
| PUT | `/api/users/spaces` | `user_id`, `space_id` | `users_endpoint.py` | — (dict) |
| DELETE | `/api/users/spaces` | `user_id`, `space_id` | `users_endpoint.py` | — (dict) |
| POST | `/api/users/me/password` | — | `users_endpoint.py` | `PasswordChangeResponse` |

### 1.4 API Keys (`/api/keys`) — REFACTORED

All identifiers moved from path parameters to query parameters.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| POST | `/api/keys` | — | `api_keys_endpoint.py` | `ApiKeyCreateResponse` |
| GET | `/api/keys` | `username?` | `api_keys_endpoint.py` | `ApiKeyListResponse` |
| GET | `/api/keys/key` | `key_id` | `api_keys_endpoint.py` | `ApiKeyInfo` |
| DELETE | `/api/keys` | `key_id` | `api_keys_endpoint.py` | `ApiKeyDeleteResponse` |

### 1.5 Graph Data (`/api/graphs/...`)

| Method | Effective URL | Server File | Response Model |
|--------|--------------|-------------|----------------|
| **SPARQL** | | | |
| POST | `/api/graphs/sparql/query` | `sparql_query_endpoint.py` | `SPARQLQueryResponse` |
| POST | `/api/graphs/sparql/update` | `sparql_update_endpoint.py` | `SPARQLUpdateResponse` |
| POST | `/api/graphs/sparql/insert` | `sparql_insert_endpoint.py` | `SPARQLInsertResponse` |
| POST | `/api/graphs/sparql/delete` | `sparql_delete_endpoint.py` | `SPARQLDeleteResponse` |
| **Graphs** | | | |
| GET | `/api/graphs/graphs?space_id=` | `sparql_graph_endpoint.py` | `List[GraphInfo]` |
| GET | `/api/graphs/graph?space_id=&graph_uri=` | `sparql_graph_endpoint.py` | `GraphInfoResponse` |
| PUT | `/api/graphs/graph?space_id=&graph_uri=` | `sparql_graph_endpoint.py` | `SPARQLGraphResponse` |
| DELETE | `/api/graphs/graph?space_id=&graph_uri=` | `sparql_graph_endpoint.py` | `SPARQLGraphResponse` |
| POST | `/api/graphs/graph?space_id=` | `sparql_graph_endpoint.py` | `SPARQLGraphResponse` |
| GET | `/api/graphs/graph_counts?space_id=&graph_id=` | `sparql_graph_endpoint.py` | `{entity_count, frame_count, relation_count}` |
| **Triples** | | | |
| GET | `/api/graphs/triples` | `triples_endpoint.py` | `TripleListResponse` |
| POST | `/api/graphs/triples` | `triples_endpoint.py` | `TripleOperationResponse` |
| PUT | `/api/graphs/triples` | `triples_endpoint.py` | `TripleOperationResponse` |
| DELETE | `/api/graphs/triples` | `triples_endpoint.py` | `TripleOperationResponse` |
| **Objects** | | | |
| GET | `/api/graphs/objects` | `objects_endpoint.py` | `ObjectsListResponse` / `ObjectCreateResponse` |
| POST | `/api/graphs/objects` | `objects_endpoint.py` | `ObjectCreateResponse` |
| PUT | `/api/graphs/objects` | `objects_endpoint.py` | `ObjectUpdateResponse` |
| DELETE | `/api/graphs/objects` | `objects_endpoint.py` | `ObjectDeleteResponse` |
| **KGTypes** | | | |
| GET | `/api/graphs/kgtypes` | `kgtypes_endpoint.py` | `KGTypesListResponse` / etc |
| POST | `/api/graphs/kgtypes` | `kgtypes_endpoint.py` | `KGTypeCreateResponse` |
| PUT | `/api/graphs/kgtypes` | `kgtypes_endpoint.py` | `KGTypeUpdateResponse` |
| DELETE | `/api/graphs/kgtypes` | `kgtypes_endpoint.py` | `KGTypeDeleteResponse` |
| **KGEntities** | | | |
| GET | `/api/graphs/kgentities` | `kgentities_endpoint.py` | `EntitiesResponse` |
| POST | `/api/graphs/kgentities` | `kgentities_endpoint.py` | `EntityCreateResponse` |
| PUT | `/api/graphs/kgentities` | `kgentities_endpoint.py` | `EntityUpdateResponse` |
| DELETE | `/api/graphs/kgentities` | `kgentities_endpoint.py` | `EntityDeleteResponse` |
| **KGFrames** | | | |
| GET | `/api/graphs/kgframes` | `kgframes_endpoint.py` | `FramesResponse` |
| POST | `/api/graphs/kgframes` | `kgframes_endpoint.py` | `FrameCreateResponse` |
| PUT | `/api/graphs/kgframes` | `kgframes_endpoint.py` | `FrameUpdateResponse` |
| DELETE | `/api/graphs/kgframes` | `kgframes_endpoint.py` | `FrameDeleteResponse` |
| **KGRelations** | | | |
| GET | `/api/graphs/kgrelations` | `kgrelations_endpoint.py` | `RelationListResponse` |
| POST | `/api/graphs/kgrelations` | `kgrelations_endpoint.py` | `RelationCreateResponse` |
| DELETE | `/api/graphs/kgrelations` | `kgrelations_endpoint.py` | `RelationDeleteResponse` |
| POST | `/api/graphs/kgrelations/query` | `kgrelations_endpoint.py` | `RelationQueryResponse` |
| **KGQueries** | | | |
| POST | `/api/graphs/kgqueries` | `kgquery_endpoint.py` | `KGQueryResponse` |
| **Files** | | | |
| GET | `/api/files` | `files_endpoint.py` | — |
| POST | `/api/files` | `files_endpoint.py` | — |
| PUT | `/api/files` | `files_endpoint.py` | — |
| DELETE | `/api/files` | `files_endpoint.py` | — |

### 1.6 Data Import/Export (`/api/data`) — REFACTORED

All job identifiers moved from path parameters to query parameters.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| POST | `/api/data/import` | — | `import_endpoint.py` | `ImportCreateResponse` |
| GET | `/api/data/import` | `space_id?`, `status?` | `import_endpoint.py` | `ImportJobsResponse` |
| GET | `/api/data/import/job` | `job_id` | `import_endpoint.py` | `ImportJobResponse` |
| DELETE | `/api/data/import` | `job_id` | `import_endpoint.py` | `ImportDeleteResponse` |
| POST | `/api/data/import/execute` | `job_id` | `import_endpoint.py` | `ImportExecuteResponse` |
| GET | `/api/data/import/status` | `job_id` | `import_endpoint.py` | `ImportStatusResponse` |
| GET | `/api/data/import/log` | `job_id` | `import_endpoint.py` | `ImportLogResponse` |
| POST | `/api/data/import/upload` | `job_id` | `import_endpoint.py` | `ImportUploadResponse` |
| POST | `/api/data/export` | — | `export_endpoint.py` | `ExportCreateResponse` |
| GET | `/api/data/export` | `space_id?`, `status?` | `export_endpoint.py` | `ExportJobsResponse` |
| GET | `/api/data/export/job` | `job_id` | `export_endpoint.py` | `ExportJobResponse` |
| DELETE | `/api/data/export` | `job_id` | `export_endpoint.py` | `ExportDeleteResponse` |
| POST | `/api/data/export/execute` | `job_id` | `export_endpoint.py` | `ExportExecuteResponse` |
| GET | `/api/data/export/status` | `job_id` | `export_endpoint.py` | `ExportStatusResponse` |
| GET | `/api/data/export/download` | `job_id` | `export_endpoint.py` | (streaming) |

### 1.7 Entity Registry (`/api/registry`)

| Method | Effective URL | Server File |
|--------|--------------|-------------|
| (multiple CRUD routes) | `/api/registry/...` | `entity_registry_endpoint.py` |

### 1.8 Agent Registry (`/api/agents`)

| Method | Effective URL | Server File |
|--------|--------------|-------------|
| (multiple CRUD routes) | `/api/agents/...` | `agent_registry_endpoint.py` |

### 1.9 Processes (`/api/processes`)

| Method | Effective URL | Server File | Response Model |
|--------|--------------|-------------|----------------|
| GET | `/api/processes` | `process_endpoint.py` | `ProcessListResponse` |
| GET | `/api/processes/scheduler` | `process_endpoint.py` | `SchedulerStatusResponse` |
| GET | `/api/processes/detail` | `process_endpoint.py` | `ProcessResponse` |
| POST | `/api/processes/trigger` | `process_endpoint.py` | `TriggerResponse` |

### 1.10 Admin (`/api/admin`)

| Method | Effective URL | Server File | Response Model |
|--------|--------------|-------------|----------------|
| POST | `/api/admin/resync` | `admin_endpoint.py` | `ResyncResponse` |
| GET | `/api/admin/audit` | `admin_endpoint.py` | `AuditLogResponse` |

### 1.11 Vector Mappings (`/api/vector-mappings`) — REFACTORED

All identifiers moved from path parameters to query parameters.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| GET | `/api/vector-mappings` | `space_id`, `mapping_id?`, `index_name?`, `mapping_type?`, `enabled?` | `vector_mappings_endpoint.py` | `MappingListResponse` / `MappingOut` |
| POST | `/api/vector-mappings` | `space_id` | `vector_mappings_endpoint.py` | `MappingOut` |
| PUT | `/api/vector-mappings` | `space_id`, `mapping_id` | `vector_mappings_endpoint.py` | `MappingOut` |
| DELETE | `/api/vector-mappings` | `space_id`, `mapping_id` | `vector_mappings_endpoint.py` | — |
| POST | `/api/vector-mappings/properties` | `space_id`, `mapping_id` | `vector_mappings_endpoint.py` | `MappingPropertyOut` |
| DELETE | `/api/vector-mappings/properties` | `space_id`, `mapping_id`, `property_id` | `vector_mappings_endpoint.py` | — |

### 1.12 Vector Indexes (`/api/vector-indexes`) — REFACTORED + NEW ROUTES

All identifiers moved from path parameters to query parameters. New direct vector upsert/get routes added.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| GET | `/api/vector-indexes` | `space_id`, `index_name?` | `vector_indexes_endpoint.py` | `VectorIndexListResponse` / `VectorIndexOut` |
| POST | `/api/vector-indexes` | `space_id` | `vector_indexes_endpoint.py` | `VectorIndexOut` |
| DELETE | `/api/vector-indexes` | `space_id`, `index_name` | `vector_indexes_endpoint.py` | — |
| POST | `/api/vector-indexes/reindex` | `space_id`, `index_name` | `vector_indexes_endpoint.py` | `ReindexResponse` |
| POST | `/api/vector-indexes/vectors` | `space_id`, `index_name` | `vector_indexes_endpoint.py` | `VectorUpsertResponse` |
| GET | `/api/vector-indexes/vectors` | `space_id`, `index_name`, `subject_uri?`, `graph_uri?` | `vector_indexes_endpoint.py` | `VectorGetResponse` |

### 1.13 Geo Config (`/api/geo-config`) — REFACTORED

All identifiers moved from path parameters to query parameters.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| GET | `/api/geo-config` | `space_id` | `geo_config_endpoint.py` | `GeoConfigOut` |
| PUT | `/api/geo-config` | `space_id` | `geo_config_endpoint.py` | `GeoConfigOut` |
| DELETE | `/api/geo-config` | `space_id` | `geo_config_endpoint.py` | — |

### 1.14 Geo Points (`/api/geo`) — REFACTORED

All identifiers moved from path parameters to query parameters.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| GET | `/api/geo` | `space_id`, `near_lat?`, `near_lon?`, `radius_km?`, `graph_uri?`, `limit?`, `offset?` | `geo_points_endpoint.py` | `GeoPointsResponse` |

### 1.15 Metrics (`/api/metrics`) — REFACTORED

Refactored from path params to query params.

| Method | Effective URL | Query Params | Server File | Response Model |
|--------|--------------|-------------|-------------|----------------|
| GET | `/api/metrics` | `space_id`, `range?` | `metrics_endpoint.py` | — (inline dict) |
| GET | `/api/metrics/slow` | `space_id`, `limit?` | `metrics_endpoint.py` | — (inline dict) |

### 1.16 KG Documents (`/api/graphs/kgdocuments`) — NEW

| Method | Effective URL | Server File | Response Model |
|--------|--------------|-------------|----------------|
| GET | `/api/graphs/kgdocuments` | `kgdocuments_endpoint.py` | `QuadResponse` |
| POST | `/api/graphs/kgdocuments` | `kgdocuments_endpoint.py` | `QuadResultsResponse` |
| PUT | `/api/graphs/kgdocuments` | `kgdocuments_endpoint.py` | `QuadResultsResponse` |
| DELETE | `/api/graphs/kgdocuments` | `kgdocuments_endpoint.py` | `QuadResultsResponse` |
| GET | `/api/graphs/kgdocuments/segments` | `kgdocuments_endpoint.py` | `QuadResponse` |
| POST | `/api/graphs/kgdocuments/segment` | `kgdocuments_endpoint.py` | `SegmentDocumentResponse` |
| GET | `/api/graphs/kgdocuments/segmentation-status` | `kgdocuments_endpoint.py` | `SegmentationStatusSummaryResponse` |
| GET | `/api/graphs/kgdocuments/segmentation-configs` | `kgdocuments_endpoint.py` | `SegmentationConfigListResponse` |
| POST | `/api/graphs/kgdocuments/segmentation-configs` | `kgdocuments_endpoint.py` | `SegmentationConfigResponse` |
| PUT | `/api/graphs/kgdocuments/segmentation-configs` | `config_id` | `kgdocuments_endpoint.py` | `SegmentationConfigResponse` |
| DELETE | `/api/graphs/kgdocuments/segmentation-configs` | `space_id`, `config_id` | `kgdocuments_endpoint.py` | — |

---

## 2. Client Endpoint Coverage Matrix

### 2.1 Covered by Client (has client endpoint class)

| Server Group | Client Class | Client File | Status |
|-------------|-------------|------------|--------|
| Spaces | `SpacesEndpoint` | `client/endpoint/spaces_endpoint.py` | COVERED |
| Users | `UsersEndpoint` | `client/endpoint/users_endpoint.py` | COVERED |
| SPARQL | `SparqlEndpoint` | `client/endpoint/sparql_endpoint.py` | COVERED |
| Graphs | `GraphsEndpoint` | `client/endpoint/graphs_endpoint.py` | COVERED |
| Triples | `TriplesEndpoint` | `client/endpoint/triples_endpoint.py` | COVERED |
| Objects | `ObjectsEndpoint` | `client/endpoint/objects_endpoint.py` | COVERED |
| KGTypes | `KGTypesEndpoint` | `client/endpoint/kgtypes_endpoint.py` | COVERED |
| KGEntities | `KGEntitiesEndpoint` | `client/endpoint/kgentities_endpoint.py` | COVERED |
| KGFrames | `KGFramesEndpoint` | `client/endpoint/kgframes_endpoint.py` | COVERED |
| KGRelations | `KGRelationsEndpoint` | `client/endpoint/kgrelations_endpoint.py` | COVERED |
| KGQueries | `KGQueriesEndpoint` | `client/endpoint/kgqueries_endpoint.py` | COVERED |
| Files | `FilesEndpoint` | `client/endpoint/files_endpoint.py` | COVERED |
| Import | `ImportEndpoint` | `client/endpoint/import_endpoint.py` | COVERED |
| Export | `ExportEndpoint` | `client/endpoint/export_endpoint.py` | COVERED |
| Entity Registry | `EntityRegistryClientEndpoint` | `client/endpoint/entity_registry_endpoint.py` | COVERED |
| Agent Registry | `AgentRegistryClientEndpoint` | `client/endpoint/agent_registry_endpoint.py` | COVERED |
| Processes | `ProcessClientEndpoint` | `client/endpoint/process_endpoint.py` | COVERED |
| Admin | `AdminClientEndpoint` | `client/endpoint/admin_endpoint.py` | ✅ COVERED |
| API Keys | `ApiKeysClientEndpoint` | `client/endpoint/api_keys_endpoint.py` | ✅ COVERED |
| Vector Mappings | `VectorMappingsClientEndpoint` | `client/endpoint/vector_mappings_endpoint.py` | ✅ COVERED |
| Vector Indexes | `VectorIndexesClientEndpoint` | `client/endpoint/vector_indexes_endpoint.py` | ✅ COVERED |
| Geo Config | `GeoConfigClientEndpoint` | `client/endpoint/geo_config_endpoint.py` | ✅ COVERED |
| Geo Points | `GeoPointsClientEndpoint` | `client/endpoint/geo_points_endpoint.py` | ✅ COVERED |
| Metrics | `MetricsClientEndpoint` | `client/endpoint/metrics_endpoint.py` | ✅ COVERED |
| KG Documents | `KGDocumentsEndpoint` | `client/endpoint/kgdocuments_endpoint.py` | ✅ COVERED |

### 2.2 NOT Covered by Client (no client endpoint class)

| Server Group | Server File | Priority | Notes |
|-------------|------------|----------|-------|
| **WebSocket** | `vitalgraphapp_impl.py` | DEFERRED | Requires different transport (not REST) |

### 2.3 Partial Coverage (client exists but missing routes)

~~All previously partial endpoints have been completed.~~

None — all REST endpoints now have full client coverage.

---

## 3. Mounting Point Consistency Check

Verify that client URL construction matches server router prefixes:

| Endpoint Group | Server Mount | Client URL Pattern | Match? |
|---------------|-------------|-------------------|--------|
| Spaces | `/api` + `/spaces` | `/api/spaces/...` | YES |
| Users | `/api` + `/users` | `/api/users/...` | YES |
| API Keys | `/api/keys` | `/api/keys/...` | YES |
| SPARQL | `/api/graphs/sparql` + `/query` etc | `/api/graphs/sparql/...` | YES |
| Graphs | `/api/graphs` + `/graphs` | `/api/graphs/graphs` | YES |
| Triples | `/api/graphs` + `/triples` | `/api/graphs/triples` | YES |
| Objects | `/api/graphs` + `/objects` | `/api/graphs/objects` | YES |
| KGTypes | `/api/graphs` + `/kgtypes` | `/api/graphs/kgtypes` | YES |
| KGEntities | `/api/graphs` + `/kgentities` | `/api/graphs/kgentities` | YES |
| KGFrames | `/api/graphs` + `/kgframes` | `/api/graphs/kgframes` | YES |
| KGRelations | `/api/graphs` + `/kgrelations` | `/api/graphs/kgrelations` | YES |
| KGQueries | `/api/graphs` + `/kgqueries` | `/api/graphs/kgqueries` | YES |
| Files | `/api` + `/files` | `/api/files/...` | YES |
| Import | `/api/data` + `/import` | `/api/data/import/...` | YES |
| Export | `/api/data` + `/export` | `/api/data/export/...` | YES |
| Entity Registry | `/api/registry` + `/...` | `/api/registry/...` | YES |
| Agent Registry | `/api/agents` + `/...` | `/api/agents/...` | YES |
| Processes | `/api` + `/processes` | `/api/processes/...` | YES |
| Admin | `/api/admin` + `/resync` | `/api/admin/...` | YES |
| Vector Mappings | `/api` + `/vector-mappings` | `/api/vector-mappings?space_id=...` | ✅ YES (refactored) |
| Vector Indexes | `/api` + `/vector-indexes` | `/api/vector-indexes?space_id=...` | ✅ YES (refactored) |
| Geo Config | `/api` + `/geo-config` | `/api/geo-config?space_id=...` | ✅ YES (refactored) |
| Geo Points | `/api` + `/geo` | `/api/geo?space_id=...` | ✅ YES (refactored) |
| Metrics | `/api` + `/metrics` | `/api/metrics?space_id=...` | ✅ YES (refactored) |
| KG Documents | `/api/graphs` + `/kgdocuments` | `/api/graphs/kgdocuments` | ✅ YES |

**Result**: All existing client endpoint URL patterns match the server mounts correctly. No inconsistencies detected.

---

## 4. Pydantic Model Assessment

### 4.1 Models in `vitalgraph/model/` (shared between server and client)

| Model File | Used By |
|-----------|---------|
| `api_key_model.py` | Server `api_keys_endpoint.py` — not yet used by client |
| `api_model.py` | General API models |
| `entity_registry_model.py` | Entity registry |
| `export_model.py` | Import/export endpoints |
| `files_model.py` | Files endpoint |
| `import_model.py` | Import endpoint |
| `kgentities_model.py` | KGEntities |
| `kgframes_model.py` | KGFrames |
| `kgqueries_model.py` | KGQueries |
| `kgrelations_model.py` | KGRelations |
| `kgtypes_model.py` | KGTypes |
| `objects_model.py` | Objects |
| `quad_model.py` | Quad operations |
| `spaces_model.py` | Spaces (includes analytics models) |
| `sparql_model.py` | SPARQL operations |
| `triples_model.py` | Triples |
| `users_model.py` | Users |
| `kgdocuments_model.py` | KGDocuments (segmentation request/response/config/status) |

### 4.2 Models extracted from server endpoint files ✅ DONE

| Server Endpoint | Models | Extracted To |
|----------------|--------|-------------|
| `vector_mappings_endpoint.py` | `MappingPropertyOut`, `MappingOut`, `MappingListResponse`, `CreateMappingRequest`, `UpdateMappingRequest`, `AddPropertyRequest` | ✅ `model/vector_mappings_model.py` |
| `vector_indexes_endpoint.py` | `VectorIndexOut`, `VectorIndexListResponse`, `CreateVectorIndexRequest`, `ReindexRequest`, `ReindexResponse` | ✅ `model/vector_indexes_model.py` |
| `geo_config_endpoint.py` | `GeoConfigOut`, `UpdateGeoConfigRequest` | ✅ `model/geo_model.py` |
| `geo_points_endpoint.py` | `GeoPointOut`, `GeoPointsResponse` | ✅ `model/geo_model.py` |
| `process_endpoint.py` | `ProcessResponse`, `ProcessListResponse`, `TriggerRequest`, `TriggerResponse`, `SchedulerStatusResponse` | ✅ `model/process_model.py` |
| `admin_endpoint.py` | `ResyncResponse`, `AuditLogEntry`, `AuditLogResponse` | ✅ `model/admin_model.py` |
| `metrics_endpoint.py` | (new formal models created) `MetricsTotals`, `MetricsResponse`, `SlowQueryEntry`, `SlowQueriesResponse` | ✅ `model/metrics_model.py` |
| `vector_indexes_endpoint.py` | `VectorEntry`, `VectorUpsertRequest`, `VectorUpsertResponse`, `VectorGetOut`, `VectorGetResponse` | ✅ `model/vector_indexes_model.py` (extended) |
| `kgdocuments_endpoint.py` | `SegmentDocumentRequest`, `SegmentDocumentResponse`, `SegmentationConfigRequest/Response/ListResponse`, `SegmentationJobStatusResponse`, `SegmentationStatusSummaryResponse` | ✅ `model/kgdocuments_model.py` |

---

## 5. Implementation Plan

### Phase 1: Model Extraction ✅ DONE
Moved inline Pydantic models from server endpoint files into `vitalgraph/model/`. Updated server endpoint imports to use shared models.

### Phase 2: New Client Endpoints (HIGH priority) ✅ DONE

1. **API Keys** — `client/endpoint/api_keys_endpoint.py`
   - `create_key()`, `list_keys()`, `get_key()`, `revoke_key()`
   - Registered as `self.api_keys` in `vitalgraph_client.py`

### Phase 3: Missing Methods on Existing Endpoints ✅ DONE

2. **Admin** — Added `audit_log()` method to `AdminClientEndpoint`
3. **Spaces** — Added `get_space_analytics()` method to `SpacesEndpoint`
4. **Users** — Added `change_password()` method to `UsersEndpoint`

### Phase 4: New Client Endpoints (MEDIUM priority) ✅ DONE

5. **Vector Mappings** — `client/endpoint/vector_mappings_endpoint.py` (7 methods)
   - `list_mappings()`, `create_mapping()`, `get_mapping()`, `update_mapping()`, `delete_mapping()`, `add_property()`, `remove_property()`
6. **Vector Indexes** — `client/endpoint/vector_indexes_endpoint.py` (5 methods + 2 new)
   - `list_indexes()`, `create_index()`, `get_index()`, `delete_index()`, `reindex()`
   - `upsert_vectors()`, `get_vectors()` — direct vector upsert/get

### Phase 5: New Client Endpoints (LOW priority) ✅ DONE

7. **Geo Config** — `client/endpoint/geo_config_endpoint.py` (3 methods)
   - `get_config()`, `update_config()`, `delete_config()`
8. **Geo Points** — `client/endpoint/geo_points_endpoint.py` (1 method)
   - `list_points()`
9. **Metrics** — `client/endpoint/metrics_endpoint.py` (2 methods)
   - `get_metrics()`, `get_slow_queries()`

### Phase 6: Registration ✅ DONE

10. All new endpoint instances registered in `VitalGraphClient.__init__()`:
    - `self.api_keys`, `self.vector_mappings`, `self.vector_indexes`
    - `self.geo_config`, `self.geo_points`, `self.metrics`

### Phase 7: Route Refactoring — Path Params → Query Params ✅ DONE

Server endpoints refactored to use static URL paths with query parameters instead of dynamic path segments. Both server and client updated:

| Endpoint | Old URL Pattern | New URL Pattern |
|----------|----------------|----------------|
| Vector Mappings | `/api/spaces/{id}/vector-mappings/{mid}/properties/{pid}` | `/api/vector-mappings/properties?space_id=&mapping_id=&property_id=` |
| Vector Indexes | `/api/spaces/{id}/vector-indexes/{name}/reindex` | `/api/vector-indexes/reindex?space_id=&index_name=` |
| Geo Config | `/api/spaces/{id}/geo-config` | `/api/geo-config?space_id=` |
| Geo Points | `/api/spaces/{id}/geo` | `/api/geo?space_id=` |

### Phase 8: KG Documents ✅ DONE

11. **KG Documents** — `client/endpoint/kgdocuments_endpoint.py` (registered as `self.kgdocuments`)
    - ✅ `list_kgdocuments()`, `get_kgdocument()`, `create_kgdocuments()`, `update_kgdocuments()`
    - ✅ `delete_kgdocument()`, `delete_kgdocuments_batch()`
    - ✅ `list_segments()` — list segment children of a parent document
    - ✅ `segment_document()` — trigger segmentation
    - ✅ `get_segmentation_status()` — job status for a space/document
    - ✅ `setup_document_segments_index()` — convenience wrapper for vector index creation
    - ✅ `setup_document_segments_mapping()` — convenience wrapper for mapping creation
    - ✅ `reindex_document_segments()` — convenience wrapper for reindexing
    - ✅ Delegation methods on `VitalGraphClient`: `list_kgdocuments`, `get_kgdocument`, `create_kgdocuments`, `update_kgdocuments`, `delete_kgdocument`, `delete_kgdocuments_batch`, `segment_document`, `get_segmentation_status`
    - ✅ `list_segmentation_configs()`, `create_segmentation_config()`, `update_segmentation_config()`, `delete_segmentation_config()`
    - ✅ Delegation methods on `VitalGraphClient` for all four config CRUD methods

### Phase 9: New Vector Index Routes ✅ DONE

12. **Vector Indexes** — added `upsert_vectors()` and `get_vectors()` methods
    - Direct pre-computed embedding upsert (batch, up to 1000)
    - Vector retrieval by subject URI and/or graph URI
    - Models: `VectorUpsertRequest`, `VectorUpsertResponse`, `VectorGetOut`, `VectorGetResponse`

### Phase 10: Interface & Testing ✅ DONE

13. ✅ `VitalGraphClientInterface` extended with abstract methods for all new endpoints:
    - Segmentation config CRUD (4 methods)
    - KGFrames with Slots (4 methods)
    - KGEntities (7 methods)
    - Health / diagnostics (2 methods)
14. ✅ Metrics endpoint refactored: path params → query params (server + client)
15. ✅ Integration tests added for new endpoints (live server, no mocks):
    - `test_segmentation_configs_endpoint.py` — full CRUD cycle (7 tests, all passing)
    - `test_metrics_endpoint.py` — all time ranges + slow queries
    - `test_vector_geo_endpoints.py` — vector indexes, vector mappings, geo config, geo points
16. ✅ Server bug fix: `_get_config_manager` in `kgdocuments_endpoint.py` — `_get_connection()` wasn't navigating backend object hierarchy (`db_impl._pool` / `postgresql_impl.connection_pool`)
17. ✅ Swagger tags: added `tags=["KG Documents"]` to segment + segmentation-config routes

### Phase 11: Route Refactoring — Remaining Endpoints ✅ DONE

Extended the Phase 7 query-param pattern to all remaining path-param endpoints. Both server and Python client updated:

| Endpoint Group | Old URL Pattern | New URL Pattern |
|---------------|----------------|----------------|
| API Keys | `/api/keys/{key_id}` | `/api/keys?key_id=` / `/api/keys/key?key_id=` |
| Spaces | `/api/spaces/{id}` | `/api/spaces?space_id=` / `/api/spaces/space?space_id=` |
| Users | `/api/users/{id}` | `/api/users?user_id=` / `/api/users/user?user_id=` |
| User Spaces | `/api/users/{id}/spaces/{sid}` | `/api/users/spaces?user_id=&space_id=` |
| Segmentation Configs | `/segmentation-configs/{config_id}` | `/segmentation-configs?config_id=` |
| Import | `/api/data/import/{job_id}/*` | `/api/data/import/*?job_id=` |
| Export | `/api/data/export/{job_id}/*` | `/api/data/export/*?job_id=` |

### Phase 12: Type Lint Cleanup — `vitalgraph_client.py` + `vitalgraph_client_inf.py` ✅ DONE

Fixed pre-existing type mismatches between `client_response.py` models and `model/` models in delegation methods:

18. ✅ Updated `vitalgraph_client.py` imports — replaced `model/` TYPE_CHECKING imports with runtime `client_response` imports for all response types (Spaces, KGTypes, Objects, Frames, Entities, Files)
19. ✅ Fixed ~30 return type annotations on delegation methods (e.g. `QuadResponse` → `KGTypesListResponse`, `FrameCreateResponse` → `CreateEntityResponse`, etc.)
20. ✅ Removed duplicate file method stubs that overrode correct implementations with stale helper calls
21. ✅ Updated `vitalgraph_client_inf.py` imports and return type annotations to match `client_response.py`
22. ✅ Fixed `kgentities_endpoint.py`: `create_kgentities()` and `update_kgentities()` return type corrected (`EntityResponse` → `CreateEntityResponse`/`UpdateEntityResponse`)

### Phase 13: Frontend ApiService.ts Sync ✅ DONE

23. ✅ Updated TypeScript `frontend/src/services/ApiService.ts` — 13 methods refactored from path params to query params:
    - **Spaces** (6): `updateSpace`, `deleteSpace`, `getSpaceInfo`, `getSpaceAnalytics`, `getSpaceMetrics`, `getSpaceSlowQueries`
    - **Users** (6): `getUser`, `updateUser`, `deleteUser`, `getUserSpaces`, `grantSpaceAccess`, `revokeSpaceAccess`
    - **API Keys** (1): `revokeApiKey`
24. ✅ Fixed `getSpaceMetrics`/`getSpaceSlowQueries` — were calling wrong base path (`/api/spaces/{id}/metrics` → `/api/metrics?space_id=`)

### Phase 14: SPARQL & Graph Route Refactoring ✅ DONE

25. ✅ Server SPARQL endpoints (`query`, `update`, `insert`, `delete`) refactored from `/{space_id}/...` to `?space_id=`
26. ✅ Server Graph endpoints (`graphs`, `graph`, `graph_counts`) refactored from `/{space_id}/...` to `?space_id=&graph_uri=`
27. ✅ Python client + TS client + frontend `ApiService.ts` updated to match
28. ✅ Metrics middleware regex updated for new static routes

### Phase 15: TypeScript Client Full Sync ✅ DONE

Audited all TS client endpoints against the Python client and added missing methods:

| TS Endpoint | Methods Added |
|---|---|
| `GraphsEndpoint` | `getCounts` |
| `KGEntitiesEndpoint` | `getByUris`, `getByReferenceIds`, `updateEntityOnly`, `getFrames`, `createFrames`, `updateFrames`, `deleteFrames`, `queryEntities`, `count`, `batchCount` |
| `KGFramesEndpoint` | `getByUris`, `batchDelete`, `createSlots`, `updateSlots`, `deleteSlots`, `getChildFrames`, `createChildFrames`, `updateChildFrames`, `deleteChildFrames`, `queryFrames` + fixed `getSlots` route |
| `KGRelationsEndpoint` | `get`, `update`, `upsert` |
| `KGTypesEndpoint` | `getByUris`, `batchDelete` |
| `KGDocumentsEndpoint` | `batchDelete`, `segment`, `getSegmentationStatus`, `listSegmentationConfigs`, `createSegmentationConfig`, `updateSegmentationConfig`, `deleteSegmentationConfig` |
| `KGQueriesEndpoint` | `queryConnections`, `queryFrameConnections`, `queryRelationConnections`, `queryFrames`, `queryEntities` + fixed route (`/kgquery` → `/kgqueries`) |
| `ObjectsEndpoint` | `batchDelete` |
| `VectorIndexesEndpoint` | `upsertVectors`, `getVectors` |
| `VectorMappingsEndpoint` | `addProperty`, `removeProperty` |
| `ProcessEndpoint` | `get` (detail) |
| `AdminEndpoint` | `rebuild` |
| `FilesEndpoint` | `batchDelete`, `getByUris` |

New endpoint classes created:

29. ✅ **`AgentRegistryEndpoint`** — `vitalgraph-client-ts/src/endpoint/AgentRegistryEndpoint.ts`
    - Agent Types: `listAgentTypes`, `createAgentType`
    - Agent CRUD: `createAgent`, `getAgent`, `getAgentByUri`, `searchAgents`, `updateAgent`, `deleteAgent`, `changeAgentStatus`
    - Agent Endpoints: `listEndpoints`, `createEndpoint`, `updateEndpoint`, `deleteEndpoint`
    - Agent Functions: `listFunctions`, `createFunction`, `getFunction`, `updateFunction`, `deleteFunction`, `discoverByFunction`
    - Change Log: `getChangeLog`

30. ✅ **`EntityRegistryEndpoint`** — `vitalgraph-client-ts/src/endpoint/EntityRegistryEndpoint.ts`
    - Entity CRUD: `createEntity`, `getEntity`, `searchEntities`, `updateEntity`, `deleteEntity`
    - Identifiers: `addIdentifier`, `listIdentifiers`, `removeIdentifier`, `lookupByIdentifier`
    - Aliases: `addAlias`, `listAliases`, `removeAlias`
    - Categories: `listCategories`, `createCategory`, `listEntityCategories`, `addEntityCategory`, `removeEntityCategory`, `listEntitiesByCategory`
    - Location Types: `listLocationTypes`, `createLocationType`
    - Locations: `createLocation`, `getLocation`, `listLocations`, `updateLocation`, `removeLocation`
    - Location Categories: `addLocationCategory`, `removeLocationCategory`, `listLocationCategories`
    - Relationship Types: `listRelationshipTypes`, `createRelationshipType`
    - Relationships: `createRelationship`, `getRelationship`, `listRelationships`, `updateRelationship`, `removeRelationship`
    - Same-As: `createSameAs`, `getSameAs`, `retractSameAs`, `resolveEntity`
    - Entity Types: `listEntityTypes`, `createEntityType`
    - Change Log: `getEntityChangelog`, `getRecentChangelog`
    - Search: `findSimilar`, `searchEntity`, `searchLocation`

31. ✅ Both registered on `VitalGraphClient` as `client.agentRegistry` and `client.entityRegistry`
32. ✅ Barrel exports added to `index.ts` with option interfaces (`SearchAgentsOptions`, `SearchEntitiesOptions`, `SearchEntityOptions`, `SearchLocationOptions`, `FindSimilarOptions`)
33. ✅ `GraphCountsResponse` added to `response/types.ts`
34. ✅ `tsc --noEmit` passes with zero errors

### Phase 16: Frontend Full Delegation to TS Client ✅ DONE

Eliminated **all** raw HTTP calls (`fetch`, `makeRequest`, `get/post/put/delete`) from the frontend. Every API call now flows through typed `vgClient.*` endpoint methods.

**ApiService.ts cleanup:**
- Removed `makeRequest`, `get`, `post`, `put`, `delete`, `patch` helpers and `baseUrl` — all dead code
- `ApiService` is now purely a thin facade over typed `vgClient.*` calls
- Remaining methods (`listApiKeys`, `healthCheck`, `cacheStats`, `getSegmentationStatus`, `segmentDocument`, `uploadFile`, `downloadFile`) all delegate to typed endpoints

**TS client endpoint fixes (matching Python client):**

| Endpoint | Fix |
|----------|-----|
| `ApiKeysEndpoint.list()` | Added optional `username` filter param |
| `AdminEndpoint` | Added `health()` and `cacheStats()` methods |
| `KGDocumentsEndpoint.getSegmentationStatus()` | Removed incorrect `graphId` requirement; added `status`, `limit`, `offset` params |
| `KGDocumentsEndpoint.segment()` | Changed to accept structured data object (not positional params) |
| `FilesEndpoint.upload()` | Fixed to require `fileUri` (matches Python client); added optional metadata |
| `FilesEndpoint.download()` | Added optional `graphId` param; fixed param name to `uri` |
| `KGQueriesEndpoint` | Added `vectorSearch()` method |

**Page refactoring:**

| Page | Before | After |
|------|--------|-------|
| `VectorSearch.tsx` | `apiService.post` to wrong routes | `vgClient.kgqueries.vectorSearch()` |
| `FileUpload.tsx` | `apiService.makeRequest` (missing `uri` bug) | Two-step flow: `vgClient.files.create()` → `vgClient.files.upload()` |
| `AbsObjectDetail.tsx` | Dynamic `apiService.get/post/put/delete` with URL strings | Typed `CrudOps` interface injected per page |

**AbsObjectDetail typed CRUD refactoring:**
- Replaced `apiEndpoint: string` config field with `crudOps: CrudOps` interface
- Each detail page passes the correct typed endpoint:
  - `ObjectDetail.tsx` → `vgClient.objects`
  - `KGEntityDetail.tsx` → `vgClient.kgentities`
  - `KGFrameDetail.tsx` → `vgClient.kgframes`
  - `KGTypeDetail.tsx` → `vgClient.kgtypes`
  - `KGDocumentDetail.tsx` → `vgClient.kgdocuments`

**Satellite service refactoring:**
- `VectorGeoService.ts` → delegates to `vgClient.vectorIndexes`, `vgClient.vectorMappings`, `vgClient.geoConfig`, `vgClient.geoPoints`
- `ImportExportService.ts` → delegates to `vgClient.imports`, `vgClient.exports`

**Result:** `grep -r 'apiService\.\(get\|post\|put\|delete\|patch\|makeRequest\)' frontend/src/` returns zero matches. No `fetch()` calls exist outside of `FrontendVitalGraphClient.ts` (auth layer) and `AuthService.ts` (login/logout). Frontend compiles cleanly (`tsc --noEmit` exits 0).

35. ✅ TS client version bumped to 0.1.2; frontend linked to local build via `file:../vitalgraph-client-ts`

### Phase 17: WebSocket Client — Python & TypeScript

Implement WebSocket client support in both the Python and TS clients for the `/api/ws` server endpoint.

**Server endpoint** (`vitalgraphapp_impl.py`):
- `WS /api/ws` — authenticated WebSocket; pushes real-time notifications (job status, segmentation progress, etc.)

**Python client** (`vitalgraph/client/`):
- New class `WebSocketClient` (or method on `VitalGraphClient`)
- Connect with JWT auth (token in query param or initial message)
- Async message listener with typed event models
- Auto-reconnect with backoff on disconnect
- Clean shutdown / context-manager support

**TS client** (`vitalgraph-client-ts/`):
- New class `WebSocketEndpoint` (or similar)
- Browser-native `WebSocket` API + Node.js `ws` compatibility
- JWT auth handshake
- Typed event callback registration (`onJobStatus`, `onSegmentationProgress`, etc.)
- Auto-reconnect with exponential backoff
- `connect()` / `disconnect()` lifecycle

**Frontend integration:**
- Replace any ad-hoc WebSocket usage with `vgClient.ws.connect()` / event subscriptions
- Use for live polling replacement (segmentation status, import/export progress)

Status: **NOT STARTED**

---

## 6. Open Questions / Remaining Work

- ~~**Model extraction scope**: Should we extract ALL inline models in Phase 1?~~ → Resolved: extracted all.
- ~~**Metrics endpoint**: Define proper Pydantic models or keep dicts?~~ → Resolved: created `model/metrics_model.py`; client returns dicts for now since server returns dicts.
- ~~**Route refactoring**: Vector/Geo endpoints moved from path params to query params.~~ → Resolved: both server and client updated.
- ~~**KGDocuments segmentation config CRUD**: Client endpoint is missing config CRUD methods.~~ → Resolved: implemented `list_segmentation_configs()`, `create_segmentation_config()`, `update_segmentation_config()`, `delete_segmentation_config()` with delegation methods on `VitalGraphClient`.
- ~~**Metrics endpoint route style**: Metrics still uses path params.~~ → Resolved: refactored to `/api/metrics?space_id=` (server + client).
- **WebSocket**: The `/api/ws` endpoint uses a different transport. → Tracked as **Phase 17** (not started).
- ~~**Interface updates**: The `VitalGraphClientInterface` abstract methods could be extended.~~ → Resolved: added abstract methods for all new endpoints.
- ~~**Pre-existing type lint issues**: `vitalgraph_client.py` has type mismatches between `client_response.py` models and `model/` models in delegation methods.~~ → Resolved in Phase 12: fixed all imports, return type annotations, and added `@overload` decorators for `list_kgentities`/`get_kgentity` to discriminate on `include_entity_graph`.
- ~~**Client tests**: No automated tests exist yet for the new endpoints.~~ → Resolved: integration tests added for segmentation configs, metrics, vector/geo endpoints.
- ~~**TS client missing methods/endpoints**: AgentRegistry and EntityRegistry not implemented; many other endpoints had gaps.~~ → Resolved in Phase 15: all methods synced, both registries implemented.

---

## 7. API Consistency Policy

**Rule (mandatory for all FastAPI endpoints)**:

> **No dynamic segments in URL paths.** All identifiers (`space_id`, `graph_uri`, `graph_id`, `index_name`, `mapping_id`, `property_id`, `key_id`, etc.) **must** be passed as query parameters (`?space_id=...&graph_uri=...`). URL paths contain only static route segments.

### Rationale
- Uniform URL structure across all endpoints — no exceptions.
- Simplifies client generation, middleware (metrics, logging), and documentation.
- Prevents ambiguous path-matching and route-ordering bugs in FastAPI.

### Scope
This rule applies to **every** FastAPI router in `vitalgraph/endpoint/`:
- Spaces, Admin, Users, API Keys
- SPARQL (query, update, insert, delete)
- Graphs (list, info, create, delete, clear, counts)
- Triples, Objects
- KGEntities, KGFrames, KGRelations, KGTypes, KGQueries, KGDocuments
- Import, Export, Process, Files
- Vector Indexes, Vector Mappings, Geo Config, Geo Points
- Metrics

### Enforcement
- **New endpoints** must follow this convention from day one.
- **Code review**: reject any PR that introduces `{param}` in a FastAPI route path.
- All three clients (Python `vitalgraph/client/`, TypeScript `vitalgraph-client-ts/`, frontend `ApiService.ts`) must stay in sync with server routes.

### Status
**All REST endpoints are now compliant.** SPARQL and Graph endpoints were the last to be refactored (Phase 14). No dynamic path segments remain.
