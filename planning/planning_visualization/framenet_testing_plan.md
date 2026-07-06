# FrameNet Test Dataset — Loading & Search Testing Plan

## 1. Overview

FrameNet 1.7 (~1,221 frames, ~1,285 unique slot types) provides a rich,
real-world dataset for testing the KG types and search infrastructure.

Two generator scripts exist:

- **`test_scripts/data/generate_framenet_kgtypes.py`** — **Types only**.
  Generates proper VitalSigns GraphObjects (`KGFrameType`, `KGSlotType`,
  `Edge_hasSubKGFrameType`) and writes a `.vital` block file (~3,300
  objects).  This is the primary script for KG Types testing.
- **`test_scripts/data/load_framenet_prototypes.py`** — Legacy script that
  generates both types and prototype objects as raw JSON-L dicts (~40,000
  objects).  Retained for reference but not used for loading.

FrameNet defines frame semantics at the **type level** — frame definitions,
typed slots (frame elements), and inheritance relationships.  It does not
define compositional structural templates (prototypes).  Prototype test
data would need to be synthetically generated if required.

This plan covers:
1. **What the generator produces** — object types, counts, and format
2. **How to load** — using `vitalgraphimport` CLI
3. **Vector & full-text search integration testing**
4. **Testing levels** — code-level and service REST API

This dataset is used by:
- `planning_visualization/kg_types_plan.md` — KG Types UI & data model
- `planning_visualization/prototype_kg_types_plan.md` — Prototype layer (future synthetic data)

---

## 2. What the Generator Produces

### 2.1 Type Objects (generate_framenet_kgtypes.py)

All objects are proper VitalSigns GraphObject instances written to a
`.vital` block file.

| Object Class | Count | Description |
|-------------|-------|-------------|
| `KGFrameType` | ~1,221 | One per FrameNet frame, with enriched description + core FE names |
| `KGSlotType` | ~1,285 | Deduplicated FE definitions, enriched with cross-frame usage |
| `Edge_hasSubKGFrameType` | ~781 | Frame inheritance hierarchy edges |
| **Total** | **~3,287** | |

Properties set per object:

- **KGFrameType**: `name`, `kGraphDescription` (enriched), `kGFrameTypeExternIdentifier`
- **KGSlotType**: `name`, `kGraphDescription` (enriched), `kGSlotTypeName`, `kGSlotTypeLabel`, `kGSlotTypeExternIdentifier`
- **Edge_hasSubKGFrameType**: `edgeSource`, `edgeDestination`

### 2.2 Prototype Objects (not generated)

FrameNet defines frame semantics (what a frame means, what roles it has)
but does not specify compositional structural templates (how an instance
should be assembled).  Prototype test data (`KGFrameProtoType`,
`KGSlotProtoType`, connecting edges) would need to be synthetically
generated if needed for prototype UI testing.

The legacy script `load_framenet_prototypes.py` generates prototype-like
objects as raw dicts, but these are not proper GraphObjects and are not
in a loadable format.

### 2.3 Known Issue: Btree Index Limit on term_text

The per-space term table stores all RDF literal values in a `text`
column (`term_text`) with no length limit.  However, the schema creates
a **btree composite index** on `(term_text, term_type)` for equality
lookups.  PostgreSQL btree indexes cannot handle row values exceeding
~2704 bytes.

FrameNet definitions can be up to ~5,900 characters (e.g.
`Conditional_scenario`), and 17 frames exceed the 2704-byte limit.
This causes `ProgramLimitExceededError` during incremental import.

**Current workaround:** The generator truncates `kGraphDescription`
to 2,500 characters (`_MAX_DESC_LEN`).  This is sufficient for search
and display purposes.

**Proper fix (future):** Replace the btree index
`idx_{space_id}_term_tt` with a **hash index** on `term_text` (hash
supports arbitrary-length values and all queries are equality-only).
The existing `btree(term_type)` index remains for type filtering.
The schema change is in `sparql_sql_schema.py` line 560:

