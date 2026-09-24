# The Entity Count Path Rebuilds From Quads While The Sort Path Reads The Derived Table

## Status: OPEN — measured on production, no fix attempted.
##
## Found 2026-09-23 while counting nurture actions per month in `prod_kg`.
## The counts themselves are correct; what this records is that they cost
## 16-25x more than the data already sitting in `entity_prop_sort` allows, and
## that at the wide end the cost is close enough to the 60s statement timeout to
## cross it on a cold cache — which it did, as an HTTP 500.

## Summary

`GET /api/graphs/kgentities/count` builds a SPARQL `COUNT(DISTINCT ?entity)`
and executes it through the generic pipeline, joining `rdf_quad` and `term`.
The equivalent listing call with `sort_by=` reads `{space}_entity_prop_sort`,
which already holds one row per (entity, context, property) for exactly the
seven properties this endpoint filters on — including
`vital-aimp#hasObjectCreationTime` — with a partial index built for the shape:

    idx_prod_kg_eps_dt (context_uuid, entity_type_uuid, property_uuid,
                           value_dt, entity_uri) WHERE value_dt IS NOT NULL

Two paths over the same question, one of which has a purpose-built index and
does not use it.

## Measured, production `prod_kg`, type `NurtureAction`

API figures are 7 runs each, cache-busted by varying the bound by one second so
`_count_cache` misses every time. SQL figures are 6 warm runs after a warmup.

    matched   via /kgentities/count        direct on entity_prop_sort
              min    med    max            min      med      max
      6,894   0.06s  0.22s  0.23s          12.5ms   13.6ms   21.0ms     ~16x
     31,005   0.41s  0.42s  0.46s          -                            -
     85,153   1.00s  1.01s  1.19s          25.3ms   41.3ms   82.0ms     ~25x

Both return identical answers (6,894 and 85,153). Cost through the endpoint is
linear in the MATCH COUNT, not the page size and not the total — roughly 12us
per matched entity. `exec_ms=1080` of `total_ms=1095` is database time, so this
is not endpoint overhead.

## The plan, from the service's own slow_query log

`report_slow_query` already flags this shape without anybody asking:

    "disproportionate": true, "max_loops": 87785, "ratio": 87785.0,
    "root_buffers": 1619100

    87,290 loops  Index Only Scan prod_kg_rdf_quad_pkey q1    431,860 buffers
    85,048 loops  Index Only Scan prod_kg_rdf_quad_pkey q0    422,846 buffers
    87,785 loops  Index Scan      prod_kg_term_pkey           351,142 buffers
    85,048 loops  Index Only Scan prod_kg_term_pkey t_v1      327,121 buffers
         3 loops  Parallel IOS    idx_prod_kg_quad_ctx_pred    86,131 buffers

Four index scans looping ~85-88k times each to produce ONE row. Every matched
entity is materialised and de-duplicated; nothing stops early, because
`COUNT(DISTINCT)` cannot.

## How it surfaces: a 500, not a slow response

2026-09-24 01:55:52 UTC, the first uncached wide count of the session:

    execute_sparql_query(prod_kg) failed: canceling statement due to
      statement timeout
    Error counting entities: SPARQL query failed: canceling statement due to
      statement timeout
    GET /api/graphs/kgentities/count?...&created_after=2000-01-01T00:00:00Z 500

Production `statement_timeout` is 60s from the RDS parameter group
(`pg_settings.source = configuration file`), the same cap as `issues/136`.
`_count_entities` wraps every exception in `HTTPException(500)`
(`kgentities_endpoint.py:637`), so a cancelled statement reaches the caller as
a server error carrying a driver message.

Ruled out while diagnosing:

  * NOT the datetime format. `Z`, `+00:00`, bare, and date-only all return 200;
    8 runs of each.
  * NOT chronic. Exactly one statement-timeout event in 24h across the service.
  * NOT endpoint overhead. See `exec_ms` above.

Warm, that same query is 1.0s. What made that execution exceed 60s is NOT
established — 1.62M buffer accesses against a cold cache on EBS is the obvious
candidate and fits, but a cold cache cannot be forced on production to prove it,
so it stays a hypothesis. The 1.0s warm figure and the 60s cancellation are both
measured; the bridge between them is not.

## What a fix would have to answer

**1. Can the count path reach the table without losing generality?** The count
builds arbitrary SPARQL — `search=`, `provenance_type=`, `status=` and free-text
all land in the same query. `entity_prop_sort` answers the narrow shape
(entity type + one of its seven properties, equality or range) and nothing else.
A fast path must recognise that shape and decline cleanly otherwise, which is
the `issues/160` gate problem again in a smaller form.

**2. Is `COUNT(DISTINCT)` needed at all here?** The pkey is
`(entity_uuid, context_uuid, property_uuid)`, so for a single property the rows
are already distinct per entity and a plain `count(*)` suffices. That is what
the 25-82ms column above measures.

**3. Should a timeout be a 500?** Per the project's convention non-200 is
reserved for server-level faults, and a cancelled statement arguably is one. But
the caller cannot distinguish it from a genuine fault, and it is retryable —
the retry succeeded in 1.0s. Worth deciding rather than leaving to the generic
`except`.

## Not established

  * Whether the listing path (`sort_by=`, which DOES read the table) has the
    same exposure at the wide end. It was 0.3s for a page in the same session,
    but a page is not a count.
  * Whether other spaces show the ratio. Only `prod_kg` was measured.
  * Whether `_count_cache` masks this in normal portal use. Every figure here
    was deliberately cache-busted; real traffic may never pay it twice.

## Reproduce

    python scripts/count_entities_by_month.py --env prod

That script buckets by month precisely to stay in the cheap part of the curve —
each month is its own short statement, so no single one approaches the 60s cap.
The expensive shape is the unbounded whole-type count it takes once at the start
and once at the end.
