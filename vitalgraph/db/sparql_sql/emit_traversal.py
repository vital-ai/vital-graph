"""Emit a traversal chain hop by hop, so the pinned end drives the walk.

Step 3 of `planning_performance/traversal_chain_plan.md`. `traversal_chain`
finds the chain and `traversal_decision` says whether to walk it hop-wise; this
is the part that changes the SQL.

WHAT IS WRONG WITH THE FLAT JOIN

A depth-3 filtered walk emits nine tables in one join. Every row estimate in it
is 1 (`issues/090`), so PostgreSQL picks a root essentially arbitrarily — and it
picks the criterion, not the pin. Measured on graph_synth_10k, `score >= 50`,
depth 3, one start entity:

    generated flat join     70,180 buffers   planning 26.5 ms   execution 56.6 ms
    nested CROSS JOIN LATERAL   194 buffers   planning 30.0 ms   execution  1.9 ms

Same answer. 362x fewer buffers and 29x less execution; planning is a flat ~28 ms
either way, which is the whole reason wall-clock shows 13x rather than 29x. The
flat plan drove from `q19` — hop 2's score criterion — and probed the pinned
entity last. The nested form drives from `femv0.source_entity_uuid = <pin>`,
which is 7 rows, and probes outward.

NESTED, NOT SEQUENTIAL

The measurement in the plan doc was for `CROSS JOIN LATERAL (... OFFSET 0)` per
hop and did not say how the laterals compose. It matters, and only one of the
two options works here.

Sequential laterals — `FROM a CROSS JOIN LATERAL (x) l1 CROSS JOIN LATERAL (y)
l2` — put each hop in its own scope. `l2` can see `a` and `l1`'s OUTPUT COLUMNS,
but not the aliases INSIDE `l1`. Hop 2's join condition references
`femv1.dest_entity_uuid`, and `femv1` lives inside `l1`, so every such condition
would have to be REWRITTEN to name a projected column instead. That is string
surgery on generated SQL, which is exactly what `reorder_joins` documents as
having cost 8x when its cardinality lookup tried to recover meaning from
constraint text (`issues/061`).

Nesting each hop inside the previous one keeps every enclosing alias in lexical
scope, at any depth, so constraints are emitted VERBATIM and nothing is
rewritten. Only the projection is renamed, and the projection is built here from
`var_slots` rather than parsed out of anything.

WHY THE ROWS ARE THE SAME

Each hop is a `CROSS JOIN LATERAL` over a subquery with no LIMIT and no ORDER
BY, so it drops an outer row exactly when an inner join would and duplicates it
exactly as often. `OFFSET 0` is an optimisation fence and does not change the
multiset. The result is the same bag of rows as the flat join, which is what
lets this be chosen per query with the flat form as fallback.

The fence is not cosmetic: unfenced, PostgreSQL flattens the lateral back into
the join and re-chooses the same bad order (16.1 ms against 0.2 ms at depth 3 in
the plan doc's measurements).

WHAT IT DECLINES

Every check below returns None and leaves the flat path untouched. The failure
mode in this area has always been a pass that quietly declines — correct,
slower, invisible — so each refusal is RECORDED, with the values it refused on,
through the rules declared below (`declines.py`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .declines import Rule
from .ir import PlanV2, TableRef
from .traversal_chain import TraversalChain

logger = logging.getLogger(__name__)

# The three decision points in this module, and what each one's preconditions
# read. All run at `emit_bgp`, and all three read `push_filters` — which is the
# whole reason the stage order is declared rather than assumed.
#
# `dedup_chain` reading `push_filters` is not incidental. Asked before push-down
# it sees a per-hop criterion as a filter over a variable dedup discards and
# declines every FILTERED traversal, measured at 1-3 s on a hub start against
# ~100 ms deduplicated. Declaring the read is what stops that being re-introduced
# by moving the call.
HOP_PARTITION = Rule("hop_partition", stage="emit_bgp",
                     reads=("collect", "push_filters"))
HOP_WISE = Rule("hop_wise", stage="emit_bgp",
                reads=("collect", "traversal_decision", "push_filters"))
DEDUP = Rule("dedup_chain", stage="emit_bgp",
             reads=("collect", "traversal_decision", "push_filters"))

# Depth 1 QUALIFIES, matching `traversal_decision.MIN_DEPTH`.
#
# It did not, briefly, and the reason it did not is worth keeping: when a hop
# emitted its link and criteria as one join, a depth-1 chain had no lateral to
# place and would have produced the SAME SQL it was asked to replace. Fencing
# each hop's criteria behind its link — forced by the boolean regression above —
# gave depth 1 a structure of its own, and it is the biggest win measured:
#
#     depth 1, hasActive = true, sparse start   158 ms -> 0.4 ms   417x
#     depth 1, score >= 50,      sparse start    31 ms -> 0.2 ms   153x
#     depth 1, hasActive = true, dense start     72 ms -> 3.0 ms    24x
#
# which is the same mechanism the whole module is for: one hop still has a
# pinned constant that ought to drive, and without the fence it does not.
MIN_EMIT_DEPTH = 1

# `identifier.` — a lexical scan for qualified column references, intersected
# with the aliases we actually emitted. Deliberately not the substring test
# `f"{a}." in sql` used elsewhere: that matches `q1.` inside `xq1.col` and would
# silently assign a constraint to the wrong hop.
_QUALIFIER_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*\.")


@dataclass
class HopGroup:
    """One hop's tables and the constraints that belong to it.

    `tables` is link-first, and the link is emitted ALONE in the hop's FROM with
    every other table of the hop inside a fenced lateral beneath it.

    Listing the link first is not enough, which cost a 55x regression to learn.
    Inside a hop PostgreSQL still reorders freely, and on a boolean criterion it
    did: it drove from `hasActive = true` (13,198 rows) and applied the pinned
    entity as a FILTER on the inner side, 3.4M buffers, the exact pathology this
    module exists to remove. The same query with `score >= 50` happened to pick
    the link — so the flat form was not wrong here, it was LUCKY, and the luck
    ran out on a different criterion.

    A lateral is what makes the dependency one-way. The link is the only table in
    the outer FROM, so nothing can be joined ahead of it.
    """
    index: int
    link_alias: str
    tables: List[TableRef] = field(default_factory=list)
    # alias -> conditions to hang on that table's JOIN ON
    on_map: Dict[str, List[str]] = field(default_factory=dict)
    # conditions belonging to the link itself — this hop's outer WHERE
    where: List[str] = field(default_factory=list)
    # conditions on the FIRST non-link table, which has no JOIN ON to hang on
    crit_where: List[str] = field(default_factory=list)


def _refs(sql: str, known: set) -> set:
    """Aliases this constraint mentions, restricted to ones we emitted."""
    return {m for m in _QUALIFIER_RE.findall(sql or "") if m in known}


def partition_hops(plan: PlanV2, chain: TraversalChain,
                   quad_tables: Sequence[TableRef]) -> Optional[List[HopGroup]]:
    """Split the BGP's tables into one group per hop, or decline.

    A table belongs to a hop when it is that hop's link, or when it reaches
    exactly one link through the constraint graph. `q9` (the score criterion) is
    two constraints away from `femv0` — through `q0`, the frame-type check — so
    reachability is a walk, not adjacency.

    Declines, rather than guessing, when:
      * a table reaches two different hops. It is a cross-hop correlation and
        putting it in either would change which rows survive.
      * a table reaches no hop at all. It is a disconnected island and the flat
        path's cartesian handling is better tested than anything invented here.
      * the plan carries no tagged constraints, so there is no graph to walk.
    """
    tagged = list(plan.tagged_constraints or [])
    if not tagged:
        return HOP_PARTITION.decline(
            "no tagged constraints to partition on",
            tables=[t.alias for t in quad_tables])

    by_alias = {t.alias: t for t in quad_tables}
    known = set(by_alias)

    link_aliases = [l.ref_id for l in chain.links]
    if not all(a in by_alias for a in link_aliases):
        return HOP_PARTITION.decline(
            "chain link(s) are not BGP tables",
            missing=[a for a in link_aliases if a not in by_alias],
            tables=sorted(known))
    hop_of = {a: i for i, a in enumerate(link_aliases)}

    # Adjacency between non-link tables, and each table's direct link contacts.
    adj: Dict[str, set] = {a: set() for a in known}
    for _owner, sql in tagged:
        rs = _refs(sql, known)
        for a in rs:
            adj[a] |= (rs - {a})

    # Label every non-link table by the hop it reaches, walking THROUGH other
    # non-link tables but never through a link (a link is where a hop ends).
    for alias in known:
        if alias in hop_of:
            continue
        seen, frontier, reached = {alias}, [alias], set()
        while frontier:
            cur = frontier.pop()
            for nxt in adj[cur]:
                if nxt in hop_of:
                    reached.add(hop_of[nxt])
                    continue
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        if len(reached) != 1:
            return HOP_PARTITION.decline(
                "a table reaches other than exactly one hop",
                table=alias, reaches=sorted(reached))
        hop_of[alias] = reached.pop()

    groups = [HopGroup(index=i, link_alias=a, tables=[by_alias[a]])
              for i, a in enumerate(link_aliases)]
    for alias, hop in hop_of.items():
        if alias not in link_aliases:
            groups[hop].tables.append(by_alias[alias])

    if not _place(groups, tagged, known, hop_of):
        return None
    return groups


def _place(groups: List[HopGroup], tagged, known: set,
           hop_of: Dict[str, int]) -> bool:
    """Order each hop's tables and assign every constraint to exactly one place.

    A constraint goes to the HIGHEST hop it mentions, because that is the only
    scope where all of its aliases exist — lower hops enclose it. Within the
    hop it hangs on the last-placed table it mentions, so every reference is
    already in scope, which is the same rule `reorder_joins` uses.

    Returns False if a table cannot be connected to what precedes it. That would
    emit `ON TRUE` — a cartesian product inside a lateral — and the flat path
    handles disconnected islands better than this does.
    """
    parsed = [(sql, _refs(sql, known) | {owner}) for owner, sql in tagged]

    for g in groups:
        mine = {t.alias for t in g.tables}
        # Link first, then repeatedly take a table joined to something already
        # placed. Outer hops are always in scope, so only in-hop refs constrain
        # the order.
        placed = [g.link_alias]
        remaining = [t for t in g.tables if t.alias != g.link_alias]
        while remaining:
            nxt = None
            for t in remaining:
                for sql, rs in parsed:
                    if t.alias not in rs:
                        continue
                    if (rs & mine) - {t.alias} <= set(placed):
                        nxt = t
                        break
                if nxt:
                    break
            if nxt is None:
                HOP_PARTITION.decline(
                    "a table joins nothing already placed in its hop",
                    table=remaining[0].alias, hop=g.index, placed=list(placed))
                return False
            placed.append(nxt.alias)
            remaining.remove(nxt)
        order = {a: i for i, a in enumerate(placed)}
        g.tables.sort(key=lambda t: order[t.alias])

    # Every constraint lands exactly once. Losing one silently widens the
    # answer, which is the failure this whole area keeps producing.
    for sql, rs in parsed:
        hop = max(hop_of[a] for a in rs)
        g = groups[hop]
        order = [t.alias for t in g.tables]
        mine = [a for a in rs if hop_of[a] == hop]
        last = max(mine, key=order.index)
        if last == g.link_alias:
            g.where.append(sql)
        elif last == order[1]:
            # The first non-link table opens the criterion lateral's FROM, so it
            # has no JOIN ON to hang on. Its conditions become that lateral's
            # WHERE — including the one tying it back to the link, which is a
            # correlated reference and exactly what makes the lateral lateral.
            g.crit_where.append(sql)
        else:
            g.on_map.setdefault(last, []).append(sql)
    return True


def emit_hop_wise(plan: PlanV2, chain: TraversalChain,
                  quad_tables: Sequence[TableRef],
                  sql_names: Dict[str, str]) -> Optional[str]:
    """The inner BGP query as nested per-hop laterals, or None to decline.

    Replaces only the inner (uuid-level) query of `emit_bgp`. The outer term
    JOINs and companion columns are untouched, so the column contract the rest
    of the pipeline depends on is unchanged.
    """
    if chain is None or chain.depth < MIN_EMIT_DEPTH:
        return HOP_WISE.decline("chain is too shallow",
                                depth=getattr(chain, "depth", None),
                                min_depth=MIN_EMIT_DEPTH)
    if not chain.pinned_head:
        # A tail pin is as good in principle and needs the chain walked in
        # reverse — a different emission, and one nothing has measured. The
        # decision reports tail pins as eligible; this declines them for now
        # rather than emitting a forward walk that drives from the wrong end.
        return HOP_WISE.decline(
            "head is not pinned (tail-pinned reverse walk is not implemented)",
            pinned_head=chain.pinned_head, pinned_tail=chain.pinned_tail)

    groups = partition_hops(plan, chain, quad_tables)
    if not groups:
        return None

    # Nothing to fence and nothing to sequence. A single hop carrying only its
    # link emits exactly the SQL it was asked to replace, so returning it would
    # cost a wasted rewrite and, worse, log "hop-wise" for a plan that is not.
    if len(groups) == 1 and len(groups[0].tables) == 1:
        return HOP_WISE.decline(
            "one hop with no criterion tables, the emitted SQL would be "
            "identical", link=groups[0].link_alias)

    hop_of = {t.alias: g.index for g in groups for t in g.tables}

    # Variables split by where they bind: on the hop's LINK, or on one of its
    # criterion tables. The two sit in different scopes once the criteria are
    # fenced, so the projection has to know which.
    link_binds: Dict[int, List[Tuple[str, str]]] = {g.index: [] for g in groups}
    crit_binds: Dict[int, List[Tuple[str, str]]] = {g.index: [] for g in groups}
    for var, slot in (plan.var_slots or {}).items():
        if not slot.positions:
            continue
        alias, col = slot.positions[0]
        hop = hop_of.get(alias)
        if hop is None:
            return HOP_WISE.decline("a variable binds on a table in no hop",
                                    var=var, alias=alias,
                                    hop_tables=sorted(hop_of))
        target = link_binds if alias == groups[hop].link_alias else crit_binds
        target[hop].append((f"{sql_names[var]}__uuid", f"{alias}.{col}"))

    def _deeper(i: int) -> List[Tuple[str, str]]:
        """Everything bound at hop i's criteria or below — re-projected by name."""
        out = list(crit_binds[i])
        for j in range(i + 1, len(groups)):
            out += link_binds[j] + crit_binds[j]
        return out

    def _criteria(i: int) -> str:
        """Hop i's non-link tables, with hop i+1 nested inside them.

        Deeper hops nest HERE rather than beside the criteria so that a
        constraint belonging to a later hop can still reference hop i's
        criterion aliases — they stay in lexical scope all the way down.
        """
        g = groups[i]
        cols = [f"{expr} AS {name}" for name, expr in crit_binds[i]]
        for j in range(i + 1, len(groups)):
            cols += [f"hop{i + 1}.{n}" for n, _ in link_binds[j] + crit_binds[j]]
        parts = [f"SELECT {', '.join(cols) if cols else '1 AS _dummy'}",
                 f"FROM {g.tables[1].table_name} AS {g.tables[1].alias}"]
        for t in g.tables[2:]:
            conds = g.on_map.get(t.alias)
            parts.append(f"JOIN {t.table_name} AS {t.alias} ON "
                         + (" AND ".join(conds) if conds else "TRUE"))
        if i + 1 < len(groups):
            parts.append(f"CROSS JOIN LATERAL (\n{_body(i + 1)}\n) AS hop{i + 1}")
        if g.crit_where:
            parts.append("WHERE " + " AND ".join(g.crit_where))
        parts.append("OFFSET 0")
        return "\n".join(parts)

    def _body(i: int) -> str:
        """Hop `i`: the link alone, everything else fenced beneath it."""
        g = groups[i]
        cols = [f"{expr} AS {name}" for name, expr in link_binds[i]]
        has_crit = len(g.tables) > 1
        if has_crit:
            cols += [f"crit{i}.{n}" for n, _ in _deeper(i)]
        else:
            for j in range(i + 1, len(groups)):
                cols += [f"hop{i + 1}.{n}"
                         for n, _ in link_binds[j] + crit_binds[j]]

        parts = [f"SELECT {', '.join(cols) if cols else '1 AS _dummy'}",
                 f"FROM {g.tables[0].table_name} AS {g.tables[0].alias}"]
        if has_crit:
            parts.append(f"CROSS JOIN LATERAL (\n{_criteria(i)}\n) AS crit{i}")
        elif i + 1 < len(groups):
            parts.append(f"CROSS JOIN LATERAL (\n{_body(i + 1)}\n) AS hop{i + 1}")
        if g.where:
            parts.append("WHERE " + " AND ".join(g.where))
        if i > 0:
            # The fence. Without it PostgreSQL pulls the lateral back into the
            # surrounding join and re-picks the order this exists to override.
            parts.append("OFFSET 0")
        return "\n".join(parts)

    sql = _body(0)
    logger.info("traversal: emitting %d hops hop-wise (%s), tables per hop %s",
                len(groups), chain.kind, [len(g.tables) for g in groups])
    return sql


