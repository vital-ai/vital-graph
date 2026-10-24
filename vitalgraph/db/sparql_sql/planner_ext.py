"""The planner-extension switch: hand the cardinality model's numbers to the
`vg_planner` PostgreSQL extension (`pg_extensions/vg_planner`).

`VG_PLANNER_EXTENSION`:

    off      (default, and when unset) today's implementation, exactly. Nothing
             in this module runs: no advice is recorded, no alias changes, the
             SQL is byte-identical.
    on       use the extension on a database where it is detected; elsewhere
             behave as `off` and warn once per database.
    require  as `on`, but a database without the extension is an error, so a
             misconfigured run cannot quietly measure the old path.

With the switch on and the extension present, ONLY planning and execution
change: EXISTS bodies get statement-unique aliases, each modelled BGP's order
and prefix row estimates are written as a leading `/*vg:plan 1 ... */` comment,
and the executor runs the statement with it. Route-arounds (the
`join_collapse_limit` pin, slot-group CTEs) are retired one at a time in
`RETIRED`, each only with a measurement behind it; until then they keep running
with the advice added around them.

The wire format and the extension's behaviour are documented in
`pg_extensions/vg_planner/src/advice_parse.c` and `advice_rules.c`.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

ADVICE_FORMAT = 1
EXTENSION = "vg_planner"

_MODES = ("off", "on", "require")
MODE = (os.getenv("VG_PLANNER_EXTENSION") or "off").strip().lower()
if MODE not in _MODES:
    logger.warning("VG_PLANNER_EXTENSION=%r is not one of %s; using 'off'", MODE, _MODES)
    MODE = "off"

#: Route-arounds the advice has replaced, each set True only with the
#: measurement that shows it (planning_planner/07). Unretired ones keep running
#: with the switch on, exactly as they do with it off.
RETIRED: Dict[str, bool] = {
    "jcl_pin": False,          # SET LOCAL join_collapse_limit = 1
    "slot_group_cte": False,   # slot_group_cte's MATERIALIZED CTEs
}

# EXPERIMENTS ONLY: `VG_PLANNER_RETIRE=jcl_pin,slot_group_cte` retires the named
# route-arounds for this process, so an A/B run can measure the advice without
# them (planning_planner/05, arm B). It has no effect with the switch off.
for _name in filter(None, (os.getenv("VG_PLANNER_RETIRE") or "").replace(" ", "").split(",")):
    if _name not in RETIRED:
        raise ValueError(f"VG_PLANNER_RETIRE: unknown route-around {_name!r}; "
                         f"known: {sorted(RETIRED)}")
    RETIRED[_name] = True


#: Planner features beyond the advice, off until measured across the dashboard
#: set. `qtree`: plan supported queries from the annotated query tree
#: (`qtree` / `qplan`; the first prototypes are in `archive/planner_prototypes`) and replace the emitted SQL with the
#: planner's. EXPERIMENTS: `VG_PLANNER_FEATURES=qtree`.
FEATURES: Dict[str, bool] = {"qtree": False, "bgp_rows": False, "oracle": False, "implied": False}
# `implied`: with `qtree` and `oracle`, also search each query WITHOUT the
# patterns a stored verdict says are implied (`pattern_verdict`), and take that
# plan only when it is clearly cheaper on sampled estimates (IMPLIED_MARGIN).
# `oracle`: with `qtree`, sample what the stored statistics cannot price (joint
# unit sizes, pair join sizes, probe fan-outs) before searching (`qcard`).
# `bgp_rows`: the FIRST design, advice of one written order's prefix rows per
# BGP (`record_bgp`). Measured harmful (planning_planner/results: arm B,
# all_of > 30 s through the API): it sizes one order's prefixes and leaves
# every other subset PostgreSQL considers on its own estimates. Kept only as an
# experiment switch; off, a statement the qtree planner declines carries NO
# advice and runs exactly as with the switch off.
for _name in filter(None, (os.getenv("VG_PLANNER_FEATURES") or "").replace(" ", "").split(",")):
    if _name not in FEATURES:
        raise ValueError(f"VG_PLANNER_FEATURES: unknown feature {_name!r}; known: {sorted(FEATURES)}")
    FEATURES[_name] = True


def retired(name: str) -> bool:
    """True when the switch is active for this statement AND `name` is retired."""
    return active() and RETIRED[name]


@dataclass
class _Statement:
    """What one `generate_sql` call collects while the switch is active."""
    bgps: List[str] = field(default_factory=list)
    exists_bodies: int = 0
    advice_override: Optional[str] = None   # a whole plan's advice (qtree)
    verdicts: bool = True                   # may use stored pattern verdicts


_current: contextvars.ContextVar[Optional[_Statement]] = contextvars.ContextVar(
    "vg_planner_statement", default=None)


@contextlib.contextmanager
def statement(active: bool, verdicts: bool = True):
    """Scope one statement's generation. Inactive: a no-op, nothing recorded.
    `verdicts=False`: plan without stored pattern verdicts (the executor's
    retry when the space changed between planning and running)."""
    token = _current.set(_Statement(verdicts=verdicts) if active else None)
    try:
        yield
    finally:
        _current.reset(token)


def active() -> bool:
    return _current.get() is not None


def exists_alias_prefix() -> str:
    """The alias prefix for an EXISTS body's own AliasGenerator.

    "ex_" as always when inactive. Active, every body in the statement gets its
    own ("ex1_", "ex2_", ...): advice names relations by alias, and two bodies
    both called `ex_q0` would make that ambiguous.
    """
    st = _current.get()
    if st is None:
        return "ex_"
    st.exists_bodies += 1
    return f"ex{st.exists_bodies}_"


def _num(v: float) -> str:
    return str(int(round(v))) if v < 1e15 else f"{v:.6g}"


def record_bgp(steps: Sequence[str], rows: Sequence[Optional[float]]) -> None:
    """Record one BGP: its left-deep join order and the model's row estimate
    after each prefix (`bgp_cardinality.estimate_order`). An estimate the
    model could not make (None) ends the rows there: unpriced is never sent
    as a guess."""
    st = _current.get()
    if st is None or len(steps) < 2 or not FEATURES["bgp_rows"]:
        return
    priced = []
    for alias, est in zip(steps[1:], rows[1:]):
        if est is None:
            break
        priced.append(f"{alias}:{_num(max(est, 1.0))}")
    line = f"bgp b{len(st.bgps)} steps({' '.join(steps)})"
    if priced:
        line += f" rows({' '.join(priced)})"
    st.bgps.append(line)


def render() -> Optional[str]:
    """The advice comment for the statement, or None if nothing was recorded."""
    st = _current.get()
    if st is None:
        return None
    if st.advice_override:
        return st.advice_override
    if not st.bgps:
        return None
    return f"/*vg:plan {ADVICE_FORMAT}\n" + "\n".join(st.bgps) + "\n*/"


#: Take the plan without the implied patterns only when it is at least this much
#: cheaper. Its estimates differ from the kept plan's in exactly the joins the
#: removal changes, and the census showed those can be badly wrong.
IMPLIED_MARGIN = 0.8
# EXPERIMENTS ONLY: `VG_PLANNER_IMPLIED_MARGIN=1.0` takes the plan without the
# implied patterns whenever it is cheaper at all (tests of the guard need a
# plan that uses a verdict). No effect unless `implied` is on.
if os.getenv("VG_PLANNER_IMPLIED_MARGIN"):
    IMPLIED_MARGIN = float(os.environ["VG_PLANNER_IMPLIED_MARGIN"])


def _all_pairs_sampled(reg) -> bool:
    """Every joined unit pair of the region has a SAMPLED join size: a plan
    change is never taken on stored-statistics estimates alone."""
    pairs = {(min(e.u, e.v), max(e.u, e.v)) for e in reg.edges
             if e.u < len(reg.units) and e.v < len(reg.units)}
    return all(p in reg.pair_rows and reg.pair_rows[p].rule.startswith("sample") for p in pairs)


async def plan_with_qtree(plan, ctx, var_map: Dict[str, str], space_id: Optional[str] = None,
                          conn=None, conn_params=None):
    """The planner's SQL for this statement, or None to keep the emitted SQL.

    Only with the switch active and `FEATURES["qtree"]`. Builds the annotated
    tree, scores it, renders the cheapest plan with the names the generator
    allocated. Anything the planner does not support, or any failure, keeps
    today's SQL; the reason is recorded in plan_decisions either way."""
    st = _current.get()
    if st is None or not FEATURES["qtree"]:
        return None
    from .plan_decisions import recorder_for
    rec = recorder_for(ctx.aliases)
    from . import qplan
    if conn is not None:
        # derived-table leaves (edge, frame_slot) are priced from PostgreSQL's
        # own statistics and capped counts, loaded before analysis (`qcard`)
        from . import qcard
        try:
            await qcard.load_derived(plan, ctx, conn)
        except Exception as exc:  # unpriced derived leaves: the planner declines them
            rec.declined("qtree_derived_stats", f"{type(exc).__name__}: {exc}"[:300])
    try:
        q = qplan.analyze(plan, ctx)
        # The generator chose an EARLY-STOP plan (an ordered scan that stops at
        # the LIMIT: `needs_ordered_scan`). The planner has no top-k cost term
        # yet (planning_planner/09 item 6), so its plan computes every match
        # and cuts after: measured on KGQuery edge pages, 4,982 matches for 25
        # rows, 95 ms against today's 12 ms. Until top-k is costed, it stands aside.
        if q.limit is not None and getattr(ctx, "needs_ordered_scan", False):
            raise qplan.Unsupported("the generator's early-stop plan for LIMIT (top-k is not costed yet)")
    except Exception as exc:     # Unsupported, or a planner defect: keep today's SQL
        rec.declined("qtree_plan", f"{type(exc).__name__}: {exc}"[:300])
        return None
    # The query as written, and (with `implied`) the query without the
    # patterns a current verdict says the rest implies.
    alts = [(q, None, frozenset())]
    if FEATURES["implied"] and st.verdicts and space_id is not None and conn is not None:
        from . import pattern_verdict as _pv
        try:
            cands = _pv.region_candidates(q.region, space_id)
            ok, guard = await _pv.usable(conn, space_id, [i for _l, i in cands]) if cands else (set(), None)
            drop = frozenset(l.alias for l, i in cands if i.key() in ok)
            if drop and guard is not None:
                alts.append((qplan.analyze(plan, ctx, exclude=drop), (space_id,) + tuple(guard), drop))
            elif cands:
                rec.declined("implied_drop", f"{len(cands)} candidate(s), none with a current verdict")
        except Exception as exc:
            rec.declined("implied_drop", f"{type(exc).__name__}: {exc}"[:300])
    oracle = None
    if FEATURES["oracle"] and space_id is not None:
        from . import qcard
        for n, (qa, guard, drop) in enumerate(list(alts)):
            try:
                info = await qcard.annotate(qa, space_id, conn=conn, conn_params=conn_params)
                oracle = info if n == 0 else oracle
            except Exception as exc:  # timeout or SQL error: plan on the stored statistics
                rec.declined("qtree_oracle", f"{type(exc).__name__}: {exc}"[:300])
                if n == 0:
                    alts[0] = (qplan.analyze(plan, ctx), None, frozenset())   # undo any partial annotation
                else:
                    alts[n] = None
    names = {sparql: sql for sql, sparql in var_map.items()}
    rendered = []
    for n, alt in enumerate(alts):
        if alt is None:
            continue
        qa, guard, drop = alt
        try:
            out = qplan.render(qa, names, ctx)
        except Exception as exc:     # Unsupported, or a planner defect: keep today's SQL
            if n == 0:
                rec.declined("qtree_plan", f"{type(exc).__name__}: {exc}"[:300])
                return None
            rec.declined("implied_drop", f"render: {type(exc).__name__}: {exc}"[:300])
            continue
        out.verdict_guard = guard
        rendered.append((out, qa, drop))
    out, qa, drop = rendered[0]
    if len(rendered) > 1:
        alt_out, alt_q, alt_drop = rendered[1]
        sampled = _all_pairs_sampled(alt_q.region)
        if sampled and alt_out.cost < IMPLIED_MARGIN * out.cost:
            rec.fired("implied_drop", "", dropped=sorted(alt_drop), cost=round(alt_out.cost),
                      kept_cost=round(out.cost))
            out = alt_out
        else:
            rec.declined("implied_drop", ("cheaper only on unsampled estimates" if not sampled else
                                          f"not clearly cheaper ({alt_out.cost:,.0f} vs {out.cost:,.0f})"),
                         dropped=sorted(alt_drop))
    st.advice_override = out.advice
    rec.fired("qtree_plan", "", cost=round(out.cost), plan=out.plan[:300], **({"oracle": oracle} if oracle else {}))
    return out


