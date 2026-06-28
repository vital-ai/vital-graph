# AI Agent Registry Plan

## Overview

A global registry (not per-space) for tracking AI agents that can be accessed by the VitalGraph system. Follows the same architectural patterns as the Entity Registry: global PostgreSQL tables, dedicated schema class, migration script, Pydantic models, and REST endpoints.

Each agent record links to an Entity Registry entity representing the agent itself (agents are a type of entity), stores connection details via the agent_endpoint table, identifies the protocol format via a constant URI, and references which authentication service is used to communicate with the agent (no credentials are stored — only a pointer to the auth service).

---

## 1. Database Tables

### 1.1 `agent_type` — Lookup table for agent categories

| Column | Type | Notes |
|--------|------|-------|
| `type_id` | `SERIAL PRIMARY KEY` | |
| `type_key` | `VARCHAR(500) UNIQUE NOT NULL` | URI identifier, e.g. `urn:vital-ai:agent-type:chat` |
| `type_label` | `VARCHAR(255) NOT NULL` | Human-readable label |
| `type_description` | `TEXT` | |
| `created_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |
| `updated_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |

**Seed values:**
- `urn:vital-ai:agent-type:chat`


### 1.2 `agent` — Core agent record

| Column | Type | Notes |
|--------|------|-------|
| `agent_id` | `VARCHAR(50) PRIMARY KEY` | Generated ID (e.g. `agt_<nanoid>`) |
| `agent_type_id` | `INTEGER NOT NULL REFERENCES agent_type(type_id)` | FK to agent_type |
| `entity_id` | `VARCHAR(50) REFERENCES entity(entity_id)` | Entity registry ID of this agent (e.g. `e_a7b3x9k2m1`). Agents are a type of entity. Nullable initially |
| `agent_name` | `VARCHAR(500) NOT NULL` | Human-readable name |
| `agent_uri` | `VARCHAR(500) UNIQUE NOT NULL` | URI identifier for this agent (e.g. `urn:vital-ai:agent:acme-chat-v2`) |
| `description` | `TEXT` | What the agent does |
| `version` | `VARCHAR(50)` | Agent version string (e.g. `1.2.0`) |
| `status` | `VARCHAR(20) NOT NULL DEFAULT 'active'` | `active`, `inactive`, `deprecated`, `deleted`. Soft-delete only — set to `deleted`, never hard-delete |
| `protocol_format_uri` | `VARCHAR(500)` | URI identifying the message protocol (see §2 Protocol Format Constants) |
| `auth_service_uri` | `VARCHAR(500)` | URI identifying the auth service used for this agent (see §3). Null = no auth required |
| `auth_service_config` | `JSONB DEFAULT '{}'` | Non-secret config pointing to the auth service: realm, token endpoint URL, grant type, etc. **No credentials stored** |
| `capabilities` | `JSONB DEFAULT '[]'` | Array of capability tags (e.g. `["text-generation", "rag", "function-calling"]`) |
| `metadata` | `JSONB DEFAULT '{}'` | Arbitrary additional metadata |
| `created_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |
| `updated_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |
| `created_by` | `VARCHAR(255)` | |
| `notes` | `TEXT` | |

### 1.3 `agent_endpoint` — Multiple endpoints per agent (optional)

Some agents may expose multiple endpoints (e.g., separate WebSocket for chat vs. REST for embeddings). This table supports that without overloading the main agent record.

| Column | Type | Notes |
|--------|------|-------|
| `endpoint_id` | `SERIAL PRIMARY KEY` | |
| `agent_id` | `VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE` | |
| `endpoint_uri` | `VARCHAR(500) NOT NULL` | URI identifier (e.g. `urn:vital-ai:agent-endpoint:chat`) |
| `endpoint_url` | `VARCHAR(1000) NOT NULL` | Full URL |
| `protocol` | `VARCHAR(20) NOT NULL DEFAULT 'websocket'` | `websocket`, `http`, `grpc` |
| `status` | `VARCHAR(20) NOT NULL DEFAULT 'active'` | |
| `created_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |
| `updated_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |
| `notes` | `TEXT` | |

