#!/usr/bin/env python3
"""
Inspect spaces and graphs on the production RDS instance.

Uses the same async asyncpg connection pool as the sparql_sql backend.

Usage:
    python test_scripts/prod_db/inspect_spaces.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from db_connect import get_prod_db_impl, print_connection_info


async def main():
    print("=" * 70)
    print("Production RDS — Space & Graph Inspection")
    print("=" * 70)
    print_connection_info()

    db_impl = await get_prod_db_impl()
    pool = db_impl.connection_pool

    try:
        async with pool.acquire() as conn:
            # PostgreSQL version
            version = await conn.fetchval("SELECT version()")
            print(f"\nPostgreSQL: {version}\n")

            # Discover spaces by finding *_term tables
            rows = await conn.fetch("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name LIKE '%_term'
                  AND table_name NOT LIKE '%_rdf_quad'
                ORDER BY table_name
            """)

            spaces = []
            for row in rows:
                term_table = row['table_name']
                space_id = term_table.rsplit('_term', 1)[0]
                quad_table = f"{space_id}_rdf_quad"

                # Verify quad table exists
                exists = await conn.fetchval("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = $1
                """, quad_table)
                if not exists:
                    continue

                quad_count = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_table}")
                term_count = await conn.fetchval(f"SELECT COUNT(*) FROM {term_table}")
                spaces.append({
                    'space_id': space_id,
                    'quad_count': quad_count,
                    'term_count': term_count,
                })

            spaces.sort(key=lambda s: s['quad_count'], reverse=True)

            print(f"--- Spaces ({len(spaces)}) ---")
            for s in spaces:
                print(f"  {s['space_id']:50s}  {s['quad_count']:>8,} quads  {s['term_count']:>8,} terms")

            # Inspect each non-empty space
            for s in spaces:
                if s['quad_count'] == 0:
                    continue

                space_id = s['space_id']
                quad_table = f"{space_id}_rdf_quad"
                term_table = f"{space_id}_term"

                print(f"\n{'=' * 70}")
                print(f"Space: {space_id}  ({s['quad_count']:,} quads, {s['term_count']:,} terms)")
                print(f"{'=' * 70}")

                # Named graphs
                graphs = await conn.fetch(f"""
                    SELECT DISTINCT c.term_text AS graph_uri, COUNT(*) AS cnt
                    FROM {quad_table} q
                    JOIN {term_table} c ON q.context_uuid = c.term_uuid
                    GROUP BY c.term_text
                    ORDER BY cnt DESC
                """)
                print(f"\n  Named graphs ({len(graphs)}):")
                for g in graphs[:20]:
                    print(f"    {g['graph_uri']:<60s}  {g['cnt']:>8,} quads")

                # rdf:type breakdown
                RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
                types = await conn.fetch(f"""
                    SELECT o.term_text AS type_uri, COUNT(*) AS cnt
                    FROM {quad_table} q
                    JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
                    JOIN {term_table} o ON q.object_uuid = o.term_uuid
                    WHERE p.term_text = $1
                    GROUP BY o.term_text
                    ORDER BY cnt DESC
                """, RDF_TYPE)
                print(f"\n  Entity types ({len(types)}):")
                for t in types:
                    print(f"    {t['type_uri']:<70s}  {t['cnt']:>6,}")

                # Predicate summary
                preds = await conn.fetch(f"""
                    SELECT p.term_text AS predicate, COUNT(*) AS cnt
                    FROM {quad_table} q
                    JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
                    GROUP BY p.term_text
                    ORDER BY cnt DESC
                """)
                print(f"\n  Predicates ({len(preds)}):")
                for p in preds:
                    print(f"    {p['predicate']:<70s}  {p['cnt']:>6,}")

                # Edge / frame_entity table presence
                for aux in ('edge', 'frame_entity', 'datatype', 'rdf_pred_stats'):
                    aux_table = f"{space_id}_{aux}"
                    exists = await conn.fetchval("""
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = $1
                    """, aux_table)
                    if exists:
                        cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {aux_table}")
                        print(f"\n  {aux_table}: {cnt:,} rows")

    finally:
        await db_impl.disconnect()

    print(f"\n{'=' * 70}")
    print("Inspection complete.")


if __name__ == "__main__":
    asyncio.run(main())
