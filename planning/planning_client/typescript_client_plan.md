# VitalGraph TypeScript Client — Implementation Plan

## Goal

Create a standalone TypeScript/JavaScript client package (`vitalgraph-client-ts`) that mirrors the Python client (`vitalgraph/client/`) for connecting to VitalGraph REST API servers. The package should be publishable to npm and usable from both Node.js and browser environments.

---

## 1. Relationship to Existing Code

### 1.1 Python Client (reference implementation)

The Python client in `vitalgraph/client/` is the reference implementation. The TS client should mirror its structure:

| Python Module | Purpose | TS Equivalent |
|--------------|---------|---------------|
| `vitalgraph_client.py` | Main client with delegation methods | `src/VitalGraphClient.ts` |
| `vitalgraph_client_inf.py` | Abstract interface | `src/VitalGraphClientInterface.ts` |
| `client_factory.py` | Factory function | `src/createClient.ts` |
| `config/client_config_loader.py` | Profile-based config from env vars | `src/config/ClientConfig.ts` |
| `endpoint/base_endpoint.py` | Base endpoint class | `src/endpoint/BaseEndpoint.ts` |
| `endpoint/*.py` (25 endpoints) | Per-domain endpoint classes | `src/endpoint/*.ts` |
| `response/client_response.py` | Pydantic response models | `src/response/types.ts` |
| `utils/client_utils.py` | Error class, param helpers | `src/utils/errors.ts`, `src/utils/params.ts` |
| `utils/format_helpers.py` | Wire format / serialization | `src/utils/format.ts` |

### 1.2 Frontend ApiService (NOT the same thing)

`frontend/src/services/ApiService.ts` is a browser-only, singleton service tightly coupled to the React frontend (token refresh via `localStorage`, `fetch` API). The TS client is a **standalone, reusable package** with:

- No React/browser dependencies
- Environment variable config (Node.js) OR constructor options (browser)
- Typed response objects (not raw `Promise<any>`)
- Proper endpoint class decomposition (not one monolith)

Once the TS client exists, `ApiService.ts` can be refactored to use it as a thin wrapper.

---

## 2. Package Setup

### 2.1 Directory Structure

```
vitalgraph-client-ts/
├── src/
│   ├── index.ts                          # Public API barrel export
│   ├── VitalGraphClient.ts               # Main client class
│   ├── VitalGraphClientInterface.ts      # Interface / abstract type
│   ├── createClient.ts                   # Factory function
│   ├── config/
│   │   └── ClientConfig.ts               # Configuration loader
│   ├── endpoint/
│   │   ├── BaseEndpoint.ts               # Base class for all endpoints
│   │   ├── SpacesEndpoint.ts
│   │   ├── UsersEndpoint.ts
│   │   ├── ApiKeysEndpoint.ts
│   │   ├── SparqlEndpoint.ts
│   │   ├── GraphsEndpoint.ts
│   │   ├── TriplesEndpoint.ts
│   │   ├── ObjectsEndpoint.ts
│   │   ├── KGTypesEndpoint.ts
│   │   ├── KGEntitiesEndpoint.ts
│   │   ├── KGFramesEndpoint.ts
│   │   ├── KGRelationsEndpoint.ts
│   │   ├── KGQueriesEndpoint.ts
│   │   ├── KGDocumentsEndpoint.ts
│   │   ├── FilesEndpoint.ts
│   │   ├── ImportEndpoint.ts
│   │   ├── ExportEndpoint.ts
│   │   ├── EntityRegistryEndpoint.ts
│   │   ├── AgentRegistryEndpoint.ts
│   │   ├── ProcessEndpoint.ts
│   │   ├── AdminEndpoint.ts
│   │   ├── MetricsEndpoint.ts
│   │   ├── VectorMappingsEndpoint.ts
│   │   ├── VectorIndexesEndpoint.ts
│   │   ├── GeoConfigEndpoint.ts
│   │   └── GeoPointsEndpoint.ts
│   ├── response/
│   │   └── types.ts                      # All response type interfaces
│   └── utils/
│       ├── errors.ts                     # VitalGraphClientError
│       ├── params.ts                     # buildQueryParams, validateRequired
│       └── format.ts                     # Wire format helpers
├── tests/
│   ├── unit/
│   │   ├── config.test.ts
│   │   ├── params.test.ts
│   │   └── errors.test.ts
│   └── integration/
│       ├── spaces.test.ts
│       ├── users.test.ts
│       └── ...
├── package.json
├── tsconfig.json
├── tsconfig.build.json
├── vitest.config.ts
├── .eslintrc.cjs
├── .gitignore
└── README.md
```

