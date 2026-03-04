#!/usr/bin/env python3
"""
load_wordnet_frames.py — Bulk-load KGFrames WordNet N-Triples into PostgreSQL.

Standalone loader for vitalgraph_sparql_sql experiments.
Populates *_term and *_rdf_quad tables (default: wordnet_exp_*).

Steps
-----
1. Connect to PostgreSQL
2. Verify target tables exist (optionally truncate with --force)
3. Save and drop non-PK indexes for fast bulk loading
4. Pass 1: Parse N-Triples with pyoxigraph, collect unique terms & UUIDs
5. COPY terms into term table
6. Pass 2: Parse N-Triples again, COPY quads into quad table
7. Recreate saved indexes
8. ANALYZE both tables
9. Print verification counts

Usage
-----
    python -m vitalgraph_sparql_sql.data.load_wordnet_frames
    python vitalgraph_sparql_sql/data/load_wordnet_frames.py [options]
    python vitalgraph_sparql_sql/data/load_wordnet_frames.py --help
"""

import argparse
import logging
import os
import sys
import time
import uuid as uuid_mod
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg
from pyoxigraph import parse as ox_parse

# ---------------------------------------------------------------------------
# Deterministic UUID generation — reproduces the vitalgraph convention
# (see vitalgraph.db.postgresql.space.postgresql_space_terms)
# ---------------------------------------------------------------------------
_VITALGRAPH_NS = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def generate_term_uuid(
    term_text: str,
    term_type: str,
    lang: Optional[str] = None,
    datatype_id: Optional[int] = None,
) -> str:
    """Return a deterministic UUID-5 string for an RDF term."""
    components: list[str] = [term_text, term_type]
    if lang is not None:
        components.append(f"lang:{lang}")
    if datatype_id is not None:
        components.append(f"datatype:{datatype_id}")
    return str(uuid_mod.uuid5(_VITALGRAPH_NS, "\x00".join(components)))


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
def _project_root() -> Path:
    """Return the project root (two levels up from this file)."""
    return Path(__file__).resolve().parents[2]


DEFAULT_DSN = "host=localhost port=5432 dbname=fuseki_sql_graph user=postgres"
DEFAULT_GRAPH_URI = "http://vital.ai/graph/kgwordnetframes"
DEFAULT_DATASET = "primary"
DEFAULT_DATA_FILE = str(_project_root() / "test_data" / "kgframe-wordnet-0.0.1.nt")

logger = logging.getLogger("load_wordnet_frames")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Bulk-load WordNet KGFrames N-Triples into PostgreSQL tables"
    )
    p.add_argument("--dsn", default=DEFAULT_DSN, help="psycopg connection string")
    p.add_argument("--data-file", default=DEFAULT_DATA_FILE, help="Path to .nt file")
    p.add_argument("--graph-uri", default=DEFAULT_GRAPH_URI)
    p.add_argument("--term-table", default="wordnet_exp_term")
    p.add_argument("--quad-table", default="wordnet_exp_rdf_quad")
    p.add_argument("--dataset", default=DEFAULT_DATASET)
    p.add_argument("--force", action="store_true", help="Truncate tables before loading")
    p.add_argument("--skip-indexes", action="store_true", help="Skip index drop/recreate")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------
def save_indexes(conn, table_name: str) -> List[Tuple[str, str]]:
    """Return [(index_name, create_sql)] for all non-PK indexes on *table_name*."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = %s
              AND schemaname = 'public'
              AND indexname NOT LIKE '%%_pkey'
            ORDER BY indexname
            """,
            (table_name,),
        )
        return list(cur.fetchall())


def drop_indexes(conn, indexes: List[Tuple[str, str]]):
    with conn.cursor() as cur:
        for name, _ in indexes:
            cur.execute(f"DROP INDEX IF EXISTS {name}")
            logger.debug(f"  dropped {name}")
    conn.commit()


def recreate_indexes(conn, indexes: List[Tuple[str, str]]):
    with conn.cursor() as cur:
        for name, create_sql in indexes:
            logger.info(f"  creating {name} ...")
            cur.execute(create_sql)
    conn.commit()