# ---------------------------------------------------------------------------
# Detection, once per database
# ---------------------------------------------------------------------------

_detected: Dict[object, bool] = {}


async def detect(conn, key: object) -> bool:
    """Whether `vg_planner` is installed AND loaded in the server `conn`
    reaches. Cached per `key` (the pool), since each install's database may
    differ. `require` raises on a database without it."""
    if MODE == "off":
        return False
    if key in _detected:
        return _detected[key]
    ok = False
    try:
        info = await conn.fetchval(
            "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname = $1) "
            "THEN vg_planner_info() END", EXTENSION)
        ok = bool(info) and "hooks=installed" in info and f"advice={ADVICE_FORMAT}" in info
    except Exception as exc:  # the function is absent unless the extension is
        logger.debug("vg_planner detection failed: %s", exc)
    if not ok:
        if MODE == "require":
            raise RuntimeError(
                "VG_PLANNER_EXTENSION=require but the database has no loaded "
                f"{EXTENSION} extension (advice format {ADVICE_FORMAT})")
        logger.warning("VG_PLANNER_EXTENSION=on but the database has no loaded %s "
                       "extension; planning as with the switch off", EXTENSION)
    else:
        logger.info("vg_planner detected: %s", info)
    _detected[key] = ok
    return ok


def on_mismatch() -> str:
    """What the extension does with advice it could not apply: fail the
    statement under `require` (tests, the planner stack), warn when serving."""
    return "error" if MODE == "require" else "warning"
