#!/usr/bin/env python
"""Load the realistic perf datasets into the vg-test database.

Closes the coverage hole in `tests/performance`: 6 of 17 benches skip on a clean
stack because `wordnet_frames` (and the lead dataset) are not loaded, so the
realistic-data query paths go unmeasured. See
planning/planning_performance/performance_regression_tracking_plan.md §1.5.

Runs **inside the vg-test stack**, not on the host. `scripts/run-perf-tests.sh
--seed-data` invokes it in the app container, which already has the vitalgraph
package, with the datasets bind-mounted at /data/... and the stack's own
PostgreSQL reachable at `postgres:5432`:

    ./scripts/run-perf-tests.sh --seed-data ...

Equivalent by hand:

    docker compose -f docker-compose.test.yml \\
                   -f docker-compose.test.persist.yml \\
                   -f docker-compose.test.data.yml \\
      exec -e VG_TEST_PG_HOST=postgres -e VG_TEST_PG_PORT=5432 \\
           -e VG_TEST_PG_PASSWORD=testpass \\
      vitalgraph python /app/scripts/perf_seed_data.py --dataset wordnet

Source paths resolve through VG_TEST_DATA_DIR / VG_INTERNAL_DATA_DIR (set to the
container mount points by docker-compose.test.data.yml), falling back to
repo-relative paths, so the script is runnable outside the stack too if needed.

Targets the database named by **VG_TEST_PG_\\***. It deliberately does NOT go
through `VitalGraphConfig`/the CLIs: those resolve `LOCAL_DB_*` from the project
`.env`, which pins `host.docker.internal:5432` — the DEV database. Loading a
multi-GB dataset into the wrong server is not a mistake worth risking, so the
connection is explicit.

Idempotent: a space that already holds quads is left alone unless --force.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import gzip
import os
import shutil
import sys
import tempfile
import time

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema  # noqa: E402

DATASETS = {
    # `pick`: "first" = use the first source that exists (alternative encodings
    #         of one dataset); "all" = concatenate every match (sharded dataset).
    "wordnet": {
        "space": "wordnet_frames",
        "graph": "urn:wordnet_frames",
        # Only the -vt export. `kgframe-wordnet-0.0.1.nt` is an OLDER EXPORT of
        # the same logical dataset and is NOT interchangeable: frames and
        # entities carry data-derived URIs identical across exports, but edges
        # and slots carry VitalSigns-generated URIs assigned at export time, so
        # the two disagree on every edge and slot. Mixing them — or loading one
        # over the other — leaves {space}_edge pointing at uuids that exist
        # nowhere, with matching row counts, and every KGQuery frame traversal
        # then returns zero rows silently. See issues/041.
        "sources": ["test_data/kgframe-wordnet-0.0.1-vt.nt"],
        "pick": "first",
        # The -vt export carries vitaltype natively (that is what the `-vt`
        # conversion adds); the older .nt files carried only rdf:type.
        "derive_vitaltype": False,
    },
    "lead": {
        "space": "space_lead_dataset_test",
        "graph": "urn:lead_entity_graph_dataset",
        "sources": ["internal_data/lead_test_data/*.nt"],
        "pick": "all",
        # These files already carry vitaltype natively.
        "derive_vitaltype": False,
    },
}


def pg_params() -> dict:
    return dict(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"),
    )


def resolve(rel: str, root: str) -> str:
    """Map a repo-relative source path to where the data actually lives.

    Lets the same script run unchanged on the host (paths relative to the repo)
    and inside the app container (data bind-mounted at /data/... by
    docker-compose.test.data.yml, which sets these env vars).
    """
    overrides = {
        "test_data": os.environ.get("VG_TEST_DATA_DIR"),
        "internal_data": os.environ.get("VG_INTERNAL_DATA_DIR"),
    }
    head, _, tail = rel.partition("/")
    base = overrides.get(head)
    return os.path.join(base, tail) if base else os.path.join(root, rel)


def find_sources(spec: dict, root: str) -> list[str]:
    """Resolve the dataset's source files that actually exist on this machine."""
    found: list[str] = []
    for rel in spec["sources"]:
        matches = sorted(glob.glob(resolve(rel, root)))
        matches = [m for m in matches if os.path.isfile(m)]
        if not matches:
            continue
        if spec["pick"] == "first":
            return matches[:1]
        found.extend(matches)
    return found


