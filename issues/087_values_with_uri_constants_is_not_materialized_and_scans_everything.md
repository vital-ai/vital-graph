# `VALUES` With URI Constants Is Not Materialized — 0.3 ms Becomes 21,790 ms

## Status: OPEN — diagnosed 2026-08-13

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
