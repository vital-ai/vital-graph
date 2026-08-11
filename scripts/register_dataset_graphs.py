"""Register a graph row for every space whose quads carry a context but do not.

Every dataset lives in a graph. The `graph` table is what makes that graph
visible to the application — space listing, graph enumeration, the API paths
that validate a graph before querying it. Loading quads with a `context_uuid`
puts the data IN a graph; it does not REGISTER one, and the loader scripts only
ever did the former.

Found on the local cluster 2026-08-10: eight spaces with data and no graph row,
including every generated perf fixture.

    sp_lead_synth_100k   50,570,000 quads    0 graph rows
    sp_lead_synth_10k     5,057,000 quads    0 graph rows
    wordnet_exp           7,375,106 quads    0 graph rows
    sp_lead_types         1,011,150 quads    0 graph rows
    sp_lead_dup             253,248 quads    0 graph rows
    sp_lead_depth1          252,850 quads    0 graph rows
    sp_kg_rel               279,886 quads    0 graph rows
    kgquery_perf              3,682 quads    0 graph rows

Consequences, which is why this is worth a script rather than a manual INSERT:
the fixtures cannot be exercised through the API or the client, so nothing
end-to-end runs against them — `issues/061` records the perf suite not reading
them for exactly this reason.

THE URI IS READ FROM THE DATA, NOT CONSTRUCTED. A graph row whose `graph_uri`
does not match the `context_uuid` the quads actually carry is worse than no row:
it registers a graph that resolves to nothing, and every query through it
returns empty while looking correctly configured. So each space is asked what
contexts its quads are in, and only a space with exactly one is registered
automatically — anything else is reported for a human, because picking among
several is a judgement about what the dataset IS.

Mirrors `sparql_sql_space_impl.create_graph`, which is the explicit mechanism.
Nothing here runs from a data path: spaces and graphs are created deliberately.

    python scripts/register_dataset_graphs.py            # report only
    python scripts/register_dataset_graphs.py --apply    # write the rows
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.getcwd())
import asyncpg  # noqa: E402

DSN = os.environ.get("TDSN",
                     "postgresql://hadfield@localhost:5432/sparql_sql_graph")
MIN_QUADS = 1_000

# Spaces integration tests create and drop. Registering a graph for one leaves a
# row pointing at a table that will not exist by morning, which is a worse state
# than the one being fixed.
EPHEMERAL_PREFIXES = ("inttest_", "apitest_", "dawg_test", "sp_dedup_test",
                      "sp_vgeo_e2e", "sp_geo_test")


async def _spaces_with_quads(conn):
    rows = await conn.fetch("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name LIKE '%\\_rdf\\_quad'
        ORDER BY 1
    """)
    return [r["table_name"][:-len("_rdf_quad")] for r in rows]


async def _contexts(conn, space_id):
    """(uri, quads) for each context the space's quads actually carry."""
    try:
        return await conn.fetch(f"""
            SELECT t.term_text AS uri, count(*) AS quads
            FROM {space_id}_rdf_quad q
            JOIN {space_id}_term t ON t.term_uuid = q.context_uuid
            GROUP BY 1 ORDER BY 2 DESC
        """)
    except Exception:
        return []


async def main(apply: bool) -> int:
    conn = await asyncpg.connect(DSN)
    registered = await conn.fetch("SELECT space_id, graph_uri FROM graph")
    have = {r["space_id"] for r in registered}
    known_spaces = {r["space_id"] for r in
                    await conn.fetch("SELECT space_id FROM space")}

    to_write, skipped = [], []
    for space_id in await _spaces_with_quads(conn):
        if space_id in have:
            continue
        if space_id.startswith(EPHEMERAL_PREFIXES):
            continue
        ctxs = await _contexts(conn, space_id)
        total = sum(c["quads"] for c in ctxs)
        if total < MIN_QUADS:
            continue
        if space_id not in known_spaces:
            skipped.append((space_id, total,
                            "no row in `space` — register the space first"))
            continue
        if len(ctxs) != 1:
            skipped.append((space_id, total,
                            f"{len(ctxs)} contexts; choosing among them is a "
                            f"judgement about what the dataset is"))
            continue
        to_write.append((space_id, ctxs[0]["uri"], int(ctxs[0]["quads"])))

    if not to_write and not skipped:
        print("  every space with quads already has a graph row")
        await conn.close()
        return 0

    for space_id, uri, quads in to_write:
        print(f"  {'REGISTER' if apply else 'would register'}  "
              f"{space_id:24s} -> {uri}   ({quads:,} quads)")
    for space_id, quads, why in skipped:
        print(f"  SKIP      {space_id:24s} {quads:>12,} quads — {why}")

    if apply:
        for space_id, uri, _ in to_write:
            # Same statement create_graph issues. graph_name defaults the way it
            # does there, so a row written here is indistinguishable from one
            # written through the API.
            await conn.execute(
                "INSERT INTO graph (space_id, graph_uri, graph_name, created_time)"
                " VALUES ($1, $2, $3, $4)",
                space_id, uri, uri.rsplit('/', 1)[-1], datetime.now())
        print(f"\n  wrote {len(to_write)} graph row(s)")
    elif to_write:
        print(f"\n  {len(to_write)} to write — re-run with --apply")

    await conn.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the rows (default is report only)")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.apply)))
