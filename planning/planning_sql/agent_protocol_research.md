# Agent Protocol Research — Phase 9a

## Purpose

Survey the leading agent communication protocols to determine what configuration, schema, and metadata the Agent Registry should capture per protocol so callers can **discover**, **connect to**, and **invoke** agents.

---

## 1. Protocol Landscape (as of mid-2025)

### Tier 1 — Established standards with broad adoption

| Protocol | Focus | Transport | Discovery Artifact |
|----------|-------|-----------|-------------------|
| **MCP** (Model Context Protocol) | Tool/resource access for LLMs | stdio, Streamable HTTP (SSE) | Server capabilities via `initialize` handshake; MCP Registry; emerging Server Card |
| **Google A2A** (Agent-to-Agent) | Peer agent collaboration, task delegation | JSON-RPC over HTTP, gRPC, HTTP+JSON/REST | **Agent Card** at `/.well-known/agent-card.json` |
| **OpenAI Function Calling / Responses API** | Tool invocation within LLM inference | HTTPS (REST) | Function definitions in API request (`tools` array) |

### Tier 2 — Framework-specific SDKs (not wire protocols)

| Framework | Notes |
|-----------|-------|
| **OpenAI Agents SDK** | Python orchestration SDK. Agents defined in code (name, instructions, tools, handoffs, guardrails, model_settings). No wire protocol — uses Responses API underneath. |
| **LangChain / LangGraph** | Python/JS framework. Agents are graph nodes with tool bindings. No standard wire protocol — typically wraps OpenAI/Anthropic APIs. |
| **CrewAI** | Multi-agent orchestration (role, goal, backstory, tools, process type). No wire protocol. |
| **AutoGen** | Multi-agent conversation framework. No wire protocol. |

### Tier 3 — Emerging protocols (early stage)

| Protocol | Notes |
|----------|-------|
| **Agent Connect Protocol (ACP)** by AGNTCY | OpenAPI-based agent invocation spec. Defines agent descriptor with capabilities, config schema, input/output schemas. **Now archived** — community converging on A2A + MCP. |
| **Agent Network Protocol (ANP)** | Three-layer protocol (DID identity, meta-protocol negotiation, application). Early stage, small adoption. |

### Key Insight

The industry is converging on **two complementary standards**:
- **MCP** for tool/resource access (agent-to-tool)
- **A2A** for peer agent communication (agent-to-agent)

With **AIMP** as Vital AI's native protocol and **OpenAI Chat/Responses** as the dominant LLM API. Framework SDKs (LangChain, CrewAI, etc.) are orchestration layers, not wire protocols — they don't need dedicated protocol config in the registry.

---

## 2. Per-Protocol Analysis

### 2.1 AIMP (Vital AI Internal Messaging Protocol)

**What it is:** Vital AI's native agent communication protocol, used for chat-based agent interactions within the Vital AI ecosystem.

**What a caller needs to know:**

| Category | Fields |
|----------|--------|
| **Discover** | Agent URI, capabilities, channel types (chat, task, etc.), supported message types |
| **Connect** | WebSocket endpoint URL, auth service reference (Keycloak), security profile |
| **Invoke** | Message format (AIMP message objects), graph URI, account URIs, reference identifiers |

**Recommended `metadata` structure:**
```json
{
  "aimp": {
    "channel_types": ["chat", "task"],
    "message_types": ["text", "structured", "file"],
    "graph_uri": "urn:vital-ai:graph:agent-x",
    "security_profile": "standard",
    "supports_streaming": true
  }
}
```

### 2.2 MCP (Model Context Protocol)

**What it is:** Open protocol (Anthropic-originated, now community-governed) for connecting LLMs to tools, resources, and prompts. The server declares capabilities; the client negotiates features during initialization.