# ---------------------------------------------------------------------------
# Pass 1 — collect unique terms
# ---------------------------------------------------------------------------
def collect_terms(data_file: str, graph_uri: str) -> Dict[Tuple, str]:
    """Parse N-Triples and return {(text, type, lang): uuid_str}."""
    terms: Dict[Tuple, str] = {}
    count = 0

    def ensure(text: str, ttype: str, lang: Optional[str] = None) -> str:
        key = (text, ttype, lang)
        uid = terms.get(key)
        if uid is None:
            uid = generate_term_uuid(text, ttype, lang=lang)
            terms[key] = uid
        return uid

    # Pre-register the graph URI
    ensure(graph_uri, "U")

    with open(data_file, "rb") as f:
        for triple in ox_parse(f, "application/n-triples"):
            # --- subject ---
            s_cls = type(triple.subject).__name__
            if s_cls == "BlankNode":
                ensure(triple.subject.value, "B")
            else:
                ensure(triple.subject.value, "U")

            # --- predicate (always URI) ---
            ensure(triple.predicate.value, "U")

            # --- object ---
            obj = triple.object
            obj_cls = type(obj).__name__
            if obj_cls == "Literal":
                lang = str(obj.language) if obj.language else None
                ensure(obj.value, "L", lang)
            elif obj_cls == "BlankNode":
                ensure(obj.value, "B")
            else:
                ensure(obj.value, "U")

            count += 1
            if count % 1_000_000 == 0:
                logger.info(f"  pass 1: {count:,} triples, {len(terms):,} unique terms")

    logger.info(f"  pass 1 done: {count:,} triples, {len(terms):,} unique terms")
    return terms


# ---------------------------------------------------------------------------
# COPY terms
# ---------------------------------------------------------------------------
def copy_terms(conn, terms: Dict[Tuple, str], table: str, dataset: str):
    """Bulk-load terms via COPY FROM STDIN."""
    logger.info(f"COPYing {len(terms):,} terms into {table} ...")
    t0 = time.time()

    with conn.cursor() as cur:
        with cur.copy(
            f"COPY {table} (term_uuid, term_text, term_type, lang, dataset) FROM STDIN"
        ) as copy:
            for (text, ttype, lang), uid in terms.items():
                copy.write_row((uid, text, ttype, lang, dataset))
    conn.commit()

    dt = time.time() - t0
    rate = len(terms) / dt if dt > 0 else 0
    logger.info(f"  {len(terms):,} terms loaded in {dt:.1f}s ({rate:,.0f}/s)")


