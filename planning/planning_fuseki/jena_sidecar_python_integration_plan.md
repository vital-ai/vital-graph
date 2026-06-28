# Jena Sidecar Python Integration — SPARQL-to-SQL via Jena ARQ

## Overview

This plan covers the Python side of integrating with the SPARQL compiler sidecar.
The goal is to:

1. Receive a SPARQL statement (query or update)
2. Send it to the Jena sidecar for parsing and compilation
3. Map the Jena-produced JSON artifacts (Op algebra, update operations)
   into Python data structures
4. Generate PostgreSQL SQL against the space's quad + term table structure
5. Execute the SQL and return results

This is a from-scratch implementation. The SQL generation is new.

---

## PostgreSQL Table Schema (per space)

Each space has the following tables, prefixed by `{global_prefix}__{space_id}__`:

**term table** (`{prefix}__{space_id}__term`):
- `term_uuid UUID` — primary key (partitioned with dataset)
- `term_text TEXT` — the actual URI, literal value, or blank node label
- `term_type CHAR(1)` — `'U'` (URI), `'L'` (Literal), `'B'` (BNode), `'G'` (Graph)
- `lang VARCHAR(20)` — language tag for literals
- `datatype_id BIGINT` — FK to datatype table
- `dataset VARCHAR(50)` — partition key (default `'primary'`)

**rdf_quad table** (`{prefix}__{space_id}__rdf_quad`):
- `subject_uuid UUID` — FK to term table
- `predicate_uuid UUID` — FK to term table
- `object_uuid UUID` — FK to term table
- `context_uuid UUID` — FK to term table (graph URI)
- `quad_uuid UUID` — unique quad identifier
- `dataset VARCHAR(50)` — partition key (default `'primary'`)

**datatype table** (`{prefix}__{space_id}__datatype`):
- `datatype_id BIGSERIAL` — primary key
- `datatype_uri VARCHAR(255)` — unique datatype URI
- `datatype_name VARCHAR(100)` — human-readable name

**namespace table** (`{prefix}__{space_id}__namespace`):
- `namespace_id BIGSERIAL` — primary key
- `prefix VARCHAR(50)` — namespace prefix
- `namespace_uri TEXT` — full namespace URI

**graph table** (`{prefix}__{space_id}__graph`):
- `graph_id BIGSERIAL` — primary key
- `graph_uri TEXT` — unique graph URI
- `triple_count BIGINT` — count of triples in graph

### Key Indexes

- `idx_*_term_text` — B-tree on `term_text`
- `idx_*_term_text_type` — composite on `(term_text, term_type)`
- `idx_*_term_text_gin_trgm` — trigram GIN for text search
- `idx_*_quad_subject` — B-tree on `subject_uuid`
- `idx_*_quad_predicate` — B-tree on `predicate_uuid`
- `idx_*_quad_object` — B-tree on `object_uuid`
- `idx_*_quad_context` — B-tree on `context_uuid`
- `idx_*_quad_spoc` — composite on `(subject_uuid, predicate_uuid, object_uuid, context_uuid)`

### SQL Pattern

Queries JOIN the quad table to the term table to resolve UUIDs to text values.
A basic triple pattern `?s <ex:p> ?o` becomes:

```sql
SELECT s_term.term_text AS s, o_term.term_text AS o
FROM rdf_quad q
JOIN term s_term ON q.subject_uuid = s_term.term_uuid
JOIN term p_term ON q.predicate_uuid = p_term.term_uuid
JOIN term o_term ON q.object_uuid = o_term.term_uuid
WHERE p_term.term_text = 'http://example.org/p'
  AND p_term.term_type = 'U'
```

---

## Architecture

```
SPARQL string
    │
    ▼
SidecarClient → POST http://localhost:7070/v1/sparql/compile
    │
    ▼
Jena JSON response:
  - parsedQuery (metadata: type, vars, distinct, limit, offset)
  - algebraCompiled (Op tree — for queries)
  - updateOperations (operation list — for updates)
    │
    ▼
JenaASTMapper → Python data structures (Op nodes, expressions, triples)
    │
    ▼
SQLGenerator → PostgreSQL SQL against quad + term tables
    │
    ▼
Execute SQL, return results
```

---

## Component Design

### 1. SidecarClient

HTTP client for the Jena sidecar.

```
vitalgraph_sparql_sql/jena_sidecar_client.py
```

- POST SPARQL to sidecar, receive JSON
- Connection pooling via `httpx.AsyncClient` (persistent, shared)
- Timeout and error handling
- Configurable URL via `SPARQL_COMPILER_URL` env var

### 2. JenaASTMapper

Maps Jena JSON into Python data structures.

```
vitalgraph_sparql_sql/jena_ast_mapper.py
```

Defines clean Python types that mirror Jena's Op/Element/Expr types and
converts the sidecar JSON into instances of those types.

#### Python Op Types (new, from scratch)

```python
@dataclass
class OpBGP:
    triples: List[TriplePattern]

@dataclass
class OpJoin:
    left: Op
    right: Op

@dataclass
class OpLeftJoin:
    left: Op
    right: Op
    exprs: List[Expr]

@dataclass
class OpUnion:
    left: Op
    right: Op

@dataclass
class OpFilter:
    exprs: List[Expr]
    sub_op: Op

@dataclass
class OpProject:
    vars: List[str]
    sub_op: Op

@dataclass
class OpSlice:
    start: int
    length: int  # -1 means no limit
    sub_op: Op

@dataclass
class OpDistinct:
    sub_op: Op

@dataclass
class OpReduced:
    sub_op: Op

@dataclass
class OpOrder:
    conditions: List[SortCondition]
    sub_op: Op

@dataclass
class OpGroup:
    group_vars: List[str]
    aggregators: List[Aggregator]
    sub_op: Op

@dataclass
class OpExtend:
    var: str
    expr: Expr
    sub_op: Op

@dataclass
class OpTable:
    vars: List[str]
    rows: List[Dict[str, RDFNode]]

@dataclass
class OpMinus:
    left: Op
    right: Op

@dataclass
class OpGraph:
    graph_node: RDFNode
    sub_op: Op

@dataclass
class OpSequence:
    elements: List[Op]
```

#### Python RDF Node Types

```python
@dataclass
class URINode:
    value: str

@dataclass
class LiteralNode:
    value: str
    lang: Optional[str] = None
    datatype: Optional[str] = None

@dataclass
class VarNode:
    name: str

@dataclass
class BNodeNode:
    label: str
```

#### Python Expression Types

```python
@dataclass
class ExprFunction:
    name: str       # "=", "<", "contains", "regex", "str", etc.
    args: List[Expr]

@dataclass
class ExprVar:
    var: str

@dataclass
class ExprValue:
    node: RDFNode

@dataclass
class ExprAggregator:
    name: str       # "COUNT", "SUM", "AVG", "MIN", "MAX"
    distinct: bool
    expr: Optional[Expr]
```

#### Python Update Operation Types

```python
@dataclass
class UpdateDataInsert:
    quads: List[QuadPattern]

@dataclass
class UpdateDataDelete:
    quads: List[QuadPattern]

@dataclass
class UpdateModify:
    with_graph: Optional[str]
    delete_quads: List[QuadPattern]
    insert_quads: List[QuadPattern]
    using_graphs: List[str]
    where_pattern: Op

@dataclass
class UpdateLoad:
    source: str
    dest_graph: Optional[str]
    silent: bool

@dataclass
class UpdateClear:
    graph: Optional[str]  # None = default graph
    target: str           # "DEFAULT", "NAMED", "ALL", or graph URI
    silent: bool

@dataclass
class UpdateDrop:
    graph: Optional[str]
    target: str
    silent: bool

@dataclass
class UpdateCreate:
    graph: str
    silent: bool

@dataclass
class UpdateCopy:
    source: str
    dest: str
    silent: bool

@dataclass
class UpdateMove:
    source: str
    dest: str
    silent: bool

@dataclass
class UpdateAdd:
    source: str
    dest: str
    silent: bool
```

#### Jena JSON → Python Mapping

| Jena Op JSON `type` | Python Type |
|---|---|
| `OpBGP` | `OpBGP` |
| `OpJoin` | `OpJoin` |
| `OpLeftJoin` | `OpLeftJoin` |
| `OpUnion` | `OpUnion` |
| `OpFilter` | `OpFilter` |
| `OpProject` | `OpProject` |
| `OpSlice` | `OpSlice` |
| `OpDistinct` | `OpDistinct` |
| `OpReduced` | `OpReduced` |
| `OpOrder` | `OpOrder` |
| `OpGroup` | `OpGroup` |
| `OpExtend` | `OpExtend` |
| `OpTable` | `OpTable` |
| `OpMinus` | `OpMinus` |
| `OpGraph` | `OpGraph` |
| `OpSequence` | `OpSequence` |

| Jena Expr JSON `type` | Python Type |
|---|---|
| `ExprFunction1` | `ExprFunction` (1 arg) |
| `ExprFunction2` | `ExprFunction` (2 args) |
| `ExprFunctionN` | `ExprFunction` (N args) |
| `ExprVar` | `ExprVar` |
| `NodeValue` | `ExprValue` |
| `ExprAggregator` | `ExprAggregator` |

| Jena Node JSON `type` | Python Type |
|---|---|
| `var` | `VarNode` |
| `uri` | `URINode` |
| `literal` | `LiteralNode` |
| `bnode` | `BNodeNode` |

| Jena Update JSON `type` | Python Type |
|---|---|
| `UpdateDataInsert` | `UpdateDataInsert` |
| `UpdateDataDelete` | `UpdateDataDelete` |
| `UpdateModify` | `UpdateModify` |
| `UpdateLoad` | `UpdateLoad` |
| `UpdateClear` | `UpdateClear` |
| `UpdateDrop` | `UpdateDrop` |
| `UpdateCreate` | `UpdateCreate` |
| `UpdateCopy` | `UpdateCopy` |
| `UpdateMove` | `UpdateMove` |
| `UpdateAdd` | `UpdateAdd` |

### 3. SQLGenerator

New from-scratch SQL generation from the Python Op types.

```
vitalgraph_sparql_sql/jena_sql_generator.py
```

Walks the Op tree and produces PostgreSQL SQL against the quad + term tables.

#### Core SQL Generation Concepts

**AliasGenerator**: produces unique aliases (`q0`, `q1`, `s_term_0`, etc.)
for quad and term table references.

**VariableBindings**: tracks which SPARQL variables are bound to which SQL
column expressions (e.g., `?s` → `s_term_0.term_text`).

**SQLComponents**: accumulates FROM, JOIN, WHERE, and SELECT fragments
as the Op tree is walked.

#### Op → SQL Translation

| Op | SQL Strategy |
|---|---|
| `OpBGP` | One quad table alias per triple, JOINed to term table for each position. Shared variables produce JOIN conditions. |
| `OpJoin` | Translate left and right, merge with INNER JOIN on shared variables |
| `OpLeftJoin` | Translate left and right, merge with LEFT JOIN; exprs become ON conditions |
| `OpUnion` | Translate left and right separately, combine with `UNION ALL` |
| `OpFilter` | Translate sub_op, add WHERE conditions from exprs |
| `OpProject` | SELECT only the projected variable columns |
| `OpSlice` | Append `LIMIT` / `OFFSET` |
| `OpDistinct` | `SELECT DISTINCT` |
| `OpReduced` | `SELECT DISTINCT` (PostgreSQL has no REDUCED) |
| `OpOrder` | `ORDER BY` with ASC/DESC per condition |
| `OpGroup` | `GROUP BY` variable columns; aggregators become SQL aggregate functions |
| `OpExtend` | Add computed column: `(expr) AS var_name` |
| `OpTable` | `VALUES` inline data or lateral join |
| `OpMinus` | Left anti-join: `WHERE NOT EXISTS (SELECT 1 FROM right WHERE ...)` |
| `OpGraph` | Add `context_uuid` filter for the graph URI |
| `OpSequence` | Sequential JOINs of all elements |