```sql
-- Current (fails for literals > ~2700 bytes):
CREATE INDEX ... ON term (term_text, term_type)
-- Proposed:
CREATE INDEX ... ON term USING hash (term_text)
```

### 2.4 Enriched Descriptions

Each KGFrameType description is enriched with the names of core frame
elements, making it more informative for both keyword and semantic search.
Each KGSlotType description is enriched with cross-frame usage context
(which frames reference this slot type), improving vector search recall.

The two-pass generation approach first collects slot type usage across all
frames, then generates enriched `KGSlotType` objects with that context.

### 2.5 Modeling Choice: Role Types vs Distinct Slot Types

When mapping FrameNet data to KG types, we need to decide how to represent
frame elements (FEs). See `kg_types_plan.md` §2.2 for the general
role-based vs type-based trade-off discussion.

**How FrameNet actually defines FEs:**

FrameNet defines FEs at the **role level** — FE names _are_ role names.
There is no separate "role type" layer in the FrameNet data:

- `Commerce_buy` has core FEs: `Buyer`, `Seller`, `Goods`, `Money`
- `Commerce_sell` has the **same FE names**: `Buyer`, `Seller`, `Goods`, `Money`
- There is no generic "CommercialParticipant" with a role annotation;
  `Buyer` and `Seller` are distinct FE names at the frame level

**FE reuse patterns (1,285 unique FE names across ~1,221 frames):**

| Category | Examples | Count |
|----------|---------|-------|
| Generic peripheral (massively reused) | `Time` (818), `Place` (685), `Manner` (663), `Degree` (479) | ~20 names |
| Mid-range semantic roles | `Agent` (209), `Theme` (90), `Source` (102), `Goal` (92) | ~50 names |
| Role-specific (single-use) | `Abuser`, `Agriculturist`, `Buyer`, `Lessee` | **678 names** (53%) |

FE inheritance mappings explicitly link FEs across frames — sometimes by
the same name (`Buyer` → `Buyer`), sometimes with renames (`Buyer` →
`Lessee` in Renting, `Donor` → `Seller` in Giving).

**Recommendation — Type-based (Option A, current loader approach):**

Since FrameNet already encodes roles as FE names, the natural mapping is
the current approach: each unique FE name becomes a deduplicated
`KGSlotType`. This preserves FrameNet's own structure without needing to
invent a separate role type layer.

- The 678 single-use FE names (like `Buyer`, `Seller`) are inherently
  role-specific slot types
- The ~20 heavily reused FE names (like `Time`, `Place`, `Manner`) are
  shared peripheral slot types that genuinely mean the same thing across
  frames

`KGSlotRoleType` is still available for custom KG modeling where users
want to reuse a single generic type (e.g. `BusinessEntity`) and
differentiate via role — but this is not needed for the FrameNet test
dataset.

---

## 3. Search Testing

### 3.1 Full-Text / Keyword Search

Each KGFrameType and KGSlotType includes a natural-language description
suitable for PostgreSQL full-text search (`tsvector` / `ts_rank_cd`):

- Searching "commercial transaction" finds `Commerce_buy`, `Commerce_sell`
- Searching "hiring" finds `Employment_start`, `Hiring`

### 3.2 Vector Embedding / Semantic Similarity

The enriched `kGraphDescription` fields are ideal candidates for
vectorization and HNSW-based ANN search:

- Searching "hiring someone for a job" finds `Employment_start` by semantic
  similarity to the description (not keyword match)
- Searching "giving money to someone" finds `Commerce_pay`, `Fining`, `Giving`

### 3.3 Prototype Discovery via Type Search

The search targets KGFrameType descriptions, then traverses graph links to
surface related prototypes:

1. Vector/FTS search finds matching KGFrameType or KGSlotType by description
2. SPARQL traverses `hasKGFrameType` to return the associated
   KGFrameProtoType and its slot prototypes

This validates that vector search integrates correctly with graph traversal
queries — the core mechanism for prototype discovery.

---

## 4. Vector & Full-Text Search Integration

