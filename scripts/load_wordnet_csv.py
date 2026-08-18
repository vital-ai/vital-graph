#!/usr/bin/env python
"""Load pre-converted wordnet CSVs into a space via PostgreSQL COPY.

The second half of the convert-then-load pipeline:

    1. scripts/convert_vital_to_ntriples.py   .vital -> .nt   (~31s, one-time)
    2. test_scripts/import/test_csv_import_process.py  .nt -> CSV  (one-time)
    3. THIS SCRIPT                            CSV -> space   (seconds)

Parsing RDF is what makes the other loaders take minutes; once the CSVs exist
this step is pure COPY. The archived design doc benchmarked this exact dataset
(8.58M triples) at 28.4s for the binary COPY phase and 9.0s for terms.

Quads need a staging hop: the quads CSV carries 14 columns (text forms, flags,
batch ids) but the quad table wants only the four uuid columns, and COPY's
column list has to match the file's column order. So the CSV goes into an
UNLOGGED staging table shaped like the file, then a single INSERT..SELECT
projects the four columns across. That is the shape
planning/planning_cleanup/import_staging_table_plan.md describes.

    VG_TEST_PG_PORT=5433 VG_TEST_PG_PASSWORD=testpass \\
        python scripts/load_wordnet_csv.py \\
            --space wordnet_frames \\
            --quads-csv test_data/wordnet_frames.csv \\
            --terms-csv test_data/wordnet_frames_terms.csv
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import pg_kwargs  # noqa: E402

BLOCK = 1024 * 1024  # 1MB chunks — the block size the convert script uses

QUAD_CSV_COLUMNS = [
    "subject_text", "predicate_text", "object_text", "object_datatype",
    "object_language", "is_literal", "graph_uri", "import_batch_id",
    "subject_uuid", "predicate_uuid", "object_uuid", "context_uuid",
    "processing_status", "dataset",
]


def pg_env() -> dict:
    """The ONE set of connection parameters this script uses.

    It reads the same VG_TEST_PG_* variables as tests/performance/conftest.py
    and scripts/perf_seed_data.py, so a fixture lands in the cluster the tests
    that use it will look in.

    There used to be two of these — the COPY path defaulted to port 5433 with
    password 'testpass', and the auxiliary resync below to port 5432 with an
    empty password. With no overrides that wrote the quad and term tables to the
    container cluster and then resynced auxiliary tables on the HOST cluster,
    against whatever space happened to share the name there. The resync is the
    step that exists to stop a stale edge table answering frame queries with
    zero rows (issues/041); pointing it at another database is the same failure
    with a longer fuse. One source, so the two cannot drift apart again.
    """
    return dict(
        **pg_kwargs(),
    )


def dsn() -> str:
    p = pg_env()
    return (f"host={p['host']} port={p['port']} dbname={p['database']} "
            f"user={p['user']} password={p['password']}")


async def copy_file(cur, sql: str, path: str) -> float:
    t0 = time.time()
    async with cur.copy(sql) as cp:
        with open(path, "rb") as fh:
            while chunk := fh.read(BLOCK):
                await cp.write(chunk)
    return time.time() - t0


async def run(space: str, quads_csv: str, terms_csv: str,
              truncate: bool, keep_indexes: bool,
              skip_resync: bool = False) -> int:
    term_tbl = f"{space}_term"
    quad_tbl = f"{space}_rdf_quad"
    stage_tbl = f"stage_{space}_quads"

    for p in (quads_csv, terms_csv):
        if not os.path.isfile(p):
            print(f"❌ missing CSV: {p}", file=sys.stderr)
            return 2

    conn = await psycopg.AsyncConnection.connect(dsn(), autocommit=True)
    total0 = time.time()
    async with conn:
        async with conn.cursor() as cur:
            # Saved index definitions, dropped for the load and rebuilt after.
            saved: list[tuple[str, str]] = []
            if not keep_indexes:
                await cur.execute(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname='public' AND tablename = ANY(%s) "
                    "AND indexname NOT LIKE '%%_pkey' ORDER BY indexname",
                    ([term_tbl, quad_tbl],))
                saved = list(await cur.fetchall())
                for name, _ in saved:
                    await cur.execute(f"DROP INDEX IF EXISTS {name}")
                print(f"🔧 dropped {len(saved)} secondary indexes")

            if truncate:
                await cur.execute(f"TRUNCATE {quad_tbl}, {term_tbl}")
                print("🗑️  truncated term + quad tables")

            # ---- terms: CSV columns match the term table exactly ----
            dt = await copy_file(
                cur,
                f"COPY {term_tbl} (term_uuid, term_text, term_type, lang, "
                f"datatype_id, created_time, dataset) FROM STDIN "
                f"WITH (FORMAT CSV, HEADER true, NULL '')",
                terms_csv)
            await cur.execute(f"SELECT count(*) FROM {term_tbl}")
            n_terms = (await cur.fetchone())[0]
            print(f"✅ terms: {n_terms:,} in {dt:.1f}s ({n_terms/max(dt,.001):,.0f}/s)")

            # ---- quads ----
            # A slim CSV (the converter's uuid_only_quads mode) has exactly the
            # four uuid columns in quad-table order, so it COPYs straight in.
            # The 14-column form cannot: COPY's column list must match the file's
            # column order, so it needs a staging table and an INSERT..SELECT to
            # project the four columns across — measured at 134s on top of a 69s
            # COPY for wordnet's 8.58M quads.
            with open(quads_csv, "r", encoding="utf-8") as fh:
                header = fh.readline().strip().replace('"', '').split(",")
            slim = header == ["subject_uuid", "predicate_uuid",
                              "object_uuid", "context_uuid"]

            if slim:
                dt = await copy_file(
                    cur,
                    f"COPY {quad_tbl} (subject_uuid, predicate_uuid, object_uuid, "
                    f"context_uuid) FROM STDIN WITH (FORMAT CSV, HEADER true, NULL '')",
                    quads_csv)
                await cur.execute(f"SELECT count(*) FROM {quad_tbl}")
                n_q = (await cur.fetchone())[0]
                print(f"✅ quads (direct COPY): {n_q:,} in {dt:.1f}s "
                      f"({n_q/max(dt,.001):,.0f}/s)")
            else:
                print("ℹ️  14-column quads CSV — using staging table + transfer. "
                      "Re-convert with uuid_only_quads=True to skip both.")
                await cur.execute(f"DROP TABLE IF EXISTS {stage_tbl}")
                cols_ddl = ", ".join(
                    f"{c} uuid" if c.endswith("_uuid") else f"{c} text"
                    for c in QUAD_CSV_COLUMNS)
                await cur.execute(f"CREATE UNLOGGED TABLE {stage_tbl} ({cols_ddl})")

                dt = await copy_file(
                    cur,
                    f"COPY {stage_tbl} ({', '.join(QUAD_CSV_COLUMNS)}) FROM STDIN "
                    f"WITH (FORMAT CSV, HEADER true, NULL '')",
                    quads_csv)
                await cur.execute(f"SELECT count(*) FROM {stage_tbl}")
                n_stage = (await cur.fetchone())[0]
                print(f"✅ staged quads: {n_stage:,} in {dt:.1f}s "
                      f"({n_stage/max(dt,.001):,.0f}/s)")

                t0 = time.time()
                await cur.execute(
                    f"INSERT INTO {quad_tbl} "
                    f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                    f"SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid "
                    f"FROM {stage_tbl}")
                dt = time.time() - t0
                print(f"✅ transferred to {quad_tbl} in {dt:.1f}s "
                      f"({n_stage/max(dt,.001):,.0f}/s)")
                await cur.execute(f"DROP TABLE IF EXISTS {stage_tbl}")

            if saved:
                t0 = time.time()
                for name, create_sql in saved:
                    await cur.execute(create_sql)
                print(f"🔧 rebuilt {len(saved)} indexes in {time.time()-t0:.1f}s")

            t0 = time.time()
            await cur.execute(f"ANALYZE {term_tbl}")
            await cur.execute(f"ANALYZE {quad_tbl}")
            print(f"📊 ANALYZE in {time.time()-t0:.1f}s")

            await cur.execute(f"SELECT count(*) FROM {quad_tbl}")
            n_quads = (await cur.fetchone())[0]

    if not skip_resync:
        await resync_aux(space)

    print(f"\n🏁 {n_terms:,} terms / {n_quads:,} quads "
          f"in {time.time()-total0:.1f}s total")
    return 0


async def resync_aux(space: str) -> None:
    """Rebuild the derived tables (edge, frame_entity, stats) after the load.

    Not optional, and not merely an optimisation. COPY writes the quad and term
    tables directly, so none of the incremental sync hooks in
    sparql_sql_space_impl fire. Any pre-existing {space}_edge therefore survives
    the load untouched, describing whatever the space held *before* — and
    `ensure_edge_table` will not notice, because it checks only that the table
    exists and is non-empty. Row counts can match exactly while every uuid in it
    is wrong, at which point KGQuery frame traversals return zero rows with no
    error. That is issues/041, found the hard way on wordnet_frames.

    Uses asyncpg rather than the script's psycopg connection: the sync helpers
    are written against asyncpg's API (fetchval/fetch).
    """
    import asyncpg
    from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables

    t0 = time.time()
    conn = await asyncpg.connect(**pg_env())
    try:
        counts = await resync_all_auxiliary_tables(conn, space)
    finally:
        await conn.close()
    print(f"🔗 resynced auxiliary tables in {time.time()-t0:.1f}s: "
          + ", ".join(f"{k}={v:,}" for k, v in sorted(counts.items())
                      if isinstance(v, int)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", required=True)
    ap.add_argument("--quads-csv", required=True)
    ap.add_argument("--terms-csv", required=True)
    ap.add_argument("--no-truncate", action="store_true")
    ap.add_argument("--keep-indexes", action="store_true")
    ap.add_argument("--skip-resync", action="store_true",
                    help="skip the auxiliary-table rebuild (edge, "
                         "frame_entity, stats). Only for loading a shard "
                         "you intend to follow with another load — a space "
                         "left without it answers KGQuery frame queries with "
                         "zero rows and no error (issues/041).")
    a = ap.parse_args()
    return asyncio.run(run(a.space, a.quads_csv, a.terms_csv,
                           not a.no_truncate, a.keep_indexes, a.skip_resync))


if __name__ == "__main__":
    sys.exit(main())