#### Expression → SQL Translation

| Expression | SQL |
|---|---|
| `=`, `!=`, `<`, `>`, `<=`, `>=` | Direct comparison operators |
| `&&`, `\|\|` | `AND`, `OR` |
| `!` | `NOT` |
| `CONTAINS(a, b)` | `a LIKE '%' \|\| b \|\| '%'` or `position(b in a) > 0` |
| `STRSTARTS(a, b)` | `a LIKE b \|\| '%'` |
| `STRENDS(a, b)` | `a LIKE '%' \|\| b` |
| `REGEX(a, pattern, flags)` | `a ~ pattern` (or `~*` for case-insensitive) |
| `STRLEN(a)` | `LENGTH(a)` |
| `UCASE(a)` / `LCASE(a)` | `UPPER(a)` / `LOWER(a)` |
| `SUBSTR(a, start, len)` | `SUBSTRING(a FROM start FOR len)` |
| `REPLACE(a, pat, rep)` | `REGEXP_REPLACE(a, pat, rep)` |
| `CONCAT(...)` | `a \|\| b \|\| ...` |
| `STR(a)` | `a` (already text in term table) |
| `LANG(a)` | `term.lang` column |
| `DATATYPE(a)` | JOIN to datatype table |
| `BOUND(a)` | `a IS NOT NULL` |
| `isURI(a)` | `term.term_type = 'U'` |
| `isLiteral(a)` | `term.term_type = 'L'` |
| `isBlank(a)` | `term.term_type = 'B'` |
| `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` | Direct SQL aggregate functions |
| `COALESCE(...)` | `COALESCE(...)` |
| `IF(cond, a, b)` | `CASE WHEN cond THEN a ELSE b END` |
| `NOW()` | `CURRENT_TIMESTAMP` |
| `YEAR/MONTH/DAY/HOURS/MINUTES/SECONDS` | `EXTRACT(field FROM ...)` |
| `ABS/CEIL/FLOOR/ROUND` | Direct SQL math functions |

#### Update → SQL Translation

| Update Op | SQL Strategy |
|---|---|
| `UpdateDataInsert` | INSERT terms (ON CONFLICT DO NOTHING), then INSERT quads with UUID subselects |
| `UpdateDataDelete` | DELETE FROM rdf_quad using UUID subselects for matching terms |
| `UpdateModify` | Translate WHERE → SELECT to find matching quads; DELETE matching; INSERT new |
| `UpdateLoad` | Application-level: fetch data, parse, bulk insert |
| `UpdateClear` | DELETE FROM rdf_quad WHERE context_uuid matches graph |
| `UpdateDrop` | DELETE quads for graph + DELETE from graph table |
| `UpdateCreate` | INSERT INTO graph table |
| `UpdateCopy` | INSERT INTO rdf_quad SELECT (with context_uuid rewritten) |
| `UpdateMove` | COPY + DROP source |
| `UpdateAdd` | INSERT INTO rdf_quad SELECT (additive, no delete) |

### 4. Orchestrator

```
vitalgraph_sparql_sql/jena_sparql_orchestrator.py
```

Top-level coordination:
- Receive SPARQL string + space_id
- Call SidecarClient to get Jena JSON
- Check `parsedQuery.sparqlForm` to determine QUERY vs UPDATE
- For QUERY: use JenaASTMapper to build Op tree, pass to SQLGenerator, execute SQL
- For UPDATE: use JenaASTMapper to build update ops, pass to SQLGenerator, execute SQL
- Return results

---

## Validation Strategy — SQL vs Fuseki Comparison

The existing development environment provides two parallel data sources that enable
direct result comparison for validating the SPARQL-to-SQL implementation:

### Existing Test Infrastructure

1. **PostgreSQL database** — populated with sample RDF data in the quad + term
   table structure. This is the target of the SQL generation.
2. **Apache Fuseki** — the same sample data is loaded into a Fuseki SPARQL
   endpoint, which can be queried directly via standard SPARQL protocol.

### Validation Approach

For any SPARQL query, we can:

1. **Run via SQL pipeline**: SPARQL → Jena sidecar → AST mapper → SQL generator
   → execute against PostgreSQL → results
2. **Run via Fuseki**: send the same SPARQL query directly to Fuseki's SPARQL
   endpoint → results
3. **Compare**: assert that both result sets are equivalent (after sorting and
   normalization)

This gives us a ground-truth oracle for correctness: Fuseki's SPARQL engine is
a reference implementation, so any discrepancy indicates a bug in our SQL
generation or result formatting.

### Comparison Test Pattern

```python
async def compare_sparql_results(sparql: str, space_id: str):
    """Run the same SPARQL query via SQL pipeline and Fuseki, compare results."""
    # 1. SQL pipeline result
    sql_results = await jena_sparql_orchestrator.execute(sparql, space_id)

    # 2. Fuseki result (direct SPARQL query)
    fuseki_results = await fuseki_client.query(sparql)

    # 3. Normalize both (sort rows, normalize URIs, strip whitespace)
    sql_normalized = normalize_results(sql_results)
    fuseki_normalized = normalize_results(fuseki_results)

    # 4. Compare
    assert sql_normalized == fuseki_normalized, (
        f"Result mismatch for query:\n{sparql}\n"
        f"SQL returned {len(sql_results)} rows, Fuseki returned {len(fuseki_results)} rows"
    )
```

### What This Validates

- **SELECT queries**: row-for-row result equivalence (variable bindings)
- **CONSTRUCT queries**: triple-set equivalence (subject/predicate/object)
- **ASK queries**: boolean result equivalence
- **DESCRIBE queries**: triple-set equivalence (implementation-specific scope)
- **UPDATE operations**: apply via SQL, then verify the resulting state via
  both Fuseki and SQL SELECT queries

### Test Data

The sample data already loaded into both PostgreSQL and Fuseki includes:
- Multiple entity types with `rdf:type` assertions
- Literal properties (strings, integers, dates, with and without language tags)
- Named graphs / contexts
- Relationships between entities (edges)

This provides sufficient coverage for basic triple patterns, filters, optional
patterns, unions, aggregation, and graph-scoped queries.

### Incremental Validation

During development, each new Op → SQL translation can be immediately validated:

1. Write the SPARQL query exercising the new construct
2. Run it against Fuseki to get expected results
3. Run it through the SQL pipeline
4. Compare — fix SQL generation until results match

This tight feedback loop ensures correctness at every step rather than
discovering mismatches only at the end.

---

## Test Framework

### Test Structure

```
test_scripts/jena_sidecar/
├── test_jena_sidecar_integration.py    # Main test orchestrator
├── test_jena_select_queries.py         # SELECT query tests
├── test_jena_construct_queries.py      # CONSTRUCT query tests
├── test_jena_ask_describe.py           # ASK + DESCRIBE tests
├── test_jena_update_operations.py      # INSERT/DELETE/MODIFY tests
├── test_jena_management_ops.py         # LOAD/CLEAR/DROP/CREATE/COPY/MOVE/ADD
├── test_jena_complex_patterns.py       # OPTIONAL, UNION, MINUS, FILTER, VALUES
├── test_jena_expressions.py            # Filter expressions, BIND, aggregates
├── test_jena_property_paths.py         # Property path queries
├── test_jena_ast_mapper.py             # Unit tests for JSON → Python types
├── test_jena_sql_generator.py          # Unit tests for Op → SQL generation
└── sparql_test_cases/
    ├── select_basic.sparql
    ├── select_optional.sparql
    ├── select_union.sparql
    ├── select_filter.sparql
    ├── select_bind.sparql
    ├── select_aggregation.sparql
    ├── select_subquery.sparql
    ├── select_values.sparql
    ├── select_minus.sparql
    ├── select_graph.sparql
    ├── select_property_path.sparql
    ├── construct_basic.sparql
    ├── construct_where.sparql
    ├── ask_basic.sparql
    ├── describe_basic.sparql
    ├── insert_data.sparql
    ├── delete_data.sparql
    ├── delete_insert_where.sparql
    ├── load.sparql
    ├── clear.sparql
    ├── drop.sparql
    ├── create_graph.sparql
    ├── copy.sparql
    ├── move.sparql
    └── add.sparql
```

### Test Categories

#### Category 1: AST Mapper Unit Tests

Test the JSON → Python type mapping without database access.
Input: canned Jena JSON responses. Output: verify Python Op/Expr/Node instances.

```
Test: Parse OpBGP with 2 triples → verify OpBGP with TriplePattern list
Test: Parse OpFilter with nested OpBGP → verify OpFilter with ExprFunction + OpBGP
Test: Parse OpLeftJoin → verify left, right, exprs
Test: Parse OpUnion → verify left, right branches
Test: Parse OpProject with OpSlice → verify vars, limit, offset
Test: Parse OpGroup with aggregators → verify group vars, ExprAggregator list
Test: Parse OpExtend (BIND) → verify var, expr, sub_op
Test: Parse OpTable (VALUES) → verify vars, rows with RDFNode values
Test: Parse OpMinus → verify left, right
Test: Parse OpGraph → verify graph_node, sub_op
Test: Parse UpdateDataInsert → verify QuadPattern list
Test: Parse UpdateModify → verify where_pattern, insert/delete quads
Test: Parse UpdateClear → verify target, silent flag
Test: Parse expression trees → verify ExprFunction nesting
```

#### Category 2: SQL Generation Unit Tests

Test that Python Op types produce correct SQL.
Requires table names but not a live database.

```
Test: OpBGP with 1 triple → single quad JOIN with term JOINs
Test: OpBGP with 2 triples, shared variable → two quad aliases with JOIN condition
Test: OpBGP with bound predicate → WHERE condition on p_term.term_text
Test: OpLeftJoin → LEFT JOIN SQL
Test: OpUnion → UNION ALL SQL
Test: OpFilter with = → WHERE clause with comparison
Test: OpFilter with REGEX → WHERE with ~ operator
Test: OpFilter with LANG → WHERE on term.lang column
Test: OpFilter with BOUND → WHERE IS NOT NULL
Test: OpFilter with isURI → WHERE term_type = 'U'
Test: OpExtend → computed column in SELECT
Test: OpTable (VALUES) → inline data
Test: OpMinus → NOT EXISTS subquery
Test: OpGraph → context_uuid = graph term UUID
Test: OpDistinct → SELECT DISTINCT
Test: OpSlice → LIMIT / OFFSET
Test: OpOrder → ORDER BY
Test: OpGroup + ExprAggregator → GROUP BY + COUNT/SUM/etc.
Test: OpProject → SELECT with only projected columns
Test: Nested Op tree (Project > Slice > Filter > BGP) → complete SQL query
Test: UpdateDataInsert → INSERT INTO term + INSERT INTO rdf_quad
Test: UpdateDataDelete → DELETE FROM rdf_quad with UUID subselects
Test: UpdateModify → SELECT matching + DELETE + INSERT
Test: UpdateClear → DELETE FROM rdf_quad WHERE context_uuid matches
```

#### Category 3: End-to-End Integration Tests

Full pipeline against a live PostgreSQL space with test data loaded.

