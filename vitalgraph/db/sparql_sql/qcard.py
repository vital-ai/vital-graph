"""The cardinality oracle (planning_planner/09, ranked item 1): index-based
join sampling, after Leis et al. (CIDR 2017) and WanderJoin.

Stored statistics price what they can price exactly: a single-leaf unit's
(predicate, object) pin, a VALUES set. Everything they cannot is SAMPLED here,
through the same SQL the renderer writes, so a sample means exactly what the
plan will compute:

    a unit with two or more leaves    rows(u): sampled anchor subjects, each
                                      completed through the unit's other leaves
    a pair of units with an edge      rows(u ⋈ v): the same sampled rows of u,
                                      joined into v on every connecting variable
    a probe into v through an edge    the PHYSICAL fan-out: rows the probed
                                      leaf's index range returns per probe,
                                      before v's other leaves narrow it

Nothing here knows a predicate name or a schema: a unit is whatever star the
query has, and an edge whatever variable two units share (principle 1).

Every number is tagged with where it came from (`Est.rule`: `sample`,
`sample_exact` when the sample was the whole input, `sample_zero` for an empty
sample). An empty sample is NOT read as independence (the "fleeing to
ignorance" of Leis et al.): it is a pseudo-count of 0.5 over the sample.

One round trip per query: every question not already cached is one branch of a
single UNION ALL statement, under a statement timeout. A failure or timeout
keeps the stored-statistics estimates and is recorded in plan_decisions.

Cached per (space, question SQL) and dropped with the space's statistics
(`generator.invalidate_stats_cache`).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .qtree import Est

logger = logging.getLogger(__name__)

SAMPLE_N = 256          # anchor subjects sampled per unit
SCAN_CAP = 20_000       # anchor rows read to draw the sample from
FAN_CAP = 5_000         # rows counted per sampled row and probe
TIMEOUT_MS = 2_000      # the whole batch
ONE_TIMEOUT_MS = 500    # each question, when the batch failed and they are retried apart
PATH_CAP = 200_000      # rows counted per sampled prefix (more: a lower bound)
PATH_ROUNDS = 2         # re-plan and sample the new plan's prefixes at most this often
HIT_BUDGET = 20_000     # rows a join-size question may complete (sample size x fan-out)
MIN_N = 8               # never sample fewer source subjects than this

#: (space_id, question SQL) -> the question's numbers.
_cache: Dict[Tuple[str, str], List[float]] = {}


def invalidate(space_id: Optional[str] = None) -> None:
    from .qtree import DERIVED_STATS, SUBLINKS
    if space_id is None:
        _cache.clear()
        DERIVED_STATS.clear()
        SUBLINKS.clear()
        return
    for k in [k for k in _cache if k[0] == space_id]:
        _cache.pop(k, None)
    from .space_names import space_prefix
    pre = f"{space_prefix(space_id)}_"
    for k in [k for k in DERIVED_STATS if k.startswith(pre)]:
        DERIVED_STATS.pop(k, None)
    for k in [k for k in SUBLINKS if k[0].startswith(pre)]:
        SUBLINKS.pop(k, None)


# ---------------------------------------------------------------------------
# Derived tables (edge, frame_slot): priced BEFORE analysis
# ---------------------------------------------------------------------------

def _sublinks(plan, aliases, out: set) -> None:
    """(tbl, sel, cond) of every leaf filter `x.col IN (SELECT sel FROM tbl WHERE
    cond)` in the plan, EXISTS bodies included."""
    from .generator import substitute_constants
    from .ir import KIND_BGP
    from .qtree import SUBLINK_RE
    if plan.kind == KIND_BGP:
        for owner, sql in plan.tagged_constraints or []:
            m = SUBLINK_RE.match(substitute_constants(sql, aliases))
            if m and m.group(1) == owner:
                out.add((m.group(4), m.group(3), m.group(5).strip()))
    for c in plan.children or []:
        _sublinks(c, aliases, out)
    for e in getattr(plan, "filter_exprs", None) or []:
        if getattr(e, "prepared_plan", None) is not None:
            _sublinks(e.prepared_plan, e.prepared_aliases, out)


async def load_sublinks(plan, ctx, conn) -> int:
    """For each leaf sub-select filter: PostgreSQL's row estimate (EXPLAIN only,
    no execution: the table's own statistics), the table's columns and its
    unique column sets. Cached per (table, column, condition) until the space's
    statistics are invalidated."""
    import json as _json
    from .qtree import SUBLINKS
    need: set = set()
    _sublinks(plan, ctx.aliases, need)
    new = [k for k in need if k not in SUBLINKS]
    tables_meta: Dict[str, Tuple[list, list]] = {}
    for tbl, sel, cond in new:
        if tbl not in tables_meta:
            cols = [r[0] for r in await conn.fetch(
                "SELECT attname FROM pg_attribute WHERE attrelid = to_regclass($1) AND attnum > 0 "
                "AND NOT attisdropped", tbl)]
            uniq = [list(r[0]) for r in await conn.fetch(
                "SELECT array_agg(a.attname ORDER BY k.n) FROM pg_index i "
                "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, n) "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum "
                "WHERE i.indrelid = to_regclass($1) AND i.indisunique GROUP BY i.indexrelid", tbl)]
            tables_meta[tbl] = (cols, uniq)
        async with conn.transaction():
            p = _json.loads(await conn.fetchval(f"EXPLAIN (FORMAT JSON) SELECT {sel} FROM {tbl} WHERE {cond}"))
        cols, uniq = tables_meta[tbl]
        SUBLINKS[(tbl, sel, cond)] = {"rows": float(p[0]["Plan"]["Plan Rows"]), "cols": cols, "unique": uniq}
    return len(new)


def _derived_tables(plan, out: set) -> None:
    """The derived tables (edge, frame_slot) a PlanV2 reads, EXISTS bodies included,
    and its quad tables: their totals and distinct subjects, predicates and objects
    price a leaf with a VARIABLE predicate or a constant subject (qtree._leaves)."""
    from .ir import KIND_BGP
    from .qtree import DERIVED_KINDS
    if plan.kind == KIND_BGP:
        out.update(t.table_name for t in plan.tables if t.kind in DERIVED_KINDS + ("quad",))
    for c in plan.children or []:
        _derived_tables(c, out)
    for e in getattr(plan, "filter_exprs", None) or []:
        if getattr(e, "prepared_plan", None) is not None:
            _derived_tables(e.prepared_plan, out)


async def load_derived(plan, ctx, conn) -> Dict[str, int]:
    """PostgreSQL's statistics for the derived tables the plan reads: rows,
    distinct values and most-common values per column, into qtree.DERIVED_STATS.
    One catalog read for the tables not yet cached; none when cached. A derived
    leaf's constants are then priced from these and the stored pair counts
    (qtree._derived_leaf), with no count query."""
    from .qtree import DERIVED_STATS
    tables: set = set()
    _derived_tables(plan, tables)
    new_t = sorted(t for t in tables if t not in DERIVED_STATS)
    if new_t:
        rows = await conn.fetch(
            "SELECT c.relname, CASE WHEN c.reltuples >= 0 THEN c.reltuples ELSE "
            "  (SELECT coalesce(sum(greatest(k.reltuples, 0)), 0) FROM pg_inherits i "
            "   JOIN pg_class k ON k.oid = i.inhrelid WHERE i.inhparent = c.oid) END AS rows, "
            "  s.attname, s.n_distinct, s.most_common_vals::text AS mcv, s.most_common_freqs AS mcf "
            "FROM pg_class c LEFT JOIN pg_stats s ON s.tablename = c.relname AND s.schemaname = 'public' "
            "WHERE c.relname = ANY($1::text[]) AND c.relnamespace = 'public'::regnamespace", new_t)
        for r in rows:
            d = DERIVED_STATS.setdefault(r["relname"], {"rows": float(r["rows"]), "ndv": {}, "mcv": {}})
            if r["attname"] is None:
                continue
            if r["n_distinct"] is not None:
                nd = float(r["n_distinct"])
                d["ndv"][r["attname"]] = (-nd * d["rows"]) if nd < 0 else nd
            if r["mcv"] and r["mcf"]:
                vals = r["mcv"].strip("{}").split(",")
                d["mcv"][r["attname"]] = {v.strip('"'): float(f) for v, f in zip(vals, r["mcf"])}
    return {"tables": len(new_t)}


@dataclass
class _Question:
    region: object
    unit: int
    target: Optional[int]           # the unit joined into, or None (unit size only)
    fans: List[Tuple[object, int]]  # (edge, index into the result array)
    sql: str
    n: int = SAMPLE_N               # source subjects sampled


# ---------------------------------------------------------------------------
# The questions, as SQL
# ---------------------------------------------------------------------------

def _unit_sql(reg, i: int):
    """The unit rendered alone, as the renderer writes it: (from-sql, the
    columns of its variables, its pending conditions)."""
    from . import qplan
    r = qplan._R(qplan._Pos(reg.plans, reg.values))
    node = qplan._base(reg, i)
    sql, _present, pend = qplan._render_node(node, reg, r)
    return sql, r, pend, r.pos


def _question(reg, s: int, t: Optional[int], hits: bool = True) -> Optional[_Question]:
    """Sample unit s's anchor subjects; complete each through s; join into t
    (`hits`), and count the index range of each probe into t (the fan-out)."""
    u = reg.units[s]
    if not u.subject.startswith("?") or u.anchor is None or u.anchor.s_var is None:
        return None
    if t is not None and any(l.kind == "subq" for l in reg.units[t].leaves):
        return None              # a sub-SELECT: no table to join a sample into (its own region is sampled)
    var = u.subject[1:]
    s_sql, s_r, s_pend, pos = _unit_sql(reg, s)
    a = u.anchor
    a_col = next((f"{al}.{c}" for al, c in pos.positions.get(var, []) if al == a.alias), None)
    s_col = s_r.bound.get(var)
    if a_col is None or s_col is None:
        return None
    a_where = " AND ".join(pos.filters.get(a.alias, []) or ["TRUE"])
    n = _sample_size(reg, s, t) if (t is not None and hits) else SAMPLE_N
    smp = (f"SELECT x0 FROM (SELECT DISTINCT {a_col} AS x0 FROM {pos.table[a.alias]} AS {a.alias} "
           f"WHERE {a_where} LIMIT {SCAN_CAP}) a ORDER BY x0 LIMIT {n}")
    cols = [f"{s_col} AS x0"]
    joins, fans, out = [], [], ["(SELECT count(*) FROM smp)", "count(su.x0)"]
    if t is not None:
        t_sql, t_r, t_pend, _ = _unit_sql(reg, t)
        conn = [e for e in reg.edges if {e.u, e.v} == {s, t}]
        vars_ = sorted({e.var for e in conn})
        eqs = []
        for k, v in enumerate(vars_):
            if v not in s_r.bound or v not in t_r.bound:
                return None
            cols.append(f"{s_r.bound[v]} AS y{k}")
            eqs.append(f"{t_r.bound[v]} = su.y{k}")
        if hits:
            joins.append(f"CROSS JOIN LATERAL (SELECT count(*) AS n FROM (SELECT 1 FROM {t_sql} WHERE "
                         + " AND ".join(t_pend + eqs) + f" LIMIT {FAN_CAP}) z) h")
            out.append("coalesce(sum(h.n), 0)")
        else:
            out.append("-1")
        # the physical fan-out of each probe into t by object (a probe into
        # t's subject reads one subject's leaves: 1, nothing to learn)
        for e in conn:
            first = e.leaf_u if e.u == t else (e.leaf_v if e.kind == "shared" else None)
            if first is None:
                continue
            col = next((c for al, c in pos.positions.get(e.var, []) if al == first.alias), None)
            if col is None:
                continue
            k = vars_.index(e.var)
            fa = first.alias
            fw = " AND ".join(pos.filters.get(fa, []) + [f"{fa}.{col} = su.y{k}"])
            joins.append(f"CROSS JOIN LATERAL (SELECT count(*) AS n FROM (SELECT 1 FROM "
                         f"{pos.table[fa]} AS {fa} WHERE {fw} LIMIT {FAN_CAP}) z) f{len(fans)}")
            fans.append((e, len(out)))
            out.append(f"coalesce(sum(f{len(fans) - 1}.n), 0)")
    su = (f"SELECT {', '.join(cols)} FROM {s_sql} WHERE "
          + " AND ".join(s_pend + [f"{a_col} = smp.x0"]) + f" LIMIT {FAN_CAP}")
    sql = (f"WITH smp AS ({smp}) SELECT ARRAY[{', '.join(out)}]::float8[] AS v "
           f"FROM smp LEFT JOIN LATERAL ({su}) su ON TRUE " + " ".join(joins))
    from .generator import substitute_constants
    sql = substitute_constants(sql, reg.aliases)
    if "_const" in sql:              # an unresolved constant: matches nothing, nothing to learn
        return None
    return _Question(region=reg, unit=s, target=t, fans=fans, sql=sql, n=n)


def _sample_size(reg, s: int, t: int) -> int:
    """Source subjects to sample for a join-size question from s into t, so that
    completing t stays within HIT_BUDGET rows. Per sampled row, the probe into t
    reads its fan-out (stored-statistics estimate) and completes t's other
    leaves for each. Two slot stars joined on a shared `?d` probe each other by
    object through the whole decision graph (~888 members), and 256 samples of
    that timed out the batch, leaving the plan on stored statistics."""
    from . import qplan
    fan = 1.0
    for e in reg.edges:
        if {e.u, e.v} == {s, t}:
            f = qplan._probe_fan(e, t)
            if f:
                fan = max(fan, f)
    per_row = fan * max(1, len(reg.units[t].leaves))
    return int(max(MIN_N, min(SAMPLE_N, HIT_BUDGET / per_row)))


def _hits_side(reg, i: int, j: int) -> int:
    """Which unit of a pair to sample the join size from. Completing the other
    unit per sampled row costs one probe per row it reaches, so: from the unit
    holding a link into the other's subject (one row per probe), else from the
    smaller unit. The other direction measures only its fan-out, which is an
    index count (a decision graph's ~1,088 members, completed through a slot
    star per member, made one question cost 10 s)."""
    for e in reg.edges:
        if e.kind == "link" and {e.u, e.v} == {i, j}:
            return e.u
    ri, rj = (reg.units[i].rows.rows or 0.0), (reg.units[j].rows.rows or 0.0)
    return i if ri <= rj else j


def _questions(reg) -> List[_Question]:
    out = []
    paired = set()
    for e in reg.edges:
        if e.u >= len(reg.units) or e.v >= len(reg.units):
            continue
        key = (min(e.u, e.v), max(e.u, e.v))
        if key in paired:
            continue
        paired.add(key)
        hs = _hits_side(reg, *key)
        for s, t in (key, key[::-1]):
            q = _question(reg, s, t, hits=(s == hs))
            if q:
                out.append(q)
    asked = {q.unit for q in out}
    for i, u in enumerate(reg.units):
        if i not in asked and len(u.leaves) >= 2:
            q = _question(reg, i, None)
            if q:
                out.append(q)
    return out


# ---------------------------------------------------------------------------
# Running them
# ---------------------------------------------------------------------------

async def _run(sqls: List[str], conn, conn_params) -> List[Optional[List[float]]]:
    """All questions in one statement; if that fails (a timeout, typically), each
    on its own under a shorter timeout, so one slow question costs only its own
    answer. A question that fails alone answers None."""
    try:
        return await _run_batch(sqls, conn, TIMEOUT_MS)
    except Exception as exc:
        logger.info("qcard: batch of %d failed (%s); asking each alone", len(sqls), type(exc).__name__)
    out: List[Optional[List[float]]] = []
    for s in sqls:
        try:
            out.append((await _run_batch([s], conn, ONE_TIMEOUT_MS))[0])
        except Exception:
            out.append(None)
    return out


async def _run_batch(sqls: List[str], conn, timeout_ms: int) -> List[List[float]]:
    from . import db_provider as db
    batch = " UNION ALL ".join(f"(SELECT {i} AS q, v FROM ({s}) b{i})" for i, s in enumerate(sqls))

    async def go(c):
        # A savepoint when the caller has a transaction open, so a timeout here
        # cannot abort it; and SET, not SET LOCAL, restored after, because SET
        # LOCAL outlives a savepoint's RELEASE (see `db_provider.bounded_lock_wait`).
        async with c.transaction():
            prev = await c.fetchval("SHOW statement_timeout")
            await c.execute(f"SET statement_timeout = '{int(timeout_ms)}ms'")
            try:
                return await db.execute_query(batch, conn=c)
            finally:
                try:
                    await c.execute(f"SET statement_timeout = '{prev}'")
                except Exception:  # aborted: the savepoint's rollback reverts the SET
                    logger.debug("could not restore statement_timeout to %s", prev)

    if conn is not None:
        rows = await go(conn)
    else:
        async with db.get_pool().acquire() as c:
            rows = await go(c)
    got = {r["q"]: list(r["v"]) for r in rows}
    return [got[i] for i in range(len(sqls))]


async def walk_hit_rate(q, space_id: str, conn=None, conn_params=None) -> Optional[float]:
    """For a LIMIT page walked by ?v (`qplan.topk_driver`): the share of the
    first SAMPLE_N values of ?v, in the order an early stop walks them, for which
    the WHOLE pattern has a solution. One statement: the values off the driver
    unit's anchor, each tested with the pattern rendered correlated on ?v (as a
    correlated NOT EXISTS body is). None when the shape is not one it can ask
    (NOT EXISTS or a sub-SELECT in the pattern) or the question fails."""
    from . import qplan
    from .generator import substitute_constants
    reg = q.region
    drv = qplan.topk_driver(q, reg)
    if drv is None or reg.antis or any(l.kind == "subq" for u in reg.units for l in u.leaves):
        return None
    var, d = drv
    a = reg.units[d].anchor
    if a is None or a.s_var != var:
        return None
    pos = qplan._Pos(reg.plans, reg.values)
    a_col = next((f"{al}.{c}" for al, c in pos.positions.get(var, []) if al == a.alias), None)
    if a_col is None:
        return None
    a_where = " AND ".join(pos.filters.get(a.alias, []) or ["TRUE"])
    smp = (f"SELECT DISTINCT {a_col} AS x0 FROM {pos.table[a.alias]} AS {a.alias} "
           f"WHERE {a_where} ORDER BY x0 LIMIT {SAMPLE_N}")
    tree = qplan._search_bound(reg, [var])
    br = qplan._R(qplan._Pos(reg.plans, reg.values), outer={var: "smp.x0"})
    bsql, _bp, bpend = qplan._render_node(tree, reg, br)
    body = f"SELECT 1 FROM {bsql}" + (" WHERE " + " AND ".join(bpend) if bpend else "")
    sql = (f"WITH smp AS ({smp}) SELECT ARRAY[count(*), count(*) FILTER (WHERE EXISTS ({body}))]"
           f"::float8[] AS v FROM smp")
    sql = substitute_constants(sql, reg.aliases)
    if "_const" in sql:
        return None
    key = (space_id, sql)
    if key not in _cache:
        _cache[key] = (await _run([sql], conn, conn_params))[0]
    v = _cache[key]
    if not v or v[0] <= 0:
        return None
    # no hit in the sample: the rate is below 1/n; take half that, not zero
    return (v[1] if v[1] > 0 else 0.5) / v[0]


def _visit_order(node) -> List[int]:
    """Units in the order the plan builds them: the leftmost scan first."""
    if node.kind == "scan":
        return [node.unit]
    if node.kind == "probe":
        return _visit_order(node.left) + [node.unit]
    return _visit_order(node.left) + _visit_order(node.right)


def _connected(reg, mask: int) -> bool:
    members = [i for i in range(len(reg.units)) if mask >> i & 1]
    seen, todo = {members[0]}, [members[0]]
    while todo:
        x = todo.pop()
        for e in reg.edges:
            for a, b in ((e.u, e.v), (e.v, e.u)):
                if a == x and b < len(reg.units) and mask >> b & 1 and b not in seen:
                    seen.add(b)
                    todo.append(b)
    return len(seen) == len(members)


def _path_question(reg, tree) -> Optional[Tuple[str, List[int], float]]:
    """One statement sampling join prefixes AS WHOLES: the first SAMPLE_N
    subjects of the driver (the plan's leftmost unit), then one unit at a time,
    each step a MATERIALIZED join of the previous step's rows with the next unit
    (so a prefix costs its own rows, not a re-join from scratch). The order is
    the plan's build order, taking the first unit connected to those joined so
    far (no step is a cross product). Returns (sql, the masks counted, the
    driver anchor's rows), or None when the plan cannot be asked."""
    from .generator import substitute_constants
    plan_order = _visit_order(tree)
    d = plan_order[0]
    u = reg.units[d]
    if not u.subject.startswith("?") or u.anchor is None or u.anchor.s_var is None:
        return None
    var = u.subject[1:]
    a = u.anchor
    d_sql, d_r, d_pend, pos = _unit_sql(reg, d)
    a_col = next((f"{al}.{c}" for al, c in pos.positions.get(var, []) if al == a.alias), None)
    dcol = d_r.bound.get(var)
    if a_col is None or dcol is None:
        return None
    a_where = " AND ".join(pos.filters.get(a.alias, []) or ["TRUE"])
    smp = (f"SELECT x0 FROM (SELECT DISTINCT {a_col} AS x0 FROM {pos.table[a.alias]} AS {a.alias} "
           f"WHERE {a_where} LIMIT {SCAN_CAP}) a ORDER BY x0 LIMIT {SAMPLE_N}")

    def cols(r):
        return {v: c for v, c in r.bound.items()}
    have = cols(d_r)
    ctes = [f"smp AS ({smp})",
            "c0 AS MATERIALIZED (SELECT " + ", ".join(f"{c} AS v_{v}" for v, c in sorted(have.items()))
            + f" FROM {d_sql} WHERE " + " AND ".join(d_pend + [f"{dcol} IN (SELECT x0 FROM smp)"])
            + f" LIMIT {PATH_CAP})"]
    joined, mask, masks = [d], 1 << d, []
    rest = [i for i in plan_order if i != d]
    while rest:
        nxt = next((i for i in rest if _connected(reg, mask | 1 << i)), None)
        if nxt is None:
            break
        rest.remove(nxt)
        try:
            t_sql, t_r, t_pend, _p = _unit_sql(reg, nxt)
        except Exception:
            break
        tcols = cols(t_r)
        eqs = [f"{tcols[v]} = pv.v_{v}" for v in sorted(set(tcols) & set(have))]
        if not eqs:
            break
        k = len(joined)
        new_vars = {v: c for v, c in tcols.items() if v not in have}
        sel = ["pv.*"] + [f"{c} AS v_{v}" for v, c in sorted(new_vars.items())]
        ctes.append(f"c{k} AS MATERIALIZED (SELECT {', '.join(sel)} FROM c{k - 1} AS pv, {t_sql} WHERE "
                    + " AND ".join(t_pend + eqs) + f" LIMIT {PATH_CAP})")
        have.update({v: f"v_{v}" for v in new_vars})
        joined.append(nxt)
        mask |= 1 << nxt
        masks.append(mask)
    if not masks:
        return None
    counts = ", ".join(f"(SELECT count(*) FROM c{k})" for k in range(1, len(joined)))
    sql = (f"WITH {', '.join(ctes)} SELECT ARRAY[(SELECT count(*) FROM smp), {counts}]::float8[] AS v")
    sql = substitute_constants(sql, reg.aliases)
    if "_const" in sql:
        return None
    return sql, masks, float(a.scan.rows or 0.0)


async def annotate_paths(q, space_id: str, conn=None, conn_params=None) -> Dict[str, float]:
    """Sample the chosen plan's join prefixes as wholes, set `Region.path_rows`,
    re-plan, and repeat for a changed plan (at most PATH_ROUNDS). For regions
    of three or more units: pairs are sampled already (`annotate`)."""
    from . import qplan
    t0 = time.perf_counter()
    asked = failed = 0
    for reg in _regions(q):
        if len(reg.units) < 3 or any(l.kind == "subq" for u in reg.units for l in u.leaves):
            continue
        for _round in range(PATH_ROUNDS):
            tree = qplan.search(reg)
            pq = _path_question(reg, tree)
            if pq is None:
                break
            sql, masks, anchor_rows = pq
            if all(m in reg.path_rows for m in masks):
                break
            key = (space_id, sql)
            if key not in _cache:
                asked += 1
                _cache[key] = (await _run([sql], conn, conn_params))[0]
            v = _cache[key]
            if v is None:
                failed += 1
                break
            n = v[0]
            scale = 1.0 if n < SAMPLE_N else (anchor_rows / n if n > 0 else 1.0)
            exact = n < SAMPLE_N
            for m, c in zip(masks, v[1:]):
                rule = "path_sample_capped" if c >= PATH_CAP else (
                    "path_sample_exact" if exact else "path_sample")
                # none of the sampled subjects completed it: below one sampled row
                rows = c * scale if (c > 0 or exact) else 0.5 * scale
                reg.path_rows[m] = Est(rows, rule)
    from .qplan import refresh_subqueries
    refresh_subqueries(q)
    return {"asked": asked, "failed": failed, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def _regions(q) -> list:
    out = []

    def walk(r):
        out.append(r)
        for o in r.optionals:
            walk(o)
        for a in r.antis:
            walk(a.region)
        for u in r.units:
            for l in u.leaves:
                if l.kind == "subq":
                    walk(l.sub.region)
    walk(q.region)
    return out


async def annotate(q, space_id: str, conn=None, conn_params=None, rec=None) -> Dict[str, float]:
    """Replace the stored-statistics estimates the sample can improve, in place:
    unit rows, pair join sizes (`Region.pair_rows`), probe fan-outs (`Edge.fan`)."""
    t0 = time.perf_counter()
    qs = [x for r in _regions(q) for x in _questions(r)]
    todo = [x for x in qs if (space_id, x.sql) not in _cache]
    if todo:
        vals = await _run([x.sql for x in todo], conn, conn_params)
        for x, v in zip(todo, vals):
            _cache[(space_id, x.sql)] = v
    failed = 0
    # the largest sample first: a unit's rows are set by the first answer for it
    for x in sorted(qs, key=lambda x: -x.n):
        v = _cache[(space_id, x.sql)]
        if v is None:                # failed alone: this question keeps the stored estimates
            failed += 1
            continue
        _apply(x, v)
    for r in _regions(q):
        _pairs(r)
    from .qplan import refresh_subqueries
    refresh_subqueries(q)            # a sub-SELECT's groups and cost, from its sampled region
    return {"questions": len(qs), "sampled": len(todo), "failed": failed,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


def _apply(x: _Question, v: List[float]) -> None:
    reg, u = x.region, x.region.units[x.unit]
    n_anchor, s_rows = v[0], v[1]
    anchor = u.anchor.scan.rows or n_anchor
    exact = n_anchor < x.n
    scale = (1.0 if exact else anchor / max(n_anchor, 1.0))
    if len(u.leaves) >= 2 and not u.rows.rule.startswith("sample"):
        if s_rows > 0:
            u.rows = Est(s_rows * scale, "sample_exact" if exact else "sample")
        elif n_anchor > 0:
            u.rows = Est(0.0 if exact else 0.5 * scale, "sample_exact" if exact else "sample_zero")
    if x.target is None:
        return
    hits = v[2]
    if s_rows > 0 and hits >= 0:
        if hits > 0:
            j, rule = hits * scale, ("sample_exact" if exact else "sample")
        else:
            j, rule = (0.0, "sample_exact") if exact else (0.5 * scale, "sample_zero")
        reg.pair_samples.setdefault((min(x.unit, x.target), max(x.unit, x.target)), []).append(
            (j, rule, hits))
    if s_rows > 0:
        for e, k in x.fans:
            e.fan[x.target] = v[k] / s_rows


def _pairs(reg) -> None:
    """One join size per unit pair: an exact sample first, else the sample
    with more hits (more observations behind it)."""
    for key, cands in reg.pair_samples.items():
        best = max(cands, key=lambda c: (c[1] == "sample_exact", c[2]))
        reg.pair_rows[key] = Est(best[0], best[1])
