# The Sort Fast-Path Table Covers 0.7% of Its Population, and the Check That Would Notice Times Out Into a Bare `except`

## Status: **CORE CLAIM RETRACTED 2026-09-03 — see the correction below.**
## The listing endpoint has NO wiring to the fast path, so it is not "falling
## back" from an underpopulated table; there is nothing for it to fall back
## from. Superseded by `issues/149`. Original status follows.
##
## CODE FIXED IN `main` (10e1157), BACKFILL STILL PENDING.
## Measured against prod 2026-09-02. This is the reported slow page. The probe
## and the swallowed-timeout defects are fixed; the table is still 0.6%
## populated until the deploy lands and Phase 3 runs the backfill. Do NOT run
## the backfill first — without 10e1157 it decays again, which is this history.

## Correction, 2026-09-03

This file claims the listing page "fell back" to an O(total) scan because
`{space}_entity_slot_sort` was 0.6% populated. Both halves are true separately;
the causal link between them is not.

    kgentities_endpoint.py   fast_slot_sort=0   entity_slot_sort=0
    kgentity_list_impl.py    fast_slot_sort=0   entity_slot_sort=0
    kgquery_endpoint.py      fast_slot_sort=7

The slow request goes to `/api/graphs/kgentities`, which never consults the
derived table. The fast path is wired only into `/api/graphs/kgqueries`. So
filling the table to 100% would not change this page at all.

I inferred the fallback from the SQL touching only `rdf_quad` and `term`, and
did not check whether the endpoint had any code to do otherwise. The 77,310-loop
measurement and the 0.6% figure both stand; the explanation joining them does
not.

`issues/149` covers why the table is 1% full (a client-side `command_timeout`
killed the probe that gates the backfill) and what would actually make the page
fast.

## The user-visible query

The entity listing page ("N total, 25 per page, sorted") for the largest entity
type in `prod_kg`. From the Postgres log — `ORDER BY s0.v1 DESC, s0.v0 LIMIT 25`,
a frame/slot walk over `rdf_quad` + `term`. Four executions in one 46-minute
window: **11,187 / 2,501 / 1,368 / 1,216 ms**. Users have reported ~40s.

## What it actually does

`EXPLAIN (ANALYZE, BUFFERS)` on prod, warm:

    Execution 1,347 ms          total buffers 1,298,340  (~10.4 GB)

    own buffers      rows    loops   node
        382,857       1.0   77,310   Index Only Scan  rdf_quad
        309,240       1.0   77,310   Index Scan       term
        309,240       1.0   77,310   Index Scan       term
        218,574  76,695.0        3   Bitmap Heap Scan rdf_quad

**77,310 loops to return 25 rows.** The sort key is not available without
visiting every entity, so the whole population is materialised and sorted before
`LIMIT 25` applies. The page costs O(total), not O(page) — ~17 buffers per
entity, 1.3M buffer touches, to display 25.

Warm, that is 1.4s. It is 1.4s only because the data is in cache; nothing is
read from storage. That is the entire fragility — see `issues/143`: the
maintenance job scans the quad table every 300s and evicts exactly this. Same
SQL, 9x spread in the log, ~40s as reported.

## The fast path exists, is the right shape, and is empty

`{space}_entity_slot_sort` exists precisely to make this page O(page):
`fast_slot_sort.py` serves a single sort criterion over a typed entity
population directly from the denormalised table.

On prod:

    prod_kg_entity_slot_sort      17,260 rows      3.6 MB
    prod_kg_frame_entity               0 rows
    prod_kg_edge               3,214,313 rows      617 MB

Broken down, the table contains **one entity type — the very type the slow page
lists** — and:

    slot_rows  17,267        entities  507

**507 of ~76,682 entities. 0.66% coverage.** So the table is not unused-by-
design; it is the correct table for this exact query, built and then never
filled. The logged query references none of `entity_slot_sort`, `frame_entity`,
or `edge` — it fell back, and the fallback is the O(total) scan above.

## Why nothing noticed

`_run_entity_slot_sort_integrity` (maintenance_job.py) exists to catch this. It
calls `entity_slot_sort_drift`, which computes `expected` as:

```python
expected = await conn.fetchval(
    f"SELECT count(*) FROM (SELECT DISTINCT slot_uuid, context_uuid FROM ("
    f"{_select_rows(space_id, 'TRUE')}) s) d", *args)
```

`_select_rows(space_id, 'TRUE')` is the **full unseeded `WITH RECURSIVE
frame_walk`** — O(graph), not O(change). Measured on prod: **it does not
complete in 120 seconds.** The deployed build runs maintenance with
`statement_timeout = 60s`.

The caller:

```python
try:
    async with self._pool.acquire() as conn:
        expected, actual = await entity_slot_sort_drift(conn, space_id)
except Exception:
    continue  # space predates the table, or is not a KG space
```

A bare `except Exception: continue` whose comment asserts a benign cause. A
statement timeout is not that cause, but it is caught by the same clause. So
every cycle, for months: the drift probe times out, the exception is swallowed
as "not a KG space", and the space is skipped. The backfill that would populate
the table **has never run for this space and cannot report that it did not**.

That is the whole failure: a self-healing mechanism disabled by its own health
check being too slow to finish, with the failure absorbed by an `except` that
was written for a different situation.

## The three defects, separable

1. **`entity_slot_sort` is 0.7% populated** → the listing page is O(total).
   Repair: `resync_entity_slot_sort` (`scripts/repair_derived_tables.py`).
2. **The drift probe cannot finish** → the seeded-walk fix already measured
   (24,571→1,473ms, 16,897→467ms, 8,452→300ms, 5,934→32ms; row-identical on
   prod) makes it viable. Currently uncommitted.
3. **`except Exception: continue` hides a timeout as "not a KG space".** Even
   with 1 and 2 fixed this must be narrowed — distinguish "table absent" from
   "probe failed", and log the latter at WARNING. A silent skip of a repair step
   is the reason this ran for months unnoticed.

Defect 3 is the one that matters beyond this incident: it is the same shape as
`issues/140` (a swallowed `UnboundLocalError` that silently disabled a plan
optimisation). Two independent instances of "the code fell back correctly and
said nothing" is a pattern, not a coincidence.

## Order of operations

1. Land the seeded walk (defect 2) — it is also the fix for the live 10.9x
   write regression, so it is wanted regardless.
2. Narrow the `except` (defect 3) so the next failure is visible.
3. Then run the backfill (defect 1), which the maintenance job will do on its
   own once 2 is in — but running it deliberately is faster and observable.

Do not run the backfill first. Without 2 and 3 it will drift back out and go
quiet again, which is exactly the history this issue records.

## Verifying

After backfill, the same page should stop referencing `rdf_quad` for the sort
and drop from 1.3M buffers to O(page). Re-run the `EXPLAIN (ANALYZE, BUFFERS)`
above and compare loop counts — 77,310 is the number to watch, not the
milliseconds, because milliseconds move with cache state (`issues/143`).