```
Test: SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10
Test: SELECT ?s WHERE { ?s <rdf:type> <ex:Person> }
Test: SELECT ?s ?name WHERE { ?s <ex:name> ?name . OPTIONAL { ?s <ex:age> ?age } }
Test: SELECT ?s WHERE { { ?s <rdf:type> <ex:Person> } UNION { ?s <rdf:type> <ex:Org> } }
Test: SELECT ?s WHERE { ?s <ex:name> ?name . FILTER(CONTAINS(?name, "John")) }
Test: SELECT ?s (?age + 1 AS ?nextAge) WHERE { ?s <ex:age> ?age }
Test: SELECT (COUNT(?s) AS ?count) WHERE { ?s ?p ?o } GROUP BY ?p
Test: CONSTRUCT { ?s <ex:label> ?name } WHERE { ?s <ex:name> ?name }
Test: ASK { <ex:person1> <rdf:type> <ex:Person> }
Test: DESCRIBE <ex:person1>
Test: INSERT DATA { <ex:new> <rdf:type> <ex:Thing> }
Test: DELETE DATA { <ex:old> <rdf:type> <ex:Thing> }
Test: DELETE { ?s <ex:old> ?o } INSERT { ?s <ex:new> ?o } WHERE { ?s <ex:old> ?o }
Test: CLEAR GRAPH <ex:graph1>
```

---

## Execution Plan

### Phase 0: Database Interface + Data Inspection ✅ COMPLETE

Set up the Python database interface and inspect the existing sample data
to understand its shape, volume, and content.

- [x] Create `vitalgraph_sparql_sql/db.py` — sync psycopg connection helper
  - Sync connection with `dict_row` default, configurable via env vars
- [x] Create `test_scripts/jena_sidecar/inspect_data.py` — PostgreSQL data inspection
  - Discovered 46 spaces, profiled top 5 by quad count
- [x] Create `test_scripts/jena_sidecar/inspect_fuseki_data.py` — Fuseki data inspection
  - Confirmed Fuseki stores XSD datatypes on literals (xsd:integer, xsd:dateTime,
    xsd:boolean, xsd:decimal) while PostgreSQL stores all as plain strings
- [x] Document `test_scripts/jena_sidecar/data_profile.md`
  - Table naming: `{space_id}_term` / `{space_id}_rdf_quad` (single underscore)
  - Recommended test space: `space_multi_org_crud_test` (6,075 quads)
  - Recommended comparison dataset: `lead_test` (674,334 quads, loaded in both PG and Fuseki)
  - Datatype mismatch: Fuseki returns typed literals, SQL returns plain strings

**Key finding**: SPARQL-vs-SQL comparison normalizer must strip datatype annotations,
normalize numeric/datetime formatting, and sort result rows.

### Phase 1: SidecarClient + AST Mapper ✅ COMPLETE

- [x] Create `jena_sidecar_client.py` — sync HTTP client (`SidecarClient`, httpx-based)
- [x] Create `jena_types.py` — 30+ dataclasses (Op, Expr, Node, Update, CompileResult)
- [x] Create `jena_ast_mapper.py` — `map_compile_response()` JSON → Python type tree
  - Registry-based Op dispatcher (`_OP_MAPPERS`)
  - Handles `OpExtend` with both single and array `extensions` format
- [x] Create `test_jena_ast_mapper.py` — **33 unit tests** (canned JSON, no sidecar)
- [x] Create `test_sidecar_live.py` — **10/10 live integration tests**
  - SELECT, DISTINCT, OPTIONAL, UNION, GROUP BY, GRAPH, CONSTRUCT, ASK,
    INSERT DATA, DELETE/INSERT WHERE

### Phase 2a: SQL Generator v1 (single-pass) ✅ COMPLETE (unit tests only)

Initial implementation used a single-pass `singledispatch` walk producing
`sqlglot.exp.Expression` nodes directly. **44 unit tests pass** against canned
Op trees, but live orchestrator tests fail with "missing FROM-clause entry"
errors — the single-pass approach cannot correctly handle subquery boundaries.

**Root cause**: When OpProject/OpJoin/OpLeftJoin wrap child SQL in subqueries,
the inner table aliases (e.g. `t0.term_text`) become invisible to the outer
query. A single recursive walk cannot defer binding decisions until the full
tree shape is known.

- [x] Create `jena_sql_generator.py` with SQLContext, AliasGenerator
- [x] Implement Op → SQL for all Op types (BGP through Null)
- [x] Implement Expr → SQL, Update → SQL
- [x] Create `test_jena_sql_generator.py` — **44 unit tests pass**
- [x] Identified: live queries fail due to subquery scope leaking

### Phase 2b: SQL Generator v2 (three-pass collect/resolve/emit) ✅ COMPLETE

Rewrite based on academic literature (Chebotko et al., W3C StemMapping) and
compiler IR patterns. The key insight is to **separate what the query needs
from how it is rendered**, using three passes over the Op tree.

**References**:
- W3C "A Mapping of SPARQL Onto Conventional SQL" (StemMapping)
  - Defines `tableList`, `varmap`, `expression` as intermediate state
  - Uses `_DISJOINT_` sentinels for UNION branch tracking
  - Partial bindings for OPTIONAL variables with conditional resolution
- Chebotko et al. "Semantics Preserving SPARQL-to-SQL Translation"
  - Relational algebra–based semantics for SPARQL → SQL
  - Correct handling of nested OPTIONALs via LEFT OUTER JOIN subselects
- sqlglot DeepWiki — AST as universal IR, dialect-aware generation

**Why three passes**:
The single-pass approach (v1) fails because it must commit to SQL structure
(aliases, column names, subquery boundaries) before it knows how the parent
operators will compose the result. With three passes:
1. **Collect** defers all decisions — just records what tables, variables,
   and constraints each Op needs
2. **Resolve** sees the full picture — assigns concrete aliases, detects
   shared variables across Join/LeftJoin/Union children, determines which
   variables need subquery wrapping
3. **Emit** renders the resolved plan into sqlglot AST → SQL string

**Architecture**:

```
┌────────────────────────────────────────────────────────────────┐
│  Pass 1: COLLECT  (Op tree → RelationPlan tree)                │
│  Walk Op tree via singledispatch → produce RelationPlan IR     │
│  - tables: List[TableRef]  (quad + term table refs)            │
│  - var_slots: Dict[str, VarSlot]  (unresolved placeholders)   │
│  - constraints: List[str]  (WHERE clause fragments)            │
│  - modifiers: {distinct, limit, offset, order_by, group_by}   │
│  - children: List[RelationPlan]  (for Join/LeftJoin/Union)     │
│  No SQL is generated. No aliases are finalized.                │
└────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Pass 2: RESOLVE  (RelationPlan tree → ResolvedPlan tree)      │
│  Walk RelationPlan tree, assign concrete column names          │
│  - Detect shared variables across Join/LeftJoin children       │
│  - Assign final table aliases (AliasGenerator)                 │
│  - Resolve VarSlots → concrete uuid_col, text_col, type_col   │
│  - Generate ON clauses for joins (UUID-based equality)         │
│  - Handle partial bindings for OPTIONAL/UNION                  │
│  - Determine subquery boundaries                               │
└────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Pass 3: EMIT  (ResolvedPlan → sqlglot AST → SQL string)       │
│  Build sqlglot expressions from resolved plan                  │
│  - Compose SELECT, FROM, JOIN, WHERE, ORDER BY, LIMIT         │
│  - Apply PostgreSQL dialect rendering                          │
│  - Pretty-print for debugging                                  │
└────────────────────────────────────────────────────────────────┘
```

**Key IR dataclasses**:

```python
@dataclass
class VarSlot:
    """A SPARQL variable's binding — resolved in Pass 2."""
    name: str                              # SPARQL var name
    positions: List[Tuple[str, str]]       # [(table_ref_id, uuid_col_name), ...]
    resolved_uuid: Optional[str] = None    # e.g. "j0.s__uuid"
    resolved_text: Optional[str] = None    # e.g. "j0.s"
    resolved_type: Optional[str] = None    # e.g. "j0.s__type"
    partial: bool = False                  # True if from OPTIONAL/UNION

@dataclass
class TableRef:
    """A reference to a quad or term table, finalized in Pass 2."""
    ref_id: str           # Logical ID (assigned in collect)
    kind: str             # "quad" or "term"
    join_on: str = ""     # e.g. "q0.subject_uuid = t0.term_uuid"
    alias: str = ""       # Final SQL alias (assigned in resolve)

@dataclass
class RelationPlan:
    """IR node produced by Pass 1, resolved by Pass 2, emitted by Pass 3."""
    kind: str             # "bgp", "join", "left_join", "union", "filter", ...
    tables: List[TableRef]
    var_slots: Dict[str, VarSlot]
    constraints: List[str]
    children: List['RelationPlan']
    # Modifiers (set by Project, Slice, Order, etc.)
    select_vars: Optional[List[str]] = None
    distinct: bool = False
    limit: int = -1
    offset: int = 0
    order_by: Optional[List[Tuple[str, str]]] = None
    group_by: Optional[List[str]] = None
    having_exprs: Optional[List] = None
    filter_exprs: Optional[List] = None
    extend_exprs: Optional[Dict[str, Any]] = None
    graph_uri: Optional[str] = None
```

**Subquery boundary rules**:
- A BGP is always a flat query (no subquery needed)
- OpJoin: each child becomes a subquery; ON clause uses UUID equality
- OpLeftJoin: left + right subqueries; LEFT JOIN ON UUID equality
- OpUnion: each child subquery padded with NULL for missing vars; UNION ALL
- OpProject: modifies SELECT list of inner plan (no subquery)
- OpFilter: adds WHERE clause to inner plan (no subquery)
- OpSlice/OpDistinct/OpOrder: modifies plan modifiers (no subquery)

**Variable resolution rules**:
- First encounter of a var in a BGP → new VarSlot with position
- Second encounter in same BGP → add co-reference constraint
- Shared var across Join children → ON clause `left.var__uuid = right.var__uuid`
- Var in OPTIONAL right side only → partial binding (NULL when unmatched)
- Var in UNION → present in all branches (NULL-padded where missing)

- [x] Create `jena_sql_generator.py` v2 with RelationPlan, VarSlot, TableRef
- [x] Implement collect pass (Op → RelationPlan) via singledispatch
- [x] Implement resolve pass (RelationPlan → resolved aliases + columns)
- [x] Implement emit pass (resolved plan → sqlglot AST → SQL string)
- [x] Implement Expr → SQL (reuse from v1 with updated var resolution)
- [x] Implement Update → SQL (reuse from v1)
- [x] Update `test_jena_sql_generator.py` for new architecture
- [x] Verify all 44 unit tests pass
- [x] Verify live orchestrator tests pass (9/9)

### Phase 3: Orchestrator + End-to-End (live PostgreSQL) ✅ COMPLETE

- [x] Create `jena_sparql_orchestrator.py` wiring client → mapper → generator → execute
- [x] Test data already loaded in `lead_test` space (674,334 quads, 107,597 terms)
- [x] Create `test_orchestrator_live.py` — **9/9 live tests pass**
- [x] Create `test_sql_direct.py` — direct SQL testing with timing
- [x] All SPARQL patterns verified: SELECT, COUNT, DISTINCT, OPTIONAL, UNION,
  ORDER BY, LIMIT/OFFSET, FILTER, GRAPH scoping

### Phase 3b: SQL Performance Optimization ✅ COMPLETE

Diagnosed and fixed critical performance issues with SQL generation against
the `lead_test` dataset (674K quads, 107K terms).

**Problem diagnosed**: PostgreSQL query planner chose catastrophic nested loop
plans (est. cost 586M) when joining the full term table for ORDER BY, because
the composite PK `(term_uuid, dataset)` doesn't support efficient single-column
lookups and there are no secondary indexes on individual UUID columns.

**Three optimizations implemented**:

1. **Constants as scalar subqueries** — URIs and literals in triple patterns
   are resolved via `WHERE q.predicate_uuid = (SELECT term_uuid FROM term
   WHERE term_text = '...' LIMIT 1)` instead of JOINing the term table for
   every constant. Eliminates unnecessary JOINs for constant nodes.