# ---------------------------------------------------------------------------
# Set-based emission: deduplicate between hops
# ---------------------------------------------------------------------------
#
# The hop-wise form above still carries one row per PATH. On a wide walk that is
# almost all redundant: `wordnet_frames` depth 3 materialises 501,538 rows to
# produce 3,108 answers, because the distinct entity count per hop is only
# 671 -> 583 -> 3,108 and the rest is the same entities reached different ways.
#
# Deduplicating between hops collapses that. Measured on that query, answer sets
# verified IDENTICAL rather than merely the same size:
#
#     hop-wise, one row per path        2,129 ms
#     deduplicated between hops            61 ms      35x
#
# WHY THIS IS A SEPARATE EMISSION AND NOT A FLAG
#
# It changes the shape from nested laterals to a chain of CTEs, each holding a
# SET of entities. That is the form `traversal_chain_plan.md` rejected for the
# general case, because moving each hop into its own scope means a constraint
# referencing an earlier hop's alias has to be rewritten. It is available here
# only because the precondition below rules those constraints out.
#
# WHEN IT IS WRONG
#
# Deduplicating destroys path multiplicity, and multiplicity is sometimes the
# answer. `SELECT ?e3` without DISTINCT returns one row per path — 501,538 of
# them — and this would return 3,108. `COUNT(*)` would change. Projecting an
# intermediate variable would too. So the precondition is not a heuristic; it is
# the correctness argument, and `dedup_feasible` refuses everything it cannot
# prove.