**Constraint:** `UNIQUE (agent_id, endpoint_uri)`

### 1.4 `agent_function` — Structured function identifiers per agent

Each agent may expose N discrete functions that can be invoked by callers. An agent function provides a **structured URI identifier** that routes directly to the agent's internal implementation of that function, reducing ambiguity and enabling function-level discovery.

Functions also serve as an **advertisement mechanism**: callers can discover what an agent is capable of by listing its registered functions, rather than relying on free-text capability tags alone.

| Column | Type | Notes |
|--------|------|-------|
| `function_id` | `SERIAL PRIMARY KEY` | |
| `agent_id` | `VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE` | |
| `function_uri` | `VARCHAR(500) NOT NULL` | Structured URI identifier, e.g. `urn:generate_investor_report` |
| `function_name` | `VARCHAR(255) NOT NULL` | Human-readable name, e.g. "Generate Investor Report" |
| `description` | `TEXT` | What the function does |
| `parameters` | `JSONB DEFAULT '{}'` | Map of parameter definitions: `{ "param_key": { "description": "...", "type": "string", "required": true } }` |
| `status` | `VARCHAR(20) NOT NULL DEFAULT 'active'` | `active`, `deprecated`, `deleted` |
| `created_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |
| `updated_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |
| `notes` | `TEXT` | |

**Constraint:** `UNIQUE (agent_id, function_uri)`

#### Example: Investor Report Function

```json
{
  "function_uri": "urn:generate_investor_report",
  "function_name": "Generate Investor Report",
  "description": "Generates a comprehensive investor report for a given business, optionally focused on specific market segments.",
  "parameters": {
    "business_name": {
      "description": "Name of the business to generate the report for",
      "type": "string",
      "required": true
    },
    "report_focus": {
      "description": "Specific focus area or topic for the report",
      "type": "string",
      "required": false
    },
    "market_segments": {
      "description": "List of market segments to analyze",
      "type": "array",
      "required": false
    },
    "time_period": {
      "description": "Time period for the analysis (e.g. 'Q1 2026', 'last 12 months')",
      "type": "string",
      "required": false
    }
  }
}
```

#### Example: Knowledge Graph Query Function

```json
{
  "function_uri": "urn:query_knowledge_graph",
  "function_name": "Query Knowledge Graph",
  "description": "Executes a structured query against the agent's knowledge graph.",
  "parameters": {
    "query": {
      "description": "Natural language or structured query string",
      "type": "string",
      "required": true
    },
    "max_results": {
      "description": "Maximum number of results to return",
      "type": "integer",
      "required": false
    }
  }
}
```

### 1.5 `agent_change_log` — Audit trail

| Column | Type | Notes |
|--------|------|-------|
| `log_id` | `BIGSERIAL PRIMARY KEY` | |
| `agent_id` | `VARCHAR(50) REFERENCES agent(agent_id) ON DELETE SET NULL` | |
| `change_type` | `VARCHAR(50) NOT NULL` | `created`, `updated`, `status_changed`, `endpoint_added`, `endpoint_removed`, `auth_updated`, `deleted` |
| `change_detail` | `JSONB` | Details of what changed |
| `changed_by` | `VARCHAR(255)` | |
| `comment` | `TEXT` | |
| `created_time` | `TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | |

---

## 2. Protocol Format Constants

The `protocol_format_uri` field references a well-known URI that identifies the message protocol the agent speaks. These are fixed constants defined in code.

| Constant Key | URI | Description |
|-------------|-----|-------------|
| `AIMP` | `urn:vital-ai:protocol:aimp:1.0` | AI Messaging Protocol — Vital AI's native agent protocol |
| `OPENAI_CHAT` | `urn:vital-ai:protocol:openai-chat:1.0` | OpenAI Chat Completions compatible |
| `A2A` | `urn:vital-ai:protocol:a2a:1.0` | Google Agent-to-Agent protocol |
| `MCP` | `urn:vital-ai:protocol:mcp:1.0` | Model Context Protocol |

These are defined as constants in `agent_models.py`:

```python
class AgentProtocol:
    """Well-known protocol format URIs."""
    AIMP = "urn:vital-ai:protocol:aimp:1.0"
    OPENAI_CHAT = "urn:vital-ai:protocol:openai-chat:1.0"
    A2A = "urn:vital-ai:protocol:a2a:1.0"
    MCP = "urn:vital-ai:protocol:mcp:1.0"

    ALL = [AIMP, OPENAI_CHAT, A2A, MCP]
