"""Render a plan chosen over the annotated tree as SQL + vg:plan advice
(planning_planner/09, the deliverable).

The written JOIN nesting IS the plan: planned under `join_collapse_limit = 1`,
PostgreSQL follows the tree and chooses join methods from the sizes the advice
gives it. Supported shape, the one `qcost` scores: a hub unit, units linked to
it (required or OPTIONAL, each its own block), then ORDER BY / LIMIT and the
decode of the projected variables, which runs on the limited rows only.

Joins are derived from VARIABLE POSITIONS, not from the generator's tagged
constraints: an OPTIONAL block's join to the hub is implied by the shared
variable and never written as a constraint. Single-table filters (constants,
graph scope) come from the tagged constraints, unchanged.

Anything outside the supported shape raises `Unsupported`: the caller then
keeps today's SQL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from archive.planner_prototypes.qcost import ANCHOR, Linked, _star
from vitalgraph.db.sparql_sql.qtree import Block, Unit

_ALIAS = re.compile(r"\b([a-z][a-z0-9_]*[0-9])\.")


class Unsupported(Exception):
    pass


@dataclass
class Rendered:
    sql: str                        # with __CONST_x__ tokens; substitute before running
    advice: str
    columns: List[str]              # output column per projected variable, in order
    sizes: List[Tuple[str, float, List[str]]] = field(default_factory=list)


class _Ctx:
    """Positions, filters and table names across the whole plan."""

    def __init__(self, plan):
        self.table: Dict[str, str] = {}
        self.filters: Dict[str, List[str]] = {}
        self.positions: Dict[str, List[Tuple[str, str]]] = {}
        self.term_table: Optional[str] = None
        self._walk(plan)

    def _walk(self, p):
        if p.kind == "bgp":
            for t in p.tables:
                if t.kind == "term":
                    self.term_table = self.term_table or t.table_name
                else:
                    self.table[t.alias] = t.table_name
            for owner, sql in p.tagged_constraints:
                refs = set(_ALIAS.findall(sql))
                if refs <= {owner}:
                    self.filters.setdefault(owner, []).append(sql)
                elif not re.fullmatch(r"\s*\w+\.\w+ = \w+\.\w+\s*", sql):
                    raise Unsupported(f"cross-table condition that is not a variable equality: {sql}")
            for var, slot in p.var_slots.items():
                for pos in slot.positions:
                    if pos[0] in self.table or any(t.alias == pos[0] and t.kind != "term" for t in p.tables):
                        self.positions.setdefault(var, []).append(pos)
        for c in p.children:
            self._walk(c)


def _unit_sql(u: Unit, cx: _Ctx, bound: Dict[str, str]) -> Tuple[str, List[str]]:
    """A unit as a join nest: anchor, then its probes. Returns the SQL and the
    conditions the ENCLOSING join must carry (the anchor's own filters, which
    cannot sit on a bare first table)."""
    order = [u.anchor] + list(u.probes)
    first = order[0].alias
    parts = [f"{cx.table[first]} AS {first}"]
    pending = list(cx.filters.get(first, []))
    present = {first}
    _bind(order[0].alias, cx, bound)
    for leaf in order[1:]:
        a = leaf.alias
        conds = _equalities(a, cx, bound, present) + cx.filters.get(a, [])
        parts.append(f"JOIN {cx.table[a]} AS {a} ON " + " AND ".join(conds or ["TRUE"]))
        present.add(a)
        _bind(a, cx, bound)
    if len(parts) == 1:
        return parts[0], pending
    # Fold the anchor's filters into the first ON so the nest is self-contained.
    head, rest = parts[0], parts[1:]
    rest[0] = rest[0] + (" AND " + " AND ".join(pending) if pending else "")
    return "(" + head + "\n   " + "\n   ".join(rest) + ")", []


def _bind(alias: str, cx: _Ctx, bound: Dict[str, str]):
    """Record the first position of every variable this alias binds."""
    for var, poss in cx.positions.items():
        for a, col in poss:
            if a == alias and var not in bound:
                bound[var] = f"{a}.{col}"


def _equalities(alias: str, cx: _Ctx, bound: Dict[str, str], present: Set[str]) -> List[str]:
    """`alias.col = <first position>` for every variable `alias` shares with
    what is already joined."""
    out = []
    for var, poss in cx.positions.items():
        canon = bound.get(var)
        if canon is None or canon.split(".")[0] not in present:
            continue
        for a, col in poss:
            if a == alias and f"{a}.{col}" != canon:
                out.append(f"{a}.{col} = {canon}")
    return out


def _block_units(L: Linked) -> List[Unit]:
    return [L.unit] + (list(L.extra.units) if L.extra else [])


def render(tree: Block, modes: Dict[str, str], plan, names: Optional[Dict[str, str]] = None,
           ctx=None) -> Rendered:
    """`names` (sparql var -> sql name) and `ctx` (the EmitContext): emit the
    executor's full column set per variable, under the names the generator
    already allocated (`TypeRegistry.term_table_columns`). Without them, one
    decoded text column per variable (development and comparison)."""
    if any(m != ANCHOR for m in modes.values()):
        raise Unsupported("only all-anchor star plans are rendered so far")
    hub, linked = _star(tree)
    if hub is None:
        raise Unsupported("no hub unit")
    mods = _modifiers(tree)
    cx = _Ctx(plan)
    if cx.term_table is None:
        raise Unsupported("no term table to decode with")

    bound: Dict[str, str] = {}
    hub_sql, hub_pending = _unit_sql(hub, cx, bound)
    present = {l.alias for l in hub.leaves}
    sql = hub_sql
    where = list(hub_pending)
    advice = [_unit_advice(hub, "u0")] if len(hub.leaves) > 1 else []
    sizes = []
    acc = [l.alias for l in hub.leaves]
    hub_rows = hub.rows.rows or 0.0
    rows = hub_rows

    for i, L in enumerate(linked, 1):
        units = _block_units(L)
        inner_sqls, inner_present = [], set()
        local_bound: Dict[str, str] = dict(bound)
        nest = None
        for j, u in enumerate(units):
            usql, upend = _unit_sql(u, cx, local_bound)
            if nest is None:
                nest, nest_pending = usql, upend
            else:
                eqs = _equalities_between(u, cx, local_bound, inner_present)
                nest = f"({nest}\n  JOIN {usql} ON " + " AND ".join(eqs + upend or ["TRUE"]) + ")"
            inner_present |= {l.alias for l in u.leaves}
            advice.append(_unit_advice(u, f"u{i}{'abcdefgh'[j]}"))
        # join the block to what is already built, on the shared variables
        eqs = []
        for var, poss in cx.positions.items():
            canon = bound.get(var)
            if canon is None or canon.split(".")[0] not in present:
                continue
            for a, col in poss:
                if a in inner_present:
                    eqs.append(f"{a}.{col} = {canon}")
                    break
        join_kw = "LEFT JOIN" if L.optional else "JOIN"
        sql = f"{sql}\n{join_kw} {nest} ON " + " AND ".join(eqs + nest_pending or ["TRUE"])
        if len(units) > 1:
            inner_rows = min(u.rows.rows or 0.0 for u in units)
            sizes.append((f"b{i}", inner_rows, sorted(inner_present)))
        if not L.optional:
            rows = min(rows, L.unit.rows.rows or 0.0)
        present |= inner_present
        acc += sorted(inner_present)
        sizes.append((f"k{i}", rows, list(acc)))
        for var, pos in local_bound.items():
            bound.setdefault(var, pos)

    # the key set, sorted and cut, then decoded
    proj = mods.get("project") or []
    order = mods.get("order") or []
    limit, offset = mods.get("limit"), mods.get("offset", 0)
    keys = []
    for v in proj:
        if v not in bound:
            raise Unsupported(f"projected ?{v} is not bound by the plan")
        keys.append(f"{bound[v]} AS k_{v}")
    sort_joins, sort_cols = [], []
    for n, (expr, direction) in enumerate(order):
        v = str(expr).lstrip("?")
        if v not in bound:
            raise Unsupported(f"ORDER BY {expr}: not a plain bound variable")
        ts = f"sort{n}"
        sort_joins.append(f"LEFT JOIN {cx.term_table} AS {ts} ON {ts}.term_uuid = {bound[v]}")
        d = "DESC" if str(direction).upper().startswith("DESC") else "ASC"
        for col in ("dt_val", "num_val", "term_text"):
            keys.append(f"{ts}.{col} AS s{n}_{col}")
            sort_cols.append((f"s{n}_{col}", d))
    inner = "SELECT " + ",\n  ".join(keys) + "\nFROM " + sql + ("\n" + "\n".join(sort_joins) if sort_joins else "")
    if where:
        inner += "\nWHERE " + " AND ".join(where)
    if sort_cols:
        inner += "\nORDER BY " + ", ".join(f"{c} {d}" for c, d in sort_cols)
    if limit is not None and limit >= 0:
        inner += f"\nLIMIT {limit}"
    if offset:
        inner += f" OFFSET {offset}"
    if names is not None and ctx is not None:
        from vitalgraph.db.sparql_sql.emit_bgp import (_BOOLEAN_DT, _DATETIME_DATATYPES, _NUMERIC_DATATYPES,
                               _NUMERIC_DT_SQL_LIST)
        from vitalgraph.db.sparql_sql.sql_type_generation import TypeRegistry
        cols = []
        for v in proj:
            sn = names.get(v)
            if sn is None:
                raise Unsupported(f"no SQL name allocated for ?{v}")
            t = f"d_{v}"
            cols += TypeRegistry.term_table_columns(
                sn, t, "top", _NUMERIC_DT_SQL_LIST,
                dt_case_sql=ctx.dt_case_expr(t),
                numeric_dt_id_list=ctx.dt_ids_for_uris(_NUMERIC_DATATYPES),
                boolean_dt_id=ctx.dt_ids_for_uris([_BOOLEAN_DT]),
                datetime_dt_id_list=ctx.dt_ids_for_uris(_DATETIME_DATATYPES))
        # the uuid companion reads `top.<sn>__uuid`
        inner = inner.replace("SELECT ", "SELECT " + ", ".join(
            f"{bound[v]} AS {names[v]}__uuid" for v in proj) + ",\n  ", 1)
        dec = ",\n  ".join(cols)
        out_cols = [names[v] for v in proj]
    else:
        dec = ",\n  ".join(f"d_{v}.term_text AS \"{v}\"" for v in proj)
        out_cols = list(proj)
    djoins = "\n".join(f"LEFT JOIN {cx.term_table} AS d_{v} ON d_{v}.term_uuid = top.k_{v}" for v in proj)
    outer = f"SELECT {dec}\nFROM ({inner}) AS top\n{djoins}"
    if sort_cols:
        outer += "\nORDER BY " + ", ".join(f"top.{c} {d}" for c, d in sort_cols)

    lines = ["/*vg:plan 1"] + [a for a in advice if a] + \
            [f"size {n} {r:.0f} {' '.join(al)}" for n, r, al in sizes] + ["*/"]
    return Rendered(sql=outer, advice="\n".join(lines), columns=out_cols, sizes=sizes)


def _equalities_between(u: Unit, cx: _Ctx, bound: Dict[str, str], present: Set[str]) -> List[str]:
    out = []
    aliases = {l.alias for l in u.leaves}
    for var, poss in cx.positions.items():
        canon = bound.get(var)
        if canon is None or canon.split(".")[0] not in present:
            continue
        for a, col in poss:
            if a in aliases and f"{a}.{col}" != canon:
                out.append(f"{a}.{col} = {canon}")
                break
    return out


def _unit_advice(u: Unit, name: str) -> str:
    if len(u.leaves) < 2 or u.rows.rows is None:
        return ""
    steps = [u.anchor.alias] + [p.alias for p in u.probes]
    r = f"{u.rows.rows:.0f}"
    return f"bgp {name} steps({' '.join(steps)}) rows({' '.join(f'{s}:{r}' for s in steps[1:])})"


def _modifiers(tree: Block) -> Dict:
    out: Dict = {}
    b = tree
    while b is not None and b.kind != "bgp" and b.kind != "left_join" and b.kind != "join":
        if b.kind == "slice":
            m = re.match(r"limit (-?\d+) offset (\d+)", b.note)
            out["limit"], out["offset"] = int(m.group(1)), int(m.group(2))
        elif b.kind == "order":
            out["order"] = b.order
        elif b.kind == "project":
            out["project"] = b.project
        b = b.children[0] if b.children else None
    return out