_TRANSPARENT_ABOVE_BGP = None      # filled in lazily to avoid a circular import


def _expr_vars(expr, out, depth=0):
    """Every variable an expression mentions, walked structurally."""
    from vitalgraph.db.jena_sparql.jena_types import ExprFunction, ExprVar
    if expr is None or depth > 16:
        return out
    if isinstance(expr, ExprVar):
        out.add(expr.var)
    for a in (getattr(expr, "args", None) or []):
        _expr_vars(a, out, depth + 1)
    return out


def _path_to_bgp(node, depth=0):
    """The chain of nodes from `node` down to a single BGP, or None.

    None when there is more than one BGP, or none, or the chain is deeper than
    a traversal query plausibly is. Several BGPs mean something joins to this
    one, and then rows this drops may be rows that join.
    """
    from .ir import KIND_BGP
    if node is None or depth > 8:
        return None
    if node.kind == KIND_BGP:
        return [node]
    kids = list(node.children or [])
    if len(kids) != 1:
        return None
    below = _path_to_bgp(kids[0], depth + 1)
    return None if below is None else [node] + below


def dedup_feasible(root, chain, text_needed_vars):
    """Can this plan's rows be deduplicated between hops without changing it?

    Returns `(final_vars, surviving_vars)` when yes, None when no.
    `surviving_vars` is what still has a value after dedup — the final hop's
    variables plus the pinned head, which is a constant and is carried through.

    Computed from the ROOT of the plan, not from the BGP, because the question
    is what the operators ABOVE the traversal do with path multiplicity — and
    `emit_bgp` cannot see them.

    Every condition here is a correctness condition:

    * **A DISTINCT must be present.** Without one the multiplicity IS the
      result: `SELECT ?e3` returns a row per path.
    * **Only PROJECT / DISTINCT / SLICE / FILTER / ORDER may sit above.** GROUP
      or an aggregate counts rows, which IS the multiplicity. A FILTER is
      row-wise and an ORDER re-arranges rows; neither can observe how many paths
      produced a row. Both are allowed only when every variable they mention
      SURVIVES — a predicate or a sort key over a nulled intermediate column
      would silently drop or mis-order everything.

      ORDER matters more than it looks: `LIMIT` introduces one, sorting by the
      projected variable. Refusing ORDER outright therefore refused every PAGED
      traversal, and measured on graph_synth_100k depth 3 that made `LIMIT 25`
      cost 1,554 ms against 78.9 ms for the same walk unlimited — asking for 25
      rows cost 20x more than asking for all 4,249.
    * **The projection must be a subset of the final hop's variables**, since
      those are the only ones that survive.
    * **Nothing else may need TEXT.** Intermediate variables are emitted NULL,
      and `_wrap_with_terms` joins the term table on `__uuid` with an INNER
      join, so a NULL there would silently DROP rows rather than leave a column
      empty. The pinned head is exempt: it is a constant, so it is carried
      through rather than nulled.
    """
    from .ir import KIND_PROJECT, KIND_DISTINCT, KIND_SLICE, KIND_BGP

    if chain is None or chain.depth < 2 or not chain.pinned_head:
        return DEDUP.decline("chain is too shallow or has no pinned head",
                             depth=getattr(chain, "depth", None),
                             pinned_head=getattr(chain, "pinned_head", None))
    path = _path_to_bgp(root)
    if path is None:
        return DEDUP.decline(
            "no single-child path from the root down to one BGP",
            root_kind=root.kind)
    bgp = path[-1]
    above = path[:-1]

    if not any(n.kind == KIND_DISTINCT for n in above):
        return DEDUP.decline(
            "no DISTINCT above the traversal, so path multiplicity is part "
            "of the answer", above=[n.kind for n in above])
    from .ir import KIND_FILTER, KIND_ORDER
    _ok_kinds = (KIND_PROJECT, KIND_DISTINCT, KIND_SLICE, KIND_FILTER,
                 KIND_ORDER)
    if any(n.kind not in _ok_kinds for n in above):
        return DEDUP.decline(
            "an operator above the traversal may read path multiplicity",
            offending=[n.kind for n in above if n.kind not in _ok_kinds],
            above=[n.kind for n in above])

    quad_tables = [tb for tb in (bgp.tables or [])
                   if tb.kind in ("quad", "edge", "frame_entity")]
    groups = partition_hops(bgp, chain, quad_tables)
    if not groups:
        return None
    last, first = groups[-1], groups[0]
    last_aliases = {t.alias for t in last.tables}

    # SURVIVING is narrower than "bound by the last hop", and the difference
    # cost a wrong answer. `emit_dedup_chain` projects exactly two things: the
    # final link's DEST column, and the pinned head. Everything else — including
    # a criterion value bound on one of the last hop's quad tables — is emitted
    # NULL, because a set of entities does not remember what it was filtered by.
    #
    # Treating all last-hop variables as surviving let a criterion variable keep
    # its term JOIN, which then inner-joined against that NULL and dropped every
    # row: 0 answers where 16 were expected, on 46 of 120 cases.
    final_vars, head_var, final_dest_var = set(), None, None
    for var, slot in (bgp.var_slots or {}).items():
        if not slot.positions:
            continue
        alias, col = slot.positions[0]
        if alias in last_aliases:
            final_vars.add(var)
        if alias == groups[-1].link_alias and col == chain.links[-1].dest_col:
            final_dest_var = var
        if alias == first.link_alias and col == chain.links[0].source_col:
            head_var = var
    if final_dest_var is None:
        return DEDUP.decline(
            "the final hop's destination binds no variable, so nothing "
            "survives to project",
            link=groups[-1].link_alias, dest_col=chain.links[-1].dest_col)

    allowed = {final_dest_var} | ({head_var} if head_var else set())

    projected = set()
    for n in above:
        if n.kind == KIND_PROJECT and n.project_vars:
            projected |= set(n.project_vars)
    if not projected or not projected <= allowed:
        return DEDUP.decline(
            "the projection is not confined to what survives dedup",
            projected=sorted(projected), allowed=sorted(allowed),
            extra=sorted(projected - allowed))


    # A filter or a sort above the traversal is fine only if everything it
    # reads survives. An order key arrives either as a bare variable name or as
    # an expression, so both forms are walked.
    read_above = set()
    for n in above:
        if n.kind == KIND_FILTER:
            for e in (n.filter_exprs or []):
                _expr_vars(e, read_above)
        elif n.kind == KIND_ORDER:
            for key, _dir in (n.order_conditions or []):
                if isinstance(key, str):
                    read_above.add(key)
                else:
                    _expr_vars(key, read_above)
    if not read_above <= allowed:
        return DEDUP.decline(
            "a filter or sort above the traversal reads what dedup discards",
            discarded=sorted(read_above - allowed),
            read_above=sorted(read_above), allowed=sorted(allowed))

    # NOT compared against `text_needed_vars` any more.
    #
    # That set is computed at stage 2c, BEFORE push-down, so a per-hop criterion
    # variable is marked text-needed because a FILTER mentions it. By the time
    # this runs the filter has been pushed into the hop and the variable is
    # unused — but the stale set still named it, and every FILTERED traversal
    # declined on a variable nothing reads. Measured at 1-3 s on a hub start
    # against ~100 ms deduplicated.
    #
    # The caller suppresses the term JOIN for anything outside `allowed`, which
    # is sound by the proof already established above: nothing beyond these
    # variables is read by any operator over this traversal. Emitting a term
    # join for one of them would inner-join against a NULL and drop every row.
    return final_vars, allowed


