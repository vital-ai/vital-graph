#!/usr/bin/env python3
"""
happy_words.py — Find WordNet words related to "happy" via SPARQL-to-SQL.

Queries the KGFrame graph structure to find all entities connected to
entities named "happy", then pretty-prints the relationships as:

    happy ---Hyponym---> blissful
    happy ---Hypernym---> feeling

Usage:
    python vitalgraph_sparql_sql/scripts/happy_words.py
    python -m vitalgraph_sparql_sql.scripts.happy_words [--limit 50]
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

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


def _remap_rows(result) -> list:
    """Remap row keys from opaque (v0, v1) to SPARQL variable names using var_map."""
    vm = getattr(result, 'var_map', None) or {}
    if not vm or not result.rows:
        return result.rows or []
    # var_map: {opaque: sparql_name} — lowercase sparql names for PG compat
    remap = {opaque: sparql.lower() for opaque, sparql in vm.items()}
    return [{remap.get(k, k): v for k, v in row.items()} for row in result.rows]


def _format_sql(sql: str, width: int = 100) -> str:
    """Lightly format SQL for display: collapse whitespace, indent keywords."""
    import re
    sql = re.sub(r'\s+', ' ', sql.strip())
    for kw in ['FROM', 'JOIN', 'LEFT JOIN', 'WHERE', 'GROUP BY',
               'ORDER BY', 'LIMIT', 'ON ', 'AND ']:
        sql = sql.replace(f' {kw}', f'\n  {kw}')
    # Wrap WITH/SELECT at top
    sql = sql.replace('WITH ', 'WITH\n  ')
    sql = sql.replace(') SELECT ', ')\nSELECT ')
    return sql


def _print_timing(label: str, timing: dict, wall_ms: float, row_count: int):
    """Print timing breakdown for a run."""
    gd = timing.get("generate_detail", {})
    opt_ms = gd.get("optimize_ms", 0)
    print(f"  {label}:")
    print(f"    rows={row_count}, wall={wall_ms:.0f}ms")
    print(f"    sidecar={timing.get('sidecar_ms', 0):.0f}ms, "
          f"generate={timing.get('generate_ms', 0):.0f}ms, "
          f"execute={timing.get('execute_ms', 0):.0f}ms")
    print(f"    generate detail: "
          f"collect={gd.get('collect_ms', 0):.1f}ms, "
          f"materialize={gd.get('materialize_ms', 0):.1f}ms, "
          f"resolve={gd.get('resolve_ms', 0):.1f}ms, "
          f"emit={gd.get('emit_ms', 0):.1f}ms, "
          f"substitute={gd.get('substitute_ms', 0):.1f}ms, "
          f"optimize={opt_ms:.1f}ms")


def run(limit: int = 50, verbose: bool = False, query: str = "all"):
    """Query for words related to 'happy' and pretty-print the graph.

    Args:
        query: Which section to run — 'relationships', 'frames', or 'all'.
    """

    sparql = f"""
        SELECT ?srcName ?relationType ?dstName WHERE {{
            ?srcEntity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
            ?srcEntity <{VITAL_NAME}> ?srcName .
            FILTER(CONTAINS(?srcName, "happy"))

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

    print(f"Querying WordNet for words related to 'happy' (limit {limit}, query={query})...")
    print()

    # Warm the connection pool before timing
    from vitalgraph_sparql_sql import db
    with db.get_connection() as _:
        pass

    run_rels = query in ("all", "relationships")
    run_frames = query in ("all", "frames")

    results = {}

    if not run_rels:
        # Skip to frame query
        pass

    for opt_flag in [False, True] if run_rels else []:
        label = "optimize=ON" if opt_flag else "optimize=OFF"
        with SparqlOrchestrator(space_id=SPACE_ID, optimize=opt_flag) as orch:
            # Phase 1: get SQL only (no execution)
            sql_result = orch.execute(sparql, sql_only=True)
            if not sql_result.ok:
                print(f"ERROR ({label}): {sql_result.error}")
                return 1

            # Phase 2: execute FIRST — before EXPLAIN, so PG plan cache
            # is cold and we measure the real optimizer benefit.
            t0 = time.monotonic()
            result = orch.execute(sparql, include_sql=True)
            wall_ms = (time.monotonic() - t0) * 1000

            if not result.ok:
                print(f"ERROR ({label}): {result.error}")
                return 1

            # Phase 3: EXPLAIN ANALYZE — runs after for analysis only
            explain_rows = []
            try:
                explain_sql = f"EXPLAIN ANALYZE {sql_result.sql}"
                raw = db.execute_query(explain_sql)
                explain_rows = [list(r.values())[0] for r in raw]
            except Exception as e:
                explain_rows = [f"EXPLAIN failed: {e}"]

            results[label] = {
                "sql": sql_result.sql,
                "explain": explain_rows,
                "result": result,
                "wall_ms": wall_ms,
            }

    if run_rels:
        # ── SQL Analysis ──────────────────────────────────────────────────
        print("=" * 70)
        print("SQL Analysis")
        print("=" * 70)

        for label in ["optimize=OFF", "optimize=ON"]:
            info = results[label]
            sql = info["sql"]
            print(f"\n{'─' * 70}")
            print(f"  {label}  ({len(sql)} chars)")
            print(f"{'─' * 70}")
            if verbose:
                print(_format_sql(sql))
            else:
                formatted = _format_sql(sql)
                if len(formatted) > 500:
                    print(formatted[:500])
                    print(f"    ... ({len(formatted) - 500} more chars, use -v for full SQL)")
                else:
                    print(formatted)
            print()

        # ── Query Plans ───────────────────────────────────────────────────
        print("=" * 70)
        print("Query Plans (EXPLAIN ANALYZE)")
        print("=" * 70)

        for label in ["optimize=OFF", "optimize=ON"]:
            info = results[label]
            print(f"\n{'─' * 70}")
            print(f"  {label}")
            print(f"{'─' * 70}")
            for line in info["explain"]:
                print(f"  {line}")
            print()

        # ── Timing Comparison ─────────────────────────────────────────────
        print("=" * 70)
        print("Timing Comparison")
        print("=" * 70)

        for label in ["optimize=OFF", "optimize=ON"]:
            info = results[label]
            r = info["result"]
            _print_timing(label, r.timing or {}, info["wall_ms"], r.row_count)
            print()

        # Summary table
        off = results["optimize=OFF"]
        on = results["optimize=ON"]
        off_exec = (off["result"].timing or {}).get("execute_ms", 0)
        on_exec = (on["result"].timing or {}).get("execute_ms", 0)
        speedup = off_exec / on_exec if on_exec > 0 else 0

        print(f"{'─' * 70}")
        print(f"  {'Metric':<20} {'optimize=OFF':>14} {'optimize=ON':>14} {'Speedup':>10}")
        print(f"  {'─' * 58}")
        print(f"  {'Rows':<20} {off['result'].row_count:>14} {on['result'].row_count:>14} {'':>10}")
        print(f"  {'Execute ms':<20} {off_exec:>13.0f}ms {on_exec:>13.0f}ms {speedup:>9.1f}x")
        print(f"  {'Wall ms':<20} {off['wall_ms']:>13.0f}ms {on['wall_ms']:>13.0f}ms {off['wall_ms']/on['wall_ms'] if on['wall_ms'] > 0 else 0:>9.1f}x")
        print(f"  {'SQL chars':<20} {len(off['sql']):>14} {len(on['sql']):>14} {'':>10}")
        print(f"{'─' * 70}")
        print()

        # ── Relationships ─────────────────────────────────────────────────
        # Use the optimized result for display
        result = on["result"]

        if not result.rows:
            print("No relationships found.")
        else:
            print(f"Relationships ({result.row_count} found):")
            print()

            by_relation: dict = {}
            for row in _remap_rows(result):
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

    if not run_frames:
        return 0

    # ── 7e: Frame Query (source OR dest has "happy") ─────────────────────
    print()
    print("=" * 70)
    print("Frame Query: entities with 'happy' in description")
    print("  (UNION: source side OR destination side)")
    print("=" * 70)
    print()

    frame_sparql = f"""
        SELECT ?entity ?frame ?srcEntity ?dstEntity WHERE {{
            {{
                ?srcEntity <{HALEY_KG_DESC}> ?srcDesc .
                FILTER(CONTAINS(?srcDesc, "happy"))
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
                FILTER(CONTAINS(?dstDesc, "happy"))
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

    with SparqlOrchestrator(space_id=SPACE_ID) as orch:
        # Get SQL for EXPLAIN
        sql_only_result = orch.execute(frame_sparql, sql_only=True)
        # Execute
        t0 = time.monotonic()
        frame_result = orch.execute(frame_sparql, include_sql=True)
        frame_wall = (time.monotonic() - t0) * 1000

    if not frame_result.ok:
        print(f"  ERROR: {frame_result.error}")
    elif not frame_result.rows:
        print("  No frames found.")
    else:
        exec_ms = (frame_result.timing or {}).get("execute_ms", 0)
        print(f"  {frame_result.row_count} rows | execute={exec_ms:.0f}ms | wall={frame_wall:.0f}ms")

        # EXPLAIN ANALYZE
        if sql_only_result.ok and sql_only_result.sql:
            from vitalgraph_sparql_sql import db as _db
            try:
                explain_rows = _db.execute_query(f"EXPLAIN ANALYZE {sql_only_result.sql}")
                print()
                print(f"  {'─' * 66}")
                print(f"  EXPLAIN ANALYZE")
                print(f"  {'─' * 66}")
                for row in explain_rows:
                    print(f"  {list(row.values())[0]}")
                print()
            except Exception as e:
                print(f"  EXPLAIN failed: {e}")
                print()

        # Collect all unique entity and frame URIs for name resolution
        entity_uris = set()
        frame_uris = set()
        _frame_rows = _remap_rows(frame_result)
        for row in _frame_rows:
            for key in ("entity", "srcentity", "dstentity"):
                uri = row.get(key)
                if uri:
                    entity_uris.add(uri)
            f = row.get("frame")
            if f:
                frame_uris.add(f)

        # Resolve names via direct SQL (much faster than SPARQL VALUES for many URIs)
        print(f"  Resolving names for {len(entity_uris)} entities + {len(frame_uris)} frames...")
        t0 = time.monotonic()
        name_map: dict = {}

        from vitalgraph_sparql_sql import db
        space = SPACE_ID
        quad_tbl = f"{space}_rdf_quad"
        term_tbl = f"{space}_term"

        # Resolve entity names (hasName predicate)
        if entity_uris:
            uri_uuids = db.execute_query(
                f"SELECT term_uuid, term_text FROM {term_tbl} WHERE term_text = ANY(%s)",
                params=(list(entity_uris),),
            )
            uri_to_uuid = {r["term_text"]: r["term_uuid"] for r in uri_uuids}
            subject_uuids = [uri_to_uuid[u] for u in entity_uris if u in uri_to_uuid]
            if subject_uuids:
                # Get hasName predicate UUID
                name_pred_rows = db.execute_query(
                    f"SELECT term_uuid FROM {term_tbl} WHERE term_text = %s LIMIT 1",
                    params=(VITAL_NAME,),
                )
                if name_pred_rows:
                    name_pred_uuid = name_pred_rows[0]["term_uuid"]
                    name_rows = db.execute_query(
                        f"SELECT t_subj.term_text AS uri, t_obj.term_text AS name "
                        f"FROM {quad_tbl} q "
                        f"JOIN {term_tbl} t_subj ON q.subject_uuid = t_subj.term_uuid "
                        f"JOIN {term_tbl} t_obj ON q.object_uuid = t_obj.term_uuid "
                        f"WHERE q.predicate_uuid = %s AND q.subject_uuid = ANY(%s)",
                        params=(name_pred_uuid, subject_uuids),
                    )
                    for r in name_rows:
                        name_map[r["uri"]] = r["name"]

        # Resolve frame type descriptions
        if frame_uris:
            frame_uri_uuids = db.execute_query(
                f"SELECT term_uuid, term_text FROM {term_tbl} WHERE term_text = ANY(%s)",
                params=(list(frame_uris),),
            )
            frame_to_uuid = {r["term_text"]: r["term_uuid"] for r in frame_uri_uuids}
            frame_subj_uuids = [frame_to_uuid[u] for u in frame_uris if u in frame_to_uuid]
            if frame_subj_uuids:
                ftype_pred_rows = db.execute_query(
                    f"SELECT term_uuid FROM {term_tbl} WHERE term_text = %s LIMIT 1",
                    params=(HALEY_FRAME_TYPE_DESC,),
                )
                if ftype_pred_rows:
                    ftype_pred_uuid = ftype_pred_rows[0]["term_uuid"]
                    ftype_rows = db.execute_query(
                        f"SELECT t_subj.term_text AS uri, t_obj.term_text AS ftype "
                        f"FROM {quad_tbl} q "
                        f"JOIN {term_tbl} t_subj ON q.subject_uuid = t_subj.term_uuid "
                        f"JOIN {term_tbl} t_obj ON q.object_uuid = t_obj.term_uuid "
                        f"WHERE q.predicate_uuid = %s AND q.subject_uuid = ANY(%s)",
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
                # Shorten frame type names
                if name.startswith("Edge_Wordnet"):
                    return name[len("Edge_Wordnet"):]
                elif name.startswith("Edge_"):
                    return name[len("Edge_"):]
                return name
            parts = uri.rsplit("/", 1)
            return parts[-1] if len(parts) > 1 else uri

        # Group by entity
        by_entity: dict = {}
        for row in _frame_rows:
            entity = row.get("entity", "?")
            frame = row.get("frame", "?")
            src = row.get("srcentity", "?")
            dst = row.get("dstentity", "?")
            by_entity.setdefault(entity, []).append((frame, src, dst))

        for entity_uri in sorted(by_entity.keys(), key=lambda u: _display(u).lower()):
            frames = by_entity[entity_uri]
            is_src_list = [f for f in frames if f[1] == entity_uri]
            is_dst_list = [f for f in frames if f[2] == entity_uri]

            print(f"  {_display(entity_uri)}")
            if is_src_list:
                print(f"    as SOURCE ({len(is_src_list)}):")
                for frame_uri, _, dst_uri in sorted(is_src_list, key=lambda x: _display(x[2]).lower()):
                    print(f"      {_display(entity_uri)} ──({_display(frame_uri)})──> {_display(dst_uri)}")
            if is_dst_list:
                print(f"    as DEST ({len(is_dst_list)}):")
                for frame_uri, src_uri, _ in sorted(is_dst_list, key=lambda x: _display(x[1]).lower()):
                    print(f"      {_display(src_uri)} ──({_display(frame_uri)})──> {_display(entity_uri)}")
            print()

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Find WordNet words related to 'happy' via SPARQL-to-SQL"
    )
    parser.add_argument("--limit", type=int, default=50,
                        help="Max number of relationships to return (default: 50)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show generated SQL")
    parser.add_argument("-q", "--query", default="all",
                        choices=["all", "relationships", "frames"],
                        help="Which query to run (default: all)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    sys.exit(run(limit=args.limit, verbose=args.verbose, query=args.query))


if __name__ == "__main__":
    main()