### 2.2 Tech Stack

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Language | TypeScript 5.7+ | Match frontend |
| HTTP client | `fetch` (native) | No external dependency; works in Node 18+ and browsers |
| Build | `tsup` (esbuild-based) | Fast, outputs ESM + CJS + `.d.ts` |
| Test | `vitest` | Fast, TS-native, compatible with frontend |
| Lint | `eslint` + `typescript-eslint` | Match frontend |
| Package format | ESM primary, CJS fallback | Modern default |
| VitalSigns | `@vital-ai/vital-model-utils` (peer) | Typed graph objects, JSON conversion, graph traversal |
| Domain models | `@vital-ai/vital-kg-model-ts` (peer) | KG entity/frame/edge classes (KGEntity, KGFrame, etc.) |

### 2.3 package.json (skeleton)

```json
{
  "name": "@vital-ai/vitalgraph-client",
  "version": "0.1.0",
  "type": "module",
  "main": "./dist/index.cjs",
  "module": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "import": "./dist/index.js",
      "require": "./dist/index.cjs",
      "types": "./dist/index.d.ts"
    }
  },
  "files": ["dist"],
  "scripts": {
    "build": "tsup src/index.ts --format esm,cjs --dts",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src/",
    "typecheck": "tsc --noEmit"
  },
  "peerDependencies": {
    "@vital-ai/vital-model-utils": ">=0.1.7",
    "@vital-ai/vital-kg-model-ts": ">=0.1.0"
  },
  "devDependencies": {
    "@vital-ai/vital-model-utils": "^0.1.7",
    "@vital-ai/vital-kg-model-ts": "^0.1.0",
    "tsup": "^8.0.0",
    "typescript": "~5.7.0",
    "vitest": "^2.0.0",
    "eslint": "^9.0.0",
    "typescript-eslint": "^8.0.0"
  }
}
```

---

## 3. Core Architecture

### 3.1 Authentication

The Python client supports two modes. The TS client should mirror both:

| Mode | Python | TS Equivalent |
|------|--------|---------------|
| **JWT** | `POST /api/login` with form data → stores `access_token` + `refresh_token` → auto-refresh | Same flow with `fetch` |
| **API Key** | `api_key="vg_..."` → set as Bearer token, skip login | Same |

Key behaviors to replicate:
- Proactive token refresh before expiry (configurable)
- Reactive 401 retry with token refresh
- Automatic `Authorization: Bearer <token>` header injection

### 3.2 Configuration

```typescript
interface VitalGraphClientOptions {
  serverUrl: string;
  username?: string;      // JWT mode
  password?: string;      // JWT mode
  apiKey?: string;        // API key mode (skip JWT)
  timeout?: number;       // Request timeout in ms (default 30000)
  maxRetries?: number;    // Max retry attempts (default 3)
}
```

Also support environment variable loading (Node.js only, same profile pattern as Python):
```
VITALGRAPH_CLIENT_ENVIRONMENT=local
LOCAL_CLIENT_SERVER_URL=http://localhost:8001
LOCAL_CLIENT_AUTH_USERNAME=admin
LOCAL_CLIENT_AUTH_PASSWORD=admin
```

### 3.3 BaseEndpoint Pattern