2. **Inner/outer query split** (`_emit_bgp_optimized`) — All modifiers
   (LIMIT, DISTINCT, ORDER BY, FILTER) operate on the quad table first in an
   inner subquery using only UUID columns. Term table JOINs for text resolution
   happen in the outer query on just the small result set.
   - `SELECT ?s ?p ?o LIMIT 5`: inner gets 5 quad rows, outer resolves 3 terms on 5 rows
   - `SELECT DISTINCT ?p LIMIT 20`: inner gets 20 distinct UUIDs, outer resolves text
   - `COUNT(*)`: operates directly on quad table with zero term JOINs

3. **Pre-filtered term JOINs** — When ORDER BY or FILTER requires a term JOIN
   in the inner query, the term table is pre-filtered to only UUIDs actually
   present in the quad column: `JOIN (SELECT term_uuid, term_text FROM term
   WHERE term_uuid IN (SELECT DISTINCT col FROM quad)) AS t1 ON ...`.
   This gives PostgreSQL accurate cardinality estimates (e.g., 36 predicates
   instead of 107K terms) and forces hash join instead of nested loop.

**Performance results** (lead_test, 674K quads):

| Query | Before | After |
|-------|--------|-------|
| Simple LIMIT 5 | ~40ms | 38ms |
| COUNT(*) | ~120ms | 118ms |
| Entities by type LIMIT 10 | ~30ms | 10ms |
| OPTIONAL LIMIT 10 | ~760ms | 24ms |
| DISTINCT ?p LIMIT 20 | ~1160ms | 39ms |
| **ORDER BY ?p LIMIT 5 OFFSET 10** | **>60s (hung)** | **114ms** |
| GRAPH scoped LIMIT 5 | ~6ms | 6ms |
| UNION LIMIT 10 | ~11ms | 9ms |
| FILTER CONTAINS LIMIT 10 | ~330ms | 323ms |

**Recommended indexes** (not yet created, would further improve performance):
```sql
CREATE INDEX idx_lead_test_quad_subject ON lead_test_rdf_quad (subject_uuid);
CREATE INDEX idx_lead_test_quad_predicate ON lead_test_rdf_quad (predicate_uuid);
CREATE INDEX idx_lead_test_quad_object ON lead_test_rdf_quad (object_uuid);
CREATE INDEX idx_lead_test_quad_context ON lead_test_rdf_quad (context_uuid);
CREATE INDEX idx_lead_test_term_text ON lead_test_term (term_text);
```

### Phase 3c: v1 → v2 Expression/Function Parity

v2 covers all Op types and most expressions but is missing a few functions
present in v1. These should be added for full SPARQL coverage.

**Missing expression functions**:
- [ ] `IN` — `(x IN (a, b, c))`
- [ ] `NOT IN` — `(x NOT IN (a, b, c))`
- [ ] `ABS`, `CEIL`, `FLOOR`, `ROUND` — math functions
- [ ] `REPLACE` — `REGEXP_REPLACE(a, pat, rep)`

**Missing aggregates**:
- [ ] `SAMPLE` — approximate as `MIN()` (same as v1)

**Degraded functions**:
- [ ] `LANG` — v1 accesses the actual `term.lang` column via
  `ctx.bindings[var].term_alias + ".lang"`, v2 just returns `''`.
  Restore proper `lang` column access.

**Already equivalent / fully covered**:
All Op types (BGP, Join, LeftJoin, Union, Filter, Project, Slice, Distinct,
Reduced, Order, Group, Extend, Table, Minus, Graph, Sequence, Null), plus:
`STR`, `BOUND`, `isURI`/`isIRI`, `isLiteral`, `isBlank`, `CONTAINS`,
`STRSTARTS`, `STRENDS`, `REGEX`, `IF`, `CONCAT`, `STRLEN`, `UCASE`, `LCASE`,
`SUBSTR`, `COALESCE`, `DATATYPE`, `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`,
`GROUP_CONCAT`, all binary operators, and `UpdateModify` (both versions are
incomplete stubs for the WHERE-driven case).

**v2 improvements over v1** (no action needed):
- Performance: inner/outer split, scalar subqueries for constants, pre-filtered term JOINs
- Correct subquery scoping: 3-pass architecture avoids "missing FROM-clause" errors
- `_emit_bgp_optimized`: LIMIT/DISTINCT/ORDER BY operate on quad table before term JOINs

### Phase 3d: Modular Refactoring ✅ COMPLETE

Refactored the monolithic `jena_sql_generator.py` into focused modules:

- [x] `jena_sql_ir.py` — IR dataclasses (TableRef, VarSlot, RelationPlan, SQLContext, etc.)
- [x] `jena_sql_helpers.py` — Shared utilities (_esc, _node_text, _node_type, _vars_in_expr)
- [x] `jena_sql_collect.py` — Pass 1: Op tree → RelationPlan
- [x] `jena_sql_resolve.py` — Pass 2: assign aliases, column names
- [x] `jena_sql_emit.py` — Pass 3: RelationPlan → SQL string
- [x] `jena_sql_expressions.py` — Expr/Function/Agg → SQL translation
- [x] `jena_sql_updates.py` — Update operations → SQL
- [x] `jena_sql_generator.py` — Public API entry point (re-exports)

### Phase 4a: Property Path Support ✅ COMPLETE

Full SPARQL 1.1 property path support via recursive CTEs.

- [x] Path types in `jena_types.py`: PathLink, PathAlt, PathSeq, PathInverse,
  PathZeroOrMore, PathOneOrMore, PathZeroOrOne, PathNegatedPropertySet, OpPath
- [x] Path string parser in `jena_ast_mapper.py` (handles `/`, `|`, `^`, `*`, `+`, `?`, `!`)
- [x] `_collect_path` in `jena_sql_collect.py` — OpPath → RelationPlan with path metadata
- [x] `_emit_path` in `jena_sql_emit.py` — path → WITH RECURSIVE CTE SQL
- [x] 29 unit tests in `test_jena_property_paths.py`
- [x] 6 live path tests (link, alternative, sequence, one-or-more, zero-or-one, inverse)

### Phase 4b: Subquery Support ✅ COMPLETE

- [x] Jena represents subqueries as nested existing operators (no dedicated OpSubQuery)
- [x] Fixed `_emit_bgp_optimized` to include `__uuid` and `__type` columns in outer SELECT
  so JOINs between outer and inner queries can reference UUID/type columns
- [x] Fixed aggregate resolution: aggregates computed in inner subquery using UUID columns
  (not text columns which require term JOINs), referenced by alias in outer query
- [x] Sanitized Jena aggregate variable names (e.g., `.0` → `_0`) for valid SQL identifiers
- [x] 2 live subquery tests (inner LIMIT join, inner COUNT/GROUP BY)

### Phase 4c: ASK / CONSTRUCT / DESCRIBE ✅ COMPLETE

- [x] `construct_template` and `describe_nodes` added to `ParsedQueryMeta`
- [x] Mapped in `jena_ast_mapper.py` from sidecar JSON
- [x] **ASK**: `generate_sql` wraps query as `SELECT EXISTS(...) AS result`;
  orchestrator returns `boolean` field
- [x] **CONSTRUCT**: SQL is same as SELECT WHERE clause; orchestrator applies
  template to result rows via `_apply_construct_template`, returns `triples` list
- [x] **DESCRIBE**: Two variants:
  - Direct URI (`DESCRIBE <uri>`): generates SQL to find all triples where URI
    appears as subject or object (handles OpNull algebra)
  - With WHERE clause (`DESCRIBE ?x WHERE { ... }`): wraps inner SQL in
    `WHERE s.term_text IN (SELECT * FROM (...))` to find all triples about matched resources
  - Orchestrator returns `triples` list with subject/predicate/object/type/lang/datatype
- [x] `QueryResult` extended with `query_type`, `boolean`, `triples` fields
- [x] 2 live tests (ASK exists, CONSTRUCT simple)

**Test totals**: 44 unit + 29 path + 19 live = all passing

### Phase 4d: Index Recommendation Module ✅ CREATED

- [x] `jena_sql_indexes.py` — `get_recommended_indexes()`, `check_missing_indexes()`,
  `ensure_indexes()` (with CONCURRENTLY support)
- [x] Created `lead_exp` experiment tables (copy of `lead_test` data) for safe index testing
- [x] Ran `ensure_indexes` on `lead_exp` — 8 base indexes created
- [x] Created `lead_dataset_exp` experiment tables (copy of `space_lead_dataset_test`)
- [x] Applied full 16-index set to both exp table sets
- [ ] Run `ensure_indexes` on live `lead_test` space (deferred)

### Phase 4e: Fuseki vs SQL Comparison ✅ COMPLETE

- [x] `test_fuseki_vs_sql_comparison.py` — 18 queries (13 base + 5 direct property)
- [x] Covers: SELECT, COUNT, DISTINCT, OPTIONAL, GROUP BY, FILTER CONTAINS,
  UNION, ORDER BY, subquery, multi-join (5 TPs), ASK, CONSTRUCT,
  direct property paths (entity→frame→slot), MQL-style queries
- [x] Per-query space/graph/Fuseki overrides for multi-space testing
- [x] Case-insensitive key comparison (PostgreSQL lowercases column aliases)
- [x] Reports timing, row counts, value comparison, data sync differences
- [x] **Bug fix**: scalar subqueries using `LIMIT 1` without `AND term_type = 'U'`
  returned wrong UUID when duplicate term_text values existed (same text stored as
  both URI and Literal). Adding indexes changed row order, exposing the bug.
  Fixed in `jena_sql_collect.py`, `jena_sql_emit.py`, `jena_sql_updates.py`.
- [x] **Bug fix**: GROUP BY + inner term columns — when a grouped variable also had
  inner term JOINs (for FILTER), `term_text`/`term_type` weren't in GROUP BY clause.
  Fixed in `jena_sql_emit.py` `_emit_bgp_optimized`.

**Comparison results** (lead_exp with all optimizations vs Fuseki, 674K quads):

| Query | Fuseki | SQL | Winner |
|---|---|---|---|
| COUNT all triples | 422ms | 60ms | **SQL 7.0x** |
| COUNT KGEntity | 8ms | 6ms | **SQL 1.4x** |
| GROUP BY + COUNT | 91ms | 17ms | **SQL 5.5x** |
| ASK | 11ms | 4ms | **SQL 2.6x** |
| CONSTRUCT | 8ms | 5ms | **SQL 1.6x** |
| Subquery | 9ms | 9ms | ~tie |
| UNION LIMIT 10 | 11ms | 10ms | ~tie |
| Simple scan LIMIT 5 | 27ms | 51ms | Fuseki 1.9x |
| OPTIONAL LIMIT 10 | 10ms | 15ms | Fuseki 1.5x |
| Multi-join (5 TPs) | 8ms | 16ms | Fuseki 1.9x |
| DISTINCT LIMIT 20 | 12ms | 61ms | Fuseki 5.1x |
| FILTER CONTAINS | 9ms | 86ms | Fuseki 9.4x |
| ORDER BY + OFFSET | 9ms | 145ms | Fuseki 15.4x |

**Direct property results** (lead_dataset_exp, 284K quads incl. 19K materialized):

| Query | Fuseki | SQL | Winner |
|---|---|---|---|
| Count hasEntityFrame | 8ms | 12ms | Fuseki 1.4x |
| Entity→Frame→Slot path | 18ms | 32ms | Fuseki 1.8x |
| Entity frames + type filter | 8ms | 7ms | **SQL 1.2x** |
| MQL (entity→frame→frame→slot+value) | 76ms | 148ms | Fuseki 1.9x |
| Count by predicate type | 44ms | 32ms | **SQL 1.4x** |

