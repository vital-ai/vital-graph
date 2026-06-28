#!/usr/bin/env python3
"""
compare_sparql_vs_handwritten.py — Compare SPARQL-generated SQL with hand-written
SQL for frame/edge/slot traversal queries.

For each query level (frame, edge, slot, full traversal), this script:
  1. Sends the SPARQL to the sidecar → gets generated SQL
  2. Shows the equivalent hand-written SQL
  3. Executes both and compares timing + results

Requires:
  - Jena sidecar running at localhost:7070
  - PostgreSQL with WordNet data in wordnet_exp_* tables

Usage:
    python vitalgraph_sparql_sql/scripts/compare_sparql_vs_handwritten.py
"""

import argparse
import logging
import os
import sys
import textwrap
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator
from vitalgraph_sparql_sql import db

logger = logging.getLogger("compare_sql")

# ---------------------------------------------------------------------------
# Ontology constants
# ---------------------------------------------------------------------------
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_FRAME_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameType"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_ENTITY_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
HALEY_KG_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"

SPACE_ID = "wordnet_exp"
TERM_TABLE = f"{SPACE_ID}_term"
QUAD_TABLE = f"{SPACE_ID}_rdf_quad"


# ---------------------------------------------------------------------------
# Helper: load UUID constants from DB (same as happy frame scripts)
# ---------------------------------------------------------------------------
def load_constants() -> dict:
    """Load predicate/type UUIDs from the term table."""
    uris = {
        "rdf_type":          RDF_TYPE,
        "vital_name":        VITAL_NAME,
        "vital_edge_src":    VITAL_EDGE_SRC,
        "vital_edge_dst":    VITAL_EDGE_DST,
        "kg_entity":         HALEY_KG_ENTITY,
        "kg_frame":          HALEY_KG_FRAME,
        "frame_type":        HALEY_FRAME_TYPE,
        "frame_type_desc":   HALEY_FRAME_TYPE_DESC,
        "entity_type_desc":  HALEY_ENTITY_TYPE_DESC,
        "slot_type":         HALEY_SLOT_TYPE,
        "slot_value":        HALEY_SLOT_VALUE,
        "kg_desc":           HALEY_KG_DESC,
        "src_entity_type":   "urn:hasSourceEntity",
        "dst_entity_type":   "urn:hasDestinationEntity",
    }
    placeholders = ", ".join(["%s"] * len(uris))
    sql = f"""
        SELECT term_text, term_uuid
        FROM {TERM_TABLE}
        WHERE term_text IN ({placeholders})
    """
    rows = db.execute_query(sql, tuple(uris.values()))
    text_to_uuid = {r["term_text"]: str(r["term_uuid"]) for r in rows}
    constants = {}
    for key, uri in uris.items():
        uuid = text_to_uuid.get(uri)
        if uuid:
            constants[key] = uuid
        else:
            print(f"  WARNING: constant '{key}' ({uri}) not found in term table")
    return constants


# ---------------------------------------------------------------------------
# Query definitions: SPARQL + hand-written SQL for each level
# ---------------------------------------------------------------------------

