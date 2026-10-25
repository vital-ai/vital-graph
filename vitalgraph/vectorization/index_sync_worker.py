"""Consumers of the per-space index sync queue (`issues/291`).

One `IndexSyncWorker` per app process runs a fixed number of consumers. Each
consumer takes a space that has due rows, claims a batch (`index_sync_queue`),
syncs it with `auto_sync.sync_subjects` -- which holds no connection across the
embedding call -- and completes or fails the batch. Every process runs
consumers against the same tables, so adding ECS tasks adds consumers; claims
are `SKIP LOCKED` with a lease, so they never take the same rows.

WHY A BOUNDED SET. The fire-and-forget task this replaces ran one sync per
write with no limit, each holding an internal-pool connection through the
provider call. A burst of uploads filled the 3-connection pool, everything
else on it waited, and an acquire that waited 15 s failed its sync with
nothing to retry it. Here the number of syncs in flight is the number of
consumers, and a failure is retried with backoff.

WAKING. Enqueue NOTIFYs `index_sync_queue.NOTIFY_CHANNEL` with the space's
name prefix (`space_names.space_prefix`), which is all the capture trigger can
derive from its table; one LISTEN connection per process receives it. A sweep every
`sweep_seconds` asks each space whether anything is due, which covers a missed
notification, a retry whose backoff ran out and a lease that expired.

Default consumers: one less than the internal pool, at least one, so the
segmentation worker, ANALYZE and the maintenance job always have a
connection. `VG_INDEX_SYNC_CONSUMERS` overrides it.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import socket
import uuid
from collections import defaultdict
from typing import Dict, List, Optional, Set

from . import index_sync_queue as q
from vitalgraph.db.sparql_sql.space_names import space_id_for_prefix, space_prefix

logger = logging.getLogger(__name__)


def _uuid(uri: str) -> uuid.UUID:
    from .auto_sync import _generate_term_uuid
    return _generate_term_uuid(uri)


_VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
_HALEY = "http://vital.ai/ontology/haley-ai-kg#"
_SLOT_EDGE = f"{_HALEY}Edge_hasKGSlot"
_FRAME_EDGE = f"{_HALEY}Edge_hasEntityKGFrame"
_GEO_SLOT = f"{_HALEY}KGGeoLocationSlot"

_PRESENT_SQL = """
SELECT DISTINCT subject_uuid FROM {quad}
WHERE context_uuid = $1 AND subject_uuid = ANY($2::uuid[])
"""

# GEO SLOTS DEPEND ON EDGES. `geo_slot_handler` attributes a slot's location to
# its entity through Edge_hasKGSlot (frame -> slot) and Edge_hasEntityKGFrame
# (entity -> frame). An edge-only change -- a slot or frame re-parented --
# changes no slot quad, so the trigger queues only the edge. This adds the geo
# slots such an edge reaches, so their attribution is re-derived. Only GEO
# slots: re-syncing every slot would re-embed them for nothing.
#
# THE TYPES ARE LITERALS, NOT PARAMETERS (`issues/309`). asyncpg prepares this
# once per connection, and PostgreSQL may switch a prepared statement to a
# GENERIC plan after five runs. With the six type URIs passed as `$3`-`$8`, the
# generic plan priced each type lookup at ~11 rows by default selectivity,
# nested loops through every `Edge_hasKGSlot` of the graph (3,984,555 on the
# largest production space), and lost the early exit on the geo-slot side:
# 26,954 calls at a mean 4.4 s and ~3.7M buffers, 926 more cancelled at 60 s,
# 0 rows every time. Custom-planned, the same batch took 3.3 ms. Only the graph
# and the subjects vary per call.
#
# `geo` guards the whole statement: uncorrelated, it is one InitPlan evaluated
# first, and a graph with no geo slot (most of them) skips everything else
# whatever plan was chosen.
_GEO_SLOTS_OF_EDGES_TEMPLATE = """
WITH e AS (
  SELECT q.subject_uuid AS edge, q.object_uuid AS etype FROM {quad} q
  WHERE q.context_uuid = $1 AND q.subject_uuid = ANY($2::uuid[])
    AND q.predicate_uuid = '{vt}'::uuid AND q.object_uuid IN ('{se}'::uuid, '{fe}'::uuid)
), d AS (
  SELECT e.etype, q.object_uuid AS dest FROM e
  JOIN {quad} q ON q.subject_uuid = e.edge AND q.context_uuid = $1
               AND q.predicate_uuid = '{dst}'::uuid
), slots AS (
  SELECT dest AS slot FROM d WHERE etype = '{se}'::uuid
  UNION
  SELECT qd.object_uuid FROM d
  JOIN {quad} qs ON qs.context_uuid = $1 AND qs.predicate_uuid = '{src}'::uuid
                AND qs.object_uuid = d.dest
  JOIN {quad} qt ON qt.subject_uuid = qs.subject_uuid AND qt.context_uuid = $1
                AND qt.predicate_uuid = '{vt}'::uuid AND qt.object_uuid = '{se}'::uuid
  JOIN {quad} qd ON qd.subject_uuid = qs.subject_uuid AND qd.context_uuid = $1
                AND qd.predicate_uuid = '{dst}'::uuid
  WHERE d.etype = '{fe}'::uuid
)
SELECT DISTINCT s.slot FROM slots s
JOIN {quad} g ON g.subject_uuid = s.slot AND g.context_uuid = $1
             AND g.predicate_uuid = '{vt}'::uuid AND g.object_uuid = '{geo}'::uuid
