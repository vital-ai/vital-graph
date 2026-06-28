# SPARQL Compiler Sidecar — Jena ARQ REST API

## Implementation Status (March 2, 2026)

**Status: COMPLETE — Built, tested, and running in Docker.**

| Component | Status |
|---|---|
| Java source (App, POJOs, SparqlCompiler, 5 serializers, 2 utilities) | ✅ Done |
| Maven build (38 unit tests pass) | ✅ Done |
| Docker multi-stage build | ✅ Done |
| Smoke test (13/13 pass against Docker container) | ✅ Done |

**Final dependency versions** (updated from original plan):
- Apache Jena ARQ: **6.0.0** (upgraded from 5.2.0)
- Javalin: **7.0.1** (upgraded from 6.4.0)
- Java: **21** (required by Jena 6)
- Jackson: 2.17.0, SLF4J: 2.0.13, JUnit: 5.10.2

**Key build decisions**:
- `maven-shade-plugin` (not `maven-assembly-plugin`) — required to merge `META-INF/services` files for Jena's ServiceLoader initialization
- `eclipse-temurin:21-jre` Debian base (not Alpine) — Jena 6 needs glibc
- Eager `JenaSystem.init()` at startup for fast-fail error reporting
- Javalin 7 routing uses `config.routes.post/get()` (upfront config model)

---

## Overview

A lightweight Java sidecar service that accepts SPARQL strings over a REST API,
runs them through Apache Jena ARQ (parse → compile → optional optimize), and
returns structured JSON artifacts. Handles **all SPARQL constructs**: SELECT, CONSTRUCT,
ASK, DESCRIBE, INSERT, DELETE, LOAD, CLEAR, DROP, CREATE, COPY, MOVE, ADD.
**No query execution, no dataset required.**

This plan covers the sidecar service itself and the changes needed to the
existing Docker/docker-compose setup to run it alongside the VitalGraph container.

---

## API Specification

### Endpoints

```
POST /v1/sparql/compile
Content-Type: application/json
```

Accepts both SPARQL Query (SELECT, CONSTRUCT, ASK, DESCRIBE) and
SPARQL Update (INSERT DATA, DELETE DATA, INSERT/DELETE WHERE, LOAD, CLEAR,
DROP, CREATE, COPY, MOVE, ADD) forms. The service auto-detects the form
via Jena's parser.

### Request JSON

```json
{
  "sparql": "SELECT ?s ?o WHERE { ?s <http://example.org/p> ?o } LIMIT 10",
  "phases": {
    "parsedQuery": true,
    "syntaxTree": true,
    "algebraCompiled": true,
    "algebraOptimized": false,
    "normalizedSparql": false,
    "updateOperations": true
  },
  "optimize": {
    "enabled": false,
    "enableJoinReorder": false,
    "enableFilterPushdown": true,
    "enableExprSimplify": true
  },
  "trace": {
    "includeTiming": true,
    "includeWarnings": true,
    "includePretty": true
  }
}
```

#### Field Descriptions

| Field | Type | Description |
|---|---|---|
| `sparql` | string | The SPARQL query string (required) |
| `phases.parsedQuery` | bool | Return high-level query metadata |
| `phases.syntaxTree` | bool | Return Jena Element tree (WHERE clause) |
| `phases.algebraCompiled` | bool | Return compiled Op algebra tree |
| `phases.algebraOptimized` | bool | Return optimized Op algebra tree |
| `phases.normalizedSparql` | bool | Return canonicalized SPARQL string |
| `phases.updateOperations` | bool | Return parsed update operations list (for SPARQL Update) |
| `optimize.enabled` | bool | Master switch for optimization phase |
| `optimize.enableJoinReorder` | bool | Allow join reordering transform |
| `optimize.enableFilterPushdown` | bool | Push filters closer to BGPs |
| `optimize.enableExprSimplify` | bool | Simplify filter expressions |
| `trace.includeTiming` | bool | Include per-phase timing in ms |
| `trace.includeWarnings` | bool | Collect and return parser warnings |
| `trace.includePretty` | bool | Include pretty-printed algebra strings |

### Response JSON

