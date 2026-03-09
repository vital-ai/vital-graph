"""Handler for KIND_TABLE — VALUES inline data."""

from __future__ import annotations

from ..jena_sparql.jena_types import URINode, LiteralNode, BNodeNode
from .ir import PlanV2
from .emit_context import EmitContext
from .collect import _esc
from .sql_type_generation import TypeRegistry


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
                cols.append(f"NULL::uuid AS {sn}__uuid")
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
                cols.append(f"NULL::uuid AS {sn}__uuid")
                cols.append(f"{lang_val} AS {sn}__lang")
                cols.append(f"{dt_val} AS {sn}__datatype")
                cols.append(f"NULL::numeric AS {sn}__num")
                cols.append(f"NULL::boolean AS {sn}__bool")
                cols.append(f"NULL::timestamp AS {sn}__dt")
            elif isinstance(val, BNodeNode):
                cols.append(f"'{_esc(val.value)}' AS {sn}")
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

    # Register variables
    for var in vars:
        ctx.types.register(ColumnInfo.simple_output(var, sql_names[var]))

    return " UNION ALL\n".join(row_sqls)