def build_queries(constants: dict, frame_uri: str) -> list:
    """
    Build a list of comparison queries at increasing complexity.
    Each entry: { label, sparql, handwritten_sql, description }
    """
    c = constants
    queries = []

    # ── Q1: Frame lookup ──────────────────────────────────────────────────
    queries.append({
        "label": "Q1. Frame lookup (given URI)",
        "description": "Given a known frame URI, get its type description",
        "sparql": f"""
            SELECT ?frameType ?frameTypeDesc WHERE {{
                <{frame_uri}> <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                <{frame_uri}> <{HALEY_FRAME_TYPE}> ?frameType .
                <{frame_uri}> <{HALEY_FRAME_TYPE_DESC}> ?frameTypeDesc
            }}
        """,
        "handwritten_sql": f"""
-- Q1 hand-written: frame lookup by known URI
SELECT t_ft.term_text  AS frameType,
       t_ftd.term_text AS frameTypeDesc
FROM {TERM_TABLE} t_frame
JOIN {QUAD_TABLE} q1
  ON q1.subject_uuid = t_frame.term_uuid
 AND q1.predicate_uuid = '{c["rdf_type"]}'::uuid
 AND q1.object_uuid  = '{c["kg_frame"]}'::uuid
JOIN {QUAD_TABLE} q2
  ON q2.subject_uuid = t_frame.term_uuid
 AND q2.predicate_uuid = '{c["frame_type"]}'::uuid
JOIN {QUAD_TABLE} q3
  ON q3.subject_uuid = t_frame.term_uuid
 AND q3.predicate_uuid = '{c["frame_type_desc"]}'::uuid
JOIN {TERM_TABLE} t_ft  ON t_ft.term_uuid  = q2.object_uuid
JOIN {TERM_TABLE} t_ftd ON t_ftd.term_uuid = q3.object_uuid
WHERE t_frame.term_text = '{frame_uri}'
""",
    })

    # ── Q2: Edge lookup ───────────────────────────────────────────────────
    queries.append({
        "label": "Q2. Edges connected to frame",
        "description": "Find Edge_hasKGSlot edges whose source is the known frame",
        "sparql": f"""
            SELECT ?edge ?slot WHERE {{
                ?edge <{VITAL_EDGE_SRC}> <{frame_uri}> .
                ?edge <{VITAL_EDGE_DST}> ?slot
            }} LIMIT 20
        """,
        "handwritten_sql": f"""
-- Q2 hand-written: edges from a known frame
SELECT t_edge.term_text AS edge,
       t_slot.term_text AS slot
FROM {TERM_TABLE} t_frame
JOIN {QUAD_TABLE} q_src
  ON q_src.object_uuid = t_frame.term_uuid
 AND q_src.predicate_uuid = '{c["vital_edge_src"]}'::uuid
JOIN {QUAD_TABLE} q_dst
  ON q_dst.subject_uuid = q_src.subject_uuid
 AND q_dst.predicate_uuid = '{c["vital_edge_dst"]}'::uuid
JOIN {TERM_TABLE} t_edge ON t_edge.term_uuid = q_src.subject_uuid
JOIN {TERM_TABLE} t_slot ON t_slot.term_uuid = q_dst.object_uuid
WHERE t_frame.term_text = '{frame_uri}'
LIMIT 20
""",
    })

    # ── Q3: Slot → Entity (source side) ──────────────────────────────────
    queries.append({
        "label": "Q3. Frame → Slot → Entity (source side)",
        "description": "From frame, traverse edge to source slot, get entity",
        "sparql": f"""
            SELECT ?slot ?slotEntity WHERE {{
                ?edge <{VITAL_EDGE_SRC}> <{frame_uri}> .
                ?edge <{VITAL_EDGE_DST}> ?slot .
                ?slot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?slot <{HALEY_SLOT_VALUE}> ?slotEntity
            }}
        """,
        "handwritten_sql": f"""
-- Q3 hand-written: frame → edge → source slot → entity
SELECT t_slot.term_text   AS slot,
       t_entity.term_text AS slotEntity
FROM {TERM_TABLE} t_frame
JOIN {QUAD_TABLE} q_src
  ON q_src.object_uuid = t_frame.term_uuid
 AND q_src.predicate_uuid = '{c["vital_edge_src"]}'::uuid
JOIN {QUAD_TABLE} q_dst
  ON q_dst.subject_uuid = q_src.subject_uuid
 AND q_dst.predicate_uuid = '{c["vital_edge_dst"]}'::uuid
JOIN {QUAD_TABLE} q_st
  ON q_st.subject_uuid = q_dst.object_uuid
 AND q_st.predicate_uuid = '{c["slot_type"]}'::uuid
 AND q_st.object_uuid  = '{c["src_entity_type"]}'::uuid
JOIN {QUAD_TABLE} q_sv
  ON q_sv.subject_uuid = q_dst.object_uuid
 AND q_sv.predicate_uuid = '{c["slot_value"]}'::uuid
JOIN {TERM_TABLE} t_slot   ON t_slot.term_uuid   = q_dst.object_uuid
JOIN {TERM_TABLE} t_entity ON t_entity.term_uuid  = q_sv.object_uuid
WHERE t_frame.term_text = '{frame_uri}'
""",
    })

    # ── Q4: Full traversal: srcEntity ← slot ← edge → frame ← edge → slot → dstEntity
    queries.append({
        "label": "Q4. Full traversal: src → frame → dst (known frame)",
        "description": "Complete frame traversal: source entity, frame, destination entity",
        "sparql": f"""
            SELECT ?srcEntity ?dstEntity WHERE {{
                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> <{frame_uri}> .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> <{frame_uri}> .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot
            }}
        """,
        "handwritten_sql": f"""
-- Q4 hand-written: full traversal from a known frame
SELECT t_src.term_text AS srcEntity,
       t_dst.term_text AS dstEntity
FROM {TERM_TABLE} t_frame
-- source side
JOIN {QUAD_TABLE} q_se
  ON q_se.object_uuid = t_frame.term_uuid
 AND q_se.predicate_uuid = '{c["vital_edge_src"]}'::uuid
JOIN {QUAD_TABLE} q_sd
  ON q_sd.subject_uuid = q_se.subject_uuid
 AND q_sd.predicate_uuid = '{c["vital_edge_dst"]}'::uuid
JOIN {QUAD_TABLE} q_sst
  ON q_sst.subject_uuid = q_sd.object_uuid
 AND q_sst.predicate_uuid = '{c["slot_type"]}'::uuid
 AND q_sst.object_uuid  = '{c["src_entity_type"]}'::uuid
JOIN {QUAD_TABLE} q_ssv
  ON q_ssv.subject_uuid = q_sd.object_uuid
 AND q_ssv.predicate_uuid = '{c["slot_value"]}'::uuid
-- destination side
JOIN {QUAD_TABLE} q_de
  ON q_de.object_uuid = t_frame.term_uuid
 AND q_de.predicate_uuid = '{c["vital_edge_src"]}'::uuid
JOIN {QUAD_TABLE} q_dd
  ON q_dd.subject_uuid = q_de.subject_uuid
 AND q_dd.predicate_uuid = '{c["vital_edge_dst"]}'::uuid
JOIN {QUAD_TABLE} q_dst
  ON q_dst.subject_uuid = q_dd.object_uuid
 AND q_dst.predicate_uuid = '{c["slot_type"]}'::uuid
 AND q_dst.object_uuid  = '{c["dst_entity_type"]}'::uuid
JOIN {QUAD_TABLE} q_dsv
  ON q_dsv.subject_uuid = q_dd.object_uuid
 AND q_dsv.predicate_uuid = '{c["slot_value"]}'::uuid
-- resolve URIs
JOIN {TERM_TABLE} t_src ON t_src.term_uuid = q_ssv.object_uuid
JOIN {TERM_TABLE} t_dst ON t_dst.term_uuid = q_dsv.object_uuid
WHERE t_frame.term_text = '{frame_uri}'
""",
    })

    # ── Q5: Open-ended traversal (first 10 frames) — matches query 3c in query_wordnet
    queries.append({
        "label": "Q5. Open traversal: src → frame → dst (LIMIT 10)",
        "description": "No fixed frame — full traversal like query_wordnet 3c",
        "sparql": f"""
            SELECT ?srcEntity ?frameTypeDesc ?dstEntity WHERE {{
                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?frameTypeDesc .

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot
            }} LIMIT 10
        """,
        "handwritten_sql": f"""
-- Q5 hand-written: open full traversal (first 10)
SELECT t_src.term_text  AS srcEntity,
       t_ftd.term_text  AS frameTypeDesc,
       t_dst.term_text  AS dstEntity
FROM {QUAD_TABLE} q_ft
-- frame must be a KGFrame with a type description
JOIN {QUAD_TABLE} q_type
  ON q_type.subject_uuid = q_ft.subject_uuid
 AND q_type.predicate_uuid = '{c["rdf_type"]}'::uuid
 AND q_type.object_uuid  = '{c["kg_frame"]}'::uuid
-- source edge → slot → entity
JOIN {QUAD_TABLE} q_se
  ON q_se.object_uuid = q_ft.subject_uuid
 AND q_se.predicate_uuid = '{c["vital_edge_src"]}'::uuid
JOIN {QUAD_TABLE} q_sd
  ON q_sd.subject_uuid = q_se.subject_uuid
 AND q_sd.predicate_uuid = '{c["vital_edge_dst"]}'::uuid
JOIN {QUAD_TABLE} q_sst
  ON q_sst.subject_uuid = q_sd.object_uuid
 AND q_sst.predicate_uuid = '{c["slot_type"]}'::uuid
 AND q_sst.object_uuid  = '{c["src_entity_type"]}'::uuid
JOIN {QUAD_TABLE} q_ssv
  ON q_ssv.subject_uuid = q_sd.object_uuid
 AND q_ssv.predicate_uuid = '{c["slot_value"]}'::uuid
-- destination edge → slot → entity
JOIN {QUAD_TABLE} q_de
  ON q_de.object_uuid = q_ft.subject_uuid
 AND q_de.predicate_uuid = '{c["vital_edge_src"]}'::uuid
JOIN {QUAD_TABLE} q_dd
  ON q_dd.subject_uuid = q_de.subject_uuid
 AND q_dd.predicate_uuid = '{c["vital_edge_dst"]}'::uuid
JOIN {QUAD_TABLE} q_dst2
  ON q_dst2.subject_uuid = q_dd.object_uuid
 AND q_dst2.predicate_uuid = '{c["slot_type"]}'::uuid
 AND q_dst2.object_uuid  = '{c["dst_entity_type"]}'::uuid
JOIN {QUAD_TABLE} q_dsv
  ON q_dsv.subject_uuid = q_dd.object_uuid
 AND q_dsv.predicate_uuid = '{c["slot_value"]}'::uuid
-- resolve text
JOIN {TERM_TABLE} t_ftd ON t_ftd.term_uuid = q_ft.object_uuid
JOIN {TERM_TABLE} t_src ON t_src.term_uuid = q_ssv.object_uuid
JOIN {TERM_TABLE} t_dst ON t_dst.term_uuid = q_dsv.object_uuid
WHERE q_ft.predicate_uuid = '{c["frame_type_desc"]}'::uuid
LIMIT 10
""",
    })

    return queries


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def fmt_sql(sql: str) -> str:
    """Collapse blank lines, strip trailing whitespace."""
    lines = [l.rstrip() for l in sql.strip().split('\n') if l.strip()]
    return '\n'.join(lines)


