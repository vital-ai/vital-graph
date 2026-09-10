"""Is this query doing work proportional to its ANSWER, or to the corpus?

One dimensionless number answers it:

    loops of the busiest node / rows returned

On the reference CONSTRUCT of `issues/178` that was **285,348 / 425 = 671**
before and **341 / 425 = 0.8** after. The ratio needs no baseline, no profiling,
no domain knowledge and no intuition about what "should" be fast, and it falls
out of `EXPLAIN ANALYZE` for any query.

WHY THIS AND NOT TIMINGS. Six shape rewrites were implemented, measured and
reverted on that query before the one that worked, and **every failed attempt
left the ratio near 671 while the successful one took it to 0.8.** The ratio
would have rejected all six before any were built. Wall-clock did not: two of
them looked like improvements on a warm cache.

TWO MEASUREMENT TRAPS, both of which produced confident wrong conclusions
during that investigation and are handled here:

  * **Buffer totals must not be summed across plan lines.** A parent's
    `shared hit` already includes its children's. Naive summation inflated 13x
    on that plan. `root_buffers` reads the top node; `self_buffers` subtracts
    children.
  * **`loops` is per-execution.** A node inside a nested loop reports the loop
    count, which is the whole point here — but a PARALLEL node reports loops as
    the worker count, so a raw max over `loops` can mislead on parallel plans.
    `busiest` therefore reports actual rows x loops alongside.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Above this, a query is doing work proportional to the corpus rather than the
# answer. Deliberately loose: the shapes that matter measured 671, and a healthy
# plan measures below 1. Anything between is worth a look, not an alarm.
DISPROPORTION_THRESHOLD = 50.0

_ROWS_LOOPS = re.compile(r"actual time=[\d.]+\.\.[\d.]+ rows=([\d.]+) loops=(\d+)")
_BUFFERS = re.compile(r"Buffers: shared hit=(\d+)")
_NODE = re.compile(r"^(\s*)(->\s+)?(\S.*)$")


@dataclass
class PlanShape:
    rows: int = 0
    max_loops: int = 0
    ratio: float = 0.0
    root_buffers: int = 0
    busiest: List[Dict[str, Any]] = field(default_factory=list)
    disproportionate: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rows": self.rows,
            "max_loops": self.max_loops,
            "ratio": round(self.ratio, 1),
            "root_buffers": self.root_buffers,
            "disproportionate": self.disproportionate,
            "busiest": self.busiest,
        }


def _nodes(plan_lines: List[str]) -> List[Tuple[int, str, int, int, float]]:
    """(indent, label, buffers, loops, rows) for each plan node."""
    out = []
    for i, line in enumerate(plan_lines):
        m = _NODE.match(line)
        if not m or not (m.group(2) or i == 0):
            continue
        label = re.sub(r"\s*\(cost=[^)]*\)", "", m.group(3)).strip()
        buf = 0
        for j in range(i + 1, min(i + 9, len(plan_lines))):
            nxt = plan_lines[j].strip()
            if nxt.startswith("->"):
                break
            b = _BUFFERS.search(nxt)
            if b:
                buf = int(b.group(1))
                break
        rl = _ROWS_LOOPS.search(line)
        rows = float(rl.group(1)) if rl else 0.0
        loops = int(rl.group(2)) if rl else 1
        out.append((len(m.group(1)), label, buf, loops, rows))
    return out


def analyse(plan_lines: List[str], rows_returned: Optional[int] = None,
            top: int = 5) -> PlanShape:
    """Summarise an `EXPLAIN (ANALYZE, BUFFERS)` result."""
    nodes = _nodes(plan_lines)
    if not nodes:
        return PlanShape()

    def children(idx: int) -> List[int]:
        indent = nodes[idx][0]
        out, k, child_indent = [], idx + 1, None
        while k < len(nodes) and nodes[k][0] > indent:
            if child_indent is None:
                child_indent = nodes[k][0]
            if nodes[k][0] == child_indent:
                out.append(k)
            k += 1
        return out

    root_rows = int(nodes[0][4] * nodes[0][3]) if nodes else 0
    rows = rows_returned if rows_returned is not None else root_rows
    root_buffers = nodes[0][2]

    scored = []
    for i, (_ind, label, buf, loops, r) in enumerate(nodes):
        self_buf = buf - sum(nodes[c][2] for c in children(i))
        scored.append({
            "node": label[:90],
            "loops": loops,
            "rows_per_loop": round(r, 1),
            "total_rows": int(r * loops),
            "self_buffers": max(self_buf, 0),
        })

    max_loops = max((s["loops"] for s in scored), default=0)
    # The busiest nodes by SELF buffers, which is the attribution that survives
    # the parent-includes-child trap.
    busiest = sorted(scored, key=lambda s: s["self_buffers"], reverse=True)[:top]

    ratio = (max_loops / rows) if rows else float(max_loops)
    return PlanShape(
        rows=rows, max_loops=max_loops, ratio=ratio,
        root_buffers=root_buffers, busiest=busiest,
        disproportionate=ratio >= DISPROPORTION_THRESHOLD,
    )


async def explain_and_analyse(conn, sql: str, *args,
                              rows_returned: Optional[int] = None,
                              timeout_ms: int = 30_000) -> Optional[PlanShape]:
    """Run `EXPLAIN (ANALYZE, BUFFERS)` and summarise. None on any failure.

    EXECUTES THE QUERY AGAIN. Only call this for a query already known to be
    slow — the point is to explain a cost already paid, not to double it. The
    statement timeout is its own, so a diagnostic can never outlive the query
    it is diagnosing.
    """
    prev = None
    try:
        prev = await conn.fetchval("SHOW statement_timeout")
        await conn.execute(f"SET statement_timeout = '{int(timeout_ms)}ms'")
        rows = await conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + sql, *args)
        return analyse([r[0] for r in rows], rows_returned=rows_returned)
    except Exception as exc:
        logger.debug("plan_shape: EXPLAIN failed (%s)", exc)
        return None
    finally:
        if prev is not None:
            try:
                await conn.execute(f"SET statement_timeout = '{prev}'")
            except Exception:
                pass


def log_if_disproportionate(shape: Optional[PlanShape], *, space_id: str = "",
                            elapsed_ms: float = 0.0,
                            decisions: Optional[Dict] = None,
                            query: str = "") -> None:
    """Emit one structured line when work is not proportional to the answer."""
    if shape is None or not shape.disproportionate:
        return
    import json
    payload = shape.as_dict()
    payload.update({"space": space_id, "elapsed_ms": round(elapsed_ms, 1)})
    if decisions:
        payload["plan_decisions"] = decisions
    if query:
        payload["query"] = query[:600]
    logger.warning("disproportionate_query %s",
                   json.dumps(payload, default=str, sort_keys=True))


# ---------------------------------------------------------------------------
# Slow-query reporting
#
# WARNING, not INFO. Production does not run at INFO, so a diagnostic emitted
# there does not exist where it is most needed — which is the same failure as
# having no diagnostic at all, only more expensive to discover.
#
# The payload has to be SELF-SUFFICIENT: whoever reads it will not have the
# machine, the space, or the session. That means the SPARQL text (to reproduce),
# the plan decisions (which rewrites fired and which declined and why), the
# stage breakdown (to separate generation from execution), and the plan shape
# when it can be afforded.
# ---------------------------------------------------------------------------

# Report a query at or above this total latency. Env-overridable so a space
# under investigation can be turned down without a deploy.
SLOW_QUERY_MS = float(os.environ.get("VG_SLOW_QUERY_MS", "1000"))

# Running `EXPLAIN ANALYZE` EXECUTES THE QUERY AGAIN. For a query already known
# to be slow that doubles a cost the user has already paid, so it is opt-in:
# the cheap half of the report (timings, decisions, SQL identity) is always
# emitted, and the ratio is added only where someone has asked for it.
EXPLAIN_SLOW_QUERIES = os.environ.get("VG_EXPLAIN_SLOW_QUERIES", "") == "1"

# Enough SQL to recognise the shape; the fingerprint identifies it exactly.
_SQL_EXCERPT = int(os.environ.get("VG_SLOW_QUERY_SQL_CHARS", "2000"))


def sql_fingerprint(sql: str) -> str:
    return hashlib.sha1(sql.encode("utf-8", "replace")).hexdigest()[:12]


async def report_slow_query(conn, *, space_id: str, sparql: str, sql: str,
                            timing: Dict[str, Any],
                            plan_decisions: Optional[Dict] = None,
                            rows_returned: Optional[int] = None,
                            threshold_ms: Optional[float] = None) -> None:
    """One WARNING line carrying everything needed to optimise this query later.

    Never raises: a diagnostic that can fail a request is worse than no
    diagnostic.
    """
    try:
        limit = SLOW_QUERY_MS if threshold_ms is None else threshold_ms
        total = float(timing.get("total_ms") or 0.0)
        if total < limit:
            return

        payload: Dict[str, Any] = {
            "space": space_id,
            "sql_fingerprint": sql_fingerprint(sql or ""),
            "timing": timing,
            "sparql": (sparql or "")[:4000],
            "sql_excerpt": (sql or "")[:_SQL_EXCERPT],
            "sql_chars": len(sql or ""),
        }
        if plan_decisions:
            payload["plan_decisions"] = plan_decisions

        if EXPLAIN_SLOW_QUERIES and sql:
            shape = None
            if conn is not None:
                shape = await explain_and_analyse(conn, sql,
                                                  rows_returned=rows_returned)
            else:
                # Its OWN connection. The request's is usually released by the
                # time a report is assembled, and a diagnostic must never hold
                # or borrow the one serving the request.
                try:
                    from .db_provider import get_connection
                    async with get_connection() as diag_conn:
                        shape = await explain_and_analyse(
                            diag_conn, sql, rows_returned=rows_returned)
                except Exception as exc:
                    logger.debug("slow-query EXPLAIN skipped: %s", exc)
            if shape is not None:
                payload["plan_shape"] = shape.as_dict()
                # THE diagnostic: work proportional to the answer, or to the
                # corpus? `issues/178` measured 671 before and 0.8 after.
                payload["disproportionate"] = shape.disproportionate

        logger.warning("slow_query %s", json.dumps(payload, default=str,
                                                   sort_keys=True))
    except Exception as exc:  # pragma: no cover - diagnostics must not throw
        logger.debug("slow-query report skipped: %s", exc)
