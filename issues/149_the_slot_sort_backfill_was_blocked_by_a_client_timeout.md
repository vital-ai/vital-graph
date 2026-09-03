# The Slot-Sort Backfill Never Ran Because The Driver Gave Up At 60s

## Status: FIXED in code, UNDEPLOYED. The listing is slow until this ships and
## the backfill runs.

## The user-visible fact

The entity listing for the largest type takes 22.7s measured
(`LIST_ENTITIES query=22695ms` against a Postgres `duration: 22652ms` — a 43ms
gap, so it is real execution, not a lock wait; `issues/145` is not involved).
Reported by users at ~45s with offset and variance.

## Why it is slow

`{space}_entity_slot_sort` exists to make this page O(page). Coverage, measured
2026-09-03 by counting entities from the QUADS:

    entity type                          in table      of type   coverage
    urn:...:NurtureAction                     809       76,996      1.05%
    urn:...:KGBusiness                          0        1,254      0.00%
    urn:...:KGLead                              0        1,254      0.00%
    urn:...:<Client>Person                       0          123      0.00%

With 1% of the type present the derived table cannot serve the page, so the
query does a full frame walk.

## Why it never got repaired — and it is NOT the walk

The obvious hypothesis, which several readings reached including mine, is that
the derivation walk cannot see these entities, so a resync would reproduce the
same 809. **Measured, and false:**

    WALK YIELDS: entities=79,630   slot_rows=2,828,447   (133s)
    TABLE HAS  : entities=   812   slot_rows=   26,890

The walk reaches essentially every entity. The table is simply ~1% filled, and a
resync WOULD fix it.

The real blocker is a timeout in the wrong layer. `entity_slot_sort_drift` takes
**97-133s** on this space. The asyncpg pool is built with
`command_timeout=60` — a CLIENT-side bound that fires in the driver,
independently of the server. `maintenance_job.probe_timeouts` raises
`statement_timeout` with SET, which is the SERVER half and cannot affect it. So
the driver abandoned the call at 60s and raised a bare `TimeoutError`:

    entity_slot_sort_integrity: drift probe FAILED for <space> (TimeoutError: )

every cycle, forever. The probe that gates the backfill had never completed, so
the backfill had never run.

Note the drift probe itself is CORRECT. Run with a longer client timeout it
reports what it should:

    expected=2,742,764  actual=26,671  drift=2,716,093  would_backfill=True

## The fixes

1. **Pass a client-side timeout.** Both probes now take `timeout=` and the
   maintenance job passes `PROBE_CLIENT_TIMEOUT_S`, matched to the maintenance
   budget rather than the read path's. Raising `statement_timeout` alone was
   never going to be enough, and the failure looked identical to a server
   timeout, which is what made it hard to see.

2. **A coverage probe that cannot be fooled by its own input.**
   `entity_slot_sort_drift` compares the table against `_select_rows` — the same
   walk that POPULATES it. When the walk is at fault the two agree exactly and
   it reports converged. `entity_slot_sort_coverage` counts entities from the
   quads, which no derived table can influence, and the maintenance job now logs
   a WARNING naming the user-visible consequence:

       entity_slot_sort coverage: <space> type <type> has 809 of 76,996
       entities (1.05%) — queries sorting this type cannot use the derived
       table and will do a full frame walk

   This is `issues/141` in a different table: there the stats audit "sampled the
   end that cannot be wrong". Same defect class — a check whose input is
   downstream of the thing being checked.

3. **Bound the oversized-pair count** (`maintenance_job`). Unrelated to the
   listing but found in the same log: that probe did an unbounded `count(*)` per
   candidate and measured **14,610 ms** against a 2.7M-row pair, times
   `STATS_OVERSIZED_SAMPLE` candidates — up to ~175s of quad scanning per cycle.
   It only ever tests `actual > STATS_MAX_ROW_COUNT`, so it now saturates at
   cap+1, the pattern the semi-join gate already uses.

## What this does NOT fix

The listing endpoint `/api/graphs/kgentities` has **no wiring to the fast path at
all** — zero references to `fast_slot_sort` or `entity_slot_sort`. The only
wiring is in `/api/graphs/kgqueries`. So filling the table is necessary and not
sufficient: whether this page gets faster depends on which endpoint the client
calls. That is a separate, open decision and is recorded in `issues/144`.

## Correction to `issues/144`

144 claimed the listing "falls back" to the O(total) walk because the table was
0.6% populated. The two facts are both real and the causal link was not: the
endpoint never consults the table, so it is not falling back — it has no fast
path to fall back from. Inferred from the query touching only `rdf_quad` and
`term`, without checking whether the endpoint had code to do otherwise.
