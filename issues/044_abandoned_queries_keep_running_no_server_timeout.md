# A Client Giving Up Does Not Stop the Query — The Server-Side Fence Is Per-Statement, Not Per-Request

## Status: PARTLY FIXED — gaps 1, 2 and 5 closed; 3 and 4 remain — 2026-08-10

| gap | state |
|---|---|
| 1. fence is per-statement, not per-request | still open, but `047` removed what it was bounding |
| 2. `asyncio.gather` orphans the sibling | **FIXED** — `_gather_cancelling`, all 5 sites |
| 3. timers ordered backwards | **improved** — the server fence is now 55s against the client's 60s, so the server surfaces the error first. The per-request bound in (1) is the rest |
| 4. client disconnect not detected | still open — nothing calls `request.is_disconnected()` |
| 5. fence is client-driven, not DB-enforced | **FIXED** — `SET LOCAL statement_timeout` on the read path |

### Gap 5, closed 2026-08-10

`sparql_sql_space_impl._apply_read_fence` sets `SET LOCAL statement_timeout`
(default 55s, `VITALGRAPH_READ_STATEMENT_TIMEOUT_MS`, 0 disables) inside the
transaction that runs a SPARQL SELECT. Verified against the local cluster: the
fence fires with `QueryCanceledError`, `SHOW statement_timeout` is back to `'0'`
after COMMIT so nothing leaks onto the pooled connection, and 0 genuinely
disables it.

**Read path only, deliberately.** It is applied where SELECT executes, not on the
pool, so bulk load and index rebuild — which share that pool — are untouched.
This issue already records that `command_timeout` caps every COPY phase and
non-CONCURRENT `CREATE INDEX` at 60s today, which is a live risk on a large
load; adding a read-shaped fence to those would make it worse, not better.

The non-ordered-scan branch now also runs in a transaction, purely so `SET LOCAL`
is scoped. That is the only behavioural change to queries that were already fine.

## Original status: OPEN — researched 2026-08-07, remeasured 2026-08-08

The original diagnosis was partly wrong (see the correction below). The
remeasurement changes the *priorities*, not the findings: since `issues/040`,
`045` and `046` the page query is no longer a contributor at all, and the count
is the entire unbounded surface.

When a request exceeds the client's time budget the client stops waiting, but
PostgreSQL keeps executing. The work is not cancelled, the connection is not
released, and — because the client retries — a **second copy of the same slow
query starts while the first is still running**.

The first pass at this issue concluded there was *no* server-side fence at all.
That is not correct, and the correction matters: the fence exists, is 60s, and
the reason abandoned work still survives is five specific gaps in how it applies.

## Correction: a 60s server-side fence already exists

`vitalgraph/db/sparql_sql/sparql_sql_db_impl.py:138`:

```python
command_timeout=self.config.get('command_timeout', 60),
```

No config file sets `command_timeout` — not `vitalgraphdb-config-local.yaml`,
not `-production.yaml`, nothing in `.env` — so the hard-coded 60 applies
everywhere. `vitalgraph/db/pool.py` also sets `acquire_timeout=15`.

And asyncpg's `command_timeout` is a *real* cancel, not just a client-side
abandon. Verified against the local cluster: on timeout asyncpg sends a
PostgreSQL `CancelRequest` and the backend disappears from `pg_stat_activity`
immediately. An outer `task.cancel()` around a `fetch` does the same.

So the enforcement table is:

| | value | source |
|---|---|---|
| server per-statement cancel | 60s | `command_timeout` default, `sparql_sql_db_impl.py:138` |
| server pool acquire | 15s | `DEFAULT_ACQUIRE_TIMEOUT`, `pool.py:33` |
| client per-attempt read timeout | **60s** (was 30s — see below) | `LOCAL_CLIENT_TIMEOUT`, and the loader default |
| client per-call wall-clock budget | 60s | `request_budget`, `client_config_loader.py:224` |
| client retries | 3 | `LOCAL_CLIENT_MAX_RETRIES` |

## The five gaps that let work outlive the client anyway

### 1. The fence is per-statement; a request is many statements

One KGQuery request runs, on a single acquired connection: vector-index
metadata, FTS-index metadata and search-mapping prefetches
(`generator.py:623`, `:637`, `:654`), pair-statistics loads
(`_load_missing_pair_stats`), then the page query, then the count query. Each
gets its own independent 60s. **Nothing bounds the request as a whole.** This is
why the symptom reads as "no server-side timeout" even though a fence exists.

**2026-08-08: the two legs are now four orders of magnitude apart.** Measured on
the 22.4M-quad restored production copy, the standard high-cardinality criteria
(~34.6k matching entities):

| leg | before `issues/040` | now |
|---|---|---|
| page of 50 | 24.5–32.3 s | **2–10 ms** |
| count, capped at 1,000 | — | **51–130 s** |
| count, exact | — | did not finish in a 4-minute window |

So the request-level bound in (3) is really a bound on the count. Everything else
in a KGQuery request is now noise beside it.

