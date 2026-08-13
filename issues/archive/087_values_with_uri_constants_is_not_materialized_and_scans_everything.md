# `VALUES` With URI Constants Is Not Materialized — 0.3 ms Becomes 21,790 ms

## Status: FIXED 2026-08-13

    VALUES ?s { <uri> }        21,789.8 ms  ->    0.2 ms
    VALUES, 2 URIs              6,240.5 ms  ->    0.4 ms
    VALUES, 20 URIs            57,591.3 ms  ->    4.0 ms
    <uri> ?p ?o (control)            0.3 ms       0.2 ms

Parity with the control, and cost now follows the LIST rather than the space.

**Three changes, and all three are required** — the first two alone left it at
19,603 ms, which is how each was found:

1. **`collect._collect_table` registers the constants**, so the FIRST
   materialization pass resolves them. Registering at emit time would work for
   the uuid but would not let emit know whether each URI actually EXISTS, which
   change 3 depends on.
2. **`emit_table` emits the resolved uuid** instead of `NULL::uuid`, and claims
   term identity only when every row of the block resolved.
3. **`emit_join` drops its `IS NULL` compatibility guards for an INNER join**
   when both sides always bind the variable. Without this the condition is
   `(a IS NULL OR b IS NULL OR a = b)`, which PostgreSQL cannot hash or merge —
   it was still a nested loop over the whole graph at 6,240 ms even with correct
   uuids on both sides.

`ColumnInfo.uuid_materialized` carries the evidence. It is deliberately separate
from `from_triple`: that flag also drives OPTIONAL/MINUS boundness reasoning,
and widening it is what made MINUS a silent no-op (issue 026).

**The correctness case that constrains the design.** A URI absent from the term
table resolves to a NULL uuid, and NULL reads as "unbound" — which under SPARQL
join semantics is compatible with EVERYTHING. So the fast path is claimed only
when every value resolved; a list containing an absent URI keeps the old text
join. Verified: an absent URI returns 0 rows, and a mixed present/absent list
returns exactly what the present URI alone returns.

**Gates.** 616 conformance passed (the suite that would catch a join-semantics
error); 1811 unit; 196 integration; comparator sweep 0 cells slow warm with
buffer counts IDENTICAL to the pre-change baseline on every sampled cell, i.e.
identical plans. New bench `tests/performance/test_values_clause.py` gates the
ratio against an equivalent literal-subject query, plus the absent-URI and
mixed-list correctness cases.

`issues/086` is fixed as a consequence: its slot-count query goes 3,436 ms ->
0.2 ms, and a frame with slots reports 8, matching the UI.

## Original status: OPEN — diagnosed 2026-08-13

Found while diagnosing `issues/086` (the entity page). It is not an entity-page
problem. **Every SPARQL `VALUES` clause naming a URI degenerates into a full
scan with a text comparison**, and 18 files in this codebase build one.

Same question, same 8 rows, `sp_lead_synth_100k`:

    VALUES ?s { <urn:acme:lead:SYN000046907> }    21,789.8 ms
    <urn:acme:lead:SYN000046907> ?p ?o                 0.3 ms
    FILTER(?s = <urn:acme:lead:SYN000046907>)          0.2 ms

**~70,000x**, for three spellings of one query.

## The plan says exactly what happens

From the slot-count query in `086` (`EXPLAIN ANALYZE`):

    Parallel Seq Scan on sp_lead_synth_100k_term t_v2   (10.4M-row term table)
    Parallel Seq Scan on sp_lead_synth_100k_edge  mv0   (full edge table)
    Join Filter: (mv0.source_node_uuid IS NULL)
                 OR ('urn:acme:lead:...:frame:leadstatusframe:0'::text
                     = t_v2.term_text)
    Rows Removed by Join Filter: 1,292,333
    Buffers: shared hit=325,953

The URI is compared **as text, against the whole term table**, after hash-joining
it to the whole edge table. It is never resolved to a `term_uuid`, so nothing can
use an index — and the constant appears in the GROUP BY as
`COALESCE('urn:...'::text, t_v2.term_text)`, which is the signature of `VALUES`
being emitted as an inline projection with a filter rather than as a constant.

Contrast the working path: a literal subject or a `FILTER(?s = <uri>)` goes
through constant materialization, becomes `= 'uuid'::uuid`, and hits an index.
`generator.materialize_constants` exists and does exactly this — `VALUES` simply
does not reach it.

## Blast radius: 18 files

`grep -rn "VALUES ?" --include=*.py vitalgraph/` — every one of these builds a
`VALUES` clause over URIs at runtime:

    kg_query_builder.py             VALUES ?entity        (x2)
    kg_connection_query_builder.py  VALUES ?source_entity, ?destination_entity,
                                           ?relation_type, ?frame_type
    kg_sparql_query.py              VALUES ?frame         (issues/086)
    sparql_sql_space_impl.py        VALUES ?s             (DESCRIBE)
    kgdocuments_endpoint.py         VALUES ?managed
    kgquery_endpoint.py             VALUES ?entity_uri
    segment_deletion.py             VALUES ?s
    utils.py                        VALUES ?{variable}    (generic helper)

So this reaches KGQuery entity-URI filtering, connection/relation queries,
document management, segment deletion, and `DESCRIBE`. Anything that says "these
specific URIs" — which is the natural way to express it — pays a full scan.

## Why it hid

* The obvious spellings are fast. A literal subject and a `FILTER` both take the
  materialized path, so the pattern only bites when a caller has a LIST of URIs,
  which is exactly when `VALUES` is the right SPARQL.
* No performance test uses `VALUES`. The comparator sweep, growth curves and
  paging benches all express constants as literals or filters.
* It gets WORSE with data, not with list length: the cost is the term and edge
  tables, so a two-URI list on a large space is slower than a hundred-URI list on
  a small one.

## Fix direction

Route `VALUES` constants through the same materialization every other constant
uses — resolve each URI to its `term_uuid` at generation time and emit a
`subject_uuid IN (...)` / `= ANY(...)` against the quad or edge table.

The machinery is already there (`generator.materialize_constants`,
`aliases.constants`, the `__CONST_c_N__` token substitution). This is a matter of
making the `VALUES` collect/emit path use it, not of building something new.

Watch for: an unresolvable URI in the list. A constant that is absent from the
term table makes that binding provably empty, which the generator already knows
how to express (`issues/073`) — a `VALUES` list should drop such entries rather
than fail, since `VALUES` is a union of alternatives.

## Gate it

No bench covers `VALUES`, which is why a 70,000x gap went unnoticed. The fix
needs a performance test asserting that a `VALUES` list of URIs costs
approximately what the equivalent `FILTER` costs — a ratio, not a timing, in the
style of `test_aggregate_growth.py`.

## Related

- `issues/086` — the entity page, where this was found. Its 160x is this defect
  seen through one endpoint.
- `issues/073` — absent constants as provably-empty, the behaviour a `VALUES`
  list must preserve.