def materialize(sources: list[str], max_triples: int | None,
                tmpdir: str) -> tuple[str, bool]:
    """Return (path, is_temp) — one plain .nt path for the importer.

    The bulk importer streams a single file, so we only pre-process when there
    is more than one source, the source is gzipped, or a subset was requested.
    """
    if len(sources) == 1 and max_triples is None and not sources[0].endswith(".gz"):
        return sources[0], False

    out = os.path.join(tmpdir, "seed.nt")
    n = 0
    with open(out, "w", encoding="utf-8") as w:
        for src in sources:
            opener = gzip.open if src.endswith(".gz") else open
            with opener(src, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    w.write(line)
                    n += 1
                    if max_triples is not None and n >= max_triples:
                        break
            if max_triples is not None and n >= max_triples:
                break
    print(f"   prepared {n:,} triples from {len(sources)} file(s) → "
          f"{os.path.getsize(out) / 1e6:.0f} MB")
    if max_triples is not None:
        print("   ⚠️  --max-triples takes a PREFIX of the data. Entity records "
              "can live late in a file, so a subset may omit whole types and "
              "leave benches matching 0 rows. Prefer a full load to trust "
              "results.")
    return out, True


VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


async def derive_vitaltype(conn, space_id: str, graph_uri: str) -> int:
    """Add one `vitaltype` quad per `rdf:type` quad.

    The kgframe-wordnet N-Triples files carry only `rdf:type` — they contain no
    `vitaltype` predicate at all. But the KG fast paths (and therefore the
    fast-page benches) filter on `vitaltype`, so a raw import produces a space
    where those queries match nothing and the benches "pass" against an empty
    result — a false green, which is the exact failure mode this whole process
    exists to prevent.

    The reference `wordnet_frames` space on the dev server carries `vitaltype`
    and `rdf:type` at *exactly* equal counts (1,536,485 each), i.e. one
    `vitaltype` per typed object. This reproduces that 1:1 shape. It is a
    derivation performed by the seeder, not something the source file contains
    — worth remembering when comparing absolute numbers against dev.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

    t = SparqlSQLSchema.get_table_names(space_id)
    vt_uuid = _generate_term_uuid(VITALTYPE, "U")

    # The vitaltype URI is not in the source data, so its term may not exist.
    await conn.execute(
        f"INSERT INTO {t['term']} (term_uuid, term_text, term_type) "
        f"VALUES ($1, $2, 'U') ON CONFLICT DO NOTHING", vt_uuid, VITALTYPE)

    rdf_type_uuid = _generate_term_uuid(RDF_TYPE, "U")
    existing = await conn.fetchval(
        f"SELECT count(*) FROM {t['rdf_quad']} WHERE predicate_uuid = $1", vt_uuid)
    if existing:
        return 0

    await conn.execute(
        f"INSERT INTO {t['rdf_quad']} "
        f"  (subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"SELECT subject_uuid, $1, object_uuid, context_uuid "
        f"FROM {t['rdf_quad']} WHERE predicate_uuid = $2 "
        f"ON CONFLICT DO NOTHING", vt_uuid, rdf_type_uuid)
    return await conn.fetchval(
        f"SELECT count(*) FROM {t['rdf_quad']} WHERE predicate_uuid = $1", vt_uuid)


async def space_is_registered(conn, space_id: str) -> bool:
    """True if the space has a row in the `space` registry table.

    Table existence is NOT sufficient: a persisted vg-test volume accumulates
    orphaned per-space tables from deleted spaces (the compose header documents
    one local stack reaching 116 of them). Such a space has all 20 tables and no
    registry row, and the import then dies on the `graph_space_id_fkey` foreign
    key. Checking registration separately is what makes the seeder idempotent
    against a reused volume.
    """
    return bool(await conn.fetchval(
        "SELECT 1 FROM space WHERE space_id = $1", space_id))


async def space_quad_count(conn, space_id: str) -> int | None:
    """Quads in the space, or None if its tables don't exist."""
    t = SparqlSQLSchema.get_table_names(space_id)
    exists = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE tablename = $1",
        t["rdf_quad"].split(".")[-1])
    if not exists:
        return None
    return await conn.fetchval(f"SELECT count(*) FROM {t['rdf_quad']}")


