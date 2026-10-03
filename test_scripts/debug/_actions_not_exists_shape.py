#!/usr/bin/env python3
"""What do the two timed-out actions-space queries compile to?

Both were cancelled by `statement_timeout` on production, so neither left any
SQL or plan behind: `report_slow_query` and the plan-shape instrumentation only
fire when a query COMPLETES. This rebuilds the SQL locally so the shape can be
read without needing the queries to finish anywhere.

READ-ONLY. Generates SQL and, if a space is reachable, EXPLAINs it. Never runs
the query itself — the point is that it does not finish.

    SPACE=<space> GRAPH=<graph> python test_scripts/debug/_actions_not_exists_shape.py
    # add EXPLAIN=1 with PG* set to get a plan
"""
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Space by env var: the production name identifies the client, so it is not
# written here. `sp_graph_forms_20k` reproduces the shape locally.
SPACE = os.environ.get("SPACE", "sp_graph_forms_20k")
HALEY = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"

# As sent to `/api/graphs/sparql/query`, verbatim.
Q1 = f"""PREFIX haley: <{HALEY}>
PREFIX vital: <{CORE}>
SELECT (COUNT(*) AS ?n) WHERE {{
  GRAPH ?g {{
    ?x vital:vitaltype haley:KGFrame .
    FILTER NOT EXISTS {{ ?x haley:hasKGFormType ?t }}
    FILTER EXISTS {{ ?x haley:hasFrameGraphURI ?o }}
  }}
}}"""

Q2 = f"""PREFIX haley: <{HALEY}>
PREFIX vital: <{CORE}>
SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {{
  GRAPH ?g {{
    ?x vital:vitaltype haley:KGFrame ;
       haley:hasFrameGraphURI ?o .
    FILTER NOT EXISTS {{ ?x haley:hasKGFormType ?t }}
  }}
}}"""

# A third shape, for comparison: the same question with the graph BOUND. If this
# one is cheap and the others are not, the unbound `GRAPH ?g` is the cost.
Q3 = f"""PREFIX haley: <{HALEY}>
PREFIX vital: <{CORE}>
SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE {{
  GRAPH <{{graph}}> {{
    ?x vital:vitaltype haley:KGFrame ;
       haley:hasFrameGraphURI ?o .
    FILTER NOT EXISTS {{ ?x haley:hasKGFormType ?t }}
  }}
}}"""


def shape(sql: str) -> dict:
    """The handful of things that decide whether this plan can be fast."""
    s = sql.upper()
    return {
        "chars": len(sql),
        "SELECT count": s.count("SELECT"),
        "NOT EXISTS": s.count("NOT EXISTS"),
        "EXISTS": s.count(" EXISTS"),
        "LEFT JOIN": s.count("LEFT JOIN"),
        "DISTINCT": s.count("DISTINCT"),
        "subqueries": s.count("(SELECT"),
        # The thing that forces a scan: a correlated arm the planner hashes
        # rather than indexes (`issues/238`).
        "correlated_exists": len(re.findall(r"EXISTS\s*\(\s*SELECT", s)),
        "quad self-joins": len(re.findall(r"RDF_QUAD\b", s)) ,
        "context filter": ("CONTEXT_UUID" in s),
    }


async def main():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    impl = SparqlSQLSpaceImpl(
        postgresql_config={
            "host": os.environ.get("PGHOST", "localhost"),
            "port": int(os.environ.get("PGPORT", "5433")),
            "database": os.environ.get("PGDATABASE", "sparql_sql_graph"),
            "username": os.environ.get("PGUSER", "postgres"),
            "password": os.environ.get("PGPASSWORD", "testpass"),
            "min_pool_size": 1, "max_pool_size": 2,
        },
        sidecar_config={"url": os.environ.get(
            "VG_SIDECAR_URL", "http://localhost:3031")},
    )
    ok = await impl.connect()
    print(f"connected: {ok}\n")

    graph = os.environ.get("GRAPH", f"urn:{SPACE}")
    for label, q in (("1  original (NOT EXISTS + EXISTS)", Q1),
                     ("2  rewrite (positive triple + NOT EXISTS)", Q2),
                     ("3  control (same as 2, graph BOUND)", Q3.format(graph=graph))):
        print("=" * 74)
        print(f"QUERY {label}")
        print("=" * 74)
        try:
            sql = await impl.get_sparql_sql(SPACE, q)
        except Exception as e:
            print(f"  generation failed: {type(e).__name__}: {e}")
            continue
        if not sql:
            print("  no SQL produced")
            continue
        for k, v in shape(sql).items():
            print(f"  {k:20} {v}")
        print("\n  --- SQL ---")
        print("  " + sql.replace("\n", "\n  ")[:2600])
        print()

    await impl.disconnect()


asyncio.run(main())
