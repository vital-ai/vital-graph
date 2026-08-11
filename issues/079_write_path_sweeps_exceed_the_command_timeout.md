# The WHERE-Bound Delete Sweep Cannot Finish — 181s Against a 60s Timeout

## Status: OPEN — measured 2026-08-11 on `sp_lead_synth_100k`

    cleanup_orphan_edges scan, 4,977,000 edge rows, ZERO orphans:
        Execution Time: 181,212 ms   (3 minutes 1 second)
        asyncpg command_timeout:      60,000 ms

It is cancelled at 60s, every time, on a healthy space.

## Where it runs, which is the problem

`sparql_sql_space_impl.py:1897` — INLINE in the SPARQL UPDATE request path:

```python
if _has_where_bound_delete(cr.update_ops):
    async with conn.transaction():
        await cleanup_stale_frame_entity(conn, space_id)
        await cleanup_orphan_edges(conn, space_id)
except Exception as ee:
    logger.debug("edge sync after SPARQL UPDATE failed (non-critical): %s", ee)
```

So on a space of this size, every WHERE-bound `DELETE`:

1. adds up to 60s of latency AFTER the update itself has done its work;
2. never completes the sweep, so **the cleanup `issues/064` added does not
   happen at all** — the orphans it exists to remove stay;
3. rolls back `cleanup_stale_frame_entity` with it, since both are in the same
   transaction, losing that work too;
4. reports none of this. The handler catches everything, calls it
   "non-critical", and logs at DEBUG.

`issues/064` closed on the strength of this sweep. The sweep is correct and it
cannot run.

## Why it is O(edge table) even though it has a LIMIT

    DELETE FROM {space}_edge WHERE ctid IN (
        SELECT e.ctid FROM {space}_edge e
        WHERE NOT EXISTS (SELECT 1 FROM {space}_rdf_quad q WHERE ...)
        LIMIT {limit})

The `LIMIT` bounds rows DELETED, not rows SCANNED. When there is nothing to
delete — the healthy case, and the common one — PostgreSQL must probe every one
of the 4.98M edge rows before it can conclude the answer is empty. The bound
does nothing precisely when the sweep is cheapest to skip.

This is the same shape as `issues/070` and `073`: proving absence costs a full
scan, and absence is the normal state.

## What to do

* **Do not run an unbounded sweep inline in a request.** It belongs in
  `MaintenanceJob`, which already runs edge integrity on a cadence and has a
  connection that is not answering a user.
* **Bound the SCAN, not the deletions** — e.g. sweep a ctid range or a sampled
  window per tick, so each pass is fixed-cost and repeated ticks converge. The
  existing `edge_table_orphan_rate` already samples this way.
* **Stop swallowing it.** A sweep that never completes should be visible; DEBUG
  and "non-critical" is how this went unnoticed since `064` landed.

---

# Second finding: the bulk-load index rebuild is approaching the same bound

## Measured on the same fixture, `sp_lead_synth_100k_rdf_quad`, 50,570,000 rows

    CREATE INDEX (plain)          21,879 ms
    CREATE INDEX CONCURRENTLY     40,983 ms      68% of the 60s command_timeout

`recreate_indexes_after_bulk_load` defaults to `concurrent=True`, so the DEFAULT
path is the slow one. At the term table's projected 10x this is several minutes
per index against a 60s bound.

## The transactional path is safe; the public pair is not

`bulk_load_with_index_rebuild` drops indexes, COPYs, and recreates them inside
the caller's transaction, so a timeout rolls the drops back — DDL is
transactional in PostgreSQL, and both call sites (`_do_bulk` via the pool, and
the `connection=` form, which takes its conn from a `transaction` object) are
covered. Verified.

`drop_indexes_for_bulk_load` and `recreate_indexes_after_bulk_load` are separate
public methods, each acquiring its OWN pooled connection with no shared
transaction. Used that way — as `test_scripts/data/reload_test_data.py` does —
a timeout during the recreate leaves the space with SOME OR NO INDEXES, and both
methods report failure by returning `False`.

Worse for the default: a cancelled `CREATE INDEX CONCURRENTLY` leaves an INVALID
index behind, which PostgreSQL will not use and which must be dropped by hand.

## What to do

* Give the drop/recreate pair a shared transaction, or document that the caller
  must supply one — a bare `False` return after dropping indexes is not a
  recoverable contract.
* Raise or disable `command_timeout` for index DDL specifically. 60s is a query
  fence; an index build is not a query.
* Measure the rebuild at 10x before relying on it there.

## Related

- `issues/064` — the sweep this measures; it closed on work that cannot run.
- `issues/044` — flagged this exposure as a live risk and never measured it.
- `issues/070` / `073` — proving absence costs a full scan.