# ---------------------------------------------------------------------------
# Pass 2 — COPY quads
# ---------------------------------------------------------------------------
def copy_quads(
    conn,
    data_file: str,
    graph_uri: str,
    terms: Dict[Tuple, str],
    table: str,
    dataset: str,
) -> int:
    """Parse N-Triples a second time, COPY quads directly into the quad table."""
    graph_uuid = terms[(graph_uri, "U", None)]
    count = 0
    t0 = time.time()

    logger.info(f"COPYing quads into {table} ...")

    with conn.cursor() as cur:
        with cur.copy(
            f"COPY {table} (subject_uuid, predicate_uuid, object_uuid, context_uuid, dataset)"
            f" FROM STDIN"
        ) as copy:
            with open(data_file, "rb") as f:
                for triple in ox_parse(f, "application/n-triples"):
                    # subject
                    s_cls = type(triple.subject).__name__
                    if s_cls == "BlankNode":
                        s_uuid = terms[(triple.subject.value, "B", None)]
                    else:
                        s_uuid = terms[(triple.subject.value, "U", None)]

                    # predicate
                    p_uuid = terms[(triple.predicate.value, "U", None)]

                    # object
                    obj = triple.object
                    obj_cls = type(obj).__name__
                    if obj_cls == "Literal":
                        lang = str(obj.language) if obj.language else None
                        o_uuid = terms[(obj.value, "L", lang)]
                    elif obj_cls == "BlankNode":
                        o_uuid = terms[(obj.value, "B", None)]
                    else:
                        o_uuid = terms[(obj.value, "U", None)]

                    copy.write_row((s_uuid, p_uuid, o_uuid, graph_uuid, dataset))

                    count += 1
                    if count % 1_000_000 == 0:
                        elapsed = time.time() - t0
                        rate = count / elapsed if elapsed > 0 else 0
                        logger.info(f"  pass 2: {count:,} quads ({rate:,.0f}/s)")

    conn.commit()

    dt = time.time() - t0
    rate = count / dt if dt > 0 else 0
    logger.info(f"  {count:,} quads loaded in {dt:.1f}s ({rate:,.0f}/s)")
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    data_file = args.data_file
    if not os.path.exists(data_file):
        logger.error(f"Data file not found: {data_file}")
        sys.exit(1)

    file_size_mb = os.path.getsize(data_file) / (1024 * 1024)
    logger.info(f"Data file : {data_file} ({file_size_mb:.0f} MB)")
    logger.info(f"Graph URI : {args.graph_uri}")
    logger.info(f"Tables    : {args.term_table}, {args.quad_table}")
    logger.info(f"Dataset   : {args.dataset}")

    # ---- connect ----
    logger.info("Connecting to PostgreSQL ...")
    conn = psycopg.connect(args.dsn, autocommit=False)
    logger.info("Connected")

    try:
        # ---- pre-checks ----
        with conn.cursor() as cur:
            for tbl in (args.term_table, args.quad_table):
                cur.execute(
                    "SELECT EXISTS (SELECT FROM information_schema.tables "
                    "WHERE table_name = %s AND table_schema = 'public')",
                    (tbl,),
                )
                if not cur.fetchone()[0]:
                    logger.error(f"Table {tbl} does not exist — create it first")
                    sys.exit(1)

            cur.execute(f"SELECT COUNT(*) FROM {args.term_table}")
            existing_terms = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM {args.quad_table}")
            existing_quads = cur.fetchone()[0]

            if existing_terms > 0 or existing_quads > 0:
                if args.force:
                    logger.warning(
                        f"Truncating tables ({existing_terms:,} terms, {existing_quads:,} quads)"
                    )
                    cur.execute(f"TRUNCATE {args.quad_table}")
                    cur.execute(f"TRUNCATE {args.term_table}")
                    conn.commit()
                else:
                    logger.error(
                        f"Tables not empty ({existing_terms:,} terms, "
                        f"{existing_quads:,} quads). Use --force to truncate."
                    )
                    sys.exit(1)

        # ---- save & drop indexes ----
        all_saved: List[Tuple[str, List[Tuple[str, str]]]] = []
        if not args.skip_indexes:
            logger.info("Saving and dropping indexes for bulk load ...")
            for tbl in (args.term_table, args.quad_table):
                saved = save_indexes(conn, tbl)
                all_saved.append((tbl, saved))
                if saved:
                    logger.info(f"  {tbl}: dropping {len(saved)} indexes")
                    drop_indexes(conn, saved)

        overall_t0 = time.time()

        # ---- pass 1: unique terms ----
        logger.info("Pass 1: Collecting unique terms ...")
        t0 = time.time()
        terms = collect_terms(data_file, args.graph_uri)
        logger.info(f"Pass 1 complete: {len(terms):,} unique terms in {time.time() - t0:.1f}s")

        # ---- COPY terms ----
        copy_terms(conn, terms, args.term_table, args.dataset)

        # ---- pass 2: COPY quads ----
        quad_count = copy_quads(
            conn, data_file, args.graph_uri, terms, args.quad_table, args.dataset
        )

        overall_dt = time.time() - overall_t0
        logger.info(
            f"Data loading complete: {len(terms):,} terms, "
            f"{quad_count:,} quads in {overall_dt:.1f}s"
        )

        # ---- recreate indexes ----
        if not args.skip_indexes and all_saved:
            logger.info("Recreating indexes ...")
            idx_t0 = time.time()
            for tbl, saved in all_saved:
                if saved:
                    logger.info(f"  {tbl}: recreating {len(saved)} indexes")
                    recreate_indexes(conn, saved)
            logger.info(f"Indexes recreated in {time.time() - idx_t0:.1f}s")

        # ---- ANALYZE ----
        logger.info("Running ANALYZE ...")
        conn.autocommit = True
        with conn.cursor() as cur:
            for tbl in (args.term_table, args.quad_table):
                cur.execute(f"ANALYZE {tbl}")
        logger.info("ANALYZE complete")

        # ---- verify ----
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {args.term_table}")
            final_terms = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM {args.quad_table}")
            final_quads = cur.fetchone()[0]

        logger.info(f"Verification: {final_terms:,} terms, {final_quads:,} quads")
        logger.info("Done ✅")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