async def clean_orphan_quads(space_id: str, params: dict) -> int:
    """Delete quads whose predicate term is missing from the space's term table.

    That is the signature of the app's `backfill_server_properties_task`
    pollution (see tests/performance/README.md). Targeted repair: seconds,
    versus minutes for a full `--force` reload of a multi-million-quad space.
    """
    t = SparqlSQLSchema.get_table_names(space_id)
    conn = await asyncpg.connect(**params)
    try:
        before = await conn.fetchval(f"SELECT count(*) FROM {t['rdf_quad']}")
        await conn.execute(
            f"DELETE FROM {t['rdf_quad']} q WHERE NOT EXISTS "
            f"(SELECT 1 FROM {t['term']} tm WHERE tm.term_uuid = q.predicate_uuid)")
        after = await conn.fetchval(f"SELECT count(*) FROM {t['rdf_quad']}")
        await conn.execute(f"VACUUM (ANALYZE) {t['rdf_quad']}")
        return before - after
    finally:
        await conn.close()


async def register_space(space_id: str, params: dict) -> None:
    """Add the `space` registry row for a space whose tables already exist."""
    conn = await asyncpg.connect(**params)
    try:
        await conn.execute(
            "INSERT INTO space (space_id, space_name, space_description) "
            "VALUES ($1, $2, $3) ON CONFLICT (space_id) DO NOTHING",
            space_id, space_id, "Perf benchmark dataset (registry repaired)")
    finally:
        await conn.close()


async def ensure_graph(space_id: str, graph_uri: str, params: dict) -> None:
    """Register the graph the dataset lives in. Idempotent.

    `ensure_space` creates the space and its tables; loading quads with a
    `context_uuid` puts the data IN a graph. Neither REGISTERS one, and until
    2026-08-10 nothing did — every generated fixture on the local cluster had
    data and no `graph` row, `sp_lead_synth_100k` included at 50,570,000 quads.

    The consequence is not cosmetic. The `graph` table is what makes a graph
    visible to space listing, graph enumeration and the API paths that validate
    a graph before querying it, so an unregistered dataset can be queried by
    generating SQL directly and not through the service at all. That is why
    `issues/061` records the perf fixtures as unreachable by the perf suite.

    Pass the SAME uri the loader gives `convert_nt_to_csv --graph`. A row whose
    `graph_uri` does not match the context the quads carry is worse than no row:
    it registers a graph that resolves to nothing, and queries through it come
    back empty while looking correctly configured.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": params["host"], "port": params["port"],
                           "database": params["database"],
                           "username": params["user"],
                           "password": params["password"],
                           "min_pool_size": 1, "max_pool_size": 2},
        sidecar_config={"url": os.environ.get("VG_TEST_SIDECAR_URL",
                                              "http://localhost:7071")})
    await impl.connect()
    try:
        existing = await impl._db.execute_query(
            "SELECT 1 FROM graph WHERE space_id = $1 AND graph_uri = $2",
            [space_id, graph_uri])
        if existing:
            print(f"   graph {graph_uri} already registered")
            return
        # create_graph SWALLOWS its errors and returns False. Ignoring that
        # printed "registered" over a foreign-key violation the first time this
        # ran — a registry write reporting success on failure, which is the same
        # shape as every derived-data defect in this codebase. Fail loudly: a
        # loader that silently produces an unregistered dataset is what created
        # the eight-space backlog this helper exists to prevent.
        ok = await impl.create_graph(space_id, graph_uri)
        if not ok:
            raise SystemExit(
                f"❌ failed to register graph {graph_uri} for space {space_id} "
                f"— is the space registered, and is this the right database? "
                f"(pg_params defaults to port 5433, the docker test stack)")
        print(f"   graph {graph_uri} registered")
    finally:
        try:
            await impl.disconnect()
        except Exception:
            pass


async def ensure_space(space_id: str, params: dict) -> None:
    """Create the space (registry row + tables) via the space manager.

    Does NOT register a graph — see `ensure_graph`, which the loader must call
    with the URI it loaded the quads under.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.space.space_manager import SpaceManager

    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": params["host"], "port": params["port"],
                           "database": params["database"],
                           "username": params["user"],
                           "password": params["password"],
                           "min_pool_size": 1, "max_pool_size": 4},
        sidecar_config={"url": os.environ.get("VG_TEST_SIDECAR_URL",
                                              "http://localhost:7071")})
    await impl.connect()
    try:
        manager = SpaceManager(db_impl=getattr(impl, "db_impl", None),
                               space_backend=impl)
        ok = await manager.create_space_with_tables(
            space_id, space_id, "Perf benchmark dataset")
        if not ok:
            raise SystemExit(f"❌ failed to create space {space_id}")
    finally:
        try:
            await impl.disconnect()
        except Exception:
            pass