```typescript
abstract class BaseEndpoint {
  constructor(protected client: VitalGraphClient) {}

  protected get serverUrl(): string { return this.client.config.serverUrl; }

  protected async request<T>(method: string, path: string, options?: RequestOptions): Promise<T> {
    // Delegates to client._makeAuthenticatedRequest()
    // Parses JSON response
  }

  protected buildParams(params: Record<string, unknown>): URLSearchParams {
    // Filters out null/undefined values
  }
}
```

### 3.4 URL Convention

**All endpoints use query parameters only** — no dynamic path segments. This matches the API consistency policy established in the Python client (see `client_api_sync_plan.md` §7).

---

## 4. Response Type System

### 4.1 Base Response

```typescript
interface VitalGraphResponse {
  error_code: number;        // 0 = success
  error_message?: string;
  status_code: number;
  message?: string;
  metadata: Record<string, unknown>;
}
```

### 4.2 Response Type Inventory

Derived from Python `client_response.py`. Each maps to a TypeScript interface:

| Python Class | TS Interface | Key Fields |
|-------------|-------------|------------|
| `GraphObjectResponse` | `GraphObjectResponse` | `objects: GraphObject[]` |
| `PaginatedGraphObjectResponse` | `PaginatedResponse` | `+ total_count, page_size, offset, has_more` |
| `EntityGraph` | `EntityGraph` | `entity_uri, objects` |
| `FrameGraph` | `FrameGraph` | `frame_uri, objects` |
| `EntityResponse` | `EntityResponse` | extends `GraphObjectResponse` |
| `EntityGraphResponse` | `EntityGraphResponse` | `objects: EntityGraph` |
| `FrameGraphResponse` | `FrameGraphResponse` | `frame_graph: FrameGraph` |
| `MultiEntityGraphResponse` | `MultiEntityGraphResponse` | `graph_list: EntityGraph[]` |
| `MultiFrameGraphResponse` | `MultiFrameGraphResponse` | `frame_graph_list: FrameGraph[]` |
| `CreateEntityResponse` | `CreateEntityResponse` | `created_count, created_uris` |
| `UpdateEntityResponse` | `UpdateEntityResponse` | `updated_uri` |
| `DeleteResponse` | `DeleteResponse` | `deleted_count, deleted_uris` |
| `QueryResponse` | `QueryResponse` | `objects, query_info` |
| **Spaces** | | |
| `SpaceResponse` | `SpaceResponse` | `space` |
| `SpacesListResponse` | `SpacesListResponse` | `spaces, total` |
| `SpaceCreateResponse` | `SpaceCreateResponse` | `space, created_count` |
| `SpaceUpdateResponse` | `SpaceUpdateResponse` | `space, updated_count` |
| `SpaceDeleteResponse` | `SpaceDeleteResponse` | `deleted_count, space_id` |
| **Graphs** | | |
| `GraphResponse` | `GraphResponse` | `graph` |
| `GraphsListResponse` | `GraphsListResponse` | `graphs, total` |
| `GraphCreateResponse` | `GraphCreateResponse` | `graph_uri, created` |
| `GraphDeleteResponse` | `GraphDeleteResponse` | `graph_uri, deleted` |
| `GraphClearResponse` | `GraphClearResponse` | `graph_uri, cleared, triples_removed` |
| **KGTypes** | | |
| `KGTypeResponse` | `KGTypeResponse` | `type` |
| `KGTypesListResponse` | `KGTypesListResponse` | `types, count` |
| `KGTypeCreateResponse` | `KGTypeCreateResponse` | `created, created_count, created_uris` |
| `KGTypeUpdateResponse` | `KGTypeUpdateResponse` | `updated, updated_count, updated_uris` |
| `KGTypeDeleteResponse` | `KGTypeDeleteResponse` | `deleted, deleted_count, deleted_uris` |
| **Objects** | | |
| `ObjectResponse` | `ObjectResponse` | `object` |
| `ObjectsListResponse` | `ObjectsListResponse` | `objects, count` |
| `ObjectCreateResponse` | `ObjectCreateResponse` | `created, created_count, created_uris` |
| `ObjectUpdateResponse` | `ObjectUpdateResponse` | `updated, updated_count, updated_uris` |
| `ObjectDeleteResponse` | `ObjectDeleteResponse` | `deleted, deleted_count, deleted_uris` |
| **Files** | | |
| `FileResponse` | `FileResponse` | `file_uri, file_node, objects` |
| `FilesListResponse` | `FilesListResponse` | extends `PaginatedResponse` |
| `FileCreateResponse` | `FileCreateResponse` | `created_uris, created_count` |
| `FileUpdateResponse` | `FileUpdateResponse` | `updated_uris, updated_count` |
| `FileDeleteResponse` | `FileDeleteResponse` | `deleted_uris, deleted_count` |
| `FileUploadResponse` | `FileUploadResponse` | `file_uri, size, content_type` |
| **KGDocuments** | | |
| `KGDocumentResponse` | `KGDocumentResponse` | `document` |
| `KGDocumentsListResponse` | `KGDocumentsListResponse` | `documents, count` |
| `KGDocumentCreateResponse` | `KGDocumentCreateResponse` | `created, created_count, created_uris` |
| `KGDocumentUpdateResponse` | `KGDocumentUpdateResponse` | `updated, updated_count, updated_uris` |
| `KGDocumentDeleteResponse` | `KGDocumentDeleteResponse` | `deleted, deleted_count, deleted_uris` |