```json
{
  "ok": true,
  "meta": {
    "serviceVersion": "1.0.0",
    "jenaVersion": "5.2.0",
    "timingMs": {
      "parse": 3,
      "compile": 2,
      "optimize": 0,
      "serialize": 1
    }
  },
  "input": {
    "sparqlHash": "sha256:abc123..."
  },
  "phases": {
    "parsedQuery": {
      "sparqlForm": "QUERY",
      "queryType": "SELECT",
      "projectVars": ["s", "o"],
      "distinct": false,
      "reduced": false,
      "limit": 10,
      "offset": 0,
      "orderBy": [],
      "groupBy": [],
      "having": [],
      "datasetDefaultGraphs": [],
      "datasetNamedGraphs": [],
      "aggregates": [],
      "values": null
    },
    "syntaxTree": {
      "wherePattern": {
        "type": "ElementGroup",
        "elements": [
          {
            "type": "ElementTriplesBlock",
            "triples": [
              {
                "subject": { "type": "var", "name": "s" },
                "predicate": { "type": "uri", "value": "http://example.org/p" },
                "object": { "type": "var", "name": "o" }
              }
            ]
          },
          {
            "type": "ElementOptional",
            "sub": { "..." : "..." }
          },
          {
            "type": "ElementFilter",
            "expr": { "..." : "..." }
          }
        ]
      }
    },
    "algebraCompiled": {
      "op": {
        "type": "OpProject",
        "vars": ["?s", "?o"],
        "subOp": { "..." : "..." }
      },
      "pretty": "Project(?s ?o)\n  Slice(0, 10)\n    BGP(?s <http://example.org/p> ?o)"
    },
    "algebraOptimized": null,
    "normalizedSparql": null,
    "updateOperations": null
  },
  "warnings": []
}
```

### Error Response

```json
{
  "ok": false,
  "error": {
    "code": "PARSE_ERROR",
    "message": "Lexical error at line 1, column 23: unexpected token 'SELEC'",
    "line": 1,
    "column": 23,
    "snippet": "SELEC ?s WHERE { ... }"
  },
  "meta": {
    "serviceVersion": "1.0.0",
    "jenaVersion": "5.2.0",
    "timingMs": { "parse": 1 }
  }
}
```

Error codes: `PARSE_ERROR`, `INPUT_TOO_LARGE`, `TIMEOUT`, `INTERNAL_ERROR`.

---

## Internal Flow (Java)

The service auto-detects whether the input is a SPARQL Query or SPARQL Update
and routes to the appropriate Jena parser.

### SPARQL Query Flow (SELECT, CONSTRUCT, ASK, DESCRIBE)

```
Request JSON
    │
    ▼
1. Parse
    Query q = QueryFactory.create(sparql);
    ─ Extract metadata: queryType, vars, distinct, limit, offset, etc.
    ─ Element where = q.getQueryPattern();
    │
    ▼
2. Compile
    Op op = Algebra.compile(q);
    │
    ▼
3. Optional Optimize
    if (optimize.enabled):
        Op opOpt = Algebra.optimize(op);
        ─ Or apply controlled subset of TransformFilterPlacement,
          TransformJoinStrategy, TransformSimplify
    │
    ▼
4. Serialize
    ─ Serialize Element tree to JSON via ElementVisitor
    ─ Serialize Op tree to JSON via OpVisitor / OpWalker
    ─ Include pretty strings via WriterOp / IndentedWriter
    │
    ▼
5. Return JSON response with timings, warnings, query hash
```

### SPARQL Update Flow (INSERT, DELETE, LOAD, CLEAR, DROP, etc.)

```
Request JSON
    │
    ▼
1. Parse
    UpdateRequest req = UpdateFactory.create(sparql);
    List<Update> ops = req.getOperations();
    │
    ▼
2. Classify each Update operation
    ─ UpdateModify  (INSERT/DELETE WHERE)
    ─ UpdateDataInsert (INSERT DATA)
    ─ UpdateDataDelete (DELETE DATA)
    ─ UpdateLoad (LOAD)
    ─ UpdateClear (CLEAR)
    ─ UpdateDrop (DROP)
    ─ UpdateCreate (CREATE)
    ─ UpdateCopy (COPY)
    ─ UpdateMove (MOVE)
    ─ UpdateAdd (ADD)
    │
    ▼
3. Extract per-operation details
    ─ For UpdateModify: WHERE pattern (Element), insert/delete quads,
      USING/WITH graph URIs
    ─ For UpdateDataInsert/Delete: quad data
    ─ For management ops: target graph, silent flag
    │
    ▼
4. Serialize
    ─ Serialize each Update operation to JSON
    ─ For UpdateModify, serialize WHERE pattern via ElementVisitor
    ─ Serialize quad templates via NodeSerializer
    │
    ▼
5. Return JSON response with operation list, timings, warnings
```

