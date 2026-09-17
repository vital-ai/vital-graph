"""What a PROJECTION out of `entity_slot_sort` costs (issues/208).

The issue's open question in one script: the three lane indexes put the VALUE
before `entity_uuid`, so they answer the filter's question (seek a value, read
out entities) and not the projection's (have 25 entities, read out their
values). Nothing had measured the second direction.

Measures, on `lead_nurture_grouped` (74.5M quads, 4.06M slot-sort rows, the
fixture `test_entity_graph_fanout_bench` uses so the comparison is like for
like), for ONE 25-entity page and EIGHT slot columns spanning five frame paths:

    A  entity-led probe        entity_uuid = ANY($page) AND slot_type = ANY(...)
    B  prefix-led, 8 arms      full lane-index prefix per column + page filter
    C  A plus the term join    what a consumer actually hands back
    D  the same 8 values from the QUADS, per column, the walk the table mirrors

Usage:  python test_scripts/perf/measure_slot_projection.py
Env:    VG_PGHOST/PORT/USER/PASSWORD/DATABASE (defaults: the vg-test stack).
"""

import asyncio
import os
import re
import statistics
import sys
import uuid

sys.path.insert(0, os.getcwd())

import asyncpg

SPACE = os.getenv("VG_SPACE", "lead_nurture_grouped")
GRAPH = os.getenv("VG_GRAPH", f"urn:{SPACE}")
PAGE_SIZE = 25
OFFSET = 1000          # the offset the fan-out bench uses
REPS = 5

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
NS = "urn:acme:kg"
_VG_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _u(uri):
    return uuid.uuid5(_VG_NS, f"{uri}\x00U")


ENTITY_TYPE = f"{NS}:entity:Lead"
SORT_SLOT = f"{NS}:slot:CompanyName"

# Eight columns of a lead list, deliberately spread across FIVE frame paths --
# the case `fast_slot_sort.sort_keys` declines for a sort (one path per query)
# and a projection cannot decline, because a list view picks its own columns.
COLUMNS = [
    ("CompanyIdentityFrame",         "CompanyName",       "text"),
    ("LeadStatusCurrentFrame",       "LeadStatus",        "text"),
    ("LeadStatusQualificationFrame", "MQLRating",         "text"),
    ("CompanyAddressFrame",          "CompanyCity",       "text"),
    ("CompanyAddressFrame",          "CompanyState",      "text"),
    ("CompanyOperationsFrame",       "StartDate",         "dt"),
    ("CompanyFinancialFrame",        "MonthlyGrossSales", "num"),
    ("LeadStatusMetricsFrame",       "LeadAge",           "text"),
]

_BUF = re.compile(r"shared hit=(\d+)(?: read=(\d+))?")

# A plan node's `Buffers:` line INCLUDES its children's, so summing every
# line in the plan counts the same buffer once per level of nesting. The ROOT
# node's line is the total -- and it is the FIRST one EXPLAIN prints.


def _root_buffers(text):
    m = _BUF.search(text)
    return int(m.group(1)) + int(m.group(2) or 0)


def _root_reads(text):
    m = _BUF.search(text)
    return int(m.group(2) or 0)



async def explain(conn, sql, *args):
    """(ms, buffers, rows) for one statement, warmed and repeated."""
    for _ in range(2):
        await conn.fetch(sql, *args)
    times, bufs, rows = [], [], []
    for _ in range(REPS):
        plan = await conn.fetch(
            f"EXPLAIN (ANALYZE, BUFFERS, TIMING ON) {sql}", *args)
        text = "\n".join(r[0] for r in plan)
        ms = float(re.search(r"Execution Time: ([\d.]+) ms", text).group(1))
        n = _root_buffers(text)
        times.append(ms)
        bufs.append(n)
        rows.append(int(re.search(r"actual time=[\d.]+\.\.[\d.]+ rows=(\d+)", text).group(1)))
    return statistics.median(times), statistics.median(bufs), rows[0]