**SQL wins 7/13 base queries, 2/5 direct queries.** All values MATCH where compared.

### Phase 4f: Expression Gaps ✅ DONE

- [x] IN, NOT IN, ABS, CEIL, FLOOR, ROUND, REPLACE, LANG — all implemented in `jena_sql_expressions.py`

### Phase 4l: SPARQL 1.1 Functions (Batch) ✅ COMPLETE

Implemented all remaining SPARQL 1.1 §17.4 functions in a single batch.

- [x] `DATATYPE()` — CASE on `term_type` + `lang` columns; returns actual XSD datatype URI
  (langString for lang-tagged, xsd:string for plain literals, empty for URIs)
- [x] `LANG()` — full support via `_resolve_lang_ref()` helper across RelationPlan and SQLContext paths
- [x] `isNumeric` — regex match `~ '^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$'`
- [x] `sameTerm` — strict UUID equality (stricter than `=` value comparison)
- [x] `UUID` — `'urn:uuid:' || gen_random_uuid()::text`
- [x] `STRUUID` — `gen_random_uuid()::text`
- [x] `MD5` — `md5()` (PostgreSQL built-in)
- [x] `SHA1 / SHA256 / SHA384 / SHA512` — `encode(digest(..., 'shaX'), 'hex')` (requires pgcrypto extension; available on AWS RDS)
- [x] `ENCODE_FOR_URI` — nested `REPLACE()` chain for RFC 3986 percent-encoding
- [x] `STRLANG` — returns string value (lang tag not persisted in SELECT projection)
- [x] `STRDT` — returns string value (datatype not persisted in SELECT projection)
- [x] `IRI / URI constructor` — pass-through (returns string as-is)
- [x] `BNODE()` — `'_:b' || gen_random_uuid()::text` (no-arg) or `'_:b' || md5(arg)` (deterministic)

**AST mapper fixes**:
- [x] Added handlers for `E_StrUUID`, `E_UUID`, `BNode0` Jena expression types → `ExprFunction`
- [x] Added `_resolve_lang_ref()`, `_resolve_uuid_ref()` helpers in `jena_sql_expressions.py`
- [x] Added `lang` column to inner term JOINs in `jena_sql_emit.py`
- [x] Updated `_resolve_extend_for_outer()` with `outer_lang_refs`, `outer_type_refs`, `outer_uuid_refs`
- [x] Updated `_func_with_resolved_args()` with all new function handlers

**Prerequisite**: SHA functions require `CREATE EXTENSION IF NOT EXISTS pgcrypto` (one-time per database).

**Files modified**: `jena_ast_mapper.py`, `jena_sql_expressions.py`, `jena_sql_emit.py`

---

### Phase 4m: SPARQL Update & Data Modification ✅ COMPLETE

All SPARQL 1.1 Update operations (§3) implemented with full SQL translation. Uses dedicated
experiment tables to avoid modifying read-only test data.

#### Test Tables

| Table | Rows | Source | Purpose |
|---|---|---|---|
| `crud_test_exp_rdf_quad` | 674,334 | Copied from `lead_exp_rdf_quad` | Mutable quad store for update tests |
| `crud_test_exp_term` | 107,597 | Copied from `lead_exp_term` | Mutable term store for update tests |

These tables are disposable copies — they can be dropped and re-created from `lead_exp_*`
at any time to reset state. All SPARQL update test cases target `crud_test_exp` as `space_id`.

#### Implemented Operations

**4m-1. INSERT DATA** ✅
- [x] `term_uuid` generated via `gen_random_uuid()` (column has no default)
- [x] `lang` column populated for language-tagged literals (`LiteralNode.lang`)
- [x] Type-aware term lookups (`term_type` filter in cross-join)
- [x] Term deduplication within batch (`seen_terms` set)
- [x] `INSERT ... WHERE NOT EXISTS` pattern for idempotent term upserts
- Tested: graph-scoped insert, lang-tagged literals, multiple quads

**4m-2. DELETE DATA** ✅
- [x] Type-aware UUID lookups for s/p/o (uses `_term_uuid_subquery` with LIMIT 1)
- [x] Graph-scoped deletes (context_uuid match)
- Tested: single-quad delete, graph-scoped delete

**4m-3. DELETE/INSERT WHERE (UpdateModify)** ✅
- [x] WHERE pattern → SQL via full 3-pass pipeline (collect/resolve/emit)
- [x] Materialized temp table `_upd_bindings` with `__uuid` columns from WHERE output
- [x] DELETE via `DELETE ... USING _upd_bindings` (correlated row-level matching)
- [x] INSERT via `INSERT ... SELECT FROM _upd_bindings` (UUID column references)
- [x] New constant terms upserted before INSERT phase
- [x] `WITH <graph>` clause support (default graph for operation)
- [x] Element → Op conversion for WHERE pattern (`map_element_to_op`)
- [x] Handles `ElementGroup`, `ElementPathBlock`, `ElementNamedGraph`, `ElementFilter`,
  `ElementOptional`, `ElementUnion`
- Tested: predicate rename (DELETE old_name + INSERT new_name), verified exact row matching

**4m-4. DELETE WHERE (shorthand)** ✅
- Sidecar fix applied: `UpdateSerializer.java` now serializes `UpdateDeleteWhere.getQuads()`
- Python converts to equivalent `UpdateModify` with identical delete/where patterns
- Tested: `DELETE WHERE { GRAPH <g> { <a> ?p ?o } }` — 3→1 rows, correct subject preserved

**4m-5. INSERT WHERE (template)** ✅
- Handled via `UpdateModify` with empty `delete_quads` — DELETE phase skipped automatically
- Tested: `INSERT { ?s <ex:label> ?n } WHERE { ?s <ex:name> ?n }` — derived label from name

**4m-6. CLEAR GRAPH** ✅
- [x] `CLEAR GRAPH <uri>` → `DELETE FROM quad WHERE context_uuid = ...`
- [x] `CLEAR DEFAULT` → delete quads with default graph context
- [x] `CLEAR NAMED` → delete quads with non-default context
- [x] `CLEAR ALL` → `DELETE FROM quad` (unconditional)
- Tested: CLEAR GRAPH verified via row count

**4m-7. DROP GRAPH** ✅
- [x] Implemented as CLEAR (no separate graph catalog in current schema)
- Tested: DROP GRAPH verified via row count = 0

**4m-8. CREATE GRAPH** ✅
- [x] Ensures graph URI term exists via `_term_upsert`
- Tested: CREATE GRAPH creates term row

**4m-9. COPY** ✅
- [x] Ensures dest graph term exists, clears dest, copies source quads with dest context
- Tested: COPY 2 rows from src to dst, verified count

**4m-10. MOVE** ✅
- [x] COPY source TO dest, then DROP source
- Tested: MOVE verified src=0, moved=3

**4m-11. ADD** ✅
- [x] Additive copy — no clear of dest
- Tested: ADD 3 rows to existing 2 → 5 total

#### AST Mapper Fixes Applied

- [x] Fixed `UpdateClear`/`UpdateDrop`: parse Jena's `target` dict `{"scope": "GRAPH", "graph": uri}`
- [x] Fixed `UpdateCopy`/`UpdateMove`/`UpdateAdd`: parse `source`/`dest` dicts
- [x] Added `map_element_to_op()` — converts Jena syntax Elements to algebra Ops
- [x] Added `UpdateDeleteWhere` type to `jena_types.py` and mapper
- [x] Fixed `OpGraph` constructor (`graph_node` not `graph`)
- [x] WHERE pattern: tries `map_element_to_op` for Element types, `map_op` for Op types

#### Files Modified

| File | Changes |
|---|---|
| `jena_sql_updates.py` | Complete rewrite: 460 lines, all 11 operations + helpers |
| `jena_ast_mapper.py` | Dict format parsing, Element→Op, UpdateDeleteWhere handler |
| `jena_types.py` | Added `UpdateDeleteWhere` dataclass |

#### Known Limitations

- ~~`DELETE WHERE` shorthand~~ — fixed: sidecar now serializes quads
- `USING <graph>` / `USING NAMED <graph>` in UpdateModify: not yet implemented
- `SILENT` flag: parsed but not used (errors propagate normally)
- `UpdateLoad`: type exists, no SQL translation (requires app-level fetch+parse)
- Orphan term cleanup after DELETE: not implemented (terms persist)

---

### Immediate Next Steps — High-Priority SPARQL Gaps

#### 4g. HAVING Clause Support ✅ COMPLETE

GROUP BY queries with HAVING filters are now translated. Jena emits `OpFilter`
wrapping `OpGroup` with aggregate expressions in the filter. The collect pass
detects filter expressions referencing aggregate variables and routes them to
`having_exprs` instead of `filter_exprs`.

- [x] Detect HAVING pattern in collect pass (filter on aggregate result)
- [x] Added `having_exprs` field to `RelationPlan`
- [x] Emit `HAVING` clause in `_emit_bgp_optimized` after GROUP BY
- [x] Added `_having_expr_to_sql` helper for aggregate variable substitution
- [x] HAVING emission in both BGP-optimized and non-BGP sqlglot paths
- [x] Verified: `SELECT ?type (COUNT(*) AS ?c) WHERE { ... } GROUP BY ?type HAVING (COUNT(*) > 5)`

#### 4h. GRAPH Variable Binding ✅ COMPLETE

Both `GRAPH <uri> { ... }` (constant URI) and `GRAPH ?g { ... }` (variable) are
now supported. Variable graph nodes bind `context_uuid` to a VarSlot.

- [x] `_collect_graph` handles `VarNode` by calling `_bind_graph_var`
- [x] Recursive `_bind_graph_var` binds `context_uuid` to graph variable across
  all quad tables in the plan (handles joins, unions, etc.)
- [x] VarSlot created with term JOIN for text resolution
- [x] Co-reference handling when graph variable appears in multiple quad tables
- [x] Verified: `SELECT ?g ?s WHERE { GRAPH ?g { ?s a :Entity } }`

#### 4i. Typed Literal Comparison (xsd:integer, xsd:dateTime) ✅ COMPLETE

Comparisons involving typed literals now CAST the variable side to the appropriate
SQL type. Covers all XSD numeric types and date/time types.

- [x] `_apply_typed_casts()` detects typed literals in comparison operators
- [x] CAST to NUMERIC for xsd:integer, decimal, double, float, byte, short, long,
  and all unsigned/nonNegative/positive/negative integer variants
- [x] CAST to TIMESTAMP for xsd:dateTime, CAST to DATE for xsd:date
- [x] Applied in both outer (`_func_to_sql`) and inner (`_expr_to_sql_str_inner`) paths
- [x] Verified: `FILTER(?val > 100)` → `CAST(t1.term_text AS NUMERIC) > 100`
- [x] Verified: `FILTER(?date > "2024-01-01"^^xsd:dateTime)` → `CAST(... AS TIMESTAMP) > ...`

#### 4j. Date/Time Functions ✅ COMPLETE

All SPARQL 1.1 §17.4.5 date/time functions implemented:

| SPARQL | PostgreSQL |
|---|---|
| `YEAR(?d)` | `EXTRACT(YEAR FROM CAST(... AS TIMESTAMP))` |
| `MONTH(?d)` | `EXTRACT(MONTH FROM CAST(... AS TIMESTAMP))` |
| `DAY(?d)` | `EXTRACT(DAY FROM CAST(... AS TIMESTAMP))` |
| `HOURS(?d)` | `EXTRACT(HOUR FROM CAST(... AS TIMESTAMP))` |
| `MINUTES(?d)` | `EXTRACT(MINUTE FROM CAST(... AS TIMESTAMP))` |
| `SECONDS(?d)` | `EXTRACT(SECOND FROM CAST(... AS TIMESTAMP))` |
| `NOW()` | `CAST(NOW() AS TEXT)` |
| `TZ(?d)` | `REGEXP_REPLACE(...)` to extract timezone string |