### Auto-Detection Logic

```java
try {
    Query q = QueryFactory.create(sparql);
    // Handle as SPARQL Query
} catch (QueryParseException e) {
    try {
        UpdateRequest req = UpdateFactory.create(sparql);
        // Handle as SPARQL Update
    } catch (Exception e2) {
        // Return parse error from whichever attempt is more relevant
    }
}
```

### Key Jena Classes

| Step | Class / Method |
|---|---|
| Parse query | `QueryFactory.create(sparqlString)` |
| Parse update | `UpdateFactory.create(sparqlString)` |
| Query metadata | `query.getQueryType()`, `query.getProjectVars()`, etc. |
| Update operations | `updateRequest.getOperations()` → `List<Update>` |
| WHERE pattern | `query.getQueryPattern()` → `Element` tree |
| Update WHERE | `updateModify.getWherePattern()` → `Element` tree |
| Insert/delete quads | `updateModify.getInsertQuads()`, `updateModify.getDeleteQuads()` |
| Compile to algebra | `Algebra.compile(query)` → `Op` tree |
| Optimize | `Algebra.optimize(op)` or individual `Transform*` classes |
| Serialize Element | Custom `ElementVisitor` → JSON |
| Serialize Op | Custom `OpVisitor` → JSON |
| Serialize Update | Custom `UpdateVisitor` → JSON |
| Pretty print | `WriterOp.output(IndentedWriter, op)` or `OpAsQuery.asQuery(op)` |

---

## JSON Serialization Details

### Element Tree (Syntax)

Map each Jena `Element` subclass to a JSON node:

| Jena Element | JSON `type` | Key Children |
|---|---|---|
| `ElementGroup` | `ElementGroup` | `elements: [...]` |
| `ElementTriplesBlock` | `ElementTriplesBlock` | `triples: [{s,p,o}, ...]` |
| `ElementOptional` | `ElementOptional` | `sub: {...}` |
| `ElementUnion` | `ElementUnion` | `elements: [left, right]` |
| `ElementFilter` | `ElementFilter` | `expr: {...}` |
| `ElementBind` | `ElementBind` | `var: "x", expr: {...}` |
| `ElementSubQuery` | `ElementSubQuery` | `query: {...}` (recurse) |
| `ElementNamedGraph` | `ElementNamedGraph` | `graphNode: ..., sub: {...}` |
| `ElementMinus` | `ElementMinus` | `sub: {...}` |
| `ElementService` | `ElementService` | `serviceURI: ..., sub: {...}` |
| `ElementValues` | `ElementValues` | `vars: [...], rows: [...]` |
| `ElementNotExists` | `ElementNotExists` | `sub: {...}` |
| `ElementExists` | `ElementExists` | `sub: {...}` |

### Op Tree (Algebra)

Map each Jena `Op` subclass:

| Jena Op | JSON `type` | Key Children |
|---|---|---|
| `OpBGP` | `OpBGP` | `triples: [{s,p,o}, ...]` |
| `OpJoin` | `OpJoin` | `left: {...}, right: {...}` |
| `OpLeftJoin` | `OpLeftJoin` | `left, right, exprs` |
| `OpUnion` | `OpUnion` | `left, right` |
| `OpFilter` | `OpFilter` | `exprs: [...], subOp: {...}` |
| `OpProject` | `OpProject` | `vars: [...], subOp: {...}` |
| `OpSlice` | `OpSlice` | `start, length, subOp` |
| `OpDistinct` | `OpDistinct` | `subOp` |
| `OpReduced` | `OpReduced` | `subOp` |
| `OpOrder` | `OpOrder` | `conditions: [...], subOp` |
| `OpGroup` | `OpGroup` | `groupVars, aggregators, subOp` |
| `OpExtend` | `OpExtend` | `var, expr, subOp` |
| `OpTable` | `OpTable` | `vars, rows` (VALUES) |
| `OpMinus` | `OpMinus` | `left, right` |
| `OpGraph` | `OpGraph` | `graphNode, subOp` |
| `OpConditional` | `OpConditional` | `left, right` |
| `OpSequence` | `OpSequence` | `elements: [...]` |
| `OpLabel` | `OpLabel` | `label, subOp` |

### RDF Node Serialization