async def main():
    conn = await asyncpg.connect(
        host=os.getenv("VG_PGHOST", "localhost"),
        port=int(os.getenv("VG_PGPORT", "5433")),
        user=os.getenv("VG_PGUSER", "postgres"),
        password=os.getenv("VG_PGPASSWORD", "testpass"),
        database=os.getenv("VG_PGDATABASE", "sparql_sql_graph"),
    )
    t = f"{SPACE}_entity_slot_sort"
    tq = f"{SPACE}_rdf_quad"
    te = f"{SPACE}_edge"
    tm = f"{SPACE}_term"

    ctx = _u(GRAPH)
    ent_type = _u(ENTITY_TYPE)
    sort_slot = _u(SORT_SLOT)

    # Resolve each column to the (frame_type_path, slot_type_uuid) the table is
    # keyed by, from the table itself -- the path is data, not a convention.
    cols = []
    for frame, slot, lane in COLUMNS:
        row = await conn.fetchrow(
            f"SELECT frame_type_path FROM {t} WHERE slot_type_uuid = $1 "
            f"AND context_uuid = $2 LIMIT 1", _u(f"{NS}:slot:{slot}"), ctx)
        if row is None:
            print(f"  !! {slot} has no rows -- wrong space or fixture")
            return
        cols.append((frame, slot, lane, row["frame_type_path"],
                     _u(f"{NS}:slot:{slot}")))

    slot_types = [c[4] for c in cols]
    paths = {tuple(c[3]) for c in cols}
    print(f"space={SPACE}  page={PAGE_SIZE}@{OFFSET}  columns={len(cols)}  "
          f"distinct frame paths={len(paths)}")

    # THE PAGE, chosen the way `fast_slot_sort` chooses one: an ordered scan of
    # the text lane index. Measured too -- it is the half that already works.
    page_sql = (
        f"SELECT entity_uuid FROM {t} "
        f"WHERE context_uuid = $1 AND entity_type_uuid = $2 "
        f"  AND frame_type_path = $3 AND slot_type_uuid = $4 "
        f"ORDER BY value_text COLLATE \"C\", entity_uuid "
        f"LIMIT {PAGE_SIZE} OFFSET {OFFSET}")
    sort_path = next(c[3] for c in cols if c[1] == "CompanyName")
    ms, buf, n = await explain(conn, page_sql, ctx, ent_type, sort_path,
                               sort_slot)
    print(f"\n  page (the sort fast path, for reference)"
          f"{ms:>12.2f} ms {buf:>10} buf   {n} rows")
    page = [r["entity_uuid"] for r in
            await conn.fetch(page_sql, ctx, ent_type, sort_path, sort_slot)]
    assert len(page) == PAGE_SIZE, page

    print(f"\n  {'variant':<44}{'ms':>10}{'buffers':>10}{'rows':>8}")

    # A. Entity-led. The only index whose leading column is `entity_uuid` is
    #    idx_*_ess_entity, which does NOT carry the value columns -- so this is
    #    an index scan plus a heap fetch per row, not the index-only scan the
    #    filter path gets.
    a_sql = (f"SELECT entity_uuid, frame_type_path, slot_type_uuid, "
             f"value_text, value_num, value_dt FROM {t} "
             f"WHERE context_uuid = $1 AND entity_uuid = ANY($2::uuid[]) "
             f"  AND slot_type_uuid = ANY($3::uuid[])")
    ms, buf, n = await explain(conn, a_sql, ctx, page, slot_types)
    print(f"  {'A  entity-led, 8 columns in one probe':<44}"
          f"{ms:>10.2f}{buf:>10}{n:>8}")

    # B. Prefix-led: the index the FILTER uses, one arm per column, with the
    #    page as a filter on the trailing column.
    arms, args = [], [ctx, ent_type, page]
    for frame, slot, lane, path, st in cols:
        args += [path, st]
        i = len(args)
        arms.append(
            f"SELECT entity_uuid, ${i-1}::uuid[] AS p, ${i}::uuid AS s, "
            f"value_text, value_num, value_dt FROM {t} "
            f"WHERE context_uuid = $1 AND entity_type_uuid = $2 "
            f"  AND frame_type_path = ${i-1} AND slot_type_uuid = ${i} "
            f"  AND entity_uuid = ANY($3::uuid[])")
    b_sql = "\nUNION ALL\n".join(arms)
    ms, buf, n = await explain(conn, b_sql, *args)
    print(f"  {'B  prefix-led, 8 arms':<44}{ms:>10.2f}{buf:>10}{n:>8}")

    # C. A, plus the term join that turns entity_uuid into the URI a caller
    #    gets back. `entity_slot_sort` stores no URI (its sibling
    #    `entity_prop_sort` does), so this join is not optional.
    c_sql = (f"SELECT tm.term_text AS entity_uri, s.frame_type_path, "
             f"s.slot_type_uuid, s.value_text, s.value_num, s.value_dt "
             f"FROM {t} s JOIN {tm} tm ON tm.term_uuid = s.entity_uuid "
             f"WHERE s.context_uuid = $1 AND s.entity_uuid = ANY($2::uuid[]) "
             f"  AND s.slot_type_uuid = ANY($3::uuid[])")
    ms, buf, n = await explain(conn, c_sql, ctx, page, slot_types)
    print(f"  {'C  entity-led + term join (what is returned)':<44}"
          f"{ms:>10.2f}{buf:>10}{n:>8}")

    # D. The same eight values for the same 25 entities from the QUADS: the
    #    two-hop frame walk this table mirrors, one arm per column, which is
    #    what the general pipeline pays. One arm per column and NOT one query
    #    with OPTIONAL -- see issues/207.
    ef, cf, se = _u(f"{HALEY}Edge_hasEntityKGFrame"), \
        _u(f"{HALEY}Edge_hasKGFrame"), _u(f"{HALEY}Edge_hasKGSlot")
    ftp, stp = _u(f"{HALEY}hasKGFrameType"), _u(f"{HALEY}hasKGSlotType")
    vps = [_u(f"{HALEY}{p}") for p in (
        "hasTextSlotValue", "hasBooleanSlotValue", "hasDateTimeSlotValue",
        "hasIntegerSlotValue", "hasDoubleSlotValue", "hasCurrencySlotValue",
        "hasUriSlotValue", "hasChoiceSlotValue", "hasJsonSlotValue",
        "hasLongSlotValue")]
    arms, args = [], [ctx, page, ef, cf, se, ftp, stp, vps]
    for frame, slot, lane, path, st in cols:
        args += [path[1], st]
        i = len(args)
        arms.append(f"""
        SELECT e1.source_node_uuid AS entity_uuid, ${i}::uuid AS s,
               vt.term_text, vt.num_val, vt.dt_val
        FROM {te} e1
        JOIN {te} e2 ON e2.source_node_uuid = e1.dest_node_uuid
                    AND e2.context_uuid = e1.context_uuid
                    AND e2.edge_type_uuid = $4
        JOIN {tq} f2t ON f2t.subject_uuid = e2.dest_node_uuid
                     AND f2t.predicate_uuid = $6
                     AND f2t.context_uuid = e1.context_uuid
                     AND f2t.object_uuid = ${i-1}
        JOIN {te} e3 ON e3.source_node_uuid = e2.dest_node_uuid
                    AND e3.context_uuid = e1.context_uuid
                    AND e3.edge_type_uuid = $5
        JOIN {tq} slt ON slt.subject_uuid = e3.dest_node_uuid
                     AND slt.predicate_uuid = $7
                     AND slt.context_uuid = e1.context_uuid
                     AND slt.object_uuid = ${i}
        JOIN {tq} vq ON vq.subject_uuid = e3.dest_node_uuid
                    AND vq.predicate_uuid = ANY($8::uuid[])
                    AND vq.context_uuid = e1.context_uuid
        JOIN {tm} vt ON vt.term_uuid = vq.object_uuid
        WHERE e1.context_uuid = $1 AND e1.edge_type_uuid = $3
          AND e1.source_node_uuid = ANY($2::uuid[])""")
    d_sql = "\nUNION ALL\n".join(arms)
    ms, buf, n = await explain(conn, d_sql, *args)
    print(f"  {'D  the same 8 values from the quads':<44}"
          f"{ms:>10.2f}{buf:>10}{n:>8}")

    # Agreement: the table is a MIRROR, so if D and C disagree the numbers
    # above are comparing two different answers.
    got = await conn.fetch(c_sql, ctx, page, slot_types)
    ref = await conn.fetch(d_sql, *args)
    c_vals = {(r["entity_uri"], r["slot_type_uuid"]) for r in got}
    print(f"\n  rows: table {len(got)}  quads {len(ref)}  "
          f"distinct (entity,slot) from table {len(c_vals)}")
    tv = {(r["entity_uri"], r["slot_type_uuid"]):
          (r["value_text"], r["value_num"], r["value_dt"]) for r in got}
    uri_of = {r["term_uuid"]: r["term_text"] for r in await conn.fetch(
        f"SELECT term_uuid, term_text FROM {tm} WHERE term_uuid = ANY($1::uuid[])",
        page)}
    bad = 0
    for r in ref:
        k = (uri_of.get(r["entity_uuid"]), r["s"])
        if k not in tv or tv[k][0] != r["term_text"]:
            bad += 1
    print(f"  values disagreeing with the quads: {bad}")

    # ------------------------------------------------------------------
    # E. Page and projection in ONE statement -- what a consumer would run,
    #    with no second round trip and no URI list crossing the wire.
    # ------------------------------------------------------------------
    e_sql = (
        f"WITH page AS ({page_sql}) "
        f"SELECT tm.term_text AS entity_uri, s.frame_type_path, "
        f"s.slot_type_uuid, s.value_text, s.value_num, s.value_dt "
        f"FROM page p "
        f"JOIN {t} s ON s.entity_uuid = p.entity_uuid "
        f"           AND s.context_uuid = $1 "
        f"           AND s.slot_type_uuid = ANY($5::uuid[]) "
        f"JOIN {tm} tm ON tm.term_uuid = s.entity_uuid")
    ms, buf, n = await explain(conn, e_sql, ctx, ent_type, sort_path,
                               sort_slot, slot_types)
    print(f"  {'E  page + projection, one statement':<44}"
          f"{ms:>10.2f}{buf:>10}{n:>8}")

    # ------------------------------------------------------------------
    # PAGE SIZE. A projection is per-row work where the page selection is not,
    # so the two scale differently and only one of them is bounded by the page.
    # ------------------------------------------------------------------
    print(f"\n  page size, variant E"
          f"{'':>18}{'ms':>10}{'buffers':>10}{'rows':>8}")
    for size in (25, 100, 500):
        sql = e_sql.replace(f"LIMIT {PAGE_SIZE} OFFSET {OFFSET}",
                            f"LIMIT {size} OFFSET {OFFSET}")
        ms, buf, n = await explain(conn, sql, ctx, ent_type, sort_path,
                                   sort_slot, slot_types)
        print(f"  {'  ' + str(size) + ' entities':<44}{ms:>10.2f}{buf:>10}{n:>8}")

    # ------------------------------------------------------------------
    # FIRST TOUCH. Everything above is warm. `test_entity_graph_fanout_bench`
    # records the fan-out at 3.2-4.3 s cold against ~1 s warm on this fixture,
    # so a warm-only number for the thing replacing it would be half an answer.
    # PostgreSQL's cache cannot be emptied without a restart, so this uses
    # OFFSETS NOTHING IN THIS RUN HAS TOUCHED -- one sample each, the same
    # compromise the fan-out bench makes.
    # ------------------------------------------------------------------
    print(f"\n  first touch (fresh offset, ONE sample, cold rows)"
          f"{'':>3}{'ms':>10}{'buffers':>10}{'read':>8}")
    for off in (40000, 55000, 70000):
        sql = e_sql.replace(f"LIMIT {PAGE_SIZE} OFFSET {OFFSET}",
                            f"LIMIT {PAGE_SIZE} OFFSET {off}")
        plan = await conn.fetch(
            f"EXPLAIN (ANALYZE, BUFFERS) {sql}", ctx, ent_type, sort_path,
            sort_slot, slot_types)
        text = "\n".join(r[0] for r in plan)
        ms = float(re.search(r"Execution Time: ([\d.]+) ms", text).group(1))
        hits = _root_buffers(text)
        reads = _root_reads(text)
        print(f"  {'  E at offset ' + str(off):<44}{ms:>10.2f}{hits:>10}{reads:>8}")

        # The same offset, from the quads, also first touch.
        d_args = list(args)
        d_page = [r["entity_uuid"] for r in await conn.fetch(
            page_sql.replace(f"OFFSET {OFFSET}", f"OFFSET {off}"),
            ctx, ent_type, sort_path, sort_slot)]
        d_args[1] = d_page
        plan = await conn.fetch(f"EXPLAIN (ANALYZE, BUFFERS) {d_sql}", *d_args)
        text = "\n".join(r[0] for r in plan)
        ms = float(re.search(r"Execution Time: ([\d.]+) ms", text).group(1))
        hits = _root_buffers(text)
        reads = _root_reads(text)
        print(f"  {'  D (quads) at offset ' + str(off):<44}"
              f"{ms:>10.2f}{hits:>10}{reads:>8}")

    await conn.close()


asyncio.run(main())