### 4.3 VitalSigns Integration

The TypeScript VitalSigns ecosystem provides the same typed graph object model as the Python `vital_ai_vitalsigns` package:

| Package | Purpose | Key Exports |
|---------|---------|-------------|
| `@vital-ai/vital-model-utils` | Base classes, conversion, traversal | `VitalSignsObject`, `VitalSignsConverter`, `VitalSignsGraphTraverser`, `VitalSignsFilterEngine` |
| `@vital-ai/vital-kg-model-ts` | Generated domain model classes | `KGEntity`, `KGFrame`, `KGDocument`, `Edge_hasKGFrame`, etc. |

#### VitalSignsObject (base class)

```typescript
abstract class VitalSignsObject {
  URI?: string;
  vitaltype?: string;
  timestamp?: number;
  active?: boolean;
  toJSON(): Record<string, any>;
  fromJSON(data: Record<string, any>): void;
  abstract getPropertyDefinitions(): VitalSignsPropertyDefinition[];
}
```

This is the TS equivalent of Python's `GraphObject`. All domain classes (`KGEntity`, `KGFrame`, `VITAL_Node`, etc.) extend it.

#### Converter (JSON ↔ typed instances)

```typescript
class VitalSignsConverter {
  static toInstance<T extends VitalSignsObject>(jsonData, ClassConstructor): ConversionResult<T>;
  static fromInstance(instance: VitalSignsObject): VitalSignsJsonObject;
  static autoDetectType(jsonData: Record<string, any>): string | null;
}
```

The client will use `VitalSignsConverter` to deserialize JSON responses from the server into typed `VitalSignsObject` instances, the same way the Python client uses `deserialize_response_to_graphobjects()`.

#### Class Registry (auto-detection)

`@vital-ai/vital-kg-model-ts` exports a class registry (`VitalSignsClassRegistry`) that maps `vitaltype` URIs to constructors. The client uses this for auto-detecting the correct class from server responses:

```typescript
import { kgClassRegistry } from '@vital-ai/vital-kg-model-ts';

// Server returns: { "http://vital.ai/ontology/vital-core#vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGEntity", ... }
// Registry maps vitaltype → KGEntity constructor
// Converter instantiates typed KGEntity
```

#### GraphObject Type in Responses

Response types use `VitalSignsObject` as the base type (not `Record<string, unknown>`):

```typescript
import { VitalSignsObject } from '@vital-ai/vital-model-utils';

interface GraphObjectResponse extends VitalGraphResponse {
  objects?: VitalSignsObject[];
}
```