- [x] Function handlers in `_func_to_sql` and `_func_with_resolved_args`
- [x] Fixed AST mapper bug: `ExprFunction1` uses `"arg"` (singular) not `"args"`
- [x] Added `E_Now` and `ExprFunction0` handling in AST mapper
- [x] Fixed extend expression resolution in optimized BGP path via
  `_resolve_extend_for_outer()` — extend-referenced variables now get term JOINs
  in the inner query and resolve correctly in the outer query
- [x] Verified against live data: all date parts extract correctly

#### 4k. FILTER EXISTS / NOT EXISTS ✅ COMPLETE

SPARQL `FILTER EXISTS { pattern }` and `FILTER NOT EXISTS { pattern }` now
translate to correlated SQL `EXISTS`/`NOT EXISTS` subqueries.

- [x] Added `ExprExists` dataclass in `jena_types.py` (graph_pattern + negated flag)
- [x] AST mapper handles `ExprFunctionOp` with name `exists`/`notexists`
- [x] `_emit_exists_subquery()` runs inner pattern through full collect/resolve/emit
- [x] Uses `AliasGenerator(alias_prefix="ex_")` to avoid table alias conflicts
- [x] Replaces `_const` CTE references with direct term table lookups in inner SQL
- [x] Correlates shared variables via UUID equality (`outer.uuid = _ex.var__uuid`)
- [x] EXISTS handling in all three filter paths: optimized BGP, aggregate BGP, non-BGP
- [x] Verified: EXISTS + NOT EXISTS counts sum to total (3062 + 94047 = 97109)

---

### Phase 5: Performance Optimizations ✅ IMPLEMENTED

#### 5a. CTE Constants Precomputation ✅ DONE (code change)

Constants are registered during Pass 1 (collect) on the shared `AliasGenerator`, then
batched into a single `WITH _const AS (...)` CTE in `generate_sql()`. No regex on SQL.

- `jena_sql_ir.py` — added `constants` dict and `register_constant()` to `AliasGenerator`
- `jena_sql_helpers.py` — added `_const_subquery()`, `build_constants_cte()`, `CTE_CONST_ALIAS`
- `jena_sql_collect.py` — URINode/LiteralNode/graph_uri use `_const_subquery()` instead of inline scalar subqueries
- `jena_sql_generator.py` — `generate_sql()` prepends CTE via `build_constants_cte()`
- Literals with lang tags bypass CTE (need direct lang filter)

#### 5b. Trigram GIN Index ✅ APPLIED on exp tables

```sql
CREATE INDEX idx_{space}_term_text_trgm ON {space}_term USING GIN (term_text gin_trgm_ops);
```

#### 5c. Context-Leading Composite Indexes ✅ APPLIED on exp tables

```sql
CREATE INDEX idx_{space}_quad_cp  ON {space}_rdf_quad (context_uuid, predicate_uuid);
CREATE INDEX idx_{space}_quad_cpo ON {space}_rdf_quad (context_uuid, predicate_uuid, object_uuid);
CREATE INDEX idx_{space}_quad_cs  ON {space}_rdf_quad (context_uuid, subject_uuid);
```

#### 5d. Partial Index on URI Terms ✅ APPLIED on exp tables

```sql
CREATE INDEX idx_{space}_term_text_uri ON {space}_term (term_text) WHERE term_type = 'U';
```

#### 5e. CLUSTER Quad Table by Predicate ✅ APPLIED on exp tables

```sql
CLUSTER {space}_rdf_quad USING idx_{space}_quad_predicate;
ANALYZE {space}_rdf_quad;
```

#### 5f. Hash Indexes for UUID Equality ⚠️ NOT RECOMMENDED

```sql
CREATE INDEX idx_{space}_quad_pred_hash ON {space}_rdf_quad USING HASH (predicate_uuid);
```

**Performance issue**: Hash index builds on UUID columns are extremely slow at scale.
On the `wordnet_exp_rdf_quad` table (7M rows), the hash index took **~27 minutes** to build,
while all 9 btree indexes on the same table rebuilt in ~3 minutes total. This is because
hash indexes lack a sort-based bulk build path and suffer from repeated bucket splitting
with uniformly-distributed UUIDs. The existing btree index on `predicate_uuid` already
handles equality lookups efficiently. The hash index was dropped from `wordnet_exp_rdf_quad`
and is not recommended for future spaces.

#### 5g. Connection Pooling ✅ DONE (code change)

- `db.py` — replaced per-query `psycopg.connect()` with lazy-init `psycopg_pool.ConnectionPool`
  (min_size=2, max_size=8). Module-level pool shared across all queries.

#### 5h. ORDER BY Pushdown (DEFERRED)

Requires deeper changes to the emit pass. Moderate impact on one query pattern.

#### 5i. Join Reordering via `join_collapse_limit` (PROPOSED)

EXPLAIN ANALYZE of the MQL query (6 quad self-joins) shows PostgreSQL's planner chose
a suboptimal join order: the boolean value filter (14K→1.6K) runs before the slot type
filter (1.6K→99). Planning time was 22.7ms (nearly half the 49.7ms execution time).

Proposed approach: emit `SET LOCAL join_collapse_limit = 1` before multi-join queries
and reorder the FROM clauses using selectivity heuristics:
- Constant-heavy patterns first (more WHERE filters = more selective)
- Object-position constants before subject-chained patterns
- Literal value filters early (boolean/string equality is very selective)

---

### Phase 6: Direct Property Materialization ✅ COMPLETE

Direct properties (`vg-direct:hasEntityFrame`, `hasFrame`, `hasSlot`) bypass edge objects
for fast hierarchical queries. In production, these exist only in Fuseki (generated by
`edge_materialization.py`). For SQL pipeline testing, we derived and inserted them into
the experiment tables.

- [x] Analyzed `edge_materialization.py` — identified 3 edge types and their mapping to
  `vg-direct:*` predicates. Source/dest extracted from `hasEdgeSource`/`hasEdgeDestination`.
- [x] `analyze_direct_properties.py` — script queries exp tables, derives direct properties
  from edge objects, outputs Turtle file
- [x] Added `materialized` (boolean, default false) and `materialized_at` (timestamptz)
  columns to both exp quad tables
- [x] Inserted 19,225 materialized quads into `lead_dataset_exp` (1,200 hasEntityFrame,
  3,991 hasFrame, 14,034 hasSlot) — all with `materialized=true`
- [x] Also generated 48,024 direct property triples for `lead_exp` (output to file)
- [x] 3 `vg-direct:*` predicate terms inserted into term tables (UUID5 from URI)
- [x] 5 direct property comparison queries added to `test_fuseki_vs_sql_comparison.py`
- [x] All 18/18 tests passing, all value comparisons MATCH

**Experiment table summary**:

| Table Set | Term Rows | Quad Rows | Materialized | Graph |
|---|---|---|---|---|
| `lead_exp` | ~44K | 667,768 | 0 (file only) | `urn:lead_test` |
| `lead_dataset_exp` | 42,684 | 283,844 | 19,225 | `urn:lead_entity_graph_dataset` |

**Key findings from MQL query EXPLAIN ANALYZE** (entity→frame→frame→slot+value, 99 rows):
- 6 quad self-joins, all using indexes (pkey index-only scans)
- 68K buffer hits (all shared, no I/O)
- Planning: 22.7ms, Execution: 49.7ms
- Bottleneck: q5 (hasBooleanSlotValue filter) scans 14K rows → 1.6K (30ms)
- Suboptimal join order: if q4 (MQLv2 slot type, very selective) ran before q5,
  the 14K→99 reduction would happen earlier

---

## SPARQL Feature Coverage Matrix

Status legend: ✅ Implemented, ⚠️ Partial, ❌ Not implemented, 🚫 Not planned

### SPARQL 1.1 Query Language (W3C Rec)

#### Query Forms

| Feature | Status | Notes |
|---|---|---|
| SELECT | ✅ | Full projection, aliased expressions |
| SELECT DISTINCT | ✅ | |
| SELECT REDUCED | ✅ | Treated as DISTINCT |
| ASK | ✅ | Wrapped as `SELECT EXISTS(...)` |
| CONSTRUCT | ✅ | Returns subject/predicate/object triples |
| DESCRIBE | ✅ | With and without WHERE clause; finds all triples about matched URIs |

#### Graph Patterns

| Feature | Status | Notes |
|---|---|---|
| Basic Graph Pattern (BGP) | ✅ | Multi-triple patterns with co-reference |
| OPTIONAL (LEFT JOIN) | ✅ | With optional FILTER conditions |
| UNION | ✅ | Nested unions supported |
| MINUS | ✅ | Via `NOT EXISTS` / `EXCEPT` SQL |
| GRAPH (named graph) | ✅ | URI-based `context_uuid` filtering |
| GRAPH (variable) | ✅ | Binds `?g` to `context_uuid`; recursive across joins/unions |
| VALUES (inline data) | ✅ | Via `OpTable` → SQL VALUES clause |
| BIND (expr AS ?var) | ✅ | Via `OpExtend` |
| SERVICE (federated) | 🚫 | Jena sidecar parses but SQL gen does not support remote endpoints |
| Subqueries | ✅ | Nested SELECT within WHERE |

#### Solution Modifiers

| Feature | Status | Notes |
|---|---|---|
| ORDER BY | ✅ | ASC/DESC on variables |
| ORDER BY expression | ✅ | Arbitrary expressions (STRLEN, UCASE, arithmetic, etc.) via `_expr_to_sql_str` |
| LIMIT | ✅ | |
| OFFSET | ✅ | |
| GROUP BY | ✅ | Single and multi-variable |
| HAVING | ✅ | Detects aggregate-referencing filters; emits SQL HAVING clause |
| DISTINCT within aggregates | ✅ | e.g. `COUNT(DISTINCT ?x)` |

#### Aggregates

| Feature | Status | Notes |
|---|---|---|
| COUNT | ✅ | With/without DISTINCT, `COUNT(*)` |
| SUM | ✅ | Cast to NUMERIC |
| AVG | ✅ | Cast to NUMERIC |
| MIN | ✅ | |
| MAX | ✅ | |
| SAMPLE | ✅ | Emulated as `MIN()` |
| GROUP_CONCAT | ✅ | Via `STRING_AGG()`, custom separator |

#### Property Paths (SPARQL 1.1)

| Feature | Status | Notes |
|---|---|---|
| Link (`<uri>`) | ✅ | Simple predicate |
| Inverse (`^<uri>`) | ✅ | Swaps start/end |
| Sequence (`<a>/<b>`) | ✅ | JOIN on intermediate node |
| Alternative (`<a>\|<b>`) | ✅ | UNION |
| One or more (`<uri>+`) | ✅ | `WITH RECURSIVE` CTE, depth limit |
| Zero or more (`<uri>*`) | ✅ | `WITH RECURSIVE` CTE + identity base |
| Zero or one (`<uri>?`) | ✅ | Identity UNION one step |
| Negated property set (`!<uri>`) | ✅ | Predicate exclusion filter |
| Nested combinations | ✅ | Recursive path-to-SQL composition |

#### FILTER Functions & Operators

