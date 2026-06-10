# @vital-ai/vitalgraph-client

TypeScript client for connecting to [VitalGraph](https://github.com/vital-ai/vital-graph) REST API servers.

## Install

```bash
npm install @vital-ai/vitalgraph-client @vital-ai/vital-model-utils @vital-ai/vital-kg-model-ts
```

Both `@vital-ai/vital-model-utils` and `@vital-ai/vital-kg-model-ts` are **required peer dependencies**.

## Quick Start

```typescript
import { createClient } from '@vital-ai/vitalgraph-client';

const client = await createClient({
  serverUrl: 'http://localhost:8001',
  username: 'admin',
  password: 'admin',
});

// List spaces
const spacesResponse = await client.spaces.list();
console.log(spacesResponse.spaces);

// List entities in a graph
const entities = await client.kgentities.list('my-space', 'my-graph', {
  pageSize: 20,
  entityTypeUri: 'http://vital.ai/ontology/haley-ai-kg#KGEntity',
});

await client.close();
```

## Authentication

The client supports JWT (username/password) and API key authentication:

```typescript
// JWT auth
const client = await createClient({
  serverUrl: 'https://vitalgraph.example.com',
  username: 'user',
  password: 'pass',
});

// API key auth
const client = await createClient({
  serverUrl: 'https://vitalgraph.example.com',
  apiKey: 'vg_...',
});
```

## Environment Variable Config (Node.js)

```typescript
import { VitalGraphClient } from '@vital-ai/vitalgraph-client';

// Reads VITALGRAPH_CLIENT_ENVIRONMENT, then {PROFILE}_CLIENT_* vars
const client = VitalGraphClient.fromEnvironment();
await client.open();
```

## Endpoint Coverage

| Endpoint                  | Property             |
|---------------------------|----------------------|
| Spaces                    | `client.spaces`      |
| Graphs                    | `client.graphs`      |
| Objects                   | `client.objects`     |
| KGTypes                   | `client.kgtypes`     |
| KGEntities                | `client.kgentities`  |
| KGFrames                  | `client.kgframes`    |
| KGRelations               | `client.kgrelations` |
| KGQueries                 | `client.kgqueries`   |
| KGDocuments               | `client.kgdocuments` |
| Users                     | `client.users`       |
| API Keys                  | `client.apiKeys`     |
| Files                     | `client.files`       |
| SPARQL                    | `client.sparql`      |
| Triples                   | `client.triples`     |
| Import                    | `client.imports`     |
| Export                    | `client.exports`     |
| Metrics                   | `client.metrics`     |
| Admin                     | `client.admin`       |
| Processes                 | `client.processes`   |
| Vector Mappings           | `client.vectorMappings` |
| Vector Indexes            | `client.vectorIndexes`  |
| Geo Config                | `client.geoConfig`   |
| Geo Points                | `client.geoPoints`   |
| Agent Registry            | `client.agentRegistry` |
| Entity Registry           | `client.entityRegistry` |

## Retry & Error Handling

The client automatically retries failed requests with exponential backoff and reactively refreshes JWT tokens on 401 responses. Configure via:

```typescript
const client = await createClient({
  serverUrl: 'http://localhost:8001',
  username: 'admin',
  password: 'admin',
  maxRetries: 5,
  retryDelay: 2000,
  timeout: 60000,
});
```

## License

Apache-2.0