**Key concepts:**
- **Three primitives:** Tools (model-controlled functions), Resources (app-controlled data), Prompts (user-controlled templates)
- **Capability negotiation:** Client and server declare supported features at init
- **Transports:** stdio (local), Streamable HTTP with SSE (remote)
- **Tool definition:** name, description, inputSchema (JSON Schema 2020-12), outputSchema (optional)
- **Discovery:** MCP Registry (npm/PyPI-based), emerging Server Card standard

**What a caller needs to know:**

| Category | Fields |
|----------|--------|
| **Discover** | Server name/description, supported primitives (tools/resources/prompts), tool list with descriptions |
| **Connect** | Transport type (stdio, streamable-http), endpoint URL, auth (OAuth 2.0 with PKCE, client credentials) |
| **Invoke** | Tool name, inputSchema (JSON Schema), protocol version |

**Recommended `metadata` structure:**
```json
{
  "mcp": {
    "protocol_version": "2025-06-18",
    "transport": "streamable-http",
    "capabilities": {
      "tools": true,
      "resources": true,
      "prompts": false
    },
    "tools": [
      {
        "name": "search_documents",
        "description": "Search knowledge base documents",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10}
          },
          "required": ["query"]
        }
      }
    ],
    "auth": {
      "type": "oauth2",
      "authorization_url": "https://auth.example.com/authorize",
      "token_url": "https://auth.example.com/token"
    }
  }
}
```

### 2.3 Google A2A (Agent-to-Agent Protocol)

**What it is:** Open protocol for peer agent communication. Agents discover each other via Agent Cards, delegate tasks, exchange messages/artifacts, and support streaming + push notifications.

**Key concepts:**
- **Agent Card:** JSON document describing agent identity, capabilities, skills, supported interfaces, auth schemes. Served at `/.well-known/agent-card.json`.
- **Skills:** Declare what an agent can do, with input/output modes (MIME types), tags, and examples.
- **Task lifecycle:** submitted → working → input-required → completed/failed/canceled
- **Multiple protocol bindings:** JSON-RPC, gRPC, HTTP+JSON/REST
- **Push notifications:** Webhook-based for async task updates

**What a caller needs to know:**

| Category | Fields |
|----------|--------|
| **Discover** | Agent name, description, skills (id, name, description, tags, input/output modes), capabilities (streaming, push notifications) |
| **Connect** | Supported interfaces (URL + protocol binding), security schemes (OAuth/OIDC), agent card URL |
| **Invoke** | Protocol binding (JSON-RPC, gRPC, REST), message format (parts with MIME types), task management (send/get/cancel) |

**Recommended `metadata` structure:**
```json
{
  "a2a": {
    "agent_card_url": "https://agent.example.com/.well-known/agent-card.json",
    "version": "1.0",
    "supported_interfaces": [
      {
        "url": "https://agent.example.com/a2a/v1",
        "protocol_binding": "JSONRPC",
        "protocol_version": "1.0"
      }
    ],
    "capabilities": {
      "streaming": true,
      "push_notifications": false,
      "extended_agent_card": false
    },
    "skills": [
      {
        "id": "summarize-text",
        "name": "Summarize Text",
        "description": "Produces a concise summary of input text",
        "tags": ["summarization", "nlp"],
        "input_modes": ["text/plain", "application/json"],
        "output_modes": ["text/plain"]
      }
    ],
    "security_schemes": {
      "oauth": {
        "type": "openIdConnect",
        "openid_connect_url": "https://auth.example.com/.well-known/openid-configuration"
      }
    },
    "default_input_modes": ["text/plain"],
    "default_output_modes": ["text/plain"]
  }
}
```

### 2.4 OpenAI Chat / Responses API

**What it is:** REST API for LLM inference with function calling. Not a peer-to-peer agent protocol — rather an API for invoking an LLM-backed agent with tool definitions.

**Key concepts:**
- **Function definitions:** name, description, parameters (JSON Schema), strict mode
- **Tool choice:** auto, required, none, or specific function name
- **Streaming:** SSE-based
- **Model-specific:** Capabilities depend on model (gpt-4o, gpt-5, etc.)

**What a caller needs to know:**