This dataset validates the search infrastructure across all SPARQL `vg:`
functions. The infrastructure now includes decoupled FTS
(`{space}_fts_{idx}` tables), vector (`{space}_vec_{idx}` tables), and
the full complement of search functions — see
`planning_vector_geo/text_hybrid_search_plan.md` for the complete
architecture.

### 4.1 Setup

1. Load FrameNet KG type objects into a space via the loader script
2. Register a vector index + FTS index for the KG types graph
3. Register shared search mappings defining which properties to index
4. Vectorize descriptions via the configured embedding provider
5. Populate the FTS index (search_text → tsvector via trigger)

### 4.2 Test Scenarios

| Scenario | Search Mode | Query | Expected Result | Status |
|----------|-------------|-------|-----------------|--------|
| Exact concept | Keyword / FTS | "commercial buying" | `Commerce_buy`, `Commerce_sell` | ✅ verified |
| Semantic similarity | Vector | "hiring someone for a job" | `Employment_start`, `Hiring` | ✅ verified |
| Cross-domain similarity | Vector | "giving money to someone" | `Commerce_pay`, `Fining`, `Giving` | ✅ verified |
| Slot type discovery | Vector | "the person who performs the action" | Slot types: `Agent`, `Actor`, `Protagonist` | ✅ verified |
| Paraphrase matching | Vector | "physical movement from one place to another" | `Motion`, `Self_motion`, `Travel` | ✅ verified |
| Hybrid cooking/heat | Hybrid | "cooking food preparation heat" | `Apply_heat` | ✅ verified |
| Hybrid commerce | Hybrid | "commercial transaction buying selling goods" | `Commercial_transaction` | ✅ verified |

### 4.3 What This Validates

- ✅ Full-text search: `tsvector` / `ts_rank_cd` ranking on description text
- ✅ SPARQL integration: FTS constructs within SPARQL queries
- ✅ End-to-end pgvector integration: embedding generation → HNSW index → ANN query
- ✅ Combined search: vector similarity filtered by type class (e.g. only KGFrameType)
- ✅ SPARQL `vg:vectorSimilarity` returning semantically correct ranked results
- ✅ Hybrid search (`vg:hybridSearch`): combined vector + FTS scoring

This is a real-world test with ~2,500 type objects, each with meaningful
natural-language descriptions — large enough to validate index performance
and ranking quality, small enough for fast iteration.

### 4.4 Implementation Status

All search pipelines are **fully operational** via the REST API.
The full test suite passes **24/24** (see `kg_types_search_plan.md` §7
Phase F for details).

1. **Index creation**: `POST /api/vector-indexes/` creates `kgtype_default`
   (384-dim, cosine, HNSW + GIN tsvector indexes, `tsv GENERATED ALWAYS AS`)
2. **Mapping registration**: `POST /api/search-mappings/` registers
   `kgtype` class-level mappings with `source_type=properties`
3. **Reindex**: `POST /api/vector-indexes/reindex` populates `search_text`
   from literal properties via `vector_populator.populate_index()` and
   generates embeddings via the configured provider

Setup is handled by `test_scripts/sparql/setup_kgtype_search_framenet.py`
which creates the space, imports data, registers indexes/mappings, and
polls until population completes.

The test (`test_scripts/sparql/test_kgtype_search_framenet.py`) exercises
the REST API endpoint (`GET /api/graphs/kgtypes/search`) via the Python
client (`client.kgtypes.search_types()`), passing `search_mode` to select
the backend path. This validates the full stack: REST → SPARQL generation →
SQL/pgvector/tsvector execution → ranked response.

**Keyword + FTS** (via REST search endpoint): 11/11 tests pass ✅
**Vector** (via REST search endpoint): 4/4 tests pass ✅
**Hybrid** (via REST search endpoint): 2/2 tests pass ✅
**Direct SPARQL** (raw queries via `/api/sparql`): 4/4 tests pass ✅
  - `FILTER(CONTAINS(...))` — keyword via SPARQL endpoint
  - `vg:textSearch` — FTS via SPARQL endpoint
  - `vg:vectorSimilarity` — vector ANN via SPARQL endpoint
  - `vg:hybridSearch` — hybrid via SPARQL endpoint
