"""Attribute the issues/208 offset curve: page selection, or projection?

`measure_projection_cold_vs_offset.py` shows variant E growing 1,000 -> 264,318 buffers
between offset 0 and 90,000. The projection is bounded by the page (25 entities
x 8 columns = 200 rows) and cannot be what grows, but that is an argument, not a
measurement. This measures the page CTE ALONE at the same offsets, so the
difference is the projection's actual contribution.
"""
import asyncio, os, re, statistics, sys, uuid
sys.path.insert(0, os.getcwd())
import asyncpg

SPACE = "lead_nurture_grouped"; GRAPH = f"urn:{SPACE}"; NS = "urn:acme:kg"
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
OFFSETS = [0, 1000, 5000, 15000, 80000, 90000]


async def m(conn, q, *a):
    for _ in range(2):
        await conn.fetch(q, *a)
    out = []
    for _ in range(4):
        text = "\n".join(r[0] for r in await conn.fetch(
            f"EXPLAIN (ANALYZE, BUFFERS) {q}", *a))
        out.append((float(re.search(r"Execution Time: ([\d.]+) ms", text).group(1)),
                    _root_buffers(text)))
    return statistics.median(x[0] for x in out), statistics.median(x[1] for x in out)


async def main():
    conn = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                                 password="testpass", database="sparql_sql_graph")
    t, tm = f"{SPACE}_entity_slot_sort", f"{SPACE}_term"
    ctx, ent = _u(GRAPH), _u(f"{NS}:entity:Lead")
    ss = _u(f"{NS}:slot:CompanyName")
    path = (await conn.fetchrow(
        f"SELECT frame_type_path FROM {t} WHERE slot_type_uuid=$1 AND "
        f"context_uuid=$2 LIMIT 1", ss, ctx))["frame_type_path"]
    slots = [_u(f"{NS}:slot:{c}") for c in COLS]

    page = lambda off: (
        f"SELECT entity_uuid FROM {t} WHERE context_uuid=$1 AND "
        f"entity_type_uuid=$2 AND frame_type_path=$3 AND slot_type_uuid=$4 "
        f"ORDER BY value_text COLLATE \"C\", entity_uuid LIMIT 25 OFFSET {off}")
    full = lambda off: (
        f"WITH page AS ({page(off)}) SELECT tm.term_text, s.slot_type_uuid, "
        f"s.value_text, s.value_num, s.value_dt FROM page p "
        f"JOIN {t} s ON s.entity_uuid=p.entity_uuid AND s.context_uuid=$1 "
        f"  AND s.slot_type_uuid=ANY($5::uuid[]) "
        f"JOIN {tm} tm ON tm.term_uuid=s.entity_uuid")

    print(f"  {'offset':>8}{'page ms':>10}{'page buf':>11}"
          f"{'+proj ms':>11}{'+proj buf':>11}{'delta ms':>10}{'delta buf':>11}")
    for off in OFFSETS:
        pms, pbuf = await m(conn, page(off), ctx, ent, path, ss)
        fms, fbuf = await m(conn, full(off), ctx, ent, path, ss, slots)
        print(f"  {off:>8}{pms:>10.2f}{pbuf:>11}{fms:>11.2f}{fbuf:>11}"
              f"{fms - pms:>10.2f}{fbuf - pbuf:>11}")
    await conn.close()

asyncio.run(main())