| Feature | Status | Notes |
|---|---|---|
| Comparison (`=`, `!=`, `<`, `<=`, `>`, `>=`) | ✅ | |
| Logical (`&&`, `\|\|`, `!`) | ✅ | `AND`, `OR`, `NOT` |
| Arithmetic (`+`, `-`, `*`, `/`) | ✅ | |
| BOUND | ✅ | `IS NOT NULL` |
| IF | ✅ | `CASE WHEN ... THEN ... ELSE ... END` |
| COALESCE | ✅ | |
| IN | ✅ | |
| NOT IN | ✅ | |
| isIRI / isURI | ✅ | Checks `term_type = 'U'` |
| isLiteral | ✅ | Checks `term_type = 'L'` |
| isBlank | ✅ | Checks `term_type = 'B'` |
| isNumeric | ✅ | Regex match on term_text for numeric pattern |
| STR | ✅ | Identity (term_text is already string) |
| LANG | ✅ | Returns `COALESCE(lang, '')` |
| DATATYPE | ✅ | CASE on `term_type` + `lang` columns; returns XSD URI |
| IRI / URI constructor | ✅ | Pass-through (returns string as-is) |
| BNODE constructor | ✅ | `'_:b' || gen_random_uuid()` or `'_:b' || md5(arg)` |
| CONTAINS | ✅ | `POSITION(pat IN str) > 0` |
| STRSTARTS | ✅ | `LIKE pat \|\| '%'` |
| STRENDS | ✅ | `LIKE '%' \|\| pat` |
| STRLEN | ✅ | `LENGTH()` |
| SUBSTR | ✅ | `SUBSTRING()` |
| UCASE | ✅ | `UPPER()` |
| LCASE | ✅ | `LOWER()` |
| CONCAT | ✅ | `\|\|` operator |
| REPLACE | ✅ | `REGEXP_REPLACE()`, with flag support |
| REGEX | ✅ | `~` / `~*` (case-insensitive via 'i' flag) |
| ABS | ✅ | |
| CEIL | ✅ | |
| FLOOR | ✅ | |
| ROUND | ✅ | |
| ENCODE_FOR_URI | ✅ | Nested `REPLACE()` chain for RFC 3986 percent-encoding |
| YEAR / MONTH / DAY / HOURS / MINUTES / SECONDS | ✅ | `EXTRACT(field FROM CAST(... AS TIMESTAMP))` |
| TIMEZONE / TZ | ✅ | Regex extraction of timezone string |
| NOW | ✅ | `CAST(NOW() AS TEXT)` |
| UUID / STRUUID | ✅ | `'urn:uuid:' || gen_random_uuid()` / `gen_random_uuid()::text` |
| MD5 / SHA1 / SHA256 / SHA384 / SHA512 | ✅ | `md5()` native; SHA via `encode(digest(...), 'hex')` (pgcrypto) |
| STRLANG | ✅ | Returns string value (lang tag not persisted in SELECT) |
| STRDT | ✅ | Returns string value (datatype not persisted in SELECT) |
| sameTerm | ✅ | UUID equality check (stricter than `=`) |
| EXISTS / NOT EXISTS | ✅ | Correlated subquery via `_emit_exists_subquery`; prefixed aliases |

#### RDF Term Types

| Feature | Status | Notes |
|---|---|---|
| URIs / IRIs | ✅ | `term_type = 'U'` |
| Plain literals | ✅ | `term_type = 'L'` |
| Language-tagged literals | ✅ | Stored in `lang` column; CTE bypass for lang filter |
| Typed literals (xsd:integer, etc.) | ✅ | CAST to NUMERIC/TIMESTAMP/DATE in comparisons when typed literal present |
| Blank nodes | ✅ | `term_type = 'B'` |

### SPARQL 1.1 Update (W3C Rec)

| Feature | Status | Notes |
|---|---|---|
| INSERT DATA | ✅ | `term_uuid` gen, `lang` column, type-aware lookups, term dedup — Phase 4m-1 |
| DELETE DATA | ✅ | Type-aware UUID lookups, graph-scoped deletes — Phase 4m-2 |
| DELETE/INSERT WHERE (MODIFY) | ✅ | Full WHERE pattern matching via 3-pass pipeline + temp table — Phase 4m-3 |
| DELETE WHERE (shorthand) | ✅ | Sidecar fix applied; converts to UpdateModify internally — Phase 4m-4 |
| INSERT WHERE (template) | ✅ | Via UpdateModify with empty delete_quads — Phase 4m-5 |
| CLEAR | ✅ | GRAPH/DEFAULT/NAMED/ALL variants — Phase 4m-6 |
| DROP | ✅ | Implemented as CLEAR (no graph catalog) — Phase 4m-7 |
| CREATE | ✅ | Term upsert for graph URI — Phase 4m-8 |
| COPY | ✅ | Clear dest + copy source quads with dest context — Phase 4m-9 |
| MOVE | ✅ | COPY + DROP source — Phase 4m-10 |
| ADD | ✅ | Additive copy (no clear) — Phase 4m-11 |
| LOAD | ❌ | Type exists (`UpdateLoad`); requires app-level fetch+parse |

**Test tables**: `crud_test_exp_rdf_quad` (674K rows) / `crud_test_exp_term` (108K rows) — disposable copies from `lead_exp_*`.

### SPARQL 1.1 Other Specs

| Feature | Status | Notes |
|---|---|---|
| SPARQL Protocol (HTTP) | ✅ | Jena sidecar handles SPARQL parsing; orchestrator handles HTTP |
| SPARQL JSON Results | ✅ | Orchestrator formats results as SPARQL JSON bindings |
| SPARQL CSV/TSV Results | ❌ | |
| SPARQL XML Results | ❌ | |
| SPARQL Graph Store HTTP Protocol | 🚫 | Not applicable; direct DB access |
| SPARQL Entailment Regimes | 🚫 | No RDFS/OWL entailment |

### Proposed SPARQL 1.2 Features (W3C Draft)

| Feature | Status | Notes |
|---|---|---|
| ADJUST (datetime) | ❌ | New datetime adjustment function |
| FOLD (string case folding) | ❌ | Unicode-aware case folding |
| LATERAL joins | ❌ | Correlated subqueries; PostgreSQL supports `LATERAL` natively |
| Triple term patterns (RDF-star) | ❌ | Planned — see Phase 7 |
| Quoted triples (RDF-star) | ❌ | Planned — see Phase 7 |
| SPARQL-star annotation syntax | ❌ | Planned — see Phase 7 |
| Extended property paths | ❌ | Fixed-length paths, bounded repetition `{n,m}` |
| DESCRIBE improvements | ❌ | Concise Bounded Descriptions (CBD) |
| NaN handling | ❌ | IEEE 754 NaN semantics |
| Multi-valued BIND | ❌ | `BIND (expr1 AS ?x, expr2 AS ?y)` |
| GROUP_CONCAT ordering | ❌ | `GROUP_CONCAT(?x; ORDER BY ?y; SEPARATOR=",")` |
| SUBSTR negative indexing | ❌ | Count from end of string |
| Expanded aggregates | ❌ | Statistical aggregates (STDEV, VARIANCE) |
| Conditional aggregates | ❌ | `COUNT(?x) FILTER (WHERE ...)` |

### Implementation Priority Summary

**High priority — ALL COMPLETE** ✅:
- ~~HAVING clause support~~ → 4g ✅
- ~~GRAPH variable binding~~ → 4h ✅
- ~~Typed literal comparison (xsd:integer, xsd:dateTime ordering)~~ → 4i ✅
- ~~Date/time functions (YEAR, MONTH, NOW)~~ → 4j ✅
- ~~FILTER EXISTS / NOT EXISTS~~ → 4k ✅

**SPARQL 1.1 Functions — ALL COMPLETE** ✅:
- ~~isNumeric, ENCODE_FOR_URI, UUID/STRUUID~~ → 4l ✅
- ~~Hash functions (MD5, SHA1, SHA256, SHA384, SHA512)~~ → 4l ✅
- ~~STRLANG, STRDT, sameTerm~~ → 4l ✅
- ~~DATATYPE (full XSD URI)~~ → 4l ✅
- ~~IRI/URI constructor, BNODE constructor~~ → 4l ✅

**SPARQL Update & Data Modification — ALL COMPLETE** ✅ → 4m:
- ~~INSERT DATA, DELETE DATA~~ → 4m-1/2 ✅
- ~~DELETE/INSERT WHERE (full pattern-matching)~~ → 4m-3 ✅
- ~~INSERT WHERE template~~ → 4m-5 ✅
- ~~CLEAR, DROP, CREATE~~ → 4m-6/7/8 ✅
- ~~COPY, MOVE, ADD~~ → 4m-9/10/11 ✅
- ~~DELETE WHERE shorthand~~ → 4m-4 ✅ (sidecar fix applied)

**Medium priority** (useful for advanced queries):
- LATERAL joins (SPARQL 1.2)
- `USING <graph>` / `USING NAMED <graph>` in UpdateModify
- `SILENT` flag handling
- Orphan term cleanup after DELETE

**Low priority / not planned**:
- Federated queries (SERVICE)
- RDFS/OWL entailment
- CSV/TSV/XML result formats (JSON sufficient for API)
- UpdateLoad (requires app-level file fetch)

---

### Phase 7: RDF 1.2 Triple Terms & SPARQL 1.2 Support (FUTURE)

