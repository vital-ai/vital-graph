"""Finish segmentation jobs in 'vectorizing' once their subjects are synced.

A job is marked 'vectorizing' when its segments are stored; the index sync
workers then embed them from `{space}_index_sync_queue`. The job may say
'completed' only once none of its subjects is still queued.

This used to be one task PER JOB, each taking an internal-pool connection
every 0.5 s to ask the queue about its own subjects, then a second acquire
to write the status. A load that queued ~1,175 jobs in a minute ran that
many pollers on an internal pool of 3: acquires timed out, the job was
recorded 'completed' with the error "Vectorization task failed: " (a
TimeoutError's text is empty), and when the status write timed out as well
the job stayed 'vectorizing' for good -- although the index sync had
embedded every segment.

Now ONE completer per space, holding ONE connection per tick: a single
query finds which of every waiting job's subjects are still queued, and the
jobs that drained are completed in the same connection. A failed tick is
logged and retried; the jobs stay registered. Jobs that no process is
tracking (a restart, a cancelled task) are finished by `sweep`, which the
worker runs per space every few minutes.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Sequence

from vitalgraph.db.sparql_sql.space_names import space_prefix

logger = logging.getLogger(__name__)

POLL_SECONDS = 2.0
WAIT_SECONDS = 600.0
# A 'vectorizing' job untouched this long has no waiter left anywhere: every
# waiter gives up after WAIT_SECONDS and writes a status.
SWEEP_AFTER_SECONDS = 2 * WAIT_SECONDS
SWEEP_LIMIT = 1000


def error_text(prefix: str, exc: BaseException) -> str:
    """`prefix: TimeoutError` rather than `prefix: `: several exceptions,
    TimeoutError among them, have an empty str()."""
    detail = str(exc)
    return f"{prefix}: {type(exc).__name__}" + (f": {detail}" if detail else "")


def _uuid(text: str) -> uuid.UUID:
    from vitalgraph.vectorization.auto_sync import _generate_term_uuid
    return _generate_term_uuid(text)


@dataclass
class _Waiting:
    context_uuid: uuid.UUID
    subject_uuids: List[uuid.UUID]
    deadline: float
    error: Optional[str] = None


@dataclass
class _Space:
    jobs: Dict[int, _Waiting] = field(default_factory=dict)
    task: Optional[asyncio.Task] = None


class VectorizationCompleter:
    """One per segmentation worker. `pool_for(space_id)` returns the pool to
    use (the internal one), or None."""

    def __init__(self, pool_for: Callable[[str], Awaitable[object]], *,
                 poll: float = POLL_SECONDS, wait: float = WAIT_SECONDS):
        self._pool_for = pool_for
        self._poll = poll
        self._wait = wait
        self._spaces: Dict[str, _Space] = {}

    # -- registration ---------------------------------------------------

    def register(self, space_id: str, job_id: int, graph_uri: str,
                 subject_uris: Sequence[str], *, error: Optional[str] = None) -> None:
        """Wait for these subjects, then complete the job. With `error`, the
        job is completed with that error on the next tick, without waiting."""
        loop = asyncio.get_running_loop()
        s = self._spaces.setdefault(space_id, _Space())
        s.jobs[job_id] = _Waiting(_uuid(graph_uri), [_uuid(u) for u in subject_uris],
                                  loop.time() + self._wait, error)
        if s.task is None or s.task.done():
            s.task = loop.create_task(self._run(space_id),
                                      name=f"vectorize_completer:{space_id}")

    def tracked(self, space_id: str) -> List[int]:
        s = self._spaces.get(space_id)
        return list(s.jobs) if s else []

    def waiting(self) -> int:
        return sum(len(s.jobs) for s in self._spaces.values())

    async def stop(self) -> None:
        tasks = [s.task for s in self._spaces.values() if s.task and not s.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- the per-space loop ---------------------------------------------

    async def _run(self, space_id: str) -> None:
        s = self._spaces[space_id]
        while s.jobs:
            await asyncio.sleep(self._poll)
            try:
                await self.tick(space_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # The jobs stay registered; the next tick tries again.
                logger.warning("vectorize completer %s: %s (%d job(s) waiting)",
                               space_id, error_text("tick failed", e), len(s.jobs))

    async def tick(self, space_id: str) -> int:
        """One check of every waiting job in the space, on one connection.
        Returns how many jobs it finished."""
        s = self._spaces.get(space_id)
        if not s or not s.jobs:
            return 0
        pool = await self._pool_for(space_id)
        if pool is None:
            return 0
        jobs = dict(s.jobs)
        now = asyncio.get_running_loop().time()
        async with pool.acquire() as conn:
            queued = await _still_queued(conn, space_id, jobs.values())
            done, failed = [], {}
            for job_id, w in jobs.items():
                if w.error:
                    failed.setdefault(w.error, []).append(job_id)
                elif queued is None or not any(
                        (w.context_uuid, sub) in queued for sub in w.subject_uuids):
                    done.append(job_id)
                elif now >= w.deadline:
                    failed.setdefault(
                        f"vectorization still queued after {int(self._wait)}s", []
                    ).append(job_id)
            table = f"{space_prefix(space_id)}_segmentation_jobs"
            if done:
                await conn.execute(
                    f"UPDATE {table} SET status = 'completed', updated_at = NOW() "
                    f"WHERE job_id = ANY($1::int[]) AND status = 'vectorizing'", done)
            for message, ids in failed.items():
                await conn.execute(
                    f"UPDATE {table} SET status = 'completed', error_message = $2, "
                    f"updated_at = NOW() "
                    f"WHERE job_id = ANY($1::int[]) AND status = 'vectorizing'",
                    ids, message[:2000])
        finished = done + [j for ids in failed.values() for j in ids]
        for job_id in finished:
            s.jobs.pop(job_id, None)
        if done:
            logger.info("vectorize completer %s: %d job(s) completed", space_id, len(done))
        for message, ids in failed.items():
            logger.warning("vectorize completer %s: %d job(s) completed with %r",
                           space_id, len(ids), message)
        return len(finished)


async def _still_queued(conn, space_id: str, waiting) -> Optional[set]:
    """The (context, subject) keys among these that are still queued, or
    None when the space has no queue (it synced directly)."""
    from vitalgraph.vectorization import index_sync_queue as q
    if not await q.table_exists(conn, space_id):
        return None
    ctxs, subs = [], []
    for w in waiting:
        for sub in w.subject_uuids:
            ctxs.append(w.context_uuid)
            subs.append(sub)
    if not subs:
        return set()
    rows = await conn.fetch(
        f"SELECT DISTINCT q.context_uuid, q.subject_uuid "
        f"FROM {q.queue_table(space_id)} q "
        f"JOIN unnest($1::uuid[], $2::uuid[]) AS k(c, s) "
        f"  ON q.context_uuid = k.c AND q.subject_uuid = k.s", ctxs, subs)
    return {(r["context_uuid"], r["subject_uuid"]) for r in rows}


async def sweep(conn, space_id: str, *, tracked: Sequence[int] = (),
                older_than: float = SWEEP_AFTER_SECONDS,
                limit: int = SWEEP_LIMIT) -> int:
    """Complete 'vectorizing' jobs no waiter is left for.

    A job untouched for `older_than` seconds and not tracked in this process
    is complete when its graph has nothing queued: the index sync gives a
    failed row back to the queue with a backoff and never drops it, so an
    empty queue for the graph means its subjects were synced. A graph still
    busy keeps its stale jobs until the next sweep. Returns the count.
    """
    from vitalgraph.vectorization import index_sync_queue as q
    table = f"{space_prefix(space_id)}_segmentation_jobs"
    rows = await conn.fetch(
        f"SELECT job_id, graph_id FROM {table} "
        f"WHERE status = 'vectorizing' "
        f"AND updated_at < NOW() - make_interval(secs => $1) "
        f"AND NOT (job_id = ANY($2::int[])) "
        f"ORDER BY job_id LIMIT $3", float(older_than), list(tracked), limit)
    if not rows:
        return 0
    by_ctx: Dict[uuid.UUID, List[int]] = {}
    for r in rows:
        by_ctx.setdefault(_uuid(r["graph_id"]), []).append(r["job_id"])
    busy = set()
    if await q.table_exists(conn, space_id):
        busy = {r["context_uuid"] for r in await conn.fetch(
            f"SELECT DISTINCT context_uuid FROM {q.queue_table(space_id)} "
            f"WHERE context_uuid = ANY($1::uuid[])", list(by_ctx))}
    ids = [j for ctx, js in by_ctx.items() if ctx not in busy for j in js]
    if not ids:
        return 0
    result = await conn.execute(
        f"UPDATE {table} SET status = 'completed', updated_at = NOW() "
        f"WHERE job_id = ANY($1::int[]) AND status = 'vectorizing'", ids)
    n = int(result.split()[-1]) if result else 0
    if n:
        logger.info("vectorize sweep %s: %d stale 'vectorizing' job(s) completed "
                    "(their graphs have nothing queued)", space_id, n)
    return n
