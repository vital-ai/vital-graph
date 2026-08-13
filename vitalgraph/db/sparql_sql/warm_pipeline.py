"""Warm the SPARQL→SQL pipeline so the first USER query does not pay for it.

MEASURED 2026-08-13, same KGQuery five times in a fresh process:

    run   sidecar    generate    execute     TOTAL
      1     87.6     1,190.2      787.1    2,064.8 ms
      2     14.0         5.2       56.8       76.0 ms
      5     11.0         4.3       60.5       75.8 ms

27x, and the dominant term is SQL GENERATION — 1,190 ms against 5 ms warm, a
229x difference that has nothing to do with PostgreSQL's buffer pool. It is:

* the module-global caches in `generator.py` — `_term_cache`, `_datatype_cache`,
  quad/pair statistics, edge fan-out — all empty in a fresh process;
* ~177 ms of Python first-call cost, because the generator imports inside
  functions;
* cold reads of the per-space `rdf_stats` table, which every generation step
  consults and which is 1 GB at 0.4% residency on the 100k fixture;
* plus the sidecar's first HTTP call and JVM warm-up, 88 ms against 12 ms.

WHAT A TRIVIAL QUERY BUYS, measured rather than assumed:

    cold, no warm-up                    2,064.8 ms
    after one `?s ?p ?o LIMIT 1`          429.1 ms
    fully warm (same shape twice)         113.0 ms

So a single cheap query absorbs the sidecar connection, the Python first-call
cost and the shared caches — most of the penalty — for any query shape. It
cannot absorb the rest: 43 ms of generation and 358 ms of execution remain,
because those are SHAPE-SPECIFIC (that query's own predicate statistics, and its
own table and index pages). Warming every shape is not possible; warming the
shared foundation is, and that is what this does.

This is deliberately NOT `pg_prewarm`. Prewarming the quad tables addresses the
smallest term — emptying the buffer pool entirely costs only 25%, measured by
restarting the server. The expensive layer is in this process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

# Per space. A trivial query on a reachable space is fast; anything slower than
# this means the space is unhealthy or the sidecar is down, and warming must not
# turn that into a stalled startup.
_PER_SPACE_TIMEOUT_S = 20.0

# The cheapest query that still traverses the whole pipeline: sidecar compile,
# plan collection, emit, constant materialization, statistics loading, and one
# real execution against the space's own tables.
_WARM_SPARQL = "SELECT ?s WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }} LIMIT 1"


async def warm_space(backend, space_id: str, graph_uri: str) -> float | None:
    """Run one trivial query through the full pipeline. Returns ms, or None.

    Never raises: a space that cannot answer is a space that will not benefit,
    and startup must not depend on it.
    """
    sparql = _WARM_SPARQL.format(graph=graph_uri)
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            backend.execute_sparql_query(space_id, sparql),
            timeout=_PER_SPACE_TIMEOUT_S)
        # `execute_sparql_query` reports failure by FLAG, not by raising
        # (`issues/082`), so a space whose tables are gone would otherwise be
        # counted as warmed. Reporting 85 warmed and 0 skipped while 9 of them
        # failed is exactly the kind of untrue summary that issue is about.
        if isinstance(result, dict) and result.get("success") is False:
            logger.debug("Query warm-up for %s skipped: %s",
                         space_id, result.get("error"))
            return None
    except asyncio.TimeoutError:
        logger.warning("Query warm-up for %s timed out after %.0fs",
                       space_id, _PER_SPACE_TIMEOUT_S)
        return None
    except Exception as e:
        logger.debug("Query warm-up for %s skipped: %s", space_id, e)
        return None
    return (time.perf_counter() - t0) * 1000.0


def warm_enabled() -> bool:
    """`VITALGRAPH_WARM_QUERY_PIPELINE=0` turns this off.

    Worth having a switch: this runs on the startup path and issues a query
    against every space, so an operator debugging a slow or unhealthy start
    needs to be able to take it out of the picture without a code change.
    """
    return os.environ.get("VITALGRAPH_WARM_QUERY_PIPELINE", "1") != "0"


def warm_max_spaces() -> int:
    try:
        return int(os.environ.get("VITALGRAPH_WARM_MAX_SPACES", "0"))
    except ValueError:
        return 0


async def warm_query_pipeline(space_manager, max_spaces: int = 0) -> dict:
    """Warm the pipeline once per space. Returns a small summary.

    Sequential on purpose. The point is to populate shared caches and pull each
    space's statistics into the buffer pool, and doing that concurrently across
    dozens of spaces would compete with whatever real traffic has already
    arrived — this runs in the background precisely so it can afford to be slow.

    `max_spaces=0` means all of them. The FIRST space is the valuable one: it
    absorbs the process-global costs (imports, sidecar connection, datatype
    cache), which is most of the penalty. Later spaces only warm their own
    statistics, so capping this is a reasonable trade on an instance with very
    many spaces.
    """
    summary = {"warmed": 0, "skipped": 0, "first_ms": None, "total_ms": 0.0}
    if not warm_enabled():
        logger.info("Query pipeline warm-up disabled "
                    "(VITALGRAPH_WARM_QUERY_PIPELINE=0)")
        return summary
    max_spaces = max_spaces or warm_max_spaces()
    try:
        # Orphaned spaces — a record whose tables are gone — cannot be warmed
        # and produce a SQL-generation error apiece on every startup.
        if hasattr(space_manager, "list_active_spaces"):
            space_ids = space_manager.list_active_spaces()
        elif hasattr(space_manager, "get_active_space_ids"):
            space_ids = space_manager.get_active_space_ids()
        else:
            space_ids = list(getattr(space_manager, "_spaces", {}).keys())
    except Exception as e:
        logger.warning("Query warm-up: could not enumerate spaces: %s", e)
        return summary

    if max_spaces:
        space_ids = list(space_ids)[:max_spaces]

    t_start = time.perf_counter()
    for space_id in space_ids:
        try:
            record = await space_manager.get_space_or_load(space_id)
            if not record or not getattr(record, "space_impl", None):
                summary["skipped"] += 1
                continue
            backend = record.space_impl.get_db_space_impl()
            if backend is None:
                summary["skipped"] += 1
                continue
            # The graph URI is not known generically, and it does not need to
            # be: the pipeline work being warmed happens before any graph is
            # matched, so a graph that binds nothing warms exactly the same
            # caches. Using the space's own convention when available keeps the
            # execution half meaningful too.
            graph = getattr(record, "graph_uri", None) or f"urn:{space_id}"
            ms = await warm_space(backend, space_id, graph)
        except Exception as e:
            logger.debug("Query warm-up for %s failed: %s", space_id, e)
            summary["skipped"] += 1
            continue

        if ms is None:
            summary["skipped"] += 1
            continue
        if summary["first_ms"] is None:
            summary["first_ms"] = round(ms, 1)
        summary["warmed"] += 1

    summary["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 1)
    return summary
