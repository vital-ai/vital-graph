#!/usr/bin/env python3
"""Count the entity graphs whose entity is gone — `issues/256`, delete decision 1.

Until `issues/256`, deleting an entity WITHOUT `delete_entity_graph=true` (the
default) removed the entity subject alone. Every frame, slot and edge it owned
stayed behind, still naming it in `hasKGGraphURI`. That delete is now refused
while the entity has members, which stops NEW orphans and does nothing for the
ones already stored. This counts them.

An ORPHAN ROOT is a `hasKGGraphURI` value, in some graph, that is not the
subject of any quad in that graph. Its MEMBERS are the subjects that name it,
classified by `vitaltype`.

READ-ONLY: a direct SQL connection with `default_transaction_read_only = on`.
Nothing is changed; deciding what to do with what it finds is a separate step.

Connection as `repair_frame_groupings.py --discover-sql`: PREFIX_DB_HOST,
_PORT, _NAME, _USER, _PASSWORD.

    python scripts/census_entity_orphans.py --db LOCAL [--ssl] [--space ID ...]
"""

import argparse
import asyncio
import os
import sys
import time
from collections import Counter

# The REPO's vitalgraph, not an installed copy, which resolves differently.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid  # noqa: E402

HAS_KG_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI'
VITALTYPE = 'http://vital.ai/ontology/vital-core#vitaltype'


async def _conn(prefix: str, use_ssl: bool):
    import asyncpg
    import ssl as _ssl
    ctx = None
    if use_ssl:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
    conn = await asyncpg.connect(
        host=os.environ[f"{prefix}_DB_HOST"], port=int(os.environ.get(f"{prefix}_DB_PORT", "5432")),
        database=os.environ[f"{prefix}_DB_NAME"], user=os.environ[f"{prefix}_DB_USER"],
        password=os.environ[f"{prefix}_DB_PASSWORD"], ssl=ctx, timeout=30,
        command_timeout=None)
    await conn.execute("SET default_transaction_read_only = on")
    await conn.execute("SET statement_timeout = '30min'")
    return conn


def _kind(vitaltype: str) -> str:
    name = (vitaltype or "").rsplit('#', 1)[-1]
    if not name:
        return "untyped"
    if name.startswith("Edge_"):
        return "edge"
    if name.endswith("Frame"):
        return "frame"
    if "Slot" in name:
        return "slot"
    return "other"


async def census(conn, space: str) -> dict:
    q, term = f"{space}_rdf_quad", f"{space}_term"
    p_kgg = _generate_term_uuid(HAS_KG_GRAPH_URI, 'U')
    p_vt = _generate_term_uuid(VITALTYPE, 'U')
    t0 = time.monotonic()
    # The roots, then the ones with no quad of their own in that graph.
    # Every root, flagged: the TOTAL is what makes a zero readable — a space
    # with no `hasKGGraphURI` at all also has no orphans.
    roots = await conn.fetch(
        f"WITH roots AS (SELECT DISTINCT context_uuid AS g, object_uuid AS e "
        f"               FROM {q} WHERE predicate_uuid = $1) "
        f"SELECT r.g, r.e, NOT EXISTS ("
        f" SELECT 1 FROM {q} x WHERE x.subject_uuid = r.e AND x.context_uuid = r.g)"
        f" AS orphan FROM roots r",
        p_kgg)
    missing = [r for r in roots if r['orphan']]
    out = {"space": space, "roots": len(roots), "orphan_roots": len(missing),
           "members": Counter(), "sample": []}
    if missing:
        rows = await conn.fetch(
            f"WITH m AS (SELECT * FROM unnest($1::uuid[], $2::uuid[]) AS m(g, e)), "
            f"mem AS (SELECT DISTINCT k.subject_uuid AS s, k.context_uuid AS g "
            f"        FROM m JOIN {q} k ON k.predicate_uuid = $3 "
            f"        AND k.object_uuid = m.e AND k.context_uuid = m.g) "
            f"SELECT tt.term_text AS vt, count(*) AS n FROM mem "
            f"LEFT JOIN {q} v ON v.subject_uuid = mem.s AND v.context_uuid = mem.g "
            f" AND v.predicate_uuid = $4 "
            f"LEFT JOIN {term} tt ON tt.term_uuid = v.object_uuid GROUP BY 1",
            [r['g'] for r in missing], [r['e'] for r in missing], p_kgg, p_vt)
        for r in rows:
            out["members"][_kind(r['vt'])] += r['n']
        out["sample"] = [r['term_text'] for r in await conn.fetch(
            f"SELECT term_text FROM {term} WHERE term_uuid = ANY($1) LIMIT 3",
            [r['e'] for r in missing[:3]])]
    out["seconds"] = round(time.monotonic() - t0, 1)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, metavar="PREFIX",
                    help="read PREFIX_DB_HOST/_PORT/_NAME/_USER/_PASSWORD")
    ap.add_argument("--ssl", action="store_true")
    ap.add_argument("--space", action="append",
                    help="limit to these spaces (default: every space with a quad table)")
    a = ap.parse_args()

    conn = await _conn(a.db, a.ssl)
    try:
        spaces = a.space or [r['space_id'] for r in await conn.fetch(
            "SELECT space_id FROM space ORDER BY space_id")]
        total_roots, total = 0, Counter()
        for space in spaces:
            if not await conn.fetchval("SELECT to_regclass($1)", f"{space}_rdf_quad"):
                continue
            r = await census(conn, space)
            total_roots += r["orphan_roots"]
            total.update(r["members"])
            members = ", ".join(f"{k} {v}" for k, v in sorted(r["members"].items())) or "-"
            print(f"{space:36} roots {r['roots']:8}  orphan roots {r['orphan_roots']:7}  members: {members}"
                  f"  ({r['seconds']}s)" + (f"  e.g. {r['sample'][0]}" if r['sample'] else ""),
                  flush=True)
        print(f"{'TOTAL':36} orphan roots {total_roots:7}  members: "
              + (", ".join(f"{k} {v}" for k, v in sorted(total.items())) or "-"))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
