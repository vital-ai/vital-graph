"""Stored verdicts that one pattern is implied by others (planning_planner/09,
implied-pattern elimination; results/implied_census.md).

    ?d hasKGEntityType UWNewBusinessDecision
      <= ?f hasKGGraphURI ?d  AND  ?f hasKGSlotType UwNbdReasonKind

When every `hasKGGraphURI` object reached from a ReasonKind slot has EXACTLY one
`hasKGEntityType UWNewBusinessDecision` row, the pattern adds nothing to a query
that also has the link: it neither removes solutions nor multiplies them. The
planner may then drop it, as one plan alternative among others; it keeps it when
the plan with it is cheaper (it is often the plan's anchor, see the census).

PROOF, NOT A SAMPLE. A verdict is a full check for a counterexample, run by the
maintenance job (no user waiting). It is valid only while the space's write log
(`write_log`) is unchanged since the check, and both are read in the SAME
snapshot: the check and the write count in one REPEATABLE READ transaction, and
the reader compares in its own snapshot (`usable`; the executor re-checks
`guard` in the snapshot the query runs in).

"EXACTLY ONE", NOT "AT LEAST ONE": quads in an unpartitioned space carry a
random `quad_uuid` in their PK, so a triple can be stored twice, and a
duplicate implied row multiplies the solutions it joins.

Only quad-table patterns, all in one graph (or all with no graph): a derived
table (edge, frame_slot) can lag its quads, so a verdict about quads says
nothing about it.

Requested on demand: the query path inserts a pending row (holds NULL) for an
implication it could use; the maintenance job decides it. One global table,
`pattern_verdict`, keyed by space, created by `scripts/install_write_log.py`;
absent, nothing here does anything.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .space_names import space_prefix
from . import write_log

logger = logging.getLogger(__name__)

TABLE = "pattern_verdict"

#: Spaces without the table (or the log), so the query path does not ask again
#: on every query. Negative only: a stale negative costs an optimisation.
_MISSING: Dict[str, float] = {}
MISSING_TTL_S = 60.0

CREATE_SQL = [
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        space_id      text NOT NULL,
        verdict_key   text NOT NULL,
        spec          jsonb NOT NULL,
        holds         boolean,                 -- NULL: requested, not decided
        writes        bigint,                  -- the write count it was checked at
        quad_oid      oid,                     -- the quad table it was checked on
        checked_at    timestamptz,
        check_ms      double precision,
        requested_at  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (space_id, verdict_key))""",
]


@dataclass(frozen=True)
class Implication:
    """`implied` = (predicate, object) on subject ?s, implied by:

        link   a quad (?u `via` ?s), ?u also carrying every (p, o) in `pins`
        same   a quad (?s `via` `via_obj`) (any object when `via_obj` is None)

    `context`: the graph all of them are in, or None for no graph condition."""
    kind: str
    implied: Tuple[str, str]
    via: str
    via_obj: Optional[str] = None
    pins: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    context: Optional[str] = None

    def key(self) -> str:
        return json.dumps([self.kind, list(self.implied), self.via, self.via_obj,
                           sorted(list(p) for p in self.pins), self.context], separators=(",", ":"))

    def spec(self) -> dict:
        return {"kind": self.kind, "implied": list(self.implied), "via": self.via,
                "via_obj": self.via_obj, "pins": [list(p) for p in self.pins], "context": self.context}

    @staticmethod
    def from_spec(d: dict) -> "Implication":
        return Implication(kind=d["kind"], implied=tuple(d["implied"]), via=d["via"],
                           via_obj=d.get("via_obj"), pins=tuple(tuple(p) for p in d.get("pins") or []),
                           context=d.get("context"))


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _u(x: str) -> str:
    if not _UUID.match(x or ""):
        raise ValueError(f"not a uuid: {x!r}")
    return f"'{x}'::uuid"