async def load(dataset: str, max_triples: int | None, force: bool,
               batch_size: int) -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = DATASETS[dataset]
    space_id, graph_uri = spec["space"], spec["graph"]
    params = pg_params()

    sources = find_sources(spec, root)
    if not sources:
        print(f"⚠️  {dataset}: no source file found. Looked for:")
        for c in spec["sources"]:
            print(f"      {resolve(c, root)}")
        print("   These datasets are gitignored and machine-local — see "
              "tests/performance/README.md.")
        return 2

    total_mb = sum(os.path.getsize(s) for s in sources) / 1e6
    print(f"📚 {dataset} → space '{space_id}' graph '{graph_uri}'")
    print(f"   source: {len(sources)} file(s), {total_mb:.0f} MB"
          f"{' — ' + sources[0] if len(sources) == 1 else ''}")
    print(f"   target: {params['host']}:{params['port']}/{params['database']}")

    conn = await asyncpg.connect(**params)
    try:
        existing = await space_quad_count(conn, space_id)
        registered = await space_is_registered(conn, space_id)
    finally:
        await conn.close()

    if existing and registered and not force:
        print(f"   ✅ already loaded ({existing:,} quads) — nothing to do "
              f"(use --force to reload)")
        return 0

    if not registered:
        if existing is None:
            await ensure_space(space_id, params)
            print("   created space + tables")
        else:
            # Tables exist but no registry row — orphaned from a deleted space.
            # SpaceManager.create_space_with_tables refuses this (its existence
            # check is table-based), so repair the registry directly. This is a
            # deliberate provisioning step in a test-stack seeder, not a data
            # path quietly conjuring spaces into existence.
            print(f"   ⚠️  {space_id}: tables exist ({existing:,} quads) but the "
                  f"space is NOT registered — orphaned from a deleted space; "
                  f"restoring the registry row")
            await register_space(space_id, params)
    elif force and existing:
        print(f"   ♻️  --force: reloading over {existing:,} existing quads")

    tmpdir = tempfile.mkdtemp(prefix="perf_seed_")
    try:
        path, _ = materialize(sources, max_triples, tmpdir)

        from vitalgraph.endpoint.impl.data_import_impl import ImportEngine
        pool = await asyncpg.create_pool(**params, min_size=1, max_size=4)
        try:
            engine = ImportEngine(pool)
            t0 = time.monotonic()
            result = await engine.import_ntriples_bulk(
                space_id=space_id, graph_uri=graph_uri, file_path=path,
                batch_size=batch_size, force=force)
        finally:
            await pool.close()
        elapsed = time.monotonic() - t0

        if not result.get("success"):
            print(f"   ❌ import failed: {result}")
            return 1
        quads = result.get("quads", 0)
        print(f"   ✅ {quads:,} quads / {result.get('terms', 0):,} terms "
              f"in {elapsed:.0f}s ({quads / max(elapsed, 1):,.0f} q/s)")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    conn = await asyncpg.connect(**params)
    try:
        t = SparqlSQLSchema.get_table_names(space_id)
        if spec["derive_vitaltype"]:
            added = await derive_vitaltype(conn, space_id, graph_uri)
            if added:
                print(f"   derived {added:,} vitaltype quads from rdf:type")

        # Fresh stats + visibility map: plan-shape assertions and index-only
        # scans depend on both, and a just-bulk-loaded table has neither.
        print("   running VACUUM (ANALYZE) ...")
        await conn.execute(f"VACUUM (ANALYZE) {t['rdf_quad']}")
        await conn.execute(f"VACUUM (ANALYZE) {t['term']}")
        total = await conn.fetchval(f"SELECT count(*) FROM {t['rdf_quad']}")
        print(f"   space now holds {total:,} quads")
    finally:
        await conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="wordnet", choices=sorted(DATASETS),
                    help="which dataset to load (default: wordnet)")
    ap.add_argument("--max-triples", type=int, default=None,
                    help="load only the first N triples (fast subset). "
                         "Omit for a full-fidelity load.")
    ap.add_argument("--batch-size", type=int, default=50_000)
    ap.add_argument("--force", action="store_true",
                    help="reload even if the space already holds data")
    ap.add_argument("--clean-orphans", action="store_true",
                    help="delete quads whose predicate term is missing (the "
                         "backfill task's pollution) instead of reloading — "
                         "seconds rather than minutes")
    args = ap.parse_args()
    return asyncio.run(load(args.dataset, args.max_triples, args.force,
                            args.batch_size))


if __name__ == "__main__":
    sys.exit(main())
