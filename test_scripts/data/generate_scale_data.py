#!/usr/bin/env python3
"""
Scale-factor synthetic data generator (for growth-curve / L2 scaling tests).

Loads a space with N synthetic KGEntities directly via COPY (fast, deterministic,
seeded) — the fixture behind `tests/performance/test_growth_curve.py`, which
loads the *same* operation at several sizes and asserts the cost metric keeps
its complexity class (flat/log/linear) rather than creeping to O(N).

Writes straight to the schema tables (term + rdf_quad) — bypassing the SPARQL
pipeline — so it can hit millions of rows quickly and reproducibly. Each entity:
    <e_i>  vital-core:vitaltype  haley:KGEntity
    <e_i>  vital-core:hasName    "Entity number i"

Usage (CLI, standalone):
    python test_scripts/data/generate_scale_data.py --space perf_scale --entities 100000
    # DB via VG_TEST_PG_* env (defaults to host PG:5432; runner points at :5433)

Importable:
    from test_scripts.data.generate_scale_data import load_scale_space
    await load_scale_space(pool, "perf_scale", n_entities=100_000)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from pathlib import Path
from typing import List, Tuple

import asyncpg

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
HASNAME = "http://vital.ai/ontology/vital-core#hasName"
KGENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
_QUAD_NS = uuid.UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")


def _build_rows(n_entities: int, graph_uri: str
                ) -> Tuple[List[tuple], List[tuple]]:
    """Return (term_rows, quad_rows) for COPY. Deterministic given inputs."""
    # Shared terms
    p_vt = _generate_term_uuid(VITALTYPE, "U")
    p_name = _generate_term_uuid(HASNAME, "U")
    o_kgent = _generate_term_uuid(KGENTITY, "U")
    g = _generate_term_uuid(graph_uri, "U")

    # term columns: (term_uuid, term_text, term_type). lang/datatype_id NULL,
    # dataset defaults. Dedup by uuid.
    terms = {
        p_vt: (VITALTYPE, "U"),
        p_name: (HASNAME, "U"),
        o_kgent: (KGENTITY, "U"),
        g: (graph_uri, "U"),
    }
    quads: List[tuple] = []  # (subject, predicate, object, context, quad_uuid)
    for i in range(n_entities):
        e_uri = f"urn:perf:e:{i:09d}"
        name = f"Entity number {i}"
        e = _generate_term_uuid(e_uri, "U")
        nm = _generate_term_uuid(name, "L")
        terms[e] = (e_uri, "U")
        terms[nm] = (name, "L")
        quads.append((e, p_vt, o_kgent, g, uuid.uuid5(_QUAD_NS, f"{i}:t")))
        quads.append((e, p_name, nm, g, uuid.uuid5(_QUAD_NS, f"{i}:n")))

    term_rows = [(k, v[0], v[1]) for k, v in terms.items()]
    return term_rows, quads


async def load_scale_space(pool: asyncpg.Pool, space_id: str, n_entities: int,
                           graph_uri: str = "urn:perf", drop_first: bool = True) -> int:
    """Create `space_id` and COPY-load `n_entities` synthetic entities. Returns
    the quad count. Runs ANALYZE so the planner has fresh stats."""
    async with pool.acquire() as conn:
        if drop_first:
            try:
                await SparqlSQLSchema.drop_space(conn, space_id)
            except Exception:
                pass
        await SparqlSQLSchema.create_space(conn, space_id)

        term_rows, quad_rows = _build_rows(n_entities, graph_uri)
        t = SparqlSQLSchema.get_table_names(space_id)

        await conn.copy_records_to_table(
            t["term"].split(".")[-1], records=term_rows,
            columns=["term_uuid", "term_text", "term_type"])
        await conn.copy_records_to_table(
            t["rdf_quad"].split(".")[-1], records=quad_rows,
            columns=["subject_uuid", "predicate_uuid", "object_uuid",
                     "context_uuid", "quad_uuid"])

        # VACUUM (ANALYZE): fresh stats + set the visibility map so index-only
        # scans on the covering indexes don't do heap fetches (COPY leaves the
        # heap all-not-visible until vacuumed). VACUUM can't run in a txn.
        await conn.execute(f"VACUUM (ANALYZE) {t['term']}")
        await conn.execute(f"VACUUM (ANALYZE) {t['rdf_quad']}")
        return len(quad_rows)


async def _main(args):
    pool = await asyncpg.create_pool(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5432")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", ""),
        min_size=1, max_size=2)
    try:
        n = await load_scale_space(pool, args.space, args.entities,
                                   graph_uri=args.graph, drop_first=not args.keep)
        print(f"Loaded {args.entities} entities ({n} quads) into '{args.space}' / '{args.graph}'")
    finally:
        await pool.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Generate synthetic scale data for growth-curve tests")
    p.add_argument("--space", default="perf_scale")
    p.add_argument("--graph", default="urn:perf")
    p.add_argument("--entities", type=int, default=100_000)
    p.add_argument("--keep", action="store_true", help="Do not drop the space first")
    asyncio.run(_main(p.parse_args()))