```

---

## 3. Authentication Service Reference

The `auth_service_uri` field identifies **which** auth service is used for this agent. The `auth_service_config` JSONB stores non-secret configuration that describes how to locate and interact with that auth service. **No credentials or secrets are stored in the database.**

Credentials (client secrets, API keys, certificates) are managed externally (Vault, env vars, Kubernetes secrets, etc.) and resolved at runtime by the calling system — the agent registry simply records which service to use.

### Example: Keycloak OIDC

```json
{
  "auth_service_uri": "urn:vital-ai:auth:keycloak",
  "auth_service_config": {
    "token_url": "https://keycloak.example.com/realms/agents/protocol/openid-connect/token",
    "realm": "agents",
    "grant_type": "client_credentials",
    "scope": "agent:invoke"
  }
}
```

### Example: AWS Cognito

```json
{
  "auth_service_uri": "urn:vital-ai:auth:cognito",
  "auth_service_config": {
    "token_url": "https://my-pool.auth.us-east-1.amazoncognito.com/oauth2/token",
    "user_pool_id": "us-east-1_XXXXXXX"
  }
}
```

### Example: No auth

```json
{
  "auth_service_uri": null,
  "auth_service_config": {}
}
```

### Auth Service URI Constants

```python
class AgentAuthService:
    """Well-known auth service URIs."""
    KEYCLOAK = "urn:vital-ai:auth:keycloak"
    COGNITO = "urn:vital-ai:auth:cognito"
    AUTH0 = "urn:vital-ai:auth:auth0"
    OKTA = "urn:vital-ai:auth:okta"
    AZURE_AD = "urn:vital-ai:auth:azure-ad"