### 2. `asyncio.gather` orphans the sibling query — confirmed

`kgquery_endpoint.py:286, 529, 716, 874, 1305` all run the page query and the
count query concurrently:

```python
results, count_results = await asyncio.gather(
    backend.execute_sparql_query(space_id, sparql_query, ...),
    backend.execute_sparql_query(space_id, count_query),
)
```

No `return_exceptions`. Python's `gather` propagates the first exception
immediately but does **not** cancel the remaining awaitables. Reproduced
directly: with one leg failing at 3s, the other leg's query was still in
`pg_stat_activity` 6s later and ran to completion, holding its pool connection
the whole time.

So whenever one leg errors or hits its 60s fence, the other becomes an orphan —
server-side work with no one waiting for it and no accounting.

**2026-08-08: still a real leak, but no longer the main source of orphaned
work.** When this was written the two legs were comparable in cost, so a failing
count stranded an expensive page query. With the page now at 2–10 ms, that
direction strands nothing worth measuring, and the reverse direction (page
fails, count orphaned) is rare. The bulk of "copies left running" is the count
outliving the *client*, which is gaps 3 and 4, not this one. Fix it anyway — it
is a confirmed defect, cheap and local, and it stops being harmless the moment
the two legs are comparable again.

### 3. The timers are ordered backwards

Client per-attempt is 30s; the server fence is 60s. The client therefore *always*
gives up first, and the abandoned query runs on to 60s or to completion — the
observed ~42s count query fits exactly. Then the retry starts a second copy.

`pool.py`'s own docstring states the intended ordering — *"Keep this comfortably
below the API client's own timeout so the server surfaces the failure first,
rather than the client timing out and retrying blind."* `acquire_timeout=15`
honours that. `command_timeout=60` does not.

### 4. Client disconnect is not detected at all

uvicorn 0.35 `protocols/http/httptools_impl.py:112-121`: `connection_lost` sets
`cycle.disconnected = True` and wakes the message event, but **never cancels the
ASGI task**. Nothing under `vitalgraph/` calls `request.is_disconnected()`
(zero hits). A handler whose client hung up runs to completion, burning CPU, a
pool slot and a database backend for a response nobody will read.

### 5. The fence is client-driven, not database-enforced

asyncpg's `command_timeout` fires from an event-loop callback. If the loop stalls
— a live enough concern that `vitalgraph/utils/event_loop_monitor.py` exists to
watch for it — or the worker is killed/restarted mid-query, that callback never
runs and the query is genuinely unbounded: PostgreSQL will not notice a dead
client on a long `SELECT` until it tries to return rows. A real
`statement_timeout` is enforced by the backend regardless of client health.

## The write-path concern in the original writeup is backwards

The original said writes and bulk loads must not inherit a read timeout. They
already do. Server-side bulk load acquires from the same shared pool
(`sparql_sql_space_impl.py:857` → `bulk_load.bulk_load_with_index_rebuild`), and
`command_timeout` bounds `copy_records_to_table` as well as `execute` — verified:
a COPY fed by a slow record iterator raised `TimeoutError` at the configured
limit. So every COPY phase and every non-CONCURRENT `CREATE INDEX` in the
rebuild path is already capped at 60s today, which is a live risk on a large
load, not a hypothetical one.

The `load_wordnet_csv` counter-example does not apply: it is a standalone script
with its own connection (`scripts/load_wordnet_csv.py:79` psycopg, `:204`
asyncpg), never on the server pool, so it is unaffected either way.

## `emit_path.py:44` — reword, don't delete

```
# only penalizes narrow deep paths. Runaway is fenced by statement_timeout +
```

Partly right after all. A 60s per-statement fence does exist; it is just
asyncpg's `command_timeout` rather than `statement_timeout`, and it bounds one
statement rather than the request. The comment should say that.

## Revised fix, in priority order

Reordered 2026-08-08. (1) is unchanged — it is a confirmed leak, cheap and local.
But the new (2) displaces the timeout-policy work, because a capped count that
cost tens of milliseconds instead of 51–130 s would leave nothing in a KGQuery
request that any reasonable fence would ever trip.

1. **Stop orphaning the sibling in `gather`** (5 sites). Wrap in tasks and
   cancel the survivor on first failure, or `return_exceptions=True` plus
   explicit cancellation. Cheap, local, no policy decision needed, and it
   removes a confirmed leak.
2. ~~**Fix `issues/047`**~~ — **DONE 2026-08-08.** It was the largest
   contributor to abandoned work, and the numbers this issue was built on no
   longer hold: a 100-row page went 48,034 → 4 ms, and a capped `total_count`
   51,368–130,751 → 40–52 ms. What is left that a fence would ever trip is
   `include_total_count=exact`, which is inherently O(matches) — 2.9–5.6 s on
   22.4M quads. **Re-derive the timer values in (3)–(6) against that**, not
   against the numbers recorded below.
3. **Reorder the timers.** The server fence must be below the client's
   per-attempt timeout, not above it — otherwise the client is guaranteed to
   abandon first, every time. Either lower the read-path fence or raise the
   client attempt timeout; they must not cross.