**Auto-sync** (create → search within timeout): 3/3 tests pass ✅

**Auto-sync integration**: The KGTypes endpoint (`kgtypes_endpoint.py`) now
calls `schedule_sync()` after create, update, and delete operations — the
same fire-and-forget pattern used by entities, frames, and documents. This
means newly created/updated KGTypes are automatically re-vectorized and
their `search_text` / `tsvector` updated in the background, provided a
vector index and mapping exist for the space.

**Bugs fixed during implementation:**

| Bug | File | Fix |
|-----|------|-----|
| `context_uuid` missing `\x00U` suffix | `vitalgraph/endpoint/vector_indexes_endpoint.py` | Added suffix to match term UUID generation |
| Client `get_index` parsing wrong model | `vitalgraph/client/endpoint/vector_indexes_endpoint.py` | Parse `VectorIndexListResponse`, extract first element |
| SPARQL `VALUES` clause broken in SQL backend | `vitalgraph/db/sparql_sql/var_scope.py` | Fixed variable scoping for inline VALUES; queries now use `VALUES` as intended |

**Test results — Keyword + FTS** (11/11 passing):

| Test | Mode | Result |
|------|------|--------|
| Commerce frames | keyword | 9 results, Commerce_buy top |
| Motion frames | keyword | 89 results |
| Slot type Agent | keyword | 100 results |
| Hiring/employment | keyword | 1 result (Hiring) |
| All types (no filter) | keyword | 100+ results |
| Commercial transaction | FTS | Commercial_transaction found |
| Motion source/goal/path | FTS | Motion in top 6 |
| Cooking/food/heat | FTS | Apply_heat, Cooking_creation |
| Legal judgment | FTS | 0 results (correct — no match) |
| Nonsense query | keyword | 0 results (correct) |
| Type filter: slot only | keyword | 87 results, all KGSlotType |

**Test results — Vector** (4/4 passing ✅):

| Test | Mode | Result |
|------|------|--------|
| Hiring/employment (semantic) | vector | Hiring found ✅ |
| Physical movement (paraphrase) | vector | Motion found ✅ |
| Giving money as payment | vector | Repayment found ✅ |
| Person who performs action (slot) | vector | Performer1 found ✅ |
| Cooking preparation | hybrid | Cooking_creation found ✅ |
| Commercial transaction | hybrid | Commercial_transaction found ✅ |

### 4.5 Reindex Scalability (TODO)

The current `populate_index()` processes batches of 100 subjects
sequentially on a single connection. For small spaces (~3K subjects) this
completes in seconds. For large spaces (100K–1M+ subjects) it could run
for hours and has several limitations:

| Problem | Impact |
|---------|--------|
| Single-threaded | 1M subjects @ 100/batch = 10K batches, sequential |
| No resume/checkpoint | Restart = start over from batch 0 |
| Blocks pool connection | Holds one asyncpg connection for entire duration |
| No progress visibility | Caller has no way to check % complete |
| Event loop pressure | Long-running coroutine with many awaits |

**Planned improvements:**

1. **`missing_only` mode** — add a `mode` parameter to the reindex
   endpoint: `"full"` (current behavior — re-vectorize everything) vs
   `"missing_only"` (only process subjects with no existing row in the
   vector table). Implementation: change the subject query to a LEFT JOIN
   against `{space_id}_vec_{index_name}` and filter
   `WHERE vec.subject_uuid IS NULL`. This makes post-import and
   post-restart reindex near-instant for mostly-populated indexes.
2. **Checkpointing** — persist last-processed offset in a
   `reindex_progress` table so reindex can resume after crash/restart.
   The `ON CONFLICT DO UPDATE` upsert is already idempotent.
3. **Batch concurrency** — process N batches in parallel via
   `asyncio.gather` (e.g. 4 concurrent batches → ~4x speedup). Each
   batch acquires its own connection from the pool.
4. **Progress endpoint** — `GET /api/vector-indexes/reindex-status` to
   report subjects processed, total, ETA, and errors.
