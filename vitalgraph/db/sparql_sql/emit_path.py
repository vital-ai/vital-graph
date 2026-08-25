"""Handler for KIND_PATH — Property path emission.

Produces SQL using WITH RECURSIVE CTEs for property path patterns.
The CTE always produces (start_uuid, end_uuid, ctx_uuid) triples —
ctx_uuid is a standard column carried through every path variant, not
a conditional add-on.  This treats context_uuid the same as
subject_uuid / object_uuid.

When inside ``GRAPH ?g``, the ``same_graph`` flag enforces that all
steps in a sequence / recursion share the same ctx_uuid, and the outer
SELECT binds ``?g`` via a term-table JOIN — identical to how subject
and object variables are bound.

Supports: PathLink, PathInverse, PathSeq, PathAlt, PathOneOrMore,
PathZeroOrMore, PathZeroOrOne, PathNegPropSet.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from ..jena_sparql.jena_types import (
    VarNode, URINode,
    PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne,
    PathNegPropSet, PathExpr,
)
from .ir import PlanV2
from .emit_context import EmitContext
from .collect import _esc

logger = logging.getLogger(__name__)

# NO DEPTH FENCE — removed 2026-08-23, `issues/123`.
#
# There was one: `MAX_PATH_DEPTH = 100`, documented as "cycle prevention +
# backstop". It was containing a runaway that the mechanism enforcing it
# created.
#
# The recursive CTEs below use `UNION`, which deduplicates, and that is what
# normally terminates a transitive closure over cyclic data: revisiting a pair
# adds no new row. But `depth` was part of the tuple, so `(s, e, 1)` and
# `(s, e, 2)` were different rows, the dedup never fired, and the recursion ran
# until the cap stopped it. On a three-node cycle: 300 rows with the depth
# column, 9 without — and 9 is the correct answer.
#
# `depth` had no other consumer. Every reference to it was the column list, its
# increment, or the comparison against the cap. It existed to be compared
# against a limit that existed because of it.
#
# What the cap cost while it was there: a chain of 150 links reported 101 nodes,
# silently (`issues/122`). For frame nesting a depth of 100 is beyond anything
# real, which is why it was chosen — but for any LINEAR structure the depth IS
# the length, so the backstop was a size limit.
#
# Runaway is still fenced, and always was by something else: `statement_timeout`
# and `temp_file_limit` (Tier-0 config). The comment this replaces said so
# itself — "It is NOT the primary runaway fence". A high-fan-out predicate over
# a billion-row table blows up in two or three steps regardless of any depth
# limit, so the cap only ever penalised narrow deep paths, which are the ones
# that are cheap.
#
# `tests/integration/test_recursive_path_termination.py` pins both halves: a
# cycle terminates and yields each node once, and a chain longer than the old
# cap is not truncated.
_cte_counter = 0

def _next_cte_name(prefix: str) -> str:
    """Generate a unique CTE name to avoid collisions in nested paths."""
    global _cte_counter
    _cte_counter += 1
    return f"{prefix}_{_cte_counter}"


def _merge_ctes(inner_cte: str, new_body: str) -> str:
    """Merge an inner CTE prefix with a new recursive CTE body.

    If inner_cte is empty, wraps new_body in WITH RECURSIVE.
    If inner_cte exists, strips its WITH RECURSIVE prefix and combines
    both CTE definitions into a single WITH RECURSIVE block.
    """
    if not inner_cte:
        return f"WITH RECURSIVE {new_body}"
    inner_body = inner_cte
    if inner_body.startswith("WITH RECURSIVE "):
        inner_body = inner_body[len("WITH RECURSIVE "):]
    return f"WITH RECURSIVE {inner_body},\n{new_body}"


def emit_path(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit a property path pattern as SQL using WITH RECURSIVE CTEs."""
    meta = plan.path_meta
    if meta is None:
        raise ValueError("path plan has no path_meta")

    path_expr = meta["path"]
    subject = meta["subject"]
    obj = meta["object"]
    quad_table = meta["quad_table"]
    term_table = meta["term_table"]
    graph_uri = meta.get("graph_uri")
    cte_alias = meta["cte_alias"]
    graph_var = meta.get("graph_var")

    from .collect import GRAPH_VAR_SCOPE
    from .default_graph import DEFAULT_GRAPH_URI

    # ── Build graph_clause (WHERE filter on every leaf quad scan) ──
    graph_clauses = []

    # 1. Lock — always applied (scoping / security)
    if ctx.aliases.graph_lock_uri:
        graph_clauses.append(
            f"q.context_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(ctx.aliases.graph_lock_uri)}' AND term_type = 'U' LIMIT 1)"
        )

    # 2. GRAPH <uri> — explicit named graph constraint
    if graph_uri and graph_uri != GRAPH_VAR_SCOPE:
        graph_clauses.append(
            f"q.context_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(graph_uri)}' AND term_type = 'U' LIMIT 1)"
        )

    # 3. Default graph — only when NOT inside a GRAPH clause
    if ctx.aliases.default_graph and graph_uri is None:
        graph_clauses.append(
            f"q.context_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(ctx.aliases.default_graph)}' AND term_type = 'U' LIMIT 1)"
        )

    # Rule 3: IS DISTINCT FROM for negative comparisons (§10.5).
    # GRAPH ?g — exclude default graph (named graphs only).
    # Use IS DISTINCT FROM (not !=) so NULL from a missing default graph
    # term is treated as "no exclusion" rather than filtering all rows.
    #
    # Same fallback as collect.py: without it this fired only when a caller
    # passed an explicit default_graph, leaving `urn:default` enumerable by
    # `GRAPH ?g` on every production query (§4.2).
    if graph_uri == GRAPH_VAR_SCOPE:
        _dg = ctx.aliases.default_graph or DEFAULT_GRAPH_URI
        graph_clauses.append(
            f"q.context_uuid IS DISTINCT FROM (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(_dg)}' AND term_type = 'U' LIMIT 1)"
        )

    graph_clause = ""
    if graph_clauses:
        graph_clause = " AND " + " AND ".join(graph_clauses)

    # same_graph: enforce cross-step ctx_uuid consistency inside GRAPH scopes
    same_graph = graph_uri is not None  # True for GRAPH <uri> and GRAPH ?g

    # ── Generate path CTE — always (start_uuid, end_uuid, ctx_uuid) ──
    #
    # A pinned SUBJECT is handed down so a recursive path can seed its base term
    # from it rather than closing over the whole graph and filtering afterwards.
    # The outer WHERE below still applies the same constraint; it becomes
    # redundant rather than wrong, because every row the seeded CTE produces
    # already starts at the pin.
    # A pinned OBJECT is handed down too. It cannot seed the same recursion —
    # the forward form would anchor the last edge and then extend PAST the pin —
    # so `_path_to_sql` emits a reverse recursion for it instead.
    seed_start_sql = seed_end_sql = None
    if isinstance(subject, URINode):
        seed_start_sql = (
            f"(SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(subject.value)}' AND term_type = 'U' LIMIT 1)"
        )
    elif isinstance(subject, VarNode):
        # The start is a VARIABLE bound by a sibling in the join. `emit_join`
        # hands down SQL producing that variable's uuids, and seeding from it is
        # the difference between walking and closing over the graph.
        #
        # `issues/124`: on `sp_lead_synth_100k` the same walk is 4.2 ms pinned
        # to a constant and does not finish in 120 s reached through a join —
        # 67 s against 26 ms in raw SQL for the identical 53 results, because
        # the unseeded recursion closes over 50M quads before filtering.
        #
        # `ANY (subquery)` rather than `IN (subquery)` deliberately: the seed is
        # substituted into `_base.start_uuid = {seed}` at three sites below, so
        # a set-valued expression that still reads as `= <expr>` needs no new
        # parameter threaded through `_path_to_sql`'s recursion.
        #
        # ALWAYS, never conditionally. A switch between seeded and unseeded
        # would fire or decline on a plan property with the declining case
        # silent, which is the `issues/118` failure exactly. The seeded form is
        # marginally worse on a graph small enough for everything to be fast,
        # and unboundedly better otherwise; that trade is taken unconditionally.
        _seed = plan.hints.get("path_start_seed")
        if _seed:
            seed_start_sql = f"ANY ({_seed})"
    if isinstance(obj, URINode):
        seed_end_sql = (
            f"(SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(obj.value)}' AND term_type = 'U' LIMIT 1)"
        )
    cte_parts, path_select = _path_to_sql(
        path_expr, quad_table, term_table, graph_clause, cte_alias,
        same_graph=same_graph, seed_start_sql=seed_start_sql,
        seed_end_sql=seed_end_sql,
    )

    # ── Subject / object constraints ──
    where_parts = []
    if isinstance(subject, URINode):
        where_parts.append(
            f"{cte_alias}.start_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(subject.value)}' AND term_type = 'U' LIMIT 1)"
        )
    if isinstance(obj, URINode):
        where_parts.append(
            f"{cte_alias}.end_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(obj.value)}' AND term_type = 'U' LIMIT 1)"
        )

    where_clause = ""
    if where_parts:
        where_clause = "\nWHERE " + " AND ".join(where_parts)

    # ── Outer SELECT: bind variables via term-table JOINs ──
    # Same pattern for subject, object, AND graph variable.
    from .sql_type_generation import ColumnInfo

    from .emit_bgp import _NUMERIC_DATATYPES, _BOOLEAN_DT, _DATETIME_DATATYPES
    _NUM_RE = r"'^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$'"
    _DT_RE = r"'^\d{4}-'"

    select_cols = []
    term_joins = []

    # Bind subject, object, and graph variable uniformly
    bindings = [(subject, "start_uuid"), (obj, "end_uuid")]
    if graph_var:
        bindings.append((VarNode(name=graph_var), "ctx_uuid"))

    for node, uuid_col in bindings:
        if isinstance(node, VarNode):
            sn = ctx.types.allocate(node.name)
            t_alias = f"t_{sn}"
            term_joins.append(
                f"JOIN {term_table} AS {t_alias} "
                f"ON {cte_alias}.{uuid_col} = {t_alias}.term_uuid"
            )
            select_cols.append(f"{t_alias}.term_text AS {sn}")
            select_cols.append(f"{t_alias}.term_type AS {sn}__type")
            select_cols.append(f"{cte_alias}.{uuid_col} AS {sn}__uuid")
            select_cols.append(f"{t_alias}.lang AS {sn}__lang")
            _dt_case = ctx.dt_case_expr(t_alias)
            _num_ids = ctx.dt_ids_for_uris(_NUMERIC_DATATYPES)
            _bool_id = ctx.dt_ids_for_uris([_BOOLEAN_DT])
            _dt_ids = ctx.dt_ids_for_uris(_DATETIME_DATATYPES)
            select_cols.append(f"({_dt_case}) AS {sn}__datatype")
            select_cols.append(
                f"CASE WHEN {t_alias}.datatype_id IN ({_num_ids})"
                f" AND {t_alias}.term_text ~ {_NUM_RE}"
                f" THEN CAST({t_alias}.term_text AS NUMERIC) END AS {sn}__num"
            )
            select_cols.append(
                f"CASE WHEN {t_alias}.datatype_id = {_bool_id}"
                f" AND {t_alias}.term_text IN ('true','false','1','0')"
                f" THEN ({t_alias}.term_text = 'true') END AS {sn}__bool"
            )
            select_cols.append(
                f"CASE WHEN {t_alias}.datatype_id IN ({_dt_ids})"
                f" AND {t_alias}.term_text ~ {_DT_RE}"
                f" THEN CAST({t_alias}.term_text AS TIMESTAMP) END AS {sn}__dt"
            )
            info = ColumnInfo.simple_output(node.name, sn, from_triple=True)
            ctx.types._columns[node.name] = info

    if not select_cols:
        select_cols = ["1"]

    # ── Assemble ──
    parts = []
    if cte_parts:
        parts.append(cte_parts)
    parts.append(f"SELECT {', '.join(select_cols)}")
    parts.append(f"FROM ({path_select}) AS {cte_alias}")
    parts.extend(term_joins)
    if where_clause:
        parts.append(where_clause)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# _path_to_sql — converts PathExpr tree to SQL