Callers can narrow to specific domain types:

```typescript
import { KGEntity } from '@vital-ai/vital-kg-model-ts';

const response = await client.kgentities.list(spaceId, graphId);
const entities = response.objects?.filter((o): o is KGEntity => o instanceof KGEntity);
```

---

## 5. Endpoint Coverage

### 5.1 Full Endpoint List (25 endpoints)

All endpoints from the Python client, mapped to TS classes. Routes use query params only.

| # | Endpoint Class | Route Prefix | Methods |
|---|---------------|-------------|---------|
| 1 | `SpacesEndpoint` | `/api/spaces` | list, get, create, update, delete, getInfo, getAnalytics, filter |
| 2 | `UsersEndpoint` | `/api/users` | list, get, create, update, delete, getSpaces, grantAccess, revokeAccess, changePassword |
| 3 | `ApiKeysEndpoint` | `/api/keys` | list, get, create, revoke |
| 4 | `SparqlEndpoint` | `/api/graphs/sparql` | query, update, insert, delete |
| 5 | `GraphsEndpoint` | `/api/graphs/graphs` | list, create, delete, clear |
| 6 | `TriplesEndpoint` | `/api/graphs/triples` | list, create, update, delete |
| 7 | `ObjectsEndpoint` | `/api/graphs/objects` | list, get, create, update, delete |
| 8 | `KGTypesEndpoint` | `/api/graphs/kgtypes` | list, get, create, update, delete |
| 9 | `KGEntitiesEndpoint` | `/api/graphs/kgentities` | list, get, create, update, delete, deleteBatch, getByUris, getByReferenceIds |
| 10 | `KGFramesEndpoint` | `/api/graphs/kgframes` | list, get, create, update, delete, deleteBatch, getWithSlots |
| 11 | `KGRelationsEndpoint` | `/api/graphs/kgrelations` | list, create, delete, query |
| 12 | `KGQueriesEndpoint` | `/api/graphs/kgqueries` | execute |
| 13 | `KGDocumentsEndpoint` | `/api/graphs/kgdocuments` | list, get, create, update, delete, deleteBatch, listSegments, segment, getSegmentationStatus, listConfigs, createConfig, updateConfig, deleteConfig |
| 14 | `FilesEndpoint` | `/api/files` | list, get, create, update, delete, getByUris, upload, download |
| 15 | `ImportEndpoint` | `/api/data/import` | list, get, create, delete, execute, getStatus, getLog, upload |
| 16 | `ExportEndpoint` | `/api/data/export` | list, get, create, delete, execute, getStatus, download |
| 17 | `EntityRegistryEndpoint` | `/api/registry` | CRUD for entities, aliases, identifiers, categories, locations |
| 18 | `AgentRegistryEndpoint` | `/api/agents` | list, get, create, update, delete, changeStatus, getEndpoints, getFunctions, getChangelog, listTypes |
| 19 | `ProcessEndpoint` | `/api/processes` | list, getScheduler, getDetail, trigger |
| 20 | `AdminEndpoint` | `/api/admin` | resync, getAuditLog |
| 21 | `MetricsEndpoint` | `/api/metrics` | getMetrics, getSlowQueries |
| 22 | `VectorMappingsEndpoint` | `/api/vector-mappings` | list, get, create, update, delete, addProperty, removeProperty |
| 23 | `VectorIndexesEndpoint` | `/api/vector-indexes` | list, get, create, delete, reindex, upsertVectors, getVectors |
| 24 | `GeoConfigEndpoint` | `/api/geo-config` | get, update, delete |
| 25 | `GeoPointsEndpoint` | `/api/geo` | list |

---

## 6. Implementation Plan

### Phase 1: Scaffold & Core Infrastructure