```json
{ "type": "var",     "name": "s" }
{ "type": "uri",     "value": "http://example.org/p" }
{ "type": "literal", "value": "hello", "lang": "en" }
{ "type": "literal", "value": "42", "datatype": "http://www.w3.org/2001/XMLSchema#integer" }
{ "type": "bnode",   "label": "b0" }
```

### Expression Serialization

```json
{ "type": "ExprFunction2", "name": "=",  "args": [ {...}, {...} ] }
{ "type": "ExprFunction1", "name": "str", "arg": {...} }
{ "type": "ExprVar",       "var": "x" }
{ "type": "NodeValue",     "node": { "type": "literal", "value": "42", "datatype": "..." } }
{ "type": "ExprAggregator", "name": "COUNT", "distinct": true, "expr": {...} }
```

---

## Java Project Structure

All sidecar source lives in `vitalgraph-jena-sidecar/` at the repo root.

```
vitalgraph-jena-sidecar/
├── pom.xml                          # Maven with Jena + Javalin/Jetty
├── Dockerfile
├── docker-compose.yml               # Standalone compose for independent testing
├── src/main/java/ai/vital/sparqlcompiler/
│   ├── App.java                     # Entry point, HTTP server setup
│   ├── CompileRequest.java          # Request POJO
│   ├── CompileResponse.java         # Response POJO
│   ├── SparqlCompiler.java          # Core: parse → compile → optimize
│   ├── serializer/
│   │   ├── ElementSerializer.java   # ElementVisitor → JSON
│   │   ├── OpSerializer.java        # OpVisitor → JSON
│   │   ├── ExprSerializer.java      # Expr → JSON
│   │   ├── NodeSerializer.java      # RDF Node → JSON
│   │   └── UpdateSerializer.java    # UpdateVisitor → JSON
│   └── util/
│       ├── QueryMetadataExtractor.java
│       └── TimingContext.java
└── src/test/java/ai/vital/sparqlcompiler/
    ├── SparqlCompilerTest.java
    ├── SparqlUpdateCompilerTest.java
    ├── ElementSerializerTest.java
    ├── OpSerializerTest.java
    └── UpdateSerializerTest.java
```

### Key Dependencies (pom.xml)

```xml
<dependencies>
    <!-- Jena ARQ for SPARQL parsing and algebra -->
    <dependency>
        <groupId>org.apache.jena</groupId>
        <artifactId>jena-arq</artifactId>
        <version>6.0.0</version>
    </dependency>

    <!-- Lightweight HTTP server -->
    <dependency>
        <groupId>io.javalin</groupId>
        <artifactId>javalin</artifactId>
        <version>7.0.1</version>
    </dependency>

    <!-- JSON serialization -->
    <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
        <version>2.17.0</version>
    </dependency>

    <!-- Logging -->
    <dependency>
        <groupId>org.slf4j</groupId>
        <artifactId>slf4j-simple</artifactId>
        <version>2.0.13</version>
    </dependency>
</dependencies>
```

### Why Javalin

- Minimal footprint (~1 MB), starts in <500ms
- Embedded Jetty — no external servlet container
- Simple routing: `app.post("/v1/sparql/compile", handler)`
- Good fit for a sidecar that does one thing

---

## Docker Setup

### Sidecar Dockerfile

Create `vitalgraph-jena-sidecar/Dockerfile`:

```dockerfile
# Stage 1: Build
FROM eclipse-temurin:21-jdk AS build
RUN apt-get update && apt-get install -y --no-install-recommends maven && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY pom.xml .
RUN mvn dependency:go-offline -q
COPY src ./src
RUN mvn package -q -DskipTests

# Stage 2: Run
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/target/sparql-compiler-sidecar-1.0.0.jar app.jar

ENV PORT=7070
ENV MAX_INPUT_SIZE=1048576
ENV REQUEST_TIMEOUT_MS=5000

EXPOSE 7070

ENTRYPOINT ["java", "-Xmx256m", "-jar", "app.jar"]
```

- **Base image**: Eclipse Temurin JRE 21 Debian (~200 MB) — Jena 6 requires glibc (Alpine musl causes init failures)
- **Build**: Multi-stage — Maven builds inside Docker, only JRE + fat jar in final image
- **Fat jar**: `maven-shade-plugin` with `ServicesResourceTransformer` (merges `META-INF/services` for Jena ServiceLoader)
- **Heap**: 256 MB is sufficient for parsing/compilation (no data loaded)
- **Startup**: ~200ms (Javalin + Jena init)

