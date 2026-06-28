#!/usr/bin/env python3
"""
happy_words_v2.py — Find WordNet words related to "happy" via v2 SPARQL-to-SQL.

Uses REGEX with case-insensitive flag ("i") per SPARQL standard, and the v2
SQL generation pipeline with MV rewrites + FILTER push-down.

Usage:
    python vitalgraph_sparql_sql/scripts/happy_words_v2.py
    python -m vitalgraph_sparql_sql.scripts.happy_words_v2 [--limit 50]
"""

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.db.jena_sparql.jena_sidecar_client import SidecarClient
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.sparql_sql.generator import generate_sql as v2_generate, warm_stats_cache
from vitalgraph.db.sparql_sql import db_provider
from vitalgraph_sparql_sql import db
from vitalgraph_sparql_sql.db import DevDbImpl

# ---------------------------------------------------------------------------
# Ontology constants
# ---------------------------------------------------------------------------
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_KG_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"

SPACE_ID = "wordnet_exp"

logger = logging.getLogger(__name__)


def _format_sql(sql: str, indent: int = 0) -> str:
    """Format SQL for display: collapse whitespace, indent keywords."""
    import re
    sql = re.sub(r'\s+', ' ', sql.strip())
    pad = ' ' * indent
    for kw in ['FROM', 'JOIN', 'LEFT JOIN', 'WHERE', 'GROUP BY',
               'ORDER BY', 'LIMIT', 'ON ', 'AND ']:
        sql = sql.replace(f' {kw}', f'\n{pad}  {kw}')
    sql = sql.replace('WITH ', f'WITH\n{pad}  ')
    sql = sql.replace(') SELECT ', f')\n{pad}SELECT ')
    return sql


async def _run_query(label: str, sparql: str, sidecar: SidecarClient,
                     save_dir: str = None) -> dict:
    """Compile, generate, execute, and EXPLAIN a single SPARQL query via v2."""
    print(f"\n{'─' * 70}")
    print(f"  {label}")
    print(f"{'─' * 70}")

    # Compile via sidecar
    t0 = time.monotonic()
    raw_json = sidecar.compile(sparql)
    sidecar_ms = (time.monotonic() - t0) * 1000

    cr = map_compile_response(raw_json)
    if not cr.ok:
        print(f"  ERROR: {cr.error}")
        return {}

    async with db.get_connection() as conn:
        # Generate SQL via v2
        t0 = time.monotonic()
        gen = await v2_generate(cr, SPACE_ID, conn=conn)
        gen_ms = (time.monotonic() - t0) * 1000

        sql = gen.sql
        var_map = gen.var_map or {}

        print(f"\n  SQL ({len(sql)} chars, {sql.upper().count(' JOIN ')} JOINs)")
        if save_dir:
            sql_path = os.path.join(save_dir, f"{label.replace(' ', '_').replace(':', '')}.sql")
            with open(sql_path, 'w') as f:
                f.write(_format_sql(sql))
            print(f"  → SQL written to {sql_path}")
        else:
            print(_format_sql(sql, indent=2))
        print()

        # Execute
        t0 = time.monotonic()
        rows = await db.execute_query(sql, conn=conn)
        exec_ms = (time.monotonic() - t0) * 1000

        # EXPLAIN ANALYZE
        explain_rows = []
        try:
            raw = await db.execute_query(f"EXPLAIN ANALYZE {sql}", conn=conn)
            explain_rows = [list(r.values())[0] for r in raw]
        except Exception as e:
            explain_rows = [f"EXPLAIN failed: {e}"]

    # ── Timing Summary ────────────────────────────────────────────────
    print()
    print(f"  {'Metric':<20} {'Value':>12}")
    print(f"  {'─' * 34}")
    print(f"  {'Rows':<20} {len(rows):>12}")
    print(f"  {'Sidecar':<20} {sidecar_ms:>11.0f}ms")
    print(f"  {'Generate (v2)':<20} {gen_ms:>11.0f}ms")
    print(f"  {'Execute':<20} {exec_ms:>11.0f}ms")
    print(f"  {'SQL chars':<20} {len(sql):>12}")
    print(f"  {'─' * 34}")

    # ── EXPLAIN ANALYZE ───────────────────────────────────────────────
    print()
    if save_dir:
        explain_path = os.path.join(save_dir, f"{label.replace(' ', '_').replace(':', '')}_explain.txt")
        with open(explain_path, 'w') as f:
            for line in explain_rows:
                f.write(line + '\n')
        print(f"  → EXPLAIN written to {explain_path}")
    else:
        print(f"  EXPLAIN ANALYZE:")
        print(f"  {'─' * 66}")
        for line in explain_rows:
            print(f"  {line}")
    print()

    # Remap row keys
    remap = {opaque: sparql_name.lower() for opaque, sparql_name in var_map.items()}
    remapped = [{remap.get(k, k): v for k, v in row.items()} for row in rows]

    return {
        "rows": remapped,
        "row_count": len(rows),
        "sql": sql,
        "explain": explain_rows,
        "sidecar_ms": sidecar_ms,
        "gen_ms": gen_ms,
        "exec_ms": exec_ms,
    }