def emit_dedup_chain(plan: PlanV2, chain: TraversalChain,
                     quad_tables: Sequence[TableRef],
                     sql_names: Dict[str, str],
                     final_vars: set) -> Optional[str]:
    """The inner BGP query as a chain of deduplicating CTEs, or None.

    One CTE per hop, each holding the SET of entities reachable at that depth.
    Every hop's input is therefore distinct entities rather than distinct paths,
    which is where the 35x comes from — the wordnet depth-3 walk goes from
    501,538 rows to 671 -> 583 -> 3,108.

    `final_vars` comes from `dedup_feasible`, which has already proved that
    nothing above this BGP can observe what dedup discards.

    Variables from earlier hops are emitted NULL. They are unreachable by
    construction here — a set of entities does not remember which frame it came
    through — and `dedup_feasible` has established that none of them needs text,
    which is what would turn a NULL `__uuid` into a dropped row at the inner
    term JOIN above.
    """
    groups = partition_hops(plan, chain, quad_tables)
    if not groups:
        return None
    if any(len(g.tables) > 1 and not (g.on_map or g.crit_where) for g in groups):
        return DEDUP.decline(
            "a hop has criterion tables but no condition connecting them, "
            "which would emit a cartesian product",
            hops=[g.index for g in groups
                  if len(g.tables) > 1 and not (g.on_map or g.crit_where)])

    links = {g.link_alias for g in groups}
    head = groups[0]
    head_src = chain.links[0].source_col

    # Only the chain condition may cross a hop boundary. Anything else would
    # reference an alias that this shape puts in another CTE's scope, and
    # rewriting it is exactly what the nested-lateral form exists to avoid.
    for i, g in enumerate(groups):
        allowed = {t.alias for t in g.tables}
        if i:
            allowed.add(groups[i - 1].link_alias)
        for sql in list(g.where) + list(g.crit_where) + \
                [c for cs in g.on_map.values() for c in cs]:
            refs = _refs(sql, links | {t.alias for gg in groups
                                       for t in gg.tables})
            if not refs <= allowed:
                return DEDUP.decline(
                    "a constraint crosses more than the chain link, so it "
                    "would reference an alias in another CTE's scope",
                    hop=i, refs=sorted(refs), in_scope=sorted(allowed))

    ctes = []
    for i, g in enumerate(groups):
        link = chain.links[i]
        parts = [f"SELECT DISTINCT {g.link_alias}.{link.dest_col} AS e"]
        if i == 0:
            # The pinned head is a constant, so carrying it costs no extra rows
            # and keeps a text-needed head variable resolvable.
            parts[0] += f", {g.link_alias}.{head_src} AS head"
            parts.append(f"FROM {g.tables[0].table_name} AS {g.link_alias}")
        else:
            # Every CTE re-projects `head`, so the previous one already carries
            # it — no second reference to d0, which would alias it twice.
            parts[0] += f", d{i - 1}.head AS head"
            parts.append(f"FROM d{i - 1}")
            parts.append(f"JOIN {g.tables[0].table_name} AS {g.link_alias} "
                         f"ON {g.link_alias}.{link.source_col} = d{i - 1}.e")
        for j, t in enumerate(g.tables[1:]):
            # `crit_where` belongs to the FIRST non-link table only; it is where
            # that table's conditions go when it opens a lateral in the hop-wise
            # form. Here it opens a JOIN instead, so it becomes that JOIN's ON.
            conds = g.on_map.get(t.alias) or (g.crit_where if j == 0 else [])
            parts.append(f"JOIN {t.table_name} AS {t.alias} ON "
                         + (" AND ".join(conds) if conds else "TRUE"))
        # The chain condition is now expressed by the join to the previous CTE.
        where = [c for c in g.where
                 if not (i and f"{groups[i-1].link_alias}." in c)]
        if where:
            parts.append("WHERE " + " AND ".join(where))
        ctes.append(f"d{i} AS MATERIALIZED (\n" + "\n".join(parts) + "\n)")

    last = len(groups) - 1
    cols = []
    for var, slot in (plan.var_slots or {}).items():
        sn = sql_names[var]
        if not slot.positions:
            continue
        alias, col = slot.positions[0]
        if var in final_vars and alias == groups[last].link_alias \
                and col == chain.links[last].dest_col:
            cols.append(f"d{last}.e AS {sn}__uuid")
        elif alias == head.link_alias and col == head_src:
            cols.append(f"d{last}.head AS {sn}__uuid")
        else:
            cols.append(f"NULL::uuid AS {sn}__uuid")

    sql = ("WITH " + ",\n".join(ctes) + "\n"
           f"SELECT {', '.join(cols) if cols else '1 AS _dummy'} FROM d{last}")
    logger.info("traversal: emitting %d hops SET-BASED (dedup between hops), "
                "final vars %s", len(groups), sorted(final_vars))
    return sql
