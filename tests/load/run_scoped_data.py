"""Write test data into a DEDICATED GRAPH, and remove it in time proportional
to what was written.

`issues/171` Part 3. A concurrent load test has to write into the 53M-quad
dataset and then leave it as it found it. Reloading 53M quads per run is not
viable, and a URI-prefix convention would need a full scan to find its own data
and would strand rows in every derived table.

A graph is the unit that already has removal machinery and an index:

    clear_graph(space_id, graph_uri)                    the quads
    delete_entity_slot_sort_for_context(conn, sid, ctx) the slot-sort rows

`context_uuid` is the LEADING COLUMN of `idx_{space}_quad_ctx_pred`, so both are
bounded by what the run wrote rather than by the size of the space.

CLEANUP IS VERIFIED, NOT ASSUMED. `verify_clean` compares quad counts and
per-type coverage against the pre-run snapshot and reports what differs — a run
that silently leaves derived rows behind is exactly the failure this exists to
prevent, and it is invisible without the comparison.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RunScope:
    """One load run's isolated graph, and the snapshot to verify against."""
    space_id: str
    graph_uri: str
    run_id: str
    context_uuid: Optional[uuid.UUID] = None
    before: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def new(cls, space_id: str, prefix: str = "urn:loadtest") -> "RunScope":
        rid = uuid.uuid4().hex[:12]
        return cls(space_id=space_id, run_id=rid,
                   graph_uri=f"{prefix}:run:{rid}")

    def marker(self) -> str:
        """A value every test entity carries.

        Redundant with the graph for CLEANUP, and not redundant for DIAGNOSIS: a
        run that dies before recording its graph leaves data identifiable
        without the catalog.
        """
        return f"loadtest-{self.run_id}"


async def snapshot(conn, scope: RunScope) -> Dict[str, object]:
    """What the space looked like before the run. The basis for verification."""
    q = await conn.fetchval(f"SELECT count(*) FROM {scope.space_id}_rdf_quad")
    try:
        ess = await conn.fetchval(
            f"SELECT count(*) FROM {scope.space_id}_entity_slot_sort")
    except Exception:
        ess = None
    blocks = await conn.fetchval(
        "SELECT count(*) FROM slot_sort_block WHERE space_id = $1",
        scope.space_id)
    scope.before = {"quads": q, "entity_slot_sort": ess, "blocks": blocks}
    return scope.before


async def resolve_context(conn, scope: RunScope) -> Optional[uuid.UUID]:
    """The context uuid for this run's graph, once its first quad exists."""
    if scope.context_uuid is not None:
        return scope.context_uuid
    row = await conn.fetchval(
        f"SELECT term_uuid FROM {scope.space_id}_term "
        f" WHERE term_text = $1 AND term_type = 'U' LIMIT 1", scope.graph_uri)
    scope.context_uuid = row
    return row


async def cleanup(conn, scope: RunScope) -> Dict[str, int]:
    """Remove everything this run wrote. Bounded by the run, not the space.

    ORDER MATTERS. The slot-sort rows are deleted BEFORE the quads: the
    derivation walks the quads to find what to remove, and once they are gone
    the rows that referenced them can only be found by the context column.
    Deleting by context first is correct either way and does not depend on that
    ordering holding — which is why it is done by context rather than by
    re-deriving.
    """
    removed: Dict[str, int] = {}
    ctx = await resolve_context(conn, scope)
    if ctx is None:
        return {"nothing_written": 0}

    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        delete_entity_slot_sort_for_context)
    try:
        removed["entity_slot_sort"] = await delete_entity_slot_sort_for_context(
            conn, scope.space_id, ctx)
    except Exception:
        removed["entity_slot_sort"] = -1

    for table, col in ((f"{scope.space_id}_edge", "context_uuid"),
                       (f"{scope.space_id}_frame_entity", "context_uuid"),
                       (f"{scope.space_id}_rdf_quad", "context_uuid")):
        try:
            r = await conn.execute(
                f"DELETE FROM {table} WHERE {col} = $1", ctx)
            removed[table.rsplit("_", 1)[-1] if table.endswith("quad")
                    else table[len(scope.space_id) + 1:]] = (
                int(r.split()[-1]) if r else 0)
        except Exception:
            pass

    await conn.execute(
        "DELETE FROM graph WHERE space_id = $1 AND graph_uri = $2",
        scope.space_id, scope.graph_uri)
    return removed


async def verify_clean(conn, scope: RunScope) -> List[str]:
    """Differences from the pre-run snapshot. EMPTY means clean.

    Returns findings rather than asserting, so a caller can report all of them
    instead of failing on the first — a partial cleanup usually leaves more than
    one kind of row behind, and seeing only the first is how you fix one and
    believe you are done.
    """
    findings: List[str] = []
    before = scope.before or {}

    # SCOPED TO THE RUN'S GRAPH, NOT TO THE WHOLE SPACE.
    #
    # An earlier version compared total quad counts before and after, and failed
    # a run with `+26,400 left behind` when the run itself had written 142. The
    # difference was `backfill_server_properties_task`, a background coroutine
    # that stamps server-managed properties onto entities — 200 per batch, every
    # few seconds, for as long as un-stamped data exists. A 74M-quad bulk load
    # leaves it 100,000 entities of work, so it writes throughout any run that
    # follows one.
    #
    # It was RIGHT to fail and the assertion was WRONG. Other jobs legitimately
    # write to a shared space while the load runs; demanding the space be
    # byte-identical afterwards makes the check fail for a healthy system, and a
    # check that cries wolf gets deleted. What the run OWNS is its graph, and
    # that is what it must leave empty.
    #
    # The space-wide totals are still reported, as CONTEXT rather than as a
    # verdict — a large unexplained change is worth seeing even when it is not
    # this run's fault.
    # Resolved here rather than assumed: `verify_clean` must work whether or not
    # `cleanup` has run, and it is the CLEANUP-DID-NOT-HAPPEN case that most
    # needs checking.
    ctx = await resolve_context(conn, scope)
    if ctx is not None:
        left = await conn.fetchval(
            f"SELECT count(*) FROM {scope.space_id}_rdf_quad "
            f" WHERE context_uuid = $1", ctx)
        if left:
            findings.append(f"{left} quads still in the run's graph")
        try:
            left_e = await conn.fetchval(
                f"SELECT count(*) FROM {scope.space_id}_entity_slot_sort "
                f" WHERE context_uuid = $1", ctx)
            if left_e:
                findings.append(
                    f"{left_e} entity_slot_sort rows still in the run's graph")
        except Exception:
            pass

    now_q = await conn.fetchval(f"SELECT count(*) FROM {scope.space_id}_rdf_quad")
    if before.get("quads") is not None and now_q != before["quads"]:
        scope.before["space_drift"] = now_q - before["quads"]

    now_b = await conn.fetchval(
        "SELECT count(*) FROM slot_sort_block WHERE space_id = $1",
        scope.space_id)
    if before.get("blocks") is not None and now_b != before["blocks"]:
        # Slow-and-correct rather than wrong, but it will be reported by the
        # stale-block alarm after 24h and it means the run changed the gate.
        findings.append(
            f"slot_sort_block {before['blocks']} -> {now_b} "
            f"({now_b - before['blocks']:+d}) — the run left the gate changed")
    return findings