1. Initialize package (`package.json`, `tsconfig.json`, `tsup`, `vitest`)
2. `src/utils/errors.ts` — `VitalGraphClientError`
3. `src/utils/params.ts` — `buildQueryParams()`, `validateRequired()`
4. `src/utils/vitalsigns.ts` — Response deserializer using `VitalSignsConverter` + class registry
5. `src/config/ClientConfig.ts` — Options interface + env var loader
6. `src/endpoint/BaseEndpoint.ts` — Base class with `request<T>()` helper, response deserialization
7. `src/VitalGraphClient.ts` — Constructor, `open()`, `close()`, JWT auth flow, token refresh, `_makeAuthenticatedRequest()`
8. `src/response/types.ts` — `VitalGraphResponse` base + initial types (using `VitalSignsObject`)
9. Unit tests for utils, config, and deserialization

### Phase 2: Core Data Endpoints (HIGH priority)

9. `SpacesEndpoint` — list, get, create, update, delete, info, analytics
10. `GraphsEndpoint` — list, create, delete, clear
11. `ObjectsEndpoint` — list, get, create, update, delete
12. `KGTypesEndpoint` — list, get, create, update, delete
13. `KGEntitiesEndpoint` — list, get, create, update, delete (+ batch + entity graphs)
14. `KGFramesEndpoint` — list, get, create, update, delete (+ batch + slots)
15. `KGRelationsEndpoint` — list, create, delete, query
16. `KGQueriesEndpoint` — execute
17. Response types for all above
18. Integration tests against live server

### Phase 3: Auth, Users, Files (HIGH priority)

19. `UsersEndpoint` — CRUD + space access + password change
20. `ApiKeysEndpoint` — list, get, create, revoke
21. `FilesEndpoint` — CRUD + upload (multipart) + download (blob/stream)
22. `SparqlEndpoint` — query, update, insert, delete
23. `TriplesEndpoint` — list, create, update, delete

### Phase 4: KG Documents & Data Import/Export (MEDIUM priority)

24. `KGDocumentsEndpoint` — full CRUD + segmentation + config
25. `ImportEndpoint` — job lifecycle + file upload
26. `ExportEndpoint` — job lifecycle + download

### Phase 5: Registries & Admin (MEDIUM priority)

27. `EntityRegistryEndpoint` — full CRUD
28. `AgentRegistryEndpoint` — full CRUD + status + endpoints/functions/changelog
29. `ProcessEndpoint` — list, scheduler, trigger
30. `AdminEndpoint` — resync, audit log
31. `MetricsEndpoint` — metrics, slow queries

### Phase 6: Vector & Geo (LOW priority)

32. `VectorMappingsEndpoint` — CRUD + properties
33. `VectorIndexesEndpoint` — CRUD + reindex + vectors
34. `GeoConfigEndpoint` — get, update, delete
35. `GeoPointsEndpoint` — list

### Phase 7: Polish & Publish to npm

36. `VitalGraphClientInterface` — full abstract interface type
37. `createClient()` factory function
38. Barrel export (`src/index.ts`)
39. README with usage examples
40. npm publish configuration (see §11)
41. First publish: `npm publish --access public`

---

## 7. Design Decisions

### 7.1 `fetch` vs `axios` vs `httpx`-like

Use native `fetch` (Node 18+ built-in, browser-native). Avoids external dependencies. For Node <18 users, document polyfill requirement (`undici` or `node-fetch`).

### 7.2 Async patterns

All endpoint methods return `Promise<T>`. No callback or Observable patterns. Match Python's `async/await` style.

### 7.3 Error handling

```typescript
class VitalGraphClientError extends Error {
  constructor(message: string, public statusCode?: number) {
    super(message);
    this.name = 'VitalGraphClientError';
  }
}
```

Throw on HTTP errors (4xx/5xx). Response types have `error_code` / `error_message` for server-level errors.

### 7.4 Wire format

The Python client supports pluggable wire formats (`JSON_QUADS`, etc.). The TS client should start with JSON only and add format negotiation later if needed.

### 7.5 Delegation pattern

Like the Python client, `VitalGraphClient` exposes top-level convenience methods that delegate to endpoint instances:

```typescript
class VitalGraphClient {
  readonly spaces = new SpacesEndpoint(this);
  readonly kgentities = new KGEntitiesEndpoint(this);
  // ...

  // Convenience delegation
  async listSpaces() { return this.spaces.list(); }
  async getSpace(spaceId: string) { return this.spaces.get(spaceId); }
}
```

### 7.6 VitalSigns as Peer Dependency

`@vital-ai/vital-model-utils` and `@vital-ai/vital-kg-model-ts` are **peer dependencies**. The client uses `VitalSignsObject` as its base graph object type and `VitalSignsConverter` for response deserialization. This mirrors how the Python client depends on `vital_ai_vitalsigns`.

Benefits:
- Typed domain objects out of the box (no manual casting)
- Auto-detection of `vitaltype` → correct class constructor
- Consistent with the Python client's object model
- Graph traversal/filtering utilities available to callers

The peer dependency pattern means consumers control the version and avoid duplicate copies in the bundle.

---

## 8. Testing Strategy

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | vitest | Config loading, param building, error construction, response parsing |
| Integration | vitest | Full request cycle against running VitalGraph server |
| Type | `tsc --noEmit` | Compile-time type checking |

Integration tests use the same env var pattern as the Python client tests:
```
VITALGRAPH_CLIENT_ENVIRONMENT=local
LOCAL_CLIENT_SERVER_URL=http://localhost:8001
LOCAL_CLIENT_AUTH_USERNAME=admin
LOCAL_CLIENT_AUTH_PASSWORD=admin
```

---

## 9. Resolved Decisions

- ~~**Class registry export**~~ → **Confirmed**: `@vital-ai/vital-kg-model-ts` exports a pre-populated `kgClassRegistry` (`VitalSignsClassRegistry`) and a convenience `convertGraphObjects(rawJsonArray)` function. The client will use `convertGraphObjects()` directly for response deserialization.
- ~~**Wire format**~~ → **JSON_QUADS from day one**. The TS client will send `Accept: application/json-quads` and handle the quad response format, matching the Python client's default.
- ~~**Streaming downloads**~~ → **`ArrayBuffer`** (universal across Node and browser). File and export downloads return `ArrayBuffer`. Callers can wrap in `Blob` (browser) or `Buffer` (Node) as needed.
- ~~**Token storage**~~ → **In-memory only**. Tokens live on the client instance. Re-authenticate on each `open()`. No pluggable store needed.
- ~~**Retry/backoff policy**~~ → **Follow the Python client**: configurable `maxRetries` with exponential backoff + reactive 401 retry with token refresh.
- ~~**VitalSigns peer dep scope**~~ → **Mandatory**. Both `@vital-ai/vital-model-utils` and `@vital-ai/vital-kg-model-ts` are required peer deps. No fallback `Record<string, unknown>` mode.
- ~~**Package naming**~~ → **`@vital-ai/vitalgraph-client`** (no hyphen in "vitalgraph", aligning with the Python package name `vitalgraph`).
- ~~**Frontend migration**~~ → **Full replacement**. Once the TS client is published, `frontend/src/services/ApiService.ts` will be replaced (not just wrapped) by the TS client. The client must therefore support browser-friendly token refresh and the same auth flow currently in `ApiService.ts`.

## 10. Remaining Open Questions

- **WebSocket**: The server has `/api/ws`. Deferred — not REST.
- **Bundle size**: Monitor. Peer deps are tree-shakeable. Keep client code minimal.

---

## 11. npm Publishing

The package is published to the public npm registry under the `@vital-ai` scope (same org as `@vital-ai/vital-model-utils` and `@vital-ai/vital-kg-model-ts`).

### 11.1 Registry & Auth

The `NPM_TOKEN` is stored in the project `.env` (gitignored). The package directory needs an `.npmrc`:

```
vitalgraph-client-ts/.npmrc
```
```ini
//registry.npmjs.org/:_authToken=${NPM_TOKEN}
```