5. **Backpressure** — cap concurrent embedding API calls to avoid
   overwhelming the provider (semaphore-based rate limit).

For now the system works fine for spaces under ~10K subjects. Address
when production spaces exceed this threshold.

---

## 5. Testing Levels

Tests can be run at two levels without requiring different datasets:

- **Code-level (no service running)** — Python test scripts that directly
  call the SPARQL-SQL backend, vector index, and graph traversal functions
  against a local PostgreSQL database. This tests the query pipeline,
  embedding generation, HNSW search, and FTS ranking in isolation without
  HTTP overhead. Useful for fast iteration and debugging.
- **Service REST API** — Tests that run against the VitalGraph service
  endpoints (`GET /api/kg-types/search`, `GET /api/prototypes/frame`, etc.)
  via HTTP. This validates the full stack including serialization, endpoint
  routing, authentication, and response format. Can be run with the
  `vitalgraph_client_test` harness or standalone scripts.

---

## 6. Usage

### 6.1 Generate the .vital Block File

```bash
# Generate full dataset (~3,300 objects)
python test_scripts/data/generate_framenet_kgtypes.py -o framenet_kgtypes.vital

# Quick subset for development (~36 objects from 5 frames)
python test_scripts/data/generate_framenet_kgtypes.py --limit 5 -o framenet_kgtypes_5.vital

# Preview a single frame (no file output)
python test_scripts/data/generate_framenet_kgtypes.py --preview Commerce_buy

# Stats only
python test_scripts/data/generate_framenet_kgtypes.py --stats
```

### 6.2 Load into a Space

Use the existing `vitalgraphimport` CLI (direct PostgreSQL, no service
needed):

```bash
# Load into the system-controlled KG types graph
vitalgraphimport \
  -s <space_id> \
  -g urn:vitalgraph:<space_id>:kg_types \
  -f framenet_kgtypes.vital

# Replace mode (clear graph before loading)
vitalgraphimport \
  -s <space_id> \
  -g urn:vitalgraph:<space_id>:kg_types \
  -f framenet_kgtypes.vital \
  --mode incremental --replace-mode replace
```

The import CLI auto-detects the `.vital` format and uses
`ImportEngine.import_vital_block_incremental` to convert GraphObjects to
quads and insert them into the term/quad tables.

### 6.3 Prerequisites

```bash
pip install nltk
python -c "import nltk; nltk.download('framenet_v17')"
```

### 6.4 Current Test Space

The full FrameNet KG types dataset has been loaded into:

- **Space**: `framenet_kgtypes_test` ("FrameNet KG Types Test")
- **Graph**: `urn:vitalgraph:framenet_kgtypes_test:kg_types`
- **Block file**: `generated_instances/framenet_kgtypes.vital` (2.7 MB)

Verified counts:

| Metric | Value |
|--------|-------|
| Total quads | 21,511 |
| KGFrameType objects | 1,221 |
| KGSlotType objects | 1,285 |
| Edge_hasSubKGFrameType edges | 781 |
| **Total objects** | **3,287** |
| Import time | 2.2s |

---

## 7. Related Documents

- `planning_visualization/kg_types_plan.md` — KG Types UI & data model
- `planning_visualization/kg_types_search_plan.md` — KG Types search plan (index setup, query modes, provider swap)
- `planning_visualization/prototype_kg_types_plan.md` — Prototype layer
- `planning_vector_geo/vector_geo_plan.md` — Vector & geo infrastructure (storage design, HNSW, PostGIS)
- `planning_vector_geo/text_hybrid_search_plan.md` — FTS decoupling, `vg:textSearch`/`vg:hybridSearch` implementation, shared search mappings
- `planning_vector_geo/geo_fuzzy_search_gaps.md` — Geo & fuzzy search status (SPARQL functions, REST endpoints, client libraries)
- `planning_vector_geo/vector_geo_ui_plan.md` — Vector & geo UI integration
- `kgraphgen/planning/framenet_guide.md` — FrameNet mapping onto the three-tier Type/Prototype/Instance architecture
- `planning_kgdocument/kgdocument_plan.md` — KGDocument structure