async def run(limit: int = 50, query: str = "all", save_dir: str = None):
    """Query for words related to 'happy' and pretty-print the graph."""

    # ── F1: Relationships ────────────────────────────────────────────────
    rel_sparql = f"""
        SELECT ?srcName ?relationType ?dstName WHERE {{
            ?srcEntity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
            ?srcEntity <{VITAL_NAME}> ?srcName .
            FILTER(REGEX(?srcName, "happy", "i"))

            ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
            ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .

            ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
            ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
            ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
            ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

            ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
            ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
            ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
            ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

            ?dstEntity <{VITAL_NAME}> ?dstName .
        }}
    """

    # ── F2: Frame UNION ──────────────────────────────────────────────────
    frame_sparql = f"""
        SELECT ?entity ?frame ?srcEntity ?dstEntity WHERE {{
            {{
                ?srcEntity <{HALEY_KG_DESC}> ?srcDesc .
                FILTER(REGEX(?srcDesc, "happy", "i"))
                FILTER(?srcEntity != ?dstEntity)

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                BIND(?srcEntity AS ?entity)
            }}
            UNION
            {{
                ?dstEntity <{HALEY_KG_DESC}> ?dstDesc .
                FILTER(REGEX(?dstDesc, "happy", "i"))
                FILTER(?srcEntity != ?dstEntity)

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                BIND(?dstEntity AS ?entity)
            }}
        }}
        ORDER BY ?entity
    """

    print(f"happy_words_v2 — SPARQL-to-SQL v2 pipeline")
    print(f"  space={SPACE_ID}, REGEX case-insensitive")
    print(f"  query={query}, limit={limit}")

    # Configure db_provider so edge table / frame_entity_mv work
    dev_impl = DevDbImpl()
    await dev_impl.connect()
    db_provider.configure(dev_impl)

    # Warm connection pool + stats cache
    t0 = time.monotonic()
    async with db.get_connection() as conn:
        await warm_stats_cache(SPACE_ID, conn=conn)
    warmup_ms = (time.monotonic() - t0) * 1000
    print(f"  stats cache warmed in {warmup_ms:.0f}ms")

    sidecar = SidecarClient()

    run_rels = query in ("all", "relationships")
    run_frames = query in ("all", "frames")

    # ── Relationships ────────────────────────────────────────────────────
    if run_rels:
        print()
        print("=" * 70)
        print("F1: Relationships for 'happy' (REGEX case-insensitive)")
        print("=" * 70)

        info = await _run_query("F1: v2 pipeline", rel_sparql, sidecar, save_dir=save_dir)

        if info.get("rows"):
            print()
            by_relation: dict = {}
            for row in info["rows"]:
                src = row.get("srcname", "?")
                rel = row.get("relationtype", "?")
                dst = row.get("dstname", "?")
                rel_short = rel
                if rel_short.startswith("Edge_Wordnet"):
                    rel_short = rel_short[len("Edge_Wordnet"):]
                elif rel_short.startswith("Edge_"):
                    rel_short = rel_short[len("Edge_"):]
                by_relation.setdefault(rel_short, []).append((src, dst))

            for rel_type in sorted(by_relation.keys()):
                pairs = by_relation[rel_type]
                print(f"  {rel_type} ({len(pairs)})")
                print(f"  {'─' * (len(rel_type) + len(str(len(pairs))) + 3)}")
                for src, dst in sorted(pairs, key=lambda x: (x[0], x[1])):
                    print(f"    {src} ---{rel_type}---> {dst}")
                print()

    # ── Frame UNION ──────────────────────────────────────────────────────
    if run_frames:
        print()
        print("=" * 70)
        print("F2: Frame UNION — entities with 'happy' in description")
        print("  (REGEX case-insensitive, source OR destination side)")
        print("=" * 70)

        info = await _run_query("F2: v2 pipeline", frame_sparql, sidecar, save_dir=save_dir)

        if info.get("rows"):
            # Collect URIs for name resolution
            entity_uris = set()
            frame_uris = set()
            for row in info["rows"]:
                for key in ("entity", "srcentity", "dstentity"):
                    uri = row.get(key)
                    if uri:
                        entity_uris.add(uri)
                f = row.get("frame")
                if f:
                    frame_uris.add(f)

            # Resolve names via direct SQL
            print(f"\n  Resolving names for {len(entity_uris)} entities "
                  f"+ {len(frame_uris)} frames...")
            t0 = time.monotonic()
            name_map: dict = {}
            quad_tbl = f"{SPACE_ID}_rdf_quad"
            term_tbl = f"{SPACE_ID}_term"

            # Entity names (hasName predicate)
            if entity_uris:
                uri_uuids = await db.execute_query(
                    f"SELECT term_uuid, term_text FROM {term_tbl} "
                    f"WHERE term_text = ANY(%s)",
                    params=(list(entity_uris),),
                )
                uri_to_uuid = {r["term_text"]: r["term_uuid"] for r in uri_uuids}
                subject_uuids = [uri_to_uuid[u] for u in entity_uris
                                 if u in uri_to_uuid]
                if subject_uuids:
                    name_pred_rows = await db.execute_query(
                        f"SELECT term_uuid FROM {term_tbl} "
                        f"WHERE term_text = %s LIMIT 1",
                        params=(VITAL_NAME,),
                    )
                    if name_pred_rows:
                        name_pred_uuid = name_pred_rows[0]["term_uuid"]
                        name_rows = await db.execute_query(
                            f"SELECT t_subj.term_text AS uri, "
                            f"t_obj.term_text AS name "
                            f"FROM {quad_tbl} q "
                            f"JOIN {term_tbl} t_subj "
                            f"ON q.subject_uuid = t_subj.term_uuid "
                            f"JOIN {term_tbl} t_obj "
                            f"ON q.object_uuid = t_obj.term_uuid "
                            f"WHERE q.predicate_uuid = %s "
                            f"AND q.subject_uuid = ANY(%s)",
                            params=(name_pred_uuid, subject_uuids),
                        )
                        for r in name_rows:
                            name_map[r["uri"]] = r["name"]

            # Frame type descriptions
            if frame_uris:
                frame_uri_uuids = await db.execute_query(
                    f"SELECT term_uuid, term_text FROM {term_tbl} "
                    f"WHERE term_text = ANY(%s)",
                    params=(list(frame_uris),),
                )
                frame_to_uuid = {r["term_text"]: r["term_uuid"]
                                 for r in frame_uri_uuids}
                frame_subj_uuids = [frame_to_uuid[u] for u in frame_uris
                                    if u in frame_to_uuid]
                if frame_subj_uuids:
                    ftype_pred_rows = await db.execute_query(
                        f"SELECT term_uuid FROM {term_tbl} "
                        f"WHERE term_text = %s LIMIT 1",
                        params=(HALEY_FRAME_TYPE_DESC,),
                    )
                    if ftype_pred_rows:
                        ftype_pred_uuid = ftype_pred_rows[0]["term_uuid"]
                        ftype_rows = await db.execute_query(
                            f"SELECT t_subj.term_text AS uri, "
                            f"t_obj.term_text AS ftype "
                            f"FROM {quad_tbl} q "
                            f"JOIN {term_tbl} t_subj "
                            f"ON q.subject_uuid = t_subj.term_uuid "
                            f"JOIN {term_tbl} t_obj "
                            f"ON q.object_uuid = t_obj.term_uuid "
                            f"WHERE q.predicate_uuid = %s "
                            f"AND q.subject_uuid = ANY(%s)",
                            params=(ftype_pred_uuid, frame_subj_uuids),
                        )
                        for r in ftype_rows:
                            name_map[r["uri"]] = r["ftype"]

            name_wall = (time.monotonic() - t0) * 1000
            print(f"  Resolved {len(name_map)} names in {name_wall:.0f}ms")
            print()

            def _display(uri: str) -> str:
                if not uri or uri == "?":
                    return uri
                name = name_map.get(uri)
                if name:
                    if name.startswith("Edge_Wordnet"):
                        return name[len("Edge_Wordnet"):]
                    elif name.startswith("Edge_"):
                        return name[len("Edge_"):]
                    return name
                parts = uri.rsplit("/", 1)
                return parts[-1] if len(parts) > 1 else uri

            # Group by entity
            by_entity: dict = {}
            for row in info["rows"]:
                entity = row.get("entity", "?")
                frame = row.get("frame", "?")
                src = row.get("srcentity", "?")
                dst = row.get("dstentity", "?")
                by_entity.setdefault(entity, []).append((frame, src, dst))

            for entity_uri in sorted(by_entity.keys(),
                                     key=lambda u: _display(u).lower()):
                frames = by_entity[entity_uri]
                is_src_list = [f for f in frames if f[1] == entity_uri]
                is_dst_list = [f for f in frames if f[2] == entity_uri]

                print(f"  {_display(entity_uri)}")
                if is_src_list:
                    print(f"    as SOURCE ({len(is_src_list)}):")
                    for frame_uri, _, dst_uri in sorted(
                            is_src_list, key=lambda x: _display(x[2]).lower()):
                        print(f"      {_display(entity_uri)} "
                              f"──({_display(frame_uri)})──> "
                              f"{_display(dst_uri)}")
                if is_dst_list:
                    print(f"    as DEST ({len(is_dst_list)}):")
                    for frame_uri, src_uri, _ in sorted(
                            is_dst_list, key=lambda x: _display(x[1]).lower()):
                        print(f"      {_display(src_uri)} "
                              f"──({_display(frame_uri)})──> "
                              f"{_display(entity_uri)}")
                print()

    sidecar.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Find WordNet words related to 'happy' via v2 SPARQL-to-SQL"
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="Max rows to return (default: 0 = no limit)")
    parser.add_argument("-q", "--query", default="all",
                        choices=["all", "relationships", "frames"],
                        help="Which query to run (default: all)")
    parser.add_argument("--save-dir", default=None,
                        help="Directory to write SQL and EXPLAIN files (default: print to console)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    save_dir = args.save_dir
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
    sys.exit(asyncio.run(run(limit=args.limit, query=args.query, save_dir=save_dir)))


if __name__ == "__main__":
    main()