References:
- [RDF 1.2 Concepts and Abstract Data Model](https://www.w3.org/TR/rdf12-concepts/) — W3C Working Draft
- [SPARQL 1.2 Query Language](https://www.w3.org/TR/sparql12-query/) — W3C Working Draft

#### 7.1 RDF 1.2 Standard Definitions

##### RDF Terms (§3.2)

RDF 1.2 extends the set of **RDF terms** from three to four kinds:

| RDF Term Kind | RDF 1.1 | RDF 1.2 | Description |
|---|---|---|---|
| IRI | ✅ | ✅ | Internationalized Resource Identifier |
| Literal | ✅ | ✅ | Lexical form + datatype IRI + optional language tag |
| Blank Node | ✅ | ✅ | Locally-scoped anonymous node |
| **Triple Term** | — | ✅ | An RDF triple used as an RDF term within another triple |

##### Triples (§3.1) — Recursive Definition

An **RDF triple** `(s, p, o)` is defined inductively:

1. If `s` is an IRI or blank node, `p` is an IRI, and `o` is an IRI, blank node,
   or literal, then `(s, p, o)` is an RDF triple.
2. If `s` is an IRI or blank node, `p` is an IRI, and `o` is an **RDF triple**,
   then `(s, p, o)` is an RDF triple.

The definition is recursive — a triple can have an object which is another triple.
However, cycles of triples cannot be created (the object must already exist as a
well-formed triple).

##### Triple Terms (§3.6)

> "An RDF triple used as the object of another triple is called a **triple term**."

- In a given RDF graph, a triple can appear as a triple term, an asserted triple, or both
- **Triple term equality**: same as triple equality — `(s,p,o) = (s',p',o')` iff
  all three components are equal
- Triple terms are **transparent**: RDF terms inside a triple term have the same
  denotation as when they appear in asserted triples (e.g., `:Alice` in a triple
  term and `:Alice` in an asserted triple both denote the same resource)

##### Reification (§1.5)

RDF 1.2 introduces a standardized reification mechanism using `rdf:reifies`:

- A **reifying triple** is a triple where `p = rdf:reifies` and `o` is a triple term
- The subject of a reifying triple is called a **reifier**
- A reifier can be the subject or object of other triples (annotations)
- A **triple annotation** is the subset of triples about a reifier, when the
  corresponding triple term also appears as an asserted triple in the graph

```turtle
# The triple term (proposition) — NOT asserted
:stmt1 rdf:reifies << :alice :familyName "Liddell" >> .
:stmt1 :claimedBy :bob .

# The triple term IS also asserted (making this a triple annotation)
:alice :familyName "Liddell" .                              # asserted triple
:stmt2 rdf:reifies << :alice :familyName "Liddell" >> .     # reifying triple
:stmt2 :addedOn "2024-01-15"^^xsd:date .                    # annotation
```

Key properties:
- A proposition that is reified does **not** have to hold (non-asserted triple terms)
- Multiple distinct reifiers can relate to the same triple term
- One reifier may reify multiple distinct propositions

##### Literals — New Base Direction (§3.4)

RDF 1.2 adds a **base direction** component to literals (in addition to lexical form,
datatype IRI, and language tag). This supports bidirectional text (Arabic, Hebrew).

#### 7.2 SPARQL 1.2 Standard Definitions

##### Triple Term Syntax (§4.2, §17.4.6)

SPARQL 1.2 uses `<<( ... )>>` delimiters for triple term expressions (note: the
earlier community draft used `<< ... >>` without parentheses):

```sparql
VERSION "1.2"
PREFIX : <http://example/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

# Construct a triple term and bind it
SELECT ?s ?date {
  ?s ?p ?o .
  BIND( <<( ?s ?p ?o )>> AS ?tt )
  :myreifier rdf:reifies ?tt .
  :myreifier :tripleAdded ?date .
}
```

The `VERSION "1.2"` directive announces use of new syntax forms.

##### Functions on Triple Terms (§17.4.6)

| Function | Signature | Description |
|---|---|---|
| `TRIPLE(s, p, o)` | `triple term TRIPLE(RDF term, RDF term, RDF term)` | Construct a triple term; raises error if `(s,p,o)` is not a valid RDF triple. Shorthand: `<<( s p o )>>` |
| `isTRIPLE(term)` | `xsd:boolean isTRIPLE(RDF term)` | Returns `true` if argument is a triple term, `false` otherwise |
| `SUBJECT(tt)` | `RDF term SUBJECT(triple term)` | Returns the subject of a triple term; error if not a triple term |
| `PREDICATE(tt)` | `RDF term PREDICATE(triple term)` | Returns the predicate of a triple term; error if not a triple term |
| `OBJECT(tt)` | `RDF term OBJECT(triple term)` | Returns the object of a triple term; error if not a triple term |

##### New Language / Direction Functions (§17.4)

| Function | Signature | Description |
|---|---|---|
| `LANGDIR(lit)` | `xsd:string LANGDIR(literal)` | Returns combined language tag and base direction |
| `hasLANG(lit)` | `xsd:boolean hasLANG(literal)` | Returns `true` if literal has a language tag |
| `hasLANGDIR(lit)` | `xsd:boolean hasLANGDIR(literal)` | Returns `true` if literal has a base direction |
| `STRLANGDIR(str, lang, dir)` | `literal STRLANGDIR(...)` | Constructs a literal with language and direction |

##### Other SPARQL 1.2 Changes

- **ORDER BY triple terms**: triple terms have an in-between term type ordering
- **EXISTS/NOT EXISTS**: formal definition added (§17.4.1.4)
- **sameValue**: replaces `RDFterm-equal`, covers cross-datatype equality
- **EBV**: defined as a functional form
- **VALUES**: forbids duplicated variables
- **XPath 3.1**: updated function references from XPath 2.0

#### 7.3 Schema Design

**Option A: Triple-term reference table** (recommended)

```sql
CREATE TABLE {space}_triple_term (
    term_uuid      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_uuid   UUID NOT NULL REFERENCES {space}_term(term_uuid),
    predicate_uuid UUID NOT NULL REFERENCES {space}_term(term_uuid),
    object_uuid    UUID NOT NULL,  -- may reference term or another triple_term
    UNIQUE (subject_uuid, predicate_uuid, object_uuid)
);
```

The `term` table gets a new `term_type = 'T'` (triple term). The `term_text` stores
a canonical serialization for display: `<< <s_iri> <p_iri> <o_value> >>`.

The synthetic `term_uuid` from `triple_term` can appear in `rdf_quad.object_uuid`
(and per the RDF 1.2 spec, in `subject_uuid` for generalized RDF).

The `object_uuid` column allows recursive references — its value may be a UUID from
`triple_term` itself, enabling nested triple terms like
`<< << :a :b :c >> :source :wiki >>`.

**Option B: Reification-based** (simpler but less efficient)

Store `<< s p o >>` as standard reification quads (`rdf:Statement`, `rdf:subject`,
`rdf:predicate`, `rdf:object`). No schema changes but 4x storage overhead and
complex query translation. Not recommended.

#### 7.4 Implementation Phases

**7a. AST Support (types + mapper)**
- Add `TripleTermNode` to `jena_types.py` — an `RDFNode` containing `(subject, predicate, object)` as RDFNodes
- Update `jena_ast_mapper.py` to recognize Jena's `NodeTriple` JSON output
- Handle triple terms in BGP subject/object positions
- Unit tests for RDF 1.2 algebra parsing

**7b. Schema Migration**
- Create `{space}_triple_term` table via `jena_sql_indexes.py`
- Add `term_type = 'T'` handling in term table lookups and CTE constants
- Migration path for existing spaces (additive — no existing data affected)
- Indexes: unique composite on `(subject_uuid, predicate_uuid, object_uuid)`

**7c. Collect Pass**
- Handle `TripleTermNode` in `_collect_bgp`: when a triple term appears in
  object position of a BGP, generate a JOIN to `triple_term` table that
  resolves the inner s/p/o UUIDs
- Support variable triple terms: `<<( ?s ?p ?o )>>` as pattern matching
- Support nested triple terms via recursive collect

**7d. Emit Pass**
- Generate SQL JOINs to `triple_term` for triple-term lookups
- Support triple-term construction in CONSTRUCT/INSERT output
- Term resolution: join `triple_term` → `term` for display of inner components

**7e. Update Support**
- `INSERT DATA` with triple terms: create `triple_term` + `term` rows, then quad
- `DELETE DATA` with triple terms: resolve triple term UUID, delete quad
- `rdf:reifies` triple patterns in INSERT/DELETE WHERE

**7f. SPARQL 1.2 Functions**
- `TRIPLE(s, p, o)` and `<<( s p o )>>` shorthand → construct triple term UUID
- `isTRIPLE(?t)` → `term_type = 'T'` check
- `SUBJECT(?t)` → join `triple_term`, return `subject_uuid` resolved to term text
- `PREDICATE(?t)` → join `triple_term`, return `predicate_uuid` resolved to term text
- `OBJECT(?t)` → join `triple_term`, return `object_uuid` resolved to term text
- `LANGDIR`, `hasLANG`, `hasLANGDIR`, `STRLANGDIR` — literal direction functions

#### 7.5 Jena Sidecar Compatibility

Jena 4.x+ / 5.x has full RDF 1.2 / SPARQL 1.2 support:
- ARQ parser handles `<<( ... )>>` syntax and `VERSION "1.2"` directive
- `NodeTriple` in the algebra for triple term nodes
- `rdf:reifies` handled as a standard predicate
- The sidecar JSON output includes triple terms as structured objects

The main work is in the Python AST mapper and SQL generation, not the sidecar.

#### 7.6 PostgreSQL Advantages for RDF 1.2

- Native UUID JOINs efficient for triple-term resolution
- Composite unique index on `(subject_uuid, predicate_uuid, object_uuid)` prevents
  duplicate triple terms
- `WITH RECURSIVE` CTEs can handle nested triple terms
- The `triple_term` table is typically small (only reified/annotated triples)
- FK constraints ensure referential integrity to `term` table

#### 7.7 Risk Assessment

| Risk | Mitigation |
|---|---|
| Schema migration for existing spaces | Additive change; existing data unaffected |
| Nested triple term depth | Limit recursion depth (3-4 levels); cycles impossible per spec |
| Performance of triple-term JOINs | Small table; UUID-indexed; minimal overhead |
| Jena sidecar JSON format changes | Jena 4.x/5.x format is stable; add version detection |
| RDF 1.2 spec still Working Draft | Core triple term model stable since community group report |

---

## Key Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Sidecar latency | Parse/compile ~1-5ms; localhost TCP <1ms; negligible vs SQL execution |
| Expression coverage gaps | Build incrementally; log unsupported expressions; add as discovered |
| Complex nested Op trees | Recursive walker with clear type dispatch; comprehensive unit tests |
| Property paths | Separate phase; use PostgreSQL WITH RECURSIVE CTEs |
| Update atomicity | Wrap multi-statement updates in transactions |

---

## File Summary

| File | Purpose |
|---|---|
| **Core modules** | |
| `vitalgraph_sparql_sql/db.py` | Sync PostgreSQL connection helper (psycopg3) |
| `vitalgraph_sparql_sql/jena_sidecar_client.py` | Sync HTTP client for sidecar (httpx) |
| `vitalgraph_sparql_sql/jena_types.py` | 35+ dataclasses: Op, Expr, Node, Path, Update, CompileResult |
| `vitalgraph_sparql_sql/jena_ast_mapper.py` | Jena JSON → Python type tree (map_compile_response) |
| `vitalgraph_sparql_sql/jena_sparql_orchestrator.py` | Top-level coordination + result formatting |
| **SQL generation (modular)** | |
| `vitalgraph_sparql_sql/jena_sql_generator.py` | Public API entry point + DESCRIBE/ASK wrappers |
| `vitalgraph_sparql_sql/jena_sql_ir.py` | IR dataclasses (TableRef, VarSlot, RelationPlan, SQLContext) |
| `vitalgraph_sparql_sql/jena_sql_helpers.py` | Shared utilities (_esc, _node_text, _vars_in_expr) |
| `vitalgraph_sparql_sql/jena_sql_collect.py` | Pass 1: Op tree → RelationPlan (incl. _collect_path) |
| `vitalgraph_sparql_sql/jena_sql_resolve.py` | Pass 2: assign aliases, column names |
| `vitalgraph_sparql_sql/jena_sql_emit.py` | Pass 3: RelationPlan → SQL string (incl. _emit_path, _emit_bgp_optimized) |
| `vitalgraph_sparql_sql/jena_sql_expressions.py` | Expr/Function/Agg → SQL translation |
| `vitalgraph_sparql_sql/jena_sql_updates.py` | Update operations → SQL |
| `vitalgraph_sparql_sql/jena_sql_indexes.py` | Recommended indexes: check_missing, ensure_indexes |
| **Test files** | |
| `test_scripts/jena_sidecar/test_jena_sql_generator.py` | SQL generator unit tests (44 tests) |
| `test_scripts/jena_sidecar/test_jena_property_paths.py` | Property path unit tests (29 tests) |
| `test_scripts/jena_sidecar/test_orchestrator_live.py` | Live orchestrator tests (19 tests) |
| `test_scripts/jena_sidecar/test_jena_ast_mapper.py` | AST mapper unit tests (33 tests) |
| `test_scripts/jena_sidecar/test_sidecar_live.py` | Live sidecar integration tests (10 tests) |
| `test_scripts/jena_sidecar/test_sql_direct.py` | Direct SQL testing with timing |
| `test_scripts/jena_sidecar/test_fuseki_vs_sql_comparison.py` | Fuseki vs SQL side-by-side comparison (18 queries, multi-space) |
| `test_scripts/jena_sidecar/analyze_direct_properties.py` | Derive direct properties from edge objects in exp tables |
| `test_scripts/jena_sidecar/direct_properties_output.ttl` | Generated direct property triples for lead_exp (48K) |
| `test_scripts/jena_sidecar/direct_properties_lead_dataset.ttl` | Generated direct property triples for lead_dataset_exp (19K) |
| `test_scripts/jena_sidecar/inspect_data.py` | Data inspection script (Phase 0) |
| `test_scripts/jena_sidecar/inspect_fuseki_data.py` | Fuseki data inspection (datatype comparison) |
| `test_scripts/jena_sidecar/data_profile.md` | Sample data profile reference |