def counterexample_sql(space_id: str, imp: Implication) -> str:
    """One row iff the implication FAILS somewhere: an antecedent subject with
    other than exactly one implied row."""
    q = f"{space_prefix(space_id)}_rdf_quad"
    ctx = (lambda a: f" AND {a}.context_uuid = {_u(imp.context)}") if imp.context else (lambda a: "")
    ip, io = imp.implied
    if imp.kind == "link":
        frm, subj = f"{q} k", "k.object_uuid"
        where = [f"k.predicate_uuid = {_u(imp.via)}{ctx('k')}"]
        for n, (p, o) in enumerate(imp.pins):
            frm += (f" JOIN {q} p{n} ON p{n}.subject_uuid = k.subject_uuid AND p{n}.predicate_uuid = {_u(p)} "
                    f"AND p{n}.object_uuid = {_u(o)}{ctx(f'p{n}')}")
    elif imp.kind == "same":
        frm, subj = f"{q} k", "k.subject_uuid"
        where = [f"k.predicate_uuid = {_u(imp.via)}{ctx('k')}"]
        if imp.via_obj:
            where.append(f"k.object_uuid = {_u(imp.via_obj)}")
    else:
        raise ValueError(f"implication kind {imp.kind!r}")
    lacks = (f"(SELECT count(*) FROM (SELECT 1 FROM {q} l WHERE l.subject_uuid = {subj} "
             f"AND l.predicate_uuid = {_u(ip)} AND l.object_uuid = {_u(io)}{ctx('l')} LIMIT 2) z) <> 1")
    return f"SELECT 1 FROM {frm} WHERE {' AND '.join(where)} AND {lacks} LIMIT 1"


# ---------------------------------------------------------------------------
# Which patterns of a query could be implied
# ---------------------------------------------------------------------------

_CONST_FILTER = re.compile(r"^(\w+)\.(predicate_uuid|object_uuid|context_uuid|subject_uuid) = '([0-9a-f-]{36})'::uuid$")


def _leaf_consts(pos, alias: str, aliases) -> Optional[Dict[str, str]]:
    """The leaf's filters as {column: uuid}, or None if it has any other kind
    of filter (a range, an IN, an FTS condition)."""
    from .generator import substitute_constants
    out = {}
    for f in pos.filters.get(alias, []):
        m = _CONST_FILTER.match(substitute_constants(f, aliases).strip())
        if not m or m.group(1) != alias:
            return None
        out[m.group(2)] = m.group(3)
    return out


def region_candidates(reg, space_id: str) -> List[Tuple[object, Implication]]:
    """(leaf, implication) for each constant pattern of the region's units that
    an inbound link from a pinned unit could imply.

    The IMPLIED leaf must be exactly (predicate, object, graph) on the quad
    table: any further condition on it would make the query's pattern
    narrower than the verdict's. The ANTECEDENT may be narrower in the query
    than in the verdict (an extra filter, a pin on a derived table left out of
    the verdict): a verdict about a weaker antecedent covers a stronger one."""
    from . import qplan
    quad = f"{space_prefix(space_id)}_rdf_quad"
    pos = qplan._Pos(reg.plans, reg.values)
    out = []
    for ti, tu in enumerate(reg.units):
        for L in tu.leaves:
            if L.kind != "quad" or not L.o_const or not L.s_var or pos.table.get(L.alias) != quad:
                continue
            lc = _leaf_consts(pos, L.alias, reg.aliases)
            if not lc or set(lc) - {"predicate_uuid", "object_uuid", "context_uuid"} \
                    or "predicate_uuid" not in lc or "object_uuid" not in lc:
                continue
            for e in reg.edges:
                if e.kind != "link" or e.v != ti or e.u >= len(reg.units):
                    continue
                K = e.leaf_u
                if K.kind != "quad" or pos.table.get(K.alias) != quad:
                    continue
                kc = _leaf_consts(pos, K.alias, reg.aliases) or {}
                if "predicate_uuid" not in kc or kc.get("context_uuid") != lc.get("context_uuid"):
                    continue
                pins = []
                for P in reg.units[e.u].leaves:
                    if P is K or P.kind != "quad" or not P.o_const or pos.table.get(P.alias) != quad:
                        continue
                    pc = _leaf_consts(pos, P.alias, reg.aliases) or {}
                    if "predicate_uuid" in pc and "object_uuid" in pc \
                            and pc.get("context_uuid") == lc.get("context_uuid"):
                        pins.append((pc["predicate_uuid"], pc["object_uuid"]))
                out.append((L, Implication(kind="link", implied=(lc["predicate_uuid"], lc["object_uuid"]),
                                           via=kc["predicate_uuid"], pins=tuple(sorted(pins)),
                                           context=lc.get("context_uuid"))))
    return out


# ---------------------------------------------------------------------------
# The query path
# ---------------------------------------------------------------------------