WHERE EXISTS (SELECT 1 FROM {quad} x WHERE x.context_uuid = $1
                AND x.predicate_uuid = '{vt}'::uuid AND x.object_uuid = '{geo}'::uuid)
"""


@functools.lru_cache(maxsize=None)
def _geo_slots_of_edges_sql(quad: str) -> str:
    """The geo-slot lookup for one quad table, its types filled in as literals.
    Only `$1` (graph) and `$2` (subjects) remain parameters."""
    return _GEO_SLOTS_OF_EDGES_TEMPLATE.format(
        quad=quad, vt=_uuid(_VITALTYPE), se=_uuid(_SLOT_EDGE), fe=_uuid(_FRAME_EDGE),
        src=_uuid(_EDGE_SRC), dst=_uuid(_EDGE_DST), geo=_uuid(_GEO_SLOT))


async def resolve(conn, space_id: str, context_uuid: uuid.UUID,
                  subject_uuids: List[uuid.UUID]):
    """`(upsert, delete)` for these subjects, from the data.

    A subject with quads left in the graph is re-derived; one without is
    removed from the indexes. Plus the geo slots an edge among the upserts
    reaches.
    """
    quad = f"{space_prefix(space_id)}_rdf_quad"
    present = {r["subject_uuid"] for r in await conn.fetch(
        _PRESENT_SQL.format(quad=quad), context_uuid, list(subject_uuids))}
    absent = [s for s in subject_uuids if s not in present]
    upsert = list(present)
    if present:
        # Custom-planned every call as well (`issues/309`): planning it costs
        # well under a millisecond, and a generic plan is what made it slow.
        async with conn.transaction():
            await conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
            extra = {r["slot"] for r in await conn.fetch(
                _geo_slots_of_edges_sql(quad), context_uuid, upsert)}
        upsert += [s for s in extra if s not in present]
    return upsert, absent


async def _sync_graph(pool, space_id: str, context_uuid: uuid.UUID,
                      subject_uuids: List[uuid.UUID]) -> bool:
    """Resolve, then sync the upserts and the deletes. False if the space is gone."""
    from .auto_sync import _space_still_exists, sync_subjects
    async with pool.acquire() as conn:
        if not await _space_still_exists(conn, space_id):
            return False
        upsert, delete = await resolve(conn, space_id, context_uuid, subject_uuids)
    if delete and not await sync_subjects(pool, space_id, delete, context_uuid, "delete"):
        return False
    if upsert and not await sync_subjects(pool, space_id, upsert, context_uuid, "upsert"):
        return False
    return True

DEFAULT_BATCH_SIZE = 100
DEFAULT_SWEEP_SECONDS = 10.0


def _default_consumers(pool) -> int:
    env = os.environ.get("VG_INDEX_SYNC_CONSUMERS")
    if env:
        return max(1, int(env))
    try:
        size = pool.get_max_size()
    except Exception:
        size = 3
    return max(1, size - 1)


class IndexSyncWorker:

    def __init__(self, space_manager, *, consumers: Optional[int] = None,
                 batch_size: int = DEFAULT_BATCH_SIZE,
                 lease_seconds: int = q.DEFAULT_LEASE_SECONDS,
                 sweep_seconds: float = DEFAULT_SWEEP_SECONDS):
        self._space_manager = space_manager
        self._consumers = consumers
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._sweep_seconds = sweep_seconds
        self.consumer_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._ready: asyncio.Queue = asyncio.Queue()
        self._marked: Set[str] = set()
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._listen_conn = None
        self._tasks: List[asyncio.Task] = []
        self._claimed_in: Set[str] = set()
        # Spaces this process never drains, by prefix -- for a stack whose
        # in-process tests assert on queue rows themselves.
        self._excluded = tuple(
            p.strip() for p in os.environ.get(
                "VG_INDEX_SYNC_EXCLUDE_PREFIXES", "").split(",") if p.strip())
        self.synced = 0
        self.failed = 0

    # -- lifecycle ---------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def run(self) -> None:
        pool = await self._any_pool()
        n = self._consumers or (_default_consumers(pool) if pool is not None else 1)
        logger.info("Index sync worker %s: %d consumer(s), batch %d",
                    self.consumer_id, n, self._batch_size)
        await self._listen(pool)
        self._tasks = [asyncio.create_task(self._consume(i), name=f"index_sync:{i}")
                       for i in range(n)]
        try:
            while not self._stop.is_set():
                try:
                    await self._sweep()
                except Exception as e:
                    logger.warning("index sync sweep failed: %s: %s", type(e).__name__, e)
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._sweep_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            await self._release_claims()
            if self._listen_conn is not None:
                try:
                    await self._listen_conn.close()
                except Exception:
                    pass
            logger.info("Index sync worker %s stopped (%d synced, %d failed)",
                        self.consumer_id, self.synced, self.failed)

    async def _release_claims(self) -> None:
        for sp in sorted(self._claimed_in):
            try:
                pool = await self._pool(sp)
                if pool is None:
                    continue
                async with pool.acquire() as conn:
                    if await q.table_exists(conn, sp):
                        n = await q.release(conn, sp, self.consumer_id)
                        if n:
                            logger.info("index sync: released %d claimed row(s) in %s", n, sp)
            except Exception as e:
                logger.warning("index sync: could not release claims in %s: %s", sp, e)

    # -- discovery ---------------------------------------------------------

    def _space_ids(self) -> List[str]:
        sm = self._space_manager
        try:
            if hasattr(sm, "list_active_spaces"):
                return list(sm.list_active_spaces())
            if hasattr(sm, "get_active_space_ids"):
                return list(sm.get_active_space_ids())
            return list(getattr(sm, "_spaces", {}).keys())
        except Exception as e:
            logger.warning("index sync: could not list spaces: %s", e)
            return []

    async def _db_impl(self, space_id: str):
        record = await self._space_manager.get_space_or_load(space_id)
        if not record:
            return None
        backend = record.space_impl.get_db_space_impl()
        if not backend:
            return None
        return getattr(backend, "db_impl", None) or getattr(backend, "_db", None) or backend

    async def _pool(self, space_id: str):
        from ..db.pool import internal_pool_for
        db_impl = await self._db_impl(space_id)
        return internal_pool_for(db_impl) if db_impl is not None else None

    async def _any_pool(self):
        for sp in self._space_ids():
            try:
                pool = await self._pool(sp)
            except Exception:
                continue
            if pool is not None:
                return pool
        return None

    def _mark(self, space_id: str) -> None:
        if space_id.startswith(self._excluded) and self._excluded:
            return
        if space_id not in self._marked:
            self._marked.add(space_id)
            self._ready.put_nowait(space_id)

    async def _listen(self, pool) -> None:
        """One LISTEN connection, outside the pools: it is never returned."""
        kwargs = getattr(pool, "_connect_kwargs", None) if pool is not None else None
        if not kwargs:
            logger.warning("index sync: no LISTEN connection; the %.0fs sweep "
                           "alone will find work", self._sweep_seconds)
            return
        try:
            import asyncpg
            self._listen_conn = await asyncpg.connect(**kwargs)
            await self._listen_conn.add_listener(
                q.NOTIFY_CHANNEL,
                lambda _c, _p, _ch, payload: self._mark(space_id_for_prefix(payload)))
        except Exception as e:
            self._listen_conn = None
            logger.warning("index sync: LISTEN failed (%s: %s); relying on the sweep",
                           type(e).__name__, e)

    async def _sweep(self) -> None:
        for sp in self._space_ids():
            if self._stop.is_set():
                return
            if sp in self._marked:
                continue
            pool = await self._pool(sp)
            if pool is None:
                continue
            async with pool.acquire() as conn:
                if await q.table_exists(conn, sp) and await q.has_due(conn, sp):
                    self._mark(sp)

    # -- consuming ---------------------------------------------------------

    async def _consume(self, i: int) -> None:
        while not self._stop.is_set():
            space_id = await self._ready.get()
            self._marked.discard(space_id)
            try:
                n = await self.drain_once(space_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("index sync consumer %d on %s: %s: %s",
                             i, space_id, type(e).__name__, e)
                n = 0
            if n >= self._batch_size:
                self._mark(space_id)   # more is probably waiting

    async def drain_once(self, space_id: str) -> int:
        """Claim one batch of `space_id` and sync it. Returns rows claimed."""
        import asyncpg
        from .auto_sync import _IN_FLIGHT
        pool = await self._pool(space_id)
        if pool is None:
            return 0
        try:
            async with pool.acquire() as conn:
                claimed = await q.claim(conn, space_id, self.consumer_id,
                                        self._batch_size, self._lease_seconds)
        except asyncpg.exceptions.UndefinedTableError:
            return 0          # deleted, or not migrated
        if not claimed:
            return 0
        self._claimed_in.add(space_id)

        # By graph, NOT by the rows' `operation`: the trigger queues every
        # change as an upsert, and the operation is decided from the data in
        # `_sync_graph` (`issues/291` step 2).
        groups: Dict[uuid.UUID, List[q.Claimed]] = defaultdict(list)
        for c in claimed:
            groups[c.context_uuid].append(c)

        done: List[q.Claimed] = []
        failed: List[tuple] = []
        for ctx, rows in groups.items():
            # Registered with the space's in-flight set, so deleting the space
            # cancels a sync in progress here as it did a scheduled one.
            task = asyncio.ensure_future(
                _sync_graph(pool, space_id, ctx, [r.subject_uuid for r in rows]))
            inflight = _IN_FLIGHT.setdefault(space_id, set())
            inflight.add(task)
            try:
                exists = await task
            except asyncio.CancelledError:
                if self._stop.is_set():
                    raise
                return len(claimed)       # the space is being deleted
            except Exception as e:
                failed.append((rows, f"{type(e).__name__}: {e}"))
                continue
            finally:
                inflight.discard(task)
                if not inflight:
                    _IN_FLIGHT.pop(space_id, None)
            if not exists:
                return len(claimed)       # the space is gone; its table with it
            done.extend(rows)

        try:
            async with pool.acquire() as conn:
                if done:
                    await q.complete(conn, space_id, self.consumer_id, done)
                for rows, err in failed:
                    await q.fail(conn, space_id, self.consumer_id, rows, err)
        except asyncpg.exceptions.UndefinedTableError:
            return len(claimed)
        self.synced += len(done)
        for rows, err in failed:
            self.failed += len(rows)
            worst = max(r.attempts for r in rows)
            log = logger.error if worst >= 5 else logger.warning
            log("index sync %s: %d subject(s) failed (attempt %d), retrying in %ds: %s",
                space_id, len(rows), worst, q.backoff_seconds(worst), err)
        return len(claimed)