def count_joins(sql: str) -> int:
    """Count JOIN occurrences in SQL."""
    return sql.upper().count(' JOIN ')


def count_tables(sql: str) -> int:
    """Count quad/term table references."""
    return sql.count(QUAD_TABLE) + sql.count(TERM_TABLE)


def run_comparison(space_id: str):
    print("=" * 100)
    print("SPARQL-Generated SQL  vs  Hand-Written SQL Comparison")
    print(f"Space: {space_id}")
    print("=" * 100)

    # Phase 0: load constants
    t0 = time.time()
    constants = load_constants()
    const_ms = (time.time() - t0) * 1000
    print(f"\nLoaded {len(constants)} constants in {const_ms:.1f}ms")

    # Phase 0b: find a real frame URI to use
    print("\nFinding a real frame URI...")
    frame_rows = db.execute_query(f"""
        SELECT t.term_text
        FROM {TERM_TABLE} t
        JOIN {QUAD_TABLE} q ON q.subject_uuid = t.term_uuid
                            AND q.predicate_uuid = '{constants["rdf_type"]}'::uuid
                            AND q.object_uuid  = '{constants["kg_frame"]}'::uuid
        LIMIT 1
    """)
    if not frame_rows:
        print("ERROR: no KGFrame found in database")
        return 1
    frame_uri = frame_rows[0]["term_text"]
    print(f"  Using frame: {frame_uri}")

    queries = build_queries(constants, frame_uri)

    summary = []  # (label, sparql_ms, hw_ms, sparql_rows, hw_rows, sparql_joins, hw_joins)

    with SparqlOrchestrator(space_id=space_id) as orch:
        for q in queries:
            label = q["label"]
            sparql = q["sparql"]
            hw_sql = q["handwritten_sql"]
            desc = q.get("description", "")

            print(f"\n{'━' * 100}")
            print(f"  {label}")
            if desc:
                print(f"  {desc}")
            print(f"{'━' * 100}")

            # ── SPARQL → SQL ──
            sparql_clean = textwrap.dedent(sparql).strip()
            print(f"\n  SPARQL:")
            for line in sparql_clean.split('\n'):
                print(f"    {line}")

            t0 = time.monotonic()
            result = orch.execute(sparql, include_sql=True)
            sparql_wall_ms = (time.monotonic() - t0) * 1000

            if not result.ok:
                print(f"\n  ❌ SPARQL FAILED: {result.error}")
                if result.sql:
                    print(f"\n  Generated SQL:")
                    for line in fmt_sql(result.sql).split('\n'):
                        print(f"    {line}")
                summary.append((label, sparql_wall_ms, 0, 0, 0, 0, 0, "FAIL"))
                continue

            gen_sql = result.sql or "(no SQL returned)"
            sparql_exec_ms = result.timing.get("execute_ms", 0) if result.timing else 0
            sparql_rows = result.row_count

            print(f"\n  Generated SQL ({len(gen_sql)} chars, {count_joins(gen_sql)} JOINs, "
                  f"{count_tables(gen_sql)} table refs):")
            for line in fmt_sql(gen_sql).split('\n'):
                print(f"    {line}")

            print(f"\n  SPARQL result: {sparql_rows} rows, "
                  f"execute={sparql_exec_ms:.1f}ms, wall={sparql_wall_ms:.1f}ms")
            if result.rows:
                for i, row in enumerate(result.rows[:3]):
                    vals = {k: str(v)[-60:] for k, v in row.items()}
                    print(f"    [{i}] {vals}")
                if sparql_rows > 3:
                    print(f"    ... ({sparql_rows - 3} more)")

            # ── Hand-written SQL ──
            print(f"\n  Hand-written SQL ({len(hw_sql)} chars, {count_joins(hw_sql)} JOINs, "
                  f"{count_tables(hw_sql)} table refs):")
            for line in fmt_sql(hw_sql).split('\n'):
                print(f"    {line}")

            t0 = time.monotonic()
            try:
                hw_rows_data = db.execute_query(hw_sql.strip())
                hw_ms = (time.monotonic() - t0) * 1000
                hw_row_count = len(hw_rows_data)
            except Exception as e:
                hw_ms = (time.monotonic() - t0) * 1000
                print(f"\n  ❌ Hand-written SQL FAILED: {e}")
                hw_row_count = -1
                hw_rows_data = []

            print(f"\n  Hand-written result: {hw_row_count} rows, execute={hw_ms:.1f}ms")
            if hw_rows_data:
                for i, row in enumerate(hw_rows_data[:3]):
                    vals = {k: str(v)[-60:] for k, v in row.items()}
                    print(f"    [{i}] {vals}")
                if hw_row_count > 3:
                    print(f"    ... ({hw_row_count - 3} more)")

            # ── Comparison ──
            speedup = hw_ms / sparql_exec_ms if sparql_exec_ms > 0 else 0
            print(f"\n  ┌─ Comparison ─────────────────────────────────────────┐")
            print(f"  │  {'Metric':<25} {'SPARQL-gen':>15} {'Hand-written':>15} │")
            print(f"  │  {'-'*25} {'-'*15} {'-'*15} │")
            print(f"  │  {'Rows':<25} {sparql_rows:>15} {hw_row_count:>15} │")
            print(f"  │  {'Execute ms':<25} {sparql_exec_ms:>14.1f}ms {hw_ms:>14.1f}ms │")
            print(f"  │  {'JOINs':<25} {count_joins(gen_sql):>15} {count_joins(hw_sql):>15} │")
            print(f"  │  {'Table refs':<25} {count_tables(gen_sql):>15} {count_tables(hw_sql):>15} │")
            print(f"  │  {'SQL length':<25} {len(gen_sql):>15} {len(hw_sql):>15} │")
            if speedup > 0:
                winner = "HW faster" if hw_ms < sparql_exec_ms else "SPARQL faster"
                ratio = max(sparql_exec_ms, hw_ms) / max(min(sparql_exec_ms, hw_ms), 0.01)
                print(f"  │  {'Winner':<25} {winner + f' ({ratio:.1f}x)':>31} │")
            print(f"  └────────────────────────────────────────────────────────┘")

            summary.append((
                label, sparql_exec_ms, hw_ms,
                sparql_rows, hw_row_count,
                count_joins(gen_sql), count_joins(hw_sql),
                "OK",
            ))

    # ── Summary table ──
    print(f"\n{'=' * 100}")
    print("Summary")
    print(f"{'=' * 100}")
    print(f"  {'Query':<50} {'SPARQL':>8} {'HW':>8} {'S-rows':>7} {'H-rows':>7} {'S-JOIN':>7} {'H-JOIN':>7} {'Status':>7}")
    print(f"  {'-'*50} {'-'*8} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
    for label, s_ms, h_ms, s_rows, h_rows, s_joins, h_joins, status in summary:
        short = label[:50]
        print(f"  {short:<50} {s_ms:7.1f}ms {h_ms:7.1f}ms {s_rows:>7} {h_rows:>7} {s_joins:>7} {h_joins:>7} {status:>7}")
    print(f"{'=' * 100}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Compare SPARQL-generated SQL vs hand-written SQL"
    )
    parser.add_argument("--space", default="wordnet_exp")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)-30s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    sys.exit(run_comparison(args.space))


if __name__ == "__main__":
    main()