### Standalone docker-compose (for independent testing)

Create `vitalgraph-jena-sidecar/docker-compose.yml` so the sidecar can be
built and run without the VitalGraph service. This is used during development
and by the Python integration test suite.

```yaml
version: '3.8'

services:
  sparql-compiler:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: sparql-compiler
    ports:
      - "7070:7070"
    environment:
      - PORT=7070
      - MAX_INPUT_SIZE=1048576
      - REQUEST_TIMEOUT_MS=5000
    restart: unless-stopped
```

Usage:

```bash
cd vitalgraph-jena-sidecar
docker-compose up --build
# Sidecar is now available at http://localhost:7070
```

The Python test scripts in `test_scripts/jena_sidecar/` expect the sidecar
to be running at `localhost:7070` (or the URL in `SPARQL_COMPILER_URL`).

### Changes to Existing docker-compose.yml (for full-stack deployment)

Add the `sparql-compiler` service to the root `docker-compose.yml`.
The sidecar joins the same `vitalgraph_network` so it is reachable by the
`vitalgraph` service via `sparql-compiler:7070`.

```yaml
  sparql-compiler:
    build:
      context: ./vitalgraph-jena-sidecar
      dockerfile: Dockerfile
    container_name: sparql-compiler
    ports:
      - "7070:7070"
    environment:
      - PORT=7070
      - MAX_INPUT_SIZE=1048576
      - REQUEST_TIMEOUT_MS=5000
    restart: unless-stopped
    networks:
      - vitalgraph_network
```

Add `sparql-compiler` to the `vitalgraph` service's `depends_on`:

```yaml
  vitalgraph:
    ...
    depends_on:
      - minio
      - sparql-compiler
```

No changes to the existing `Dockerfile`, volumes, or networks sections.

### ECS Task Definition

Add the minimum container definition to the existing task definition:

```json
{
  "name": "sparql-compiler",
  "image": "sparql-compiler-sidecar:1.0.0",
  "essential": false,
  "cpu": 256,
  "memory": 512
}
```

- **`essential: false`** — sidecar crash does not kill the task
- No `portMappings` needed — only accessed via localhost within the task
- 256 CPU units + 512 MB memory is sufficient for parse-only workload

---

## Production Hardening

### Input Validation

- **Max SPARQL size**: 1 MB (configurable via `MAX_INPUT_SIZE` env var)
- **Request timeout**: 5 seconds (configurable via `REQUEST_TIMEOUT_MS`)
- Accept both SPARQL Query and SPARQL Update forms

### Deterministic Output

- Same SPARQL → same JSON output (important for caching)
- Sort map keys, use stable iteration order in visitors
- Include `sparqlHash` (SHA-256) in response for cache key use

### Error Handling

- Parse errors: return line/column/snippet from Jena `QueryParseException`
- Timeout: interrupt parse/compile if exceeds limit
- OOM protection: bounded heap + input size limit

### Logging

- Log request hash + timing per phase
- Log errors with full SPARQL for debugging
- Use structured JSON logging (SLF4J + Logback JSON encoder)

---

## Implementation Milestones

### M1: Minimal Viable Sidecar
- [x] Maven project with Jena ARQ 6.0.0 + Javalin 7.0.1
- [x] `POST /v1/sparql/compile` with `parsedQuery` phase only
- [x] Sidecar Dockerfile (multi-stage, Debian-based)
- [x] Standalone `docker-compose.yml` for independent testing
- [x] Local docker-compose test — 13/13 smoke tests pass

### M2: Full Serialization
- [x] `ElementSerializer` (syntax tree → JSON)
- [x] `OpSerializer` (algebra → JSON)
- [x] `ExprSerializer` (expressions → JSON)
- [x] Pretty-print output via Jena SSE writer
- [x] All phases working end-to-end

### M3: Production Hardening
- [x] Input size limits and request timeout
- [x] Structured error responses with line/column
- [x] Deterministic JSON output (sorted keys, stable order)
- [x] Logging with request hash and timing
- [x] Unit tests — 38 tests (SparqlCompilerTest + SparqlUpdateCompilerTest)

### M4: ECS Deployment
- [ ] Add sidecar container definition to existing ECS task definition
- [ ] CloudWatch log routing
- [ ] Integration testing in staging
- [ ] Update root `docker-compose.yml` with `sparql-compiler` service
