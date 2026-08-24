"""Handler for KIND_TABLE — VALUES inline data."""

from __future__ import annotations

from ..jena_sparql.jena_types import URINode, LiteralNode, BNodeNode
from .ir import PlanV2
from .emit_context import EmitContext
from .collect import _esc
from .sql_type_generation import TypeRegistry


def _uuid_expr(ctx, term_text: str, term_type: str) -> str:
    """The term's UUID as a constant token, or NULL if it cannot be registered.

    A VALUES row used to emit `NULL::uuid` here, and that NULL is the whole
    defect (`issues/087`). Downstream the row joins to a quad or edge table on
    `__uuid`; with NULL there, the join cannot use a uuid at all, so the planner
    falls back to comparing the row's TEXT against the term table — measured as
    a full scan of a 10.4M-row table and a 1,292,333-row join filter, turning a
    0.3 ms lookup into 21,790 ms.

    Registering the constant instead routes it through the SAME materialization
    every other constant uses. This runs during EMIT, which is fine: a second
    materialization pass in `generate_sql` exists for exactly the constants
    push-down and this path register late. If one does not resolve — a URI that
    is absent from the term table — `substitute_constants` falls back to a
    scalar subquery over the `_const` CTE, which is correct (an absent term
    matches nothing) and still small.
    """
    aliases = getattr(ctx, "aliases", None)
    if aliases is None or not hasattr(aliases, "register_constant"):
        return "NULL::uuid"
    from .collect import _CONST_PREFIX, _CONST_SUFFIX
    col = aliases.register_constant(term_text, term_type)
    return f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}"


def _all_values_resolved(ctx, rows, var) -> bool:
    """True when every row binds `var` to a constant that resolved to a uuid.

    Conservative by construction: any UNDEF, any blank node, any URI or literal
    missing from the term table, or any inability to inspect the resolution
    table, all return False and keep the slower text join. The cost of being
    wrong in the other direction is a wrong answer.
    """
    aliases = getattr(ctx, "aliases", None)
    if aliases is None or not rows:
        return False
    constants = getattr(aliases, "constants", None)
    resolved = getattr(aliases, "resolved_constants", None)
    if constants is None or resolved is None:
        return False
    for row in rows:
        val = row.get(var)
        # The FULL term identity — `constants` is keyed on
        # (text, type, lang, datatype). A 2-tuple key silently misses every
        # time, this reports "not all resolved", and the VALUES fast path is
        # abandoned: 20 URIs cost 7,342 ms against 0.4 ms for one.
        if isinstance(val, URINode):
            key = (val.value, "U", None, None)
        elif isinstance(val, LiteralNode):
            key = (val.value, "L", getattr(val, "lang", None) or None,
                   val.datatype or None)
        else:
            return False           # UNDEF, blank node, or anything unexpected
        col = constants.get(key)
        if col is None or not resolved.get(col):
            return False
    return True


def emit_table(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a VALUES clause (inline data).

    Produces a UNION ALL of literal rows, e.g.:
        SELECT 'Alice' AS x, 'U' AS x__type, ...
        UNION ALL
        SELECT 'Bob' AS x, 'L' AS x__type, ...

    Row values may be URINode, LiteralNode, BNodeNode (from AST mapper)
    or None (UNDEF).
    """
    vars = plan.values_vars or []
    rows = plan.values_rows or []

    if not rows:
        return "SELECT 1 WHERE FALSE"

    if not vars:
        return " UNION ALL\n".join("SELECT 1" for _ in rows)

    # Allocate opaque SQL names for each variable
    from .sql_type_generation import ColumnInfo
    sql_names = {}  # sparql_var → sql_name
    for var in vars:
        sql_names[var] = ctx.types.allocate(var)

    ctx.log("table", f"vars={sql_names}, rows={len(rows)}")

    row_sqls = []
    for row_dict in rows:
        cols = []
        for var in vars:
            sn = sql_names[var]
            val = row_dict.get(var)
            if val is None:
                cols.extend(TypeRegistry.null_companions(sn))
            elif isinstance(val, URINode):
                cols.append(f"'{_esc(val.value)}' AS {sn}")
                cols.append(f"'U' AS {sn}__type")
                cols.append(f"{_uuid_expr(ctx, val.value, 'U')} AS {sn}__uuid")
                cols.append(f"NULL AS {sn}__lang")
                cols.append(f"NULL AS {sn}__datatype")
                cols.append(f"NULL::numeric AS {sn}__num")
                cols.append(f"NULL::boolean AS {sn}__bool")
                cols.append(f"NULL::timestamp AS {sn}__dt")
            elif isinstance(val, LiteralNode):
                lang_val = f"'{_esc(val.lang)}'" if val.lang else "NULL"
                dt_val = f"'{_esc(val.datatype)}'" if val.datatype else "NULL"
                cols.append(f"'{_esc(val.value)}' AS {sn}")
                cols.append(f"'L' AS {sn}__type")
                cols.append(f"{_uuid_expr(ctx, val.value, 'L')} AS {sn}__uuid")
                cols.append(f"{lang_val} AS {sn}__lang")
                cols.append(f"{dt_val} AS {sn}__datatype")
                cols.append(f"NULL::numeric AS {sn}__num")
                cols.append(f"NULL::boolean AS {sn}__bool")
                cols.append(f"NULL::timestamp AS {sn}__dt")
            elif isinstance(val, BNodeNode):
                # `.label`, not `.value` — BNodeNode has no `value` field, so
                # this raised AttributeError for any VALUES clause containing a
                # blank node. The unit test passed because it patched `.value`
                # onto the node before calling, describing the implementation
                # rather than the type (issues/066).
                #
                # The bare label, matching how a blank node is stored: term_text
                # holds the label and serializers re-add `_:` on the way out.
                cols.append(f"'{_esc(val.label)}' AS {sn}")
                cols.append(f"'B' AS {sn}__type")
                cols.append(f"NULL::uuid AS {sn}__uuid")
                cols.append(f"NULL AS {sn}__lang")
                cols.append(f"NULL AS {sn}__datatype")
                cols.append(f"NULL::numeric AS {sn}__num")
                cols.append(f"NULL::boolean AS {sn}__bool")
                cols.append(f"NULL::timestamp AS {sn}__dt")
            else:
                cols.extend(TypeRegistry.null_companions(sn))

        row_sqls.append(f"SELECT {', '.join(cols)}")

    # Register variables. A variable may claim TERM IDENTITY — letting the join
    # emitter compare `__uuid` instead of casting both sides to text — only when
    # every one of its values is a constant that RESOLVED against the term
    # table. Three cases must not claim it:
    #
    #   UNDEF        no term at all;
    #   unresolved   a URI absent from the term table. Its uuid is NULL, and a
    #                NULL uuid reads as UNBOUND, which joins with EVERYTHING
    #                instead of nothing — a wrong answer, not a slow one;
    #   blank nodes  term identity for these is the open question in issues/065-076.
    #
    # Without identity the join falls back to `CAST(a AS TEXT) = CAST(b AS TEXT)`,
    # which is what made a one-URI VALUES cost 21,790 ms against 0.3 ms for the
    # same query written with a literal subject (`issues/087`).
    for var in vars:
        resolved = _all_values_resolved(ctx, rows, var)
        ctx.types.register(ColumnInfo.simple_output(
            var, sql_names[var], uuid_materialized=resolved))
        if resolved:
            ctx.log("table", f"{var}: uuid identity (all constants resolved)")

    return " UNION ALL\n".join(row_sqls)