```

---

## 4. Indexes

```sql
-- agent table
CREATE INDEX IF NOT EXISTS idx_agent_type ON agent(agent_type_id);
CREATE INDEX IF NOT EXISTS idx_agent_entity ON agent(entity_id);
CREATE INDEX IF NOT EXISTS idx_agent_name ON agent(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_uri ON agent(agent_uri);
CREATE INDEX IF NOT EXISTS idx_agent_status ON agent(status);
CREATE INDEX IF NOT EXISTS idx_agent_protocol ON agent(protocol_format_uri);
CREATE INDEX IF NOT EXISTS idx_agent_auth_service ON agent(auth_service_uri);
CREATE INDEX IF NOT EXISTS idx_agent_created ON agent(created_time);
CREATE INDEX IF NOT EXISTS idx_agent_capabilities ON agent USING GIN(capabilities);
CREATE INDEX IF NOT EXISTS idx_agent_metadata ON agent USING GIN(metadata);

-- agent_endpoint table
CREATE INDEX IF NOT EXISTS idx_agent_ep_agent ON agent_endpoint(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_ep_key ON agent_endpoint(agent_id, endpoint_uri);
CREATE INDEX IF NOT EXISTS idx_agent_ep_protocol ON agent_endpoint(protocol);
CREATE INDEX IF NOT EXISTS idx_agent_ep_status ON agent_endpoint(status);

-- agent_function table
CREATE INDEX IF NOT EXISTS idx_agent_fn_agent ON agent_function(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_fn_key ON agent_function(agent_id, function_uri);
CREATE INDEX IF NOT EXISTS idx_agent_fn_uri ON agent_function(function_uri);
CREATE INDEX IF NOT EXISTS idx_agent_fn_status ON agent_function(status);
CREATE INDEX IF NOT EXISTS idx_agent_fn_params ON agent_function USING GIN(parameters);

-- agent_change_log table
CREATE INDEX IF NOT EXISTS idx_agent_log_agent ON agent_change_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_log_type ON agent_change_log(change_type);
CREATE INDEX IF NOT EXISTS idx_agent_log_time ON agent_change_log(created_time);
```

---

## 5. Views

```sql
CREATE OR REPLACE VIEW agent_active_view AS
    SELECT a.*, at.type_key, at.type_label,
           e.primary_name AS entity_name
    FROM agent a
    JOIN agent_type at ON a.agent_type_id = at.type_id
    LEFT JOIN entity e ON a.entity_id = e.entity_id
    WHERE a.status = 'active';

CREATE OR REPLACE VIEW agent_function_view AS
    SELECT af.*, a.agent_name, a.agent_uri, a.status AS agent_status
    FROM agent_function af
    JOIN agent a ON af.agent_id = a.agent_id
    WHERE af.status = 'active' AND a.status = 'active';
```

---

## 6. Pydantic Models

### Location: `vitalgraph/agent_registry/agent_models.py`

```python
class AgentTypeResponse(BaseModel):
    type_id: int
    type_key: str
    type_label: str
    type_description: Optional[str]

class AgentCreate(BaseModel):
    agent_type_key: str                    # resolved to type_id
    entity_id: Optional[str] = None        # FK to entity registry
    agent_name: str
    agent_uri: str                         # unique machine key
    description: Optional[str] = None
    version: Optional[str] = None
    protocol_format_uri: Optional[str] = None  # AgentProtocol constant URI
    auth_service_uri: Optional[str] = None     # AgentAuthService constant URI
    auth_service_config: dict = {}             # non-secret auth service config
    capabilities: List[str] = []
    metadata: dict = {}
    notes: Optional[str] = None

class AgentUpdate(BaseModel):
    """All fields optional — only provided fields are updated."""
    agent_type_key: Optional[str] = None
    entity_id: Optional[str] = None
    agent_name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = None
    protocol_format_uri: Optional[str] = None
    auth_service_uri: Optional[str] = None
    auth_service_config: Optional[dict] = None
    capabilities: Optional[List[str]] = None
    metadata: Optional[dict] = None
    notes: Optional[str] = None

class AgentResponse(BaseModel):
    agent_id: str
    agent_type_key: str
    agent_type_label: str
    entity_id: Optional[str]
    entity_name: Optional[str]             # denormalized from entity registry
    agent_name: str
    agent_uri: str
    description: Optional[str]
    version: Optional[str]
    status: str
    protocol_format_uri: Optional[str]
    auth_service_uri: Optional[str]
    auth_service_config: dict
    capabilities: List[str]
    metadata: dict
    endpoints: List[AgentEndpointResponse] = []
    created_time: datetime
    updated_time: datetime
    created_by: Optional[str]
    notes: Optional[str]

class AgentEndpointCreate(BaseModel):
    endpoint_uri: str
    endpoint_url: str
    protocol: str = "websocket"
    notes: Optional[str] = None

class AgentEndpointResponse(BaseModel):
    endpoint_id: int
    agent_id: str
    endpoint_uri: str
    endpoint_url: str
    protocol: str
    status: str
    created_time: datetime
    updated_time: datetime
    notes: Optional[str]

class AgentFunctionCreate(BaseModel):
    function_uri: str                          # e.g. "urn:generate_investor_report"
    function_name: str                         # human-readable name
    description: Optional[str] = None
    parameters: dict = {}                      # { param_key: { description, type, required } }
    notes: Optional[str] = None

class AgentFunctionUpdate(BaseModel):
    function_name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[dict] = None
    status: Optional[str] = None
    notes: Optional[str] = None

class AgentFunctionResponse(BaseModel):
    function_id: int
    agent_id: str
    function_uri: str
    function_name: str
    description: Optional[str]
    parameters: dict
    status: str
    created_time: datetime
    updated_time: datetime
    notes: Optional[str]

class AgentListResponse(BaseModel):
    agents: List[AgentResponse]
    total_count: int
    page_size: int
    offset: int
```

---

## 7. REST Endpoints

### Location: `vitalgraph/agent_registry/agent_endpoint.py`

All endpoints use query parameters for resource identification (agent IDs/keys are URIs, so they go in query params rather than path segments).

### Agent CRUD

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent` | List agents (filter by type, status, capability, entity_id) |
| `POST` | `/api/agent` | Create agent |
| `GET` | `/api/agent?agent_id=...` | Get agent by ID |
| `GET` | `/api/agent?agent_uri=...` | Get agent by URI key |
| `PUT` | `/api/agent?agent_id=...` | Update agent |
| `DELETE` | `/api/agent?agent_id=...` | Soft-delete agent (sets status=deleted) |
| `PATCH` | `/api/agent/status?agent_id=...` | Change agent status |

### Agent Endpoints (sub-resource)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/endpoint?agent_id=...` | List endpoints for agent |
| `POST` | `/api/agent/endpoint?agent_id=...` | Add endpoint to agent |
| `PUT` | `/api/agent/endpoint?agent_id=...&endpoint_id=...` | Update endpoint |
| `DELETE` | `/api/agent/endpoint?agent_id=...&endpoint_id=...` | Remove endpoint |

### Agent Functions (sub-resource)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/function?agent_id=...` | List functions for agent |
| `POST` | `/api/agent/function?agent_id=...` | Add function to agent |
| `GET` | `/api/agent/function?function_id=...` | Get function by ID |
| `PUT` | `/api/agent/function?function_id=...` | Update function |
| `DELETE` | `/api/agent/function?function_id=...` | Soft-delete function |
| `GET` | `/api/agent/function/discover?function_uri=...` | Find agents that provide a specific function URI |

### Agent Types

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent-type` | List agent types |
| `POST` | `/api/agent-type` | Create agent type |

### Agent Discovery

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/discover` | Find agents by capability, type, protocol, and status (for agent routing) |

**Total: 19 endpoints**

### Query Parameters for `GET /api/agent` (list)

- `page_size` (int, default 20)
- `offset` (int, default 0)
- `status` (str, optional — filter by status)
- `type_key` (str, optional — filter by agent type URI)
- `entity_id` (str, optional — filter by entity)
- `capability` (str, optional — filter agents having this capability)
- `protocol_format_uri` (str, optional — filter by protocol format)
- `search` (str, optional — ILIKE search on agent_name, agent_uri, description)

---

## 8. Implementation Files

Following the entity registry pattern. The schema class and table DDL are identical across both backends.

```
vitalgraph/
  agent_registry/
    __init__.py
    agent_models.py              # Pydantic models (§6) — shared
    agent_registry_schema.py     # Table DDL, indexes, seeds, migrations (§1-5) — shared
    agent_registry_impl.py       # Core CRUD implementation (asyncpg) — shared
    agent_endpoint.py            # FastAPI router (§7) — shared

agent_registry/
    migrate_agents.py            # Schema migration script (standalone)
```

### Multi-Backend Deployment

Two current backends have existing admin/global table definitions. The agent registry tables must be added to both:

| Backend | Priority | Existing Admin Table Locations |
|---------|----------|-------------------------------|
| **sparql_sql** | Primary | Inline DDL in `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` → `_init_sparql_sql_backend()` (admin_ddl list) |
| **fuseki_postgresql** | Secondary | `vitalgraph/db/fuseki_postgresql/postgresql_schema.py` → `FusekiPostgreSQLSchema.ADMIN_TABLES` dict |

Both backends already define global admin tables (install, space, graph, user, process). The agent registry tables (`agent_type`, `agent`, `agent_endpoint`, `agent_change_log`) will be added alongside these existing tables using each backend's established pattern.

The shared `agent_registry_schema.py` defines the canonical DDL. Each backend's init/schema must be updated to include the agent registry tables, keeping definitions identical across both.

---

## 9. Integration Points

### 9.1 Entity Registry Link
- `agent.entity_id` references `entity(entity_id)` — the entity representing this agent (agents are a type of entity)
- Nullable: an agent record can exist before its entity registry entry is created
- On entity deletion: SET NULL (agent record continues to exist but loses the entity link)

### 9.2 VitalGraphAppImpl Startup
- Initialize `AgentRegistryImpl` with the shared asyncpg pool
- Call `ensure_tables()` on startup (verify tables exist, do not create)
- Mount agent router on the FastAPI app

### 9.3 Auth Service Reference (No Secrets)
- The registry only stores **which** auth service to use and non-secret config (token URL, realm, grant type)
- **No credentials are stored** — the calling system resolves secrets externally (Vault, env vars, etc.)
- This keeps the registry safe and simple — it is a directory, not a credential store

---

## 10. Design Decisions (Resolved)

1. **Soft delete only** — DELETE sets `status = 'deleted'`, never removes the row. Consistent with entity registry.
2. **Protocol format via URI constants** — `protocol_format_uri` field references well-known URIs (AIMP, OpenAI Chat, A2A, MCP).
3. **No auth secrets stored** — `auth_service_uri` + `auth_service_config` identify the auth service and non-secret config. Credentials resolved externally at runtime.
4. **No health tracking** — Health monitoring is out of scope for the registry.
5. **No agent-to-agent relationships** — Out of scope.
6. **No agent pools / load balancing** — Out of scope.
7. **Multi-backend** — Same table definitions for both sparql_sql (primary) and fuseki_postgresql backends. Schema class is shared; each backend runs its own migration.

## 11. Open Questions

1. **Agent versioning history**: Should we keep a history of agent versions (like a changelog), or is the single `version` field sufficient?
2. **Multi-tenancy**: The entity registry is global. Should agents also be global, or should there be an optional `tenant_id` / `organization_id` scope?
3. **WebSocket sub-protocol**: Should we capture WebSocket sub-protocol information (e.g., `graphql-ws`, custom binary)?  Or is `protocol_format_uri` sufficient?

---

## 12. Implementation Phases

### Phase 1: Create Tables in PostgreSQL

**Step 1 — sparql_sql backend** ✅ DONE
- Created standalone migration script: `agent_registry/migrate_agents.py`
  - Defines DDL for `agent_type`, `agent`, `agent_endpoint`, `agent_change_log`
  - 17 indexes (including GIN on capabilities, metadata)
  - Seed data: `urn:vital-ai:agent-type:chat`
  - View: `agent_active_view`
  - Status check with `--status` flag
- Tables physically created in `sparql_sql_graph` database
- Also ran `entity_registry/migrate.py` (entity tables were missing)
- Updated `vitalgraphdb_admin_cmd.py` → `_init_sparql_sql_backend()` with same DDL (for fresh init)
- Updated `sparql_sql_db_impl.py` → `initialize_schema()` to verify 9 tables (was 5)

**Step 2 — fuseki_postgresql backend** (pending)
- Add same DDL to `FusekiPostgreSQLSchema.ADMIN_TABLES`
- Add indexes to `get_admin_indexes()`

**Step 3 — Shared schema class** (pending)
- Create `agent_registry_schema.py` with canonical DDL (single source of truth)

### Phase 2: Core Implementation ✅ DONE
- Created `vitalgraph/agent_registry/agent_models.py`
  - `AgentProtocol` constants (AIMP, OpenAI Chat, A2A, MCP)
  - `AgentAuthService` constants (Keycloak, Cognito, Auth0, Okta, Azure AD)
  - Pydantic models: `AgentCreate`, `AgentUpdate`, `AgentResponse`, `AgentListResponse`
  - Pydantic models: `AgentEndpointCreate`, `AgentEndpointUpdate`, `AgentEndpointResponse`
  - `AgentTypeCreate`, `AgentTypeResponse`, `AgentStatusChange`
- Created `vitalgraph/agent_registry/agent_registry_impl.py`
  - `AgentRegistryImpl` class with asyncpg pool
  - Agent ID generation (`agt_` prefix + 10 alphanumeric chars)
  - Full CRUD: create, get, get_by_uri, update, delete (soft)
  - Search/list with filters (type, status, entity_id, capability, protocol, text search)
  - Endpoint CRUD: create, list, update, delete (soft)
  - Change log: automatic logging for all mutations, query API
  - Dynamic SET clause for partial updates (same pattern as entity registry)

### Phase 3: REST Endpoints ✅ DONE
- Created `vitalgraph/agent_registry/agent_endpoint.py`
  - `AgentRegistryEndpoint` class (same pattern as `EntityRegistryEndpoint`)
  - All endpoints use query parameters for resource identification
  - Agent types: `GET/POST /agent/types`
  - Agent CRUD: `GET/POST/PUT/DELETE /agent` (with `?agent_id=...` or `?agent_uri=...`)
  - Agent status: `PUT /agent/status?agent_id=...`
  - Endpoints: `GET/POST/PUT/DELETE /agent/endpoints`
  - Change log: `GET /agent/changelog?agent_id=...`
  - JWT auth dependency on all routes

### Phase 3b: Client & Server Wiring ✅ DONE
- Created `vitalgraph/client/endpoint/agent_registry_endpoint.py`
  - `AgentRegistryClientEndpoint` extending `BaseEndpoint`
  - All client methods matching server-side REST endpoints
  - Uses `_make_typed_request` / `_make_authenticated_request` pattern
  - Base path: `/api/agents`
- Wired into `vitalgraph/client/vitalgraph_client.py`
  - Import `AgentRegistryClientEndpoint`
  - `self.agent_registry = AgentRegistryClientEndpoint(self)`
- Wired into `vitalgraph/impl/vitalgraphapp_impl.py`
  - `_init_agent_registry_routes()` method using `create_agent_registry_router`
  - `AgentRegistryImpl` initialized at startup with shared asyncpg pool
  - Router mounted at `/api/agents`

### Phase 4: Testing ✅ DONE
- Created `vitalgraph_client_test/sparql_sql/case_agent_registry_crud.py`
  - `AgentRegistryCrudTester` class (same pattern as `KGEntitiesCrudTester`)
  - 16 test cases covering full lifecycle:
    1. List agent types (seed data)
    2. Create agent type
    3. Create agent
    4. Get agent by ID
    5. Get agent by URI
    6. Search agents (text query)
    7. Update agent (description, version, capabilities)
    8. Create endpoint
    9. List endpoints
    10. Update endpoint
    11. Delete endpoint (soft)
    12. Verify endpoint soft-deleted
    13. Change agent status
    14. Get change log
    15. Delete agent (soft)
    16. Verify soft-deleted agent hidden from search
- Created `vitalgraph_client_test/test_sparql_sql_agent_registry.py`
  - Standalone runner (same pattern as `test_sparql_sql_kgentities.py`)
  - No space/graph needed — agent registry uses global admin tables

### Phase 5: Remaining Work (pending)
- Add agent registry tables to fuseki_postgresql backend
- Create shared `agent_registry_schema.py` with canonical DDL

### Phase 6: Agent Functions (done)
- ✅ Added `agent_function` table to PostgreSQL via migration script (`migrate_agents.py`)
- ✅ Added Pydantic models: `AgentFunctionCreate`, `AgentFunctionUpdate`, `AgentFunctionResponse` to `agent_models.py`
- ✅ Added CRUD methods to `AgentRegistryImpl`: `create_function`, `list_functions`, `get_function`, `update_function`, `delete_function`
- ✅ Added function discovery method: `discover_by_function` (find agents by `function_uri`)
- ✅ Added 6 REST endpoints to `agent_endpoint.py`: list, create, get, update, delete, discover
- ✅ Added 7 client methods to `AgentRegistryClientEndpoint`: list_functions, create_function, get_function, update_function, delete_function, discover_by_function
- ✅ Client already wired via `VitalGraphClient.agent_registry` — new methods available immediately
- ✅ Added 7 function CRUD tests (13–19) to `case_agent_registry_crud.py`
- ✅ Updated migration script with `agent_function` DDL, indexes (5), and `agent_function_view`
- ✅ Updated `sparql_sql_db_impl.py` admin table count: 9 → 10