This `.npmrc` should be gitignored (or use only the env var form so no token is committed).

### 11.2 package.json Publishing Fields

```json
{
  "name": "@vital-ai/vitalgraph-client",
  "version": "0.1.0",
  "publishConfig": {
    "access": "public",
    "registry": "https://registry.npmjs.org/"
  },
  "files": [
    "dist",
    "README.md",
    "LICENSE"
  ],
  "repository": {
    "type": "git",
    "url": "https://github.com/vital-ai/vital-graph.git",
    "directory": "vitalgraph-client-ts"
  },
  "author": {
    "name": "Marc Hadfield",
    "email": "marc@vital.ai",
    "organization": "VitalAI"
  },
  "license": "Apache-2.0"
}
```

### 11.3 Build & Publish Workflow

```bash
# One-time setup (from vitalgraph-client-ts/)
echo '//registry.npmjs.org/:_authToken=${NPM_TOKEN}' > .npmrc

# Build
npm run build          # tsup → dist/ (ESM + CJS + .d.ts)

# Verify package contents before publishing
npm pack --dry-run

# Publish
NPM_TOKEN=<token> npm publish --access public

# Subsequent releases
npm version patch      # or minor/major
NPM_TOKEN=<token> npm publish
```

### 11.4 Sibling Packages (already published)

| Package | Version | Registry |
|---------|---------|----------|
| `@vital-ai/vital-model-utils` | 0.1.7 | npmjs.org |
| `@vital-ai/vital-kg-model-ts` | 0.1.0 | npmjs.org |
| `@vital-ai/vitalgraph-client` | **0.1.0** (new) | npmjs.org |

### 11.5 Consumer Install

```bash
npm install @vital-ai/vitalgraph-client @vital-ai/vital-model-utils @vital-ai/vital-kg-model-ts
```

Since `vital-model-utils` and `vital-kg-model-ts` are peer deps, consumers must install them explicitly.

---

## 12. Frontend Migration

The React frontend (`frontend/`) **must** adopt `@vital-ai/vitalgraph-client` as its sole HTTP layer for communicating with the VitalGraph API. The existing `frontend/src/services/ApiService.ts` will be fully replaced, not wrapped.

### 12.1 Migration Steps

1. **Install the client** in the frontend:
   ```bash
   cd frontend
   npm install @vital-ai/vitalgraph-client
   ```
   The peer deps (`@vital-ai/vital-model-utils`, `@vital-ai/vital-kg-model-ts`) are already installed in the frontend.

2. **Create a shared client instance** (e.g. `frontend/src/services/vitalgraphClient.ts`):
   ```typescript
   import { VitalGraphClient } from '@vital-ai/vitalgraph-client';

   export const client = new VitalGraphClient({
     serverUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8001',
   });
   ```

3. **Wire authentication** into the frontend's existing auth flow. The client's `open()` method handles JWT login; the frontend should call it after the user provides credentials. Token refresh is handled automatically by the client.

4. **Replace `ApiService` call sites** one endpoint group at a time:
   - `ApiService.getSpaces()` → `client.spaces.list()`
   - `ApiService.getGraphs(spaceId)` → `client.graphs.list(spaceId)`
   - `ApiService.getKGEntities(...)` → `client.kgentities.list(spaceId, graphId, { ... })`
   - etc.

5. **Delete `ApiService.ts`** once all call sites are migrated.

### 12.2 Benefits

- **Typed responses** — Components get `VitalSignsObject` instances instead of raw `any` JSON.
- **Single source of truth** — The client package is tested and versioned independently; both Node.js scripts and the frontend share the same API contract.
- **Automatic retry & token refresh** — Eliminates ad-hoc 401 handling scattered across the frontend.
- **Endpoint parity** — The frontend automatically gains access to every endpoint the Python client supports (vector, geo, import/export, admin, etc.) without writing new fetch calls.

### 12.3 Timeline

The frontend migration is a **separate task** that begins after the TS client is published to npm. It does not block the client package release.
