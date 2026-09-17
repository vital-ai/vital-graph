"""Separate COLD from DEEP-OFFSET in the issues/208 projection numbers.

The first-touch pass in `measure_slot_projection.py` moved to fresh offsets
to get cold rows, and a fresh offset is also a DEEPER one -- the page is chosen
by an ordered index scan, so `OFFSET 40000` skips 40,000 index tuples before it
returns anything. Those are two different costs and the first run reported their
sum.

Each offset here is measured COLD (one untouched sample) and then WARM (median
of 4). The level is the offset's cost; the gap is the cache's.
"""
import asyncio, os, re, statistics, sys, uuid
sys.path.insert(0, os.getcwd())
import asyncpg

SPACE = "lead_nurture_grouped"
GRAPH = f"urn:{SPACE}"
NS = "urn:acme:kg"
_VG = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
_u = lambda s: uuid.uuid5(_VG, f"{s}\x00U")
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

COLS = ["CompanyName", "LeadStatus", "MQLRating", "CompanyCity",
        "CompanyState", "StartDate", "MonthlyGrossSales", "LeadAge"]
# Untouched by the first script: it used 1000 and 40000/55000/70000.
OFFSETS = [2000, 3000, 7000, 20000, 33000, 96000]   # untouched by earlier runs


def _read(text):
    ms = float(re.search(r"Execution Time: ([\d.]+) ms", text).group(1))
    hits = _root_buffers(text)
    reads = _root_reads(text)
    return ms, hits, reads


async def main():
    conn = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                                 password="testpass", database="sparql_sql_graph")
    t, tm = f"{SPACE}_entity_slot_sort", f"{SPACE}_term"
    ctx, ent = _u(GRAPH), _u(f"{NS}:entity:Lead")
    sort_slot = _u(f"{NS}:slot:CompanyName")
    path = (await conn.fetchrow(
        f"SELECT frame_type_path FROM {t} WHERE slot_type_uuid=$1 "
        f"AND context_uuid=$2 LIMIT 1", sort_slot, ctx))["frame_type_path"]
    slots = [_u(f"{NS}:slot:{c}") for c in COLS]

    def sql(off, size=25):
        return (
            f"WITH page AS (SELECT entity_uuid FROM {t} "
            f" WHERE context_uuid=$1 AND entity_type_uuid=$2 "
            f"   AND frame_type_path=$3 AND slot_type_uuid=$4 "
            f" ORDER BY value_text COLLATE \"C\", entity_uuid "
            f" LIMIT {size} OFFSET {off}) "
            f"SELECT tm.term_text, s.slot_type_uuid, s.value_text, "
            f"       s.value_num, s.value_dt "
            f"FROM page p JOIN {t} s ON s.entity_uuid=p.entity_uuid "
            f"  AND s.context_uuid=$1 AND s.slot_type_uuid=ANY($5::uuid[]) "
            f"JOIN {tm} tm ON tm.term_uuid=s.entity_uuid")

    print(f"  25-entity page, 8 columns, variant E\n")
    print(f"  {'offset':>8}{'cold ms':>10}{'cold buf':>10}{'cold read':>11}"
          f"{'warm ms':>10}{'warm buf':>10}")
    for off in OFFSETS:
        q = f"EXPLAIN (ANALYZE, BUFFERS) {sql(off)}"
        cms, cbuf, cread = _read("\n".join(
            r[0] for r in await conn.fetch(q, ctx, ent, path, sort_slot, slots)))
        w = []
        for _ in range(4):
            w.append(_read("\n".join(
                r[0] for r in await conn.fetch(q, ctx, ent, path, sort_slot, slots))))
        wms = statistics.median(x[0] for x in w)
        wbuf = statistics.median(x[1] for x in w)
        print(f"  {off:>8}{cms:>10.1f}{cbuf:>10}{cread:>11}{wms:>10.2f}{wbuf:>10}")

    await conn.close()

asyncio.run(main())