async def usable(conn, space_id: str, imps: Iterable[Implication]
                 ) -> Tuple[set, Optional[Tuple[int, int]]]:
    """(keys of the implications that hold NOW, the guard they hold under).

    One round trip: the verdicts are compared with the write count and quad
    table in the same statement, so in one snapshot. Keys with no row at all
    are requested (a pending row the maintenance job decides). Any failure, a
    missing table, a missing or disabled trigger: nothing is usable."""
    imps = list(imps)
    if not imps:
        return set(), None
    miss = _MISSING.get(space_id)
    if miss is not None and time.monotonic() - miss < MISSING_TTL_S:
        return set(), None
    keys = [i.key() for i in imps]
    quad = f"{space_prefix(space_id)}_rdf_quad"
    try:
        async with conn.transaction():          # a savepoint inside a caller's transaction
            if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL AND to_regclass($2) IS NOT NULL",
                                       TABLE, write_log.table_name(space_id)):
                _MISSING[space_id] = time.monotonic()
                return set(), None
            rows = await conn.fetch(
                f"WITH g AS ({write_log._state_sql(space_id)}) "
                f"SELECT v.verdict_key, v.holds, v.writes = g.writes AND v.quad_oid = g.quad_oid "
                f"AND g.trigger_ok AS current, g.writes AS g_writes, g.quad_oid AS g_oid, g.trigger_ok "
                f"FROM g LEFT JOIN {TABLE} v ON v.space_id = $1 AND v.verdict_key = ANY($2::text[])",
                space_id, keys)
            have = {r["verdict_key"] for r in rows if r["verdict_key"] is not None}
            new = [i for i in imps if i.key() not in have]
            if new:
                await conn.executemany(
                    f"INSERT INTO {TABLE} (space_id, verdict_key, spec) VALUES ($1, $2, $3::jsonb) "
                    f"ON CONFLICT DO NOTHING",
                    [(space_id, i.key(), json.dumps(i.spec())) for i in new])
    except Exception as exc:
        logger.debug("pattern_verdict: read failed for %s: %s", space_id, exc)
        return set(), None
    if not rows or not rows[0]["trigger_ok"]:
        return set(), None
    ok = {r["verdict_key"] for r in rows if r["verdict_key"] is not None and r["holds"] and r["current"]}
    return ok, (int(rows[0]["g_writes"]), int(rows[0]["g_oid"]))


async def guard_holds(conn, space_id: str, guard: Tuple[int, int]) -> bool:
    """In the caller's snapshot: is the space exactly as it was when the plan
    used its verdicts? The executor calls this inside the REPEATABLE READ
    transaction the query then runs in."""
    st = await write_log.guard_state(conn, space_id)
    return st is not None and tuple(st) == tuple(guard)


# ---------------------------------------------------------------------------
# The maintenance job
# ---------------------------------------------------------------------------

async def refresh(conn, space_id: str) -> List[Dict]:
    """Decide every pending or out-of-date verdict of the space.

    Each in its own REPEATABLE READ transaction: the write count, the quad
    table's oid, the full check and the stored row all belong to one snapshot,
    so the stored count is exactly the state the check saw. A write committed
    during the check moves the count, and the verdict reads as out of date the
    moment it is stored: the next cycle checks again. Compacts the log first."""
    if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL AND to_regclass($2) IS NOT NULL",
                               TABLE, write_log.table_name(space_id)):
        return []
    await write_log.compact(conn, space_id)
    state = await write_log.guard_state(conn, space_id)
    if state is None:
        return []
    writes, oid = state
    rows = await conn.fetch(
        f"SELECT verdict_key, spec FROM {TABLE} WHERE space_id = $1 "
        f"AND (holds IS NULL OR writes IS DISTINCT FROM $2 OR quad_oid IS DISTINCT FROM $3::oid)",
        space_id, writes, oid)
    out = []
    for r in rows:
        imp = Implication.from_spec(json.loads(r["spec"]) if isinstance(r["spec"], str) else r["spec"])
        t0 = time.perf_counter()
        try:
            async with conn.transaction(isolation="repeatable_read"):
                st = await write_log.guard_state(conn, space_id)
                if st is None:
                    continue
                hit = await conn.fetchval(counterexample_sql(space_id, imp))
                ms = (time.perf_counter() - t0) * 1000
                await conn.execute(
                    f"UPDATE {TABLE} SET holds = $3, writes = $4, quad_oid = $5::oid, checked_at = now(), "
                    f"check_ms = $6 WHERE space_id = $1 AND verdict_key = $2",
                    space_id, r["verdict_key"], hit is None, st[0], st[1], ms)
            out.append({"key": r["verdict_key"], "holds": hit is None, "ms": round(ms, 1)})
        except Exception as exc:
            logger.warning("pattern_verdict: check failed for %s %s: %s", space_id, r["verdict_key"], exc)
            out.append({"key": r["verdict_key"], "error": type(exc).__name__})
    return out
