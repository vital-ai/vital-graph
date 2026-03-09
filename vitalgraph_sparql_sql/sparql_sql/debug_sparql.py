#!/usr/bin/env python3
"""Debug tool for v2 SPARQL-to-SQL pipeline.

Usage:
    python -m vitalgraph_sparql_sql.sparql_sql.debug_sparql "SELECT ?s WHERE { ?s ?p ?o }"
    python -m vitalgraph_sparql_sql.sparql_sql.debug_sparql --file path/to/query.rq
    python -m vitalgraph_sparql_sql.sparql_sql.debug_sparql --file query.rq --plan   # plan tree only
    python -m vitalgraph_sparql_sql.sparql_sql.debug_sparql --file query.rq --sql    # SQL only
    python -m vitalgraph_sparql_sql.sparql_sql.debug_sparql --file query.rq --sidecar  # raw sidecar JSON
"""

import argparse
import json
import sys
import urllib.request

from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.sparql_sql.ir import AliasGenerator, PlanV2
from vitalgraph.db.sparql_sql.collect import collect
from vitalgraph.db.sparql_sql.emit import emit
from vitalgraph.db.sparql_sql.emit_context import EmitContext

SIDECAR_URL = "http://localhost:7070"


def compile_sparql(sparql: str) -> dict:
    """Send SPARQL to sidecar and return raw JSON response."""
    req = urllib.request.Request(
        f"{SIDECAR_URL}/v1/sparql/compile",
        data=json.dumps({"sparql": sparql}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def show_plan(plan: PlanV2, depth: int = 0) -> None:
    """Print the PlanV2 tree."""
    indent = "  " * depth
    extras = []
    if plan.constraints:
        extras.append(f"constraints={len(plan.constraints)}")
    if plan.filter_exprs:
        extras.append(f"filters={len(plan.filter_exprs)}")
    if plan.extend_var:
        extras.append(f"extend={plan.extend_var}")
    if plan.extend_expr:
        extras.append(f"expr={plan.extend_expr}")
    if plan.group_vars:
        extras.append(f"group_vars={plan.group_vars}")
    if plan.aggregates:
        extras.append(f"aggs={list(plan.aggregates.keys())}")
    if plan.having_exprs:
        extras.append(f"having={len(plan.having_exprs)}")
    if plan.var_slots:
        extras.append(f"vars={list(plan.var_slots.keys())}")
    if plan.project_vars:
        extras.append(f"project={plan.project_vars}")
    if plan.values_vars:
        extras.append(f"values_vars={plan.values_vars}")
    if plan.values_rows:
        extras.append(f"rows={len(plan.values_rows)}")
    if plan.limit is not None:
        extras.append(f"limit={plan.limit}")
    if plan.offset:
        extras.append(f"offset={plan.offset}")
    print(f"{indent}{plan.kind} {' '.join(extras)}")
    for child in plan.children or []:
        show_plan(child, depth + 1)


def main():
    parser = argparse.ArgumentParser(description="Debug v2 SPARQL-to-SQL pipeline")
    parser.add_argument("sparql", nargs="?", help="Inline SPARQL query string")
    parser.add_argument("--file", "-f", help="Path to .rq file")
    parser.add_argument("--space", default="dawg_test", help="Space ID (default: dawg_test)")
    parser.add_argument("--plan", action="store_true", help="Show plan tree only")
    parser.add_argument("--sql", action="store_true", help="Show SQL only")
    parser.add_argument("--sidecar", action="store_true", help="Show raw sidecar algebra JSON")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            sparql = f.read()
    elif args.sparql:
        sparql = args.sparql
    else:
        parser.error("Provide SPARQL as argument or --file path")
        return

    # Step 1: Sidecar compile
    raw = compile_sparql(sparql)
    if not raw.get("ok", raw.get("phases")):
        print("Sidecar error:", json.dumps(raw, indent=2), file=sys.stderr)
        sys.exit(1)

    if args.sidecar:
        alg = raw.get("phases", {}).get("algebraCompiled", {}).get("op", {})
        print(json.dumps(alg, indent=2))
        if not args.plan and not args.sql:
            return

    # Step 2: Map + Collect
    cr = map_compile_response(raw)
    if cr.algebra is None:
        print("No algebra in compile result", file=sys.stderr)
        sys.exit(1)

    aliases = AliasGenerator()
    plan = collect(cr.algebra, args.space, aliases)

    if args.plan or not args.sql:
        print("=== Plan Tree ===")
        show_plan(plan)
        print()

    if args.plan and not args.sql:
        return

    # Step 3: Emit SQL
    ctx = EmitContext(space_id=args.space, aliases=aliases)
    sql = emit(plan, ctx)

    print("=== Generated SQL ===")
    print(sql)
    print()

    # Show TypeRegistry state
    if not args.sql:
        print("=== TypeRegistry ===")
        for var, info in ctx.types._columns.items():
            print(f"  {var}: text={info.text_col} type={info.type_col} "
                  f"uuid={info.uuid_col} dt={info.dt_col} num={info.num_col} "
                  f"from_triple={info.from_triple}")


if __name__ == "__main__":
    main()
