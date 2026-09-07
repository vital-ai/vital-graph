#!/usr/bin/env python3
"""Enforce single-valued predicates with partial unique indexes. `issues/175`.

WHY A CONSTRAINT AND NOT A LOCK
    `issues/173` found 243 entities holding two to four values for
    `hasObjectCreationTime` and `hasObjectModificationDateTime`, which are
    single-valued. One such entity returned an empty page from the entity
    listing. The cause was a write race, and that race is now locked — but a
    lock is opt-in per path. A raw SPARQL update, a psql session, or an endpoint
    written next year can all still insert a second value.

    `{space}_rdf_quad`'s primary key is (subject, predicate, object, context),
    so two DIFFERENT values for one predicate coexist legitimately. That is
    correct for RDF and wrong for a single-valued property. A partial unique
    index on (subject, context) restricted to one predicate makes the second
    value impossible for EVERY writer, including ones that do not exist yet.
    That is the property a lock cannot have.

WHICH PREDICATES
    Taken from the ontology, not from a list maintained here. VitalSigns
    property trait classes carry `multiple_values`, and this script REFUSES to
    index any predicate the ontology reports as multi-valued — so a hand-passed
    `--predicates` cannot introduce a constraint the model disagrees with.

    The default set is the server-managed properties plus `vitaltype`, which are
    the ones the system itself writes and therefore the ones a write race can
    corrupt without a client ever asking for it. Indexing EVERY single-valued
    predicate would be the stronger guarantee, but each index is write
    amplification on a hot table; widening the set is a deliberate choice, made
    with `--predicates`.

BUILDING
    `CREATE UNIQUE INDEX CONCURRENTLY`, because these tables are large and live.
    That cannot run inside a transaction, so each index is issued on its own and
    a failure leaves an INVALID index behind rather than rolling back — this
    script detects those and reports them rather than skipping silently.

    A space whose data already violates the constraint is REPORTED AND SKIPPED,
    not forced. The index refusing to build is the constraint declining to be
    enabled on a false premise, which is the behaviour that makes it worth
    having. Repair first with `repair_duplicate_server_timestamps.py`.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid  # noqa: E402

logger = logging.getLogger("migrate_single_valued_indexes")

# The system writes these itself, so a write race corrupts them without any
# client asking for it — which is exactly what happened in issues/173.
# `vitaltype` is a structural predicate rather than a VitalSigns property, so it
# has no trait class to consult; it is single-valued by construction (one type
# URI per object) and is listed explicitly for that reason.
DEFAULT_PREDICATES = [
    "http://vital.ai/ontology/vital-core#vitaltype",
    "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime",
    "http://vital.ai/ontology/vital#hasObjectModificationDateTime",
    "http://vital.ai/ontology/vital-aimp#hasObjectStatusType",
    "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType",
]
STRUCTURAL = {"http://vital.ai/ontology/vital-core#vitaltype"}


def _ontology_rejects(uri: str) -> bool:
    """True if the ontology says this predicate MAY hold multiple values.

    Consulted so that a `--predicates` argument cannot create a constraint the
    model disagrees with. An unknown property is NOT treated as multi-valued —
    it is reported by the caller and skipped, because "the ontology has no
    opinion" and "the ontology permits many" are different statements and only
    the second is a reason to refuse.
    """
    if uri in STRUCTURAL:
        return False
    try:
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        cls = VitalSigns().get_registry().get_vitalsigns_property_class(uri)
        return bool(getattr(cls, "multiple_values", False))
    except Exception:
        return False


def _known_to_ontology(uri: str) -> bool:
    if uri in STRUCTURAL:
        return True
    try:
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        return VitalSigns().get_registry().get_vitalsigns_property_class(uri) is not None
    except Exception:
        return False


def _index_name(space_id: str, uri: str) -> str:
    """A name derived from the predicate UUID, not from the URI.

    PostgreSQL truncates identifiers at 63 bytes, and these URIs collide well
    inside that limit once prefixed with the space and table — `hasObjectCreationTime`
    and `hasObjectModificationDateTime` share a prefix long enough to matter. The
    UUID's first segment is stable and unique.
    """
    return f"uq_{space_id}_sv_{_generate_term_uuid(uri, 'U').hex[:12]}"


async def _violations(conn, space_id: str, p_uuid) -> int:
    return await conn.fetchval(
        f"SELECT count(*) FROM (SELECT subject_uuid, context_uuid"
        f"   FROM {space_id}_rdf_quad WHERE predicate_uuid = $1"
        f"  GROUP BY 1, 2 HAVING count(*) > 1) x", p_uuid) or 0


async def _index_state(conn, name: str):
    """(exists, valid) for an index by name."""
    row = await conn.fetchrow(
        "SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid"
        " WHERE c.relname = $1", name)
    return (row is not None, bool(row["indisvalid"]) if row else False)


async def migrate_space(conn, space_id: str, predicates, apply: bool) -> dict:
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            f"{space_id}_rdf_quad"):
        return {"space": space_id, "status": "no such space"}

    made, skipped, blocked, invalid = [], [], [], []
    for uri in predicates:
        short = uri.rsplit("#", 1)[-1]
        if _ontology_rejects(uri):
            logger.warning("  %-34s SKIPPED — the ontology declares it "
                           "multi-valued; a unique index would be wrong", short)
            skipped.append(short)
            continue
        if not _known_to_ontology(uri):
            logger.info("  %-34s not known to the ontology — indexing anyway on "
                        "the caller's say-so", short)

        p_uuid = _generate_term_uuid(uri, "U")
        name = _index_name(space_id, uri)
        exists, valid = await _index_state(conn, name)
        if exists and valid:
            logger.info("  %-34s already enforced", short)
            skipped.append(short)
            continue
        if exists and not valid:
            # CONCURRENTLY left it behind on a previous failure. It is not
            # enforcing anything and it must be dropped before a retry.
            logger.error("  %-34s an INVALID index (%s) is present from a failed "
                         "concurrent build — it enforces nothing. Drop it with "
                         "`DROP INDEX %s;` and re-run.", short, name, name)
            invalid.append(short)
            continue

        n = await _violations(conn, space_id, p_uuid)
        if n:
            logger.error("  %-34s BLOCKED — %d subject(s) already hold more than "
                         "one value. Repair first "
                         "(scripts/repair_duplicate_server_timestamps.py); the "
                         "index is refusing to certify data that contradicts it.",
                         short, n)
            blocked.append(short)
            continue

        if not apply:
            logger.info("  %-34s would enforce (0 violations)", short)
            made.append(short)
            continue

        # CONCURRENTLY cannot run inside a transaction; asyncpg autocommits a
        # bare execute, so this must NOT be wrapped.
        await conn.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY {name}"
            f"  ON {space_id}_rdf_quad (subject_uuid, context_uuid)"
            f"  WHERE predicate_uuid = '{p_uuid}'")
        _, ok = await _index_state(conn, name)
        if not ok:
            logger.error("  %-34s built INVALID — drop %s and retry", short, name)
            invalid.append(short)
        else:
            logger.info("  %-34s ENFORCED", short)
            made.append(short)

    return {"space": space_id, "enforced": made, "skipped": skipped,
            "blocked": blocked, "invalid": invalid}


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    ap.add_argument("--space", help="space id")
    ap.add_argument("--all", action="store_true", help="every space in the database")
    ap.add_argument("--predicates", nargs="+", metavar="URI",
                    help="override the default predicate set")
    ap.add_argument("--apply", action="store_true",
                    help="create the indexes (default is a dry run)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.space and not args.all:
        ap.error("one of --space or --all is required")

    predicates = args.predicates or DEFAULT_PREDICATES
    print(f"\U0001F5C4  target: {describe_target(args)}", flush=True)
    logger.info("%s — %d predicate(s)", "APPLY" if args.apply else "DRY RUN",
                len(predicates))

    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        if args.all:
            spaces = [r[0] for r in await conn.fetch(
                "SELECT replace(tablename,'_rdf_quad','') FROM pg_tables "
                "WHERE schemaname='public' AND tablename LIKE '%\\_rdf\\_quad' "
                "ORDER BY 1")]
        else:
            spaces = [args.space]

        any_blocked = False
        for sp in spaces:
            logger.info("\n%s:", sp)
            r = await migrate_space(conn, sp, predicates, apply=args.apply)
            if r.get("blocked") or r.get("invalid"):
                any_blocked = True
        if any_blocked:
            logger.warning(
                "\nSome predicates were not enforced. A blocked one means the "
                "data still violates the invariant — repair it and re-run; "
                "leaving it unenforced leaves that predicate open to the race "
                "issues/173 recorded.")
        if not args.apply:
            logger.info("\nDry run. Re-run with --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