| Category | Fields |
|----------|--------|
| **Discover** | Model ID, supported features (function calling, vision, structured output), available tools |
| **Connect** | API base URL, API key or OAuth, organization ID |
| **Invoke** | Model, messages array, tools array (function definitions), tool_choice, temperature, response_format |

**Recommended `metadata` structure:**
```json
{
  "openai_chat": {
    "api_base_url": "https://api.openai.com/v1",
    "model": "gpt-4o",
    "supports_function_calling": true,
    "supports_streaming": true,
    "supports_vision": true,
    "supports_structured_output": true,
    "default_temperature": 0.7,
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get current weather for a location",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {"type": "string"}
            },
            "required": ["location"]
          },
          "strict": true
        }
      }
    ]
  }
}
```

---

## 3. Schema Impact Assessment

### 3.1 Current Schema

The `agent` table has:
- `protocol_format_uri VARCHAR(500)` — identifies which protocol
- `auth_service_uri VARCHAR(500)` — identifies auth provider
- `auth_service_config JSONB` — non-secret auth config
- `capabilities JSONB` — capability tags array
- `metadata JSONB` — general-purpose JSONB

The `agent_endpoint` table has:
- `endpoint_uri VARCHAR(500)` — endpoint identifier
- `endpoint_url VARCHAR(1000)` — connection URL
- `protocol VARCHAR(20)` — transport type (e.g., "websocket")
- `notes TEXT`

The `agent_function` table has:
- `function_uri VARCHAR(500)` — function identifier
- `function_name VARCHAR(255)` — display name
- `description TEXT`
- `parameters JSONB` — parameter definitions

### 3.2 What's Missing

#### A. Protocol-specific config has no home separate from general metadata

**Problem:** `metadata` is a catch-all. Protocol-specific config (MCP capabilities, A2A skills, OpenAI tool definitions) gets mixed with unrelated operational metadata.

**Recommendation:** Add a `protocol_config JSONB DEFAULT '{}'` column to `agent`. This separates protocol-specific configuration from general metadata, making it queryable and validatable.

```sql
ALTER TABLE agent ADD COLUMN protocol_config JSONB DEFAULT '{}';
```

#### B. Endpoint table lacks transport/protocol config

**Problem:** `agent_endpoint.protocol` is `VARCHAR(20)` with values like "websocket". This is too limited for:
- MCP transport config (stdio vs streamable-http, SSE settings)
- A2A protocol bindings (JSON-RPC vs gRPC vs REST, with per-binding URLs)
- WebSocket sub-protocol details

**Recommendation:** Add `transport_config JSONB DEFAULT '{}'` to `agent_endpoint`.

```sql
ALTER TABLE agent_endpoint ADD COLUMN transport_config JSONB DEFAULT '{}';
```

Example usage:
```json
// MCP endpoint
{"transport": "streamable-http", "sse_keepalive_seconds": 30}

// A2A endpoint
{"protocol_binding": "JSONRPC", "protocol_version": "1.0"}

// WebSocket endpoint
{"sub_protocol": "graphql-ws", "ping_interval_seconds": 30}
```

#### C. Function parameters should align with JSON Schema

**Problem:** `agent_function.parameters` is free-form JSONB. Both MCP and OpenAI use JSON Schema for tool/function input definitions. A2A skills use MIME type declarations.

**Recommendation:** Standardize `parameters` as JSON Schema 2020-12 format (matching MCP and OpenAI conventions). Add an optional `output_schema JSONB` column for output declarations.

```sql
ALTER TABLE agent_function ADD COLUMN output_schema JSONB DEFAULT '{}';
```

#### D. Protocol constants need expansion

**Current:** AIMP, OpenAI Chat, A2A, MCP (4 protocols)

**Recommendation:** Keep these four as the primary wire protocols. Do NOT add framework-specific entries (LangChain, CrewAI, AutoGen) — they are orchestration layers, not communication protocols. Consider adding:

```python
class AgentProtocol:
    AIMP = "urn:vital-ai:protocol:aimp:1.0"
    OPENAI_CHAT = "urn:vital-ai:protocol:openai-chat:1.0"
    OPENAI_RESPONSES = "urn:vital-ai:protocol:openai-responses:1.0"  # NEW
    A2A = "urn:vital-ai:protocol:a2a:1.0"
    MCP = "urn:vital-ai:protocol:mcp:1.0"
    REST = "urn:vital-ai:protocol:rest:1.0"  # NEW — generic REST API agents
```

- **OpenAI Responses** — separate from Chat Completions; supports tools, handoffs, sessions
- **REST** — for agents accessible via standard REST APIs that don't fit other categories

### 3.3 A2A Agent Card Alignment

The A2A Agent Card is the most comprehensive discovery artifact in the ecosystem. Our registry schema should be able to store/reconstruct an Agent Card equivalent:

| A2A Agent Card field | Our schema mapping |
|---------------------|-------------------|
| `name` | `agent.agent_name` |
| `description` | `agent.description` |
| `version` | `agent.version` |
| `supportedInterfaces` | `agent_endpoint` rows + `transport_config` |
| `capabilities` | `agent.protocol_config → a2a.capabilities` |
| `skills` | `agent_function` rows (function_uri → id, function_name → name, parameters → input schema) |
| `securitySchemes` | `agent.auth_service_uri` + `agent.auth_service_config` |
| `defaultInputModes` | `agent.protocol_config → a2a.default_input_modes` |
| `defaultOutputModes` | `agent.protocol_config → a2a.default_output_modes` |
| `provider` | `agent.metadata → provider` |
| `documentationUrl` | `agent.metadata → documentation_url` |
| `iconUrl` | `agent.metadata → icon_url` |

### 3.4 MCP Server Capabilities Alignment

| MCP concept | Our schema mapping |
|-------------|-------------------|
| Server name/version | `agent.agent_name` + `agent.version` |
| Capabilities (tools/resources/prompts) | `agent.protocol_config → mcp.capabilities` |
| Tool definitions | `agent_function` rows (function_name → name, parameters → inputSchema) |
| Transport type | `agent_endpoint.transport_config → transport` |
| Protocol version | `agent.protocol_config → mcp.protocol_version` |

---

## 4. Summary of Recommended Schema Changes

| Change | Table | Type | Effort |
|--------|-------|------|--------|
| Add `protocol_config JSONB` | `agent` | New column | Low |
| Add `transport_config JSONB` | `agent_endpoint` | New column | Low |
| Add `output_schema JSONB` | `agent_function` | New column | Low |
| Expand `AgentProtocol` constants | `agent_models.py` | Code change | Trivial |
| Add `OPENAI_RESPONSES`, `REST` protocol URIs | `agent_models.py` | Code change | Trivial |
| Standardize `parameters` as JSON Schema 2020-12 | Convention / validation | Documentation | Low |
| Migration script for new columns | `migrate_agents.py` | DDL | Low |

### Not recommended

- **No new tables needed** — the existing structure (agent + endpoint + function) maps well to all protocols
- **No framework-specific protocol URIs** — LangChain, CrewAI, AutoGen are not wire protocols
- **No separate A2A Agent Card table** — the card can be reconstructed from existing + new columns
- **No ACP support** — the AGNTCY ACP spec is archived; the community has converged on A2A + MCP

---

## 5. Implementation Priority

1. **Add `protocol_config` column** to `agent` — enables per-protocol structured config
2. **Add `transport_config` column** to `agent_endpoint` — enables rich transport details
3. **Add `output_schema` column** to `agent_function` — aligns with MCP/OpenAI output schemas
4. **Expand `AgentProtocol` constants** — add OPENAI_RESPONSES, REST
5. **Document recommended JSONB structures** per protocol (this document serves as the reference)
6. **Add optional validation helpers** for well-known protocol configs
7. **Update discovery endpoint** (Phase 8a) to support protocol-aware filtering on `protocol_config`