4. **Add a per-request bound**, not just per-statement — the metadata
   prefetches plus page plus count each carrying their own 60s is the actual
   unbounded surface.
5. **Set a real `statement_timeout`** on the read path so the limit survives a
   stalled loop or a dead worker, instead of relying on asyncpg to be alive to
   enforce it. `analytics_job.py:98` already does this
   (`SET LOCAL statement_timeout = '120s'`) and is the pattern to follow.
6. **Split read and write policy explicitly.** Today they share one pool and one
   number. Bulk load and index rebuild need their own — currently 60s, almost
   certainly by accident.
7. **Make timeout non-retryable in the client.** A cancelled-by-timeout query is
   not a transient fault; retrying it doubles load at the worst moment.
8. **Log at the boundary.** Abandoned work currently produces no log line
   anywhere — it surfaces only as unexplained database load.

### The numbers for (3)–(6), re-measured 2026-08-08 after issues/047

Everything recorded here before this date was taken either before `047` was
fixed or alongside an 18-hour orphaned scan, and both inflated it. Re-measured
on a quiet cluster, production copy, 22.4M quads, 34,423 matching entities:

| read leg | cold | warm |
|---|---|---|
| page of 1,000 | 80 ms | 40 ms |
| `include_total_count=yes` (capped 1,000) | 1,671 ms | 34 ms |
| `include_total_count=exact` | **11,081 ms** | 1,346 ms |

**The worst legitimate read is now ~11 s cold**, and it is the exact count —
inherently O(matches), which is why the cap exists. Everything else is under
two seconds cold and under 50 ms warm.

That makes the timer ordering tractable, where before it was not: no fence could
accommodate a 51–130 s capped count, so item (3) had no solution. It does now.

**Resolved 2026-08-08 by raising the client rather than lowering the server:**

    pool acquire         15 s   (unchanged)
    server read fence    60 s   (unchanged)
    client per-attempt   60 s   (was 30 s)
    client wall-clock    60 s   (unchanged)

`LOCAL_CLIENT_TIMEOUT` 30 -> 60, and the loader's fallback with it.
`PROD_CLIENT_TIMEOUT` was already 60, so this also removes a local/production
divergence that made the fault reproducible only locally.

This is the better direction than the 20-25 s server fence considered earlier.
Lowering the server would have required splitting read and write policy first,
since bulk load and index rebuild share the pool and legitimately run for
minutes — a prerequisite that no longer applies.

It also gets item (7) for free. Per-attempt now equals the wall-clock budget, so
a timed-out request has no room left to retry: a query cancelled for taking too
long is not a transient fault, and retrying it doubles load at the worst moment.

**The write path must not inherit this.** Bulk load and index rebuild acquire
from the same pool and are bounded by the same `command_timeout`, so a 20-25 s
read fence would break loads that legitimately run for minutes. Item (6) — split
read and write policy — becomes a prerequisite rather than a nicety.

**One caveat on the number.** 11 s is this dataset. Exact counts scale with the
match set, so a larger tenant is slower and no fixed fence bounds them. The
honest options are to give `exact` its own longer budget, or to treat it as a
request the server declines above some size rather than attempts. Choosing
needs the largest real tenant's match counts, which are not measurable here.

## Reproduce

Issue a KGQuery frame criteria against a large space with
`include_total_count=yes` — the parameter is now the `TotalCountMode` enum
`no` (default) | `yes` (capped at `TOTAL_COUNT_CAP`, 1,000) | `exact`, not a
boolean (see issues/040 for why the count is slow). Then while the client is
failing:

```sql
SELECT pid, state, now() - query_start AS age, left(query, 60)
FROM pg_stat_activity
WHERE state = 'active' AND query ILIKE '%rdf_quad%'
ORDER BY age DESC;
```

Queries remain after the client has returned its error, and a retry adds
another.

For gap 2 in isolation, no large dataset needed: `asyncio.gather` a
`pg_sleep(30)` with an awaitable that raises after 3s, then watch
`pg_stat_activity` — the sleep is still there.

## Related

- `issues/040` — where this surfaced; the slow count that triggered it is now
  opt-in and capped, which reduces how often this is hit but does not address it
- `issues/047` — the reason the count is slow, and the largest single source of
  abandoned work. Fix it before choosing any timer value here
- `issues/045`, `issues/046` — the two follow-on defects in the paging rewrite.
  Between them and `040` the page leg went from being the reason this issue
  existed to being irrelevant to it; the count leg did not move
- `scripts/probe_semijoin_entity_query.sh` — `PROBE_COUNT=cap|exact` reproduces
  the count timings above against the restored production copy
- `vitalgraph/db/pool.py` — the acquire fence, and the docstring stating the
  timer ordering the command timeout violates
- `vitalgraph/process/analytics_job.py:98` — the one place a real
  `statement_timeout` is already set
- `vitalgraph/db/sparql_sql/emit_path.py:44` — comment to reword
