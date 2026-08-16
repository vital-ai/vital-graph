"""Turn a single-variable VALUES join into `FILTER(?v IN (...))`.

WHY. `VALUES` is the standard SPARQL way to say "restrict this variable to a
set", and it was the slowest way to say it. `emit_table` renders the rows
correctly — a UNION ALL of literal rows — but that table then becomes a JOIN
operand and nothing carries its constants into the BGP's quad scan. The BGP is
evaluated unrestricted and filtered afterwards.

Measured on a 5.1M-quad space, ten URIs against an entity-graph pattern:

    VALUES ?entity { <u1> ... <u10> }   ~10M rows scanned, 1.9M buffers, 27.9 s
    FILTER(?entity IN (<u1>, ...))      one index search per URI,        59 ms

The same restriction, 470x apart, because `FILTER ... IN` reaches
`filter_pushdown` and becomes `subject_uuid = ANY (...)` while `VALUES` does
not. So rather than teach the emitter a second pushdown path, this rewrites the
one form into the other and lets the proven path do the work.

WHEN IT IS SOUND. `VALUES ?v {...}` joined with pattern P means: evaluate P,
keep rows whose ?v is in the set, and bind ?v. `FILTER(?v IN (...))` over P
means: evaluate P, keep rows whose ?v is in the set. Those agree only under
conditions this checks:

  * ONE variable. `VALUES (?a ?b) { (1 2) (3 4) }` constrains the PAIR — the
    tuples are correlated, and two independent INs would admit (1 4).
  * NO UNDEF. UNDEF means "leave unbound", which is not a value and has no IN
    equivalent; a row of UNDEF matches everything.
  * VALUES ARE URIs OR SIMPLE LITERALS, reusing `filter_pushdown`'s own rule so
    term-equality and value-equality coincide. A typed numeric does not
    qualify: `5`, `5.0` and `05` are three terms and one value.
  * THE OTHER SIDE BINDS THE VARIABLE. If P does not bind ?v, the join is a
    cross product that assigns it, while a FILTER on an unbound variable
    eliminates every row. Opposite answers, so this declines.
  * NO DUPLICATE ROWS. VALUES is a multiset: a repeated row duplicates each
    match, and a FILTER does not. Deduplicating would change cardinality under
    the caller's DISTINCT, so a VALUES with repeats is left alone.

Anything else falls through to today's behaviour, which is slow but correct.
That asymmetry is deliberate: a rewrite that silently changes multiset
semantics is worse than a query that takes 27 seconds.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .ir import KIND_FILTER, KIND_JOIN, KIND_TABLE, PlanV2
from .var_scope import compute_scope

logger = logging.getLogger(__name__)


def _values_constants(node: PlanV2) -> Optional[tuple]:
    """(var, [RDFNode]) when this VALUES table is expressible as an IN, else None."""
    from ..jena_sparql.jena_types import URINode, LiteralNode

    vars_ = node.values_vars or []
    rows = node.values_rows or []
    if len(vars_) != 1 or not rows:
        return None
    var = vars_[0]

    nodes = []
    seen = set()
    for row in rows:
        val = row.get(var)
        if val is None:
            return None                      # UNDEF: not a value
        if isinstance(val, URINode):
            key = ("U", val.value)
        elif isinstance(val, LiteralNode):
            # filter_pushdown's rule, restated as a check rather than reused
            # directly to avoid importing its private helper: only values whose
            # lexical form IS the value.
            if (val.datatype or "") not in ("", "http://www.w3.org/2001/XMLSchema#string"):
                return None
            if getattr(val, "lang", None):
                return None
            key = ("L", val.value or "")
        else:
            return None                      # BNode or anything else
        if key in seen:
            return None                      # multiset semantics; see module doc
        seen.add(key)
        nodes.append(val)
    return var, nodes


def _as_in_filter(var: str, nodes: List, child: PlanV2) -> PlanV2:
    from ..jena_sparql.jena_types import ExprFunction, ExprValue, ExprVar

    expr = ExprFunction(name="in",
                        args=[ExprVar(var=var)] + [ExprValue(node=n) for n in nodes])
    return PlanV2(kind=KIND_FILTER, children=[child], filter_exprs=[expr])


def rewrite_values_filter(plan: Optional[PlanV2], depth: int = 0) -> Optional[PlanV2]:
    """Replace JOIN(VALUES, P) with FILTER(?v IN ...) over P where equivalent."""
    if plan is None or depth > 32:
        return plan

    plan.children = [rewrite_values_filter(c, depth + 1) for c in (plan.children or [])]

    if plan.kind != KIND_JOIN or len(plan.children or []) != 2:
        return plan

    left, right = plan.children[0], plan.children[1]
    for table, other in ((left, right), (right, left)):
        if table is None or table.kind != KIND_TABLE:
            continue
        got = _values_constants(table)
        if got is None:
            continue
        var, nodes = got
        # The other side must DEFINITELY bind the variable — `defined`, not
        # `all_visible`. `all_visible` is `defined | maybe`, and `maybe` is
        # exactly the OPTIONAL/UNION case where the variable can arrive unbound.
        #
        # Those two forms disagree on an unbound value: VALUES is a join, and an
        # unbound variable is compatible with every VALUES row, so the solution
        # survives and gains the binding. `FILTER(?v IN (...))` on an unbound
        # variable eliminates the row instead.
        #
        # Caught by DAWG bindings/values07 (`?o2` bound inside an OPTIONAL,
        # then `VALUES (?o2)` applied after): expected 5 rows, this returned 3.
        # The first version of this guard used `all_visible` and let it through,
        # which is the difference between a variable being MENTIONABLE and being
        # BOUND.
        try:
            scope = compute_scope(other)
        except Exception:
            return plan
        if var not in scope.defined:
            logger.debug(
                "values->in declined: %s is not definitely bound by the other "
                "side (maybe=%s)", var, var in scope.maybe)
            continue
        logger.debug("values->in: %s over %d constant(s)", var, len(nodes))
        return _as_in_filter(var, nodes, other)

    return plan