#
# Always produces (start_uuid, end_uuid, ctx_uuid).
# ctx_uuid = q.context_uuid at the leaf level, propagated through every
# combinator.  When same_graph is True, sequence JOINs and recursive
# steps enforce lp.ctx_uuid = rp.ctx_uuid so the entire path resolves
# within a single named graph.
# ---------------------------------------------------------------------------

def _path_to_sql(path: PathExpr, quad_table: str, term_table: str,
                 graph_clause: str, cte_alias: str,
                 same_graph: bool = False,
                 seed_start_sql: Optional[str] = None,
                 seed_end_sql: Optional[str] = None) -> Tuple[str, str]:
    """Convert a PathExpr to SQL.

    Returns (cte_prefix, select_sql) where cte_prefix is a WITH RECURSIVE
    clause (or empty string) and select_sql is a SELECT producing
    (start_uuid, end_uuid, ctx_uuid).

    When same_graph is True, multi-step paths (PathSeq, recursive) enforce
    that all steps share the same ctx_uuid.

    `seed_start_sql` IS A SCALAR SQL EXPRESSION FOR A PINNED SUBJECT, and it is
    what stops a recursive path closing over the whole graph.

    Without it the base term of a `+` or `*` selects EVERY edge in the space and
    the pin is applied afterwards, in the outer WHERE. Measured on
    `graph_synth_10k`: `<one frame> (^hasEdgeSource/hasEdgeDestination)+ ?child`
    with 8 real descendants did not complete in 60 s, because it computed the
    transitive closure of all 144,598 edges and then kept the 8. EXPLAIN showed
    a parallel Gather over 46,911 rows feeding the Recursive Union.

    It applies to the BASE TERM ONLY. The recursive term's `step` relation must
    stay unfiltered — filtering it too would restrict every hop to edges leaving
    the pin, which stops the walk dead after one hop and silently returns only
    the direct neighbours. That is the whole subtlety here.

    Only a pinned SUBJECT is seeded. A pinned object would have to drive the
    recursion backwards, and the recursive term is written forward
    (`r.end_uuid = step.start_uuid`); filtering its base by `end_uuid` would
    anchor the wrong end and then extend PAST it, which is a wrong answer rather
    than a slow one. Tail-pinned paths therefore keep the old plan.
    """

    # Simple link: single quad scan
    if isinstance(path, PathLink):
        pred_filter = (
            f"predicate_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(path.uri)}' AND term_type = 'U' LIMIT 1)"
        )
        sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid, "
            f"q.context_uuid AS ctx_uuid "
            f"FROM {quad_table} q "
            f"WHERE {pred_filter}{graph_clause}"
        )
        return "", sql

    # Inverse: swap start/end, keep ctx_uuid
    if isinstance(path, PathInverse):
        # An inverse swaps the ends, so a pin on this path's start is a pin on
        # the sub-path's end and vice versa.
        cte, inner_sql = _path_to_sql(path.sub, quad_table, term_table,
                                       graph_clause, cte_alias, same_graph,
                                       seed_start_sql=seed_end_sql,
                                       seed_end_sql=seed_start_sql)
        sql = (
            f"SELECT inv.end_uuid AS start_uuid, inv.start_uuid AS end_uuid, "
            f"inv.ctx_uuid "
            f"FROM ({inner_sql}) AS inv"
        )
        return cte, sql

    # Alternative: UNION (both branches carry ctx_uuid)
    if isinstance(path, PathAlt):
        # Both branches start where the alternative starts, so both may be
        # seeded.
        cte_l, sql_l = _path_to_sql(path.left, quad_table, term_table,
                                     graph_clause, cte_alias + "_l", same_graph,
                                     seed_start_sql=seed_start_sql,
                                     seed_end_sql=seed_end_sql)
        cte_r, sql_r = _path_to_sql(path.right, quad_table, term_table,
                                     graph_clause, cte_alias + "_r", same_graph,
                                     seed_start_sql=seed_start_sql,
                                     seed_end_sql=seed_end_sql)
        cte = ""
        if cte_l or cte_r:
            parts = [p for p in [cte_l, cte_r] if p]
            cte = "\n".join(parts)
        sql = f"({sql_l}) UNION ({sql_r})"
        return cte, sql

    # Sequence: JOIN on end→start; enforce same ctx_uuid when same_graph
    if isinstance(path, PathSeq):
        # The sequence's start is the LEFT arm's start, so only the left may be
        # seeded. Seeding the right would anchor a middle node to the pin.
        cte_l, sql_l = _path_to_sql(path.left, quad_table, term_table,
                                     graph_clause, cte_alias + "_l", same_graph,
                                     seed_start_sql=seed_start_sql)
        cte_r, sql_r = _path_to_sql(path.right, quad_table, term_table,
                                     graph_clause, cte_alias + "_r", same_graph,
                                     seed_end_sql=seed_end_sql)
        cte = ""
        if cte_l or cte_r:
            parts = [p for p in [cte_l, cte_r] if p]
            cte = "\n".join(parts)
        ctx_constraint = " AND lp.ctx_uuid = rp.ctx_uuid" if same_graph else ""
        sql = (
            f"SELECT lp.start_uuid, rp.end_uuid, lp.ctx_uuid "
            f"FROM ({sql_l}) AS lp "
            f"JOIN ({sql_r}) AS rp ON lp.end_uuid = rp.start_uuid{ctx_constraint}"
        )
        return cte, sql

    # One or more (+): WITH RECURSIVE
    if isinstance(path, PathOneOrMore):
        inner_cte, base_sql = _path_to_sql(path.sub, quad_table, term_table,
                                            graph_clause, cte_alias + "_base", same_graph)
        rec_name = _next_cte_name(f"{cte_alias}_rec")
        ctx_rec_constraint = " AND r.ctx_uuid = step.ctx_uuid" if same_graph else ""
        # Anchor the base term at the pin. `step` below stays UNFILTERED — see
        # the note on `seed_start_sql` for why filtering it too would truncate
        # the walk to the pin's direct neighbours.
        if seed_start_sql or not seed_end_sql:
            seed_where = (f" WHERE _base.start_uuid = {seed_start_sql}"
                          if seed_start_sql else "")
            rec_body = (
                f"{rec_name}(start_uuid, end_uuid, ctx_uuid) AS (\n"
                f"  SELECT start_uuid, end_uuid, ctx_uuid FROM ({base_sql}) AS _base"
                f"{seed_where}\n"
                f"  UNION\n"
                f"  SELECT r.start_uuid, step.end_uuid, r.ctx_uuid\n"
                f"  FROM {rec_name} r\n"
                f"  JOIN ({base_sql}) AS step ON r.end_uuid = step.start_uuid{ctx_rec_constraint}\n"
                f")"
            )
        else:
            # A pinned OBJECT and a free subject: walk BACKWARD from the pin.
            #
            # Seeding the forward recursion by `end_uuid` would be wrong, not
            # merely slow — it anchors the last edge and then extends PAST the
            # pin, so the answer contains paths that pass through it rather than
            # ending at it. The recursion has to run the other way: the base is
            # the edges arriving AT the pin, and each step PREPENDS an edge,
            # moving `start_uuid` further back while `end_uuid` stays the pin.
            rec_body = (
                f"{rec_name}(start_uuid, end_uuid, ctx_uuid) AS (\n"
                f"  SELECT start_uuid, end_uuid, ctx_uuid FROM ({base_sql}) AS _base"
                f" WHERE _base.end_uuid = {seed_end_sql}\n"
                f"  UNION\n"
                f"  SELECT step.start_uuid, r.end_uuid, r.ctx_uuid\n"
                f"  FROM {rec_name} r\n"
                f"  JOIN ({base_sql}) AS step ON step.end_uuid = r.start_uuid"
                f"{ctx_rec_constraint.replace('r.ctx_uuid = step.ctx_uuid', 'step.ctx_uuid = r.ctx_uuid')}\n"
                f")"
            )
        cte = _merge_ctes(inner_cte, rec_body)
        sql = f"SELECT DISTINCT start_uuid, end_uuid, ctx_uuid FROM {rec_name}"
        return cte, sql

    # Zero or more (*): WITH RECURSIVE + identity base case
    if isinstance(path, PathZeroOrMore):
        inner_cte, base_sql = _path_to_sql(path.sub, quad_table, term_table,
                                            graph_clause, cte_alias + "_base", same_graph)
        rec_name = _next_cte_name(f"{cte_alias}_rec")
        # Identity: every node connected to itself (within its graph).
        #
        # Unseeded this is TWO full scans of the quad table, which is worse than
        # the `+` case it mirrors — a `*` path from a pinned subject materialised
        # every subject and every object in the space before anything filtered
        # it. With a pin, identity is the pin alone, and the scan reduces to the
        # rows that mention it.
        # A pin at EITHER end reduces identity to that one node: `<C> p* ?x`
        # and `?x p* <C>` both include only (C, C) from the zero-length branch.
        _id_pin = seed_start_sql or seed_end_sql
        _id_seed_s = f" AND q.subject_uuid = {_id_pin}" if _id_pin else ""
        _id_seed_o = f" AND q.object_uuid = {_id_pin}" if _id_pin else ""
        _id_where = graph_clause + _id_seed_s
        _id_where_o = graph_clause + _id_seed_o
        identity_sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.subject_uuid AS end_uuid, "
            f"q.context_uuid AS ctx_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + _id_where if _id_where else ''} "
            f"UNION SELECT q.object_uuid, q.object_uuid, "
            f"q.context_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + _id_where_o if _id_where_o else ''}"
        )
        ctx_rec_constraint = " AND r.ctx_uuid = step.ctx_uuid" if same_graph else ""
        if seed_end_sql and not seed_start_sql:
            # Same reversal as `+`: from the identity row (C, C), PREPEND edges
            # so `start_uuid` walks backwards and `end_uuid` stays the pin.
            # Extending forward from (C, C) would return C's DESCENDANTS, which
            # is the opposite question.
            step_join = (f"  SELECT step.start_uuid, r.end_uuid, "
                         f"r.ctx_uuid\n"
                         f"  FROM {rec_name} r\n"
                         f"  JOIN ({base_sql}) AS step "
                         f"ON step.end_uuid = r.start_uuid{ctx_rec_constraint}\n")
        else:
            step_join = (f"  SELECT r.start_uuid, step.end_uuid, "
                         f"r.ctx_uuid\n"
                         f"  FROM {rec_name} r\n"
                         f"  JOIN ({base_sql}) AS step "
                         f"ON r.end_uuid = step.start_uuid{ctx_rec_constraint}\n")
        rec_body = (
            f"{rec_name}(start_uuid, end_uuid, ctx_uuid) AS (\n"
            f"  ({identity_sql})\n"
            f"  UNION\n"
            f"{step_join}"
            f")"
        )
        cte = _merge_ctes(inner_cte, rec_body)
        sql = f"SELECT DISTINCT start_uuid, end_uuid, ctx_uuid FROM {rec_name}"
        return cte, sql

    # Zero or one (?): identity UNION one step
    if isinstance(path, PathZeroOrOne):
        _, base_sql = _path_to_sql(path.sub, quad_table, term_table,
                                    graph_clause, cte_alias + "_base", same_graph)
        # Same identity full-scan as `*`, and seeded the same way. Not
        # recursive, so it cannot run away — but unseeded it is still two full
        # passes over the quad table to produce the one row `<C> p? ?x` needs
        # from the zero-length branch.
        _s = f" AND q.subject_uuid = {seed_start_sql}" if seed_start_sql else ""
        _o = f" AND q.object_uuid = {seed_start_sql}" if seed_start_sql else ""
        _w, _wo = graph_clause + _s, graph_clause + _o
        identity_sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.subject_uuid AS end_uuid, "
            f"q.context_uuid AS ctx_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + _w if _w else ''} "
            f"UNION SELECT q.object_uuid, q.object_uuid, q.context_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + _wo if _wo else ''}"
        )
        sql = f"({identity_sql}) UNION ({base_sql})"
        return "", sql

    # Negated property set: all predicates EXCEPT the listed ones
    # ^uri entries are inverse: exclude on object→subject direction
    if isinstance(path, PathNegPropSet):
        fwd_uris = [u for u in path.uris if not u.startswith("^")]
        inv_uris = [u[1:] for u in path.uris if u.startswith("^")]

        parts = []
        if fwd_uris or not inv_uris:
            if fwd_uris:
                excl = " AND ".join(
                    f"q.predicate_uuid != (SELECT term_uuid FROM {term_table} "
                    f"WHERE term_text = '{_esc(u)}' AND term_type = 'U' LIMIT 1)"
                    for u in fwd_uris
                )
                parts.append(
                    f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid, "
                    f"q.context_uuid AS ctx_uuid "
                    f"FROM {quad_table} q WHERE {excl}{graph_clause}"
                )
            else:
                parts.append(
                    f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid, "
                    f"q.context_uuid AS ctx_uuid "
                    f"FROM {quad_table} q"
                    + (f" WHERE TRUE{graph_clause}" if graph_clause else "")
                )
        if inv_uris:
            excl = " AND ".join(
                f"q.predicate_uuid != (SELECT term_uuid FROM {term_table} "
                f"WHERE term_text = '{_esc(u)}' AND term_type = 'U' LIMIT 1)"
                for u in inv_uris
            )
            parts.append(
                f"SELECT q.object_uuid AS start_uuid, q.subject_uuid AS end_uuid, "
                f"q.context_uuid AS ctx_uuid "
                f"FROM {quad_table} q WHERE {excl}{graph_clause}"
            )

        sql = " UNION ".join(f"({p})" for p in parts) if len(parts) > 1 else parts[0]
        return "", sql

    # Fallback
    logger.warning("Unsupported path type: %s", type(path).__name__)
    return "", "SELECT NULL AS start_uuid, NULL AS end_uuid, NULL AS ctx_uuid WHERE FALSE"
