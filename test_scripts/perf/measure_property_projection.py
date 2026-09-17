"""What a PROPERTY projection costs, next to the slot one (`issues/208`).

The slot projection reads `entity_slot_sort`, which is keyed on the SLOT, so an
entity-led probe uses a secondary index and takes a heap fetch.
`entity_prop_sort` is keyed `(entity_uuid, context_uuid, property_uuid)` — the
entity LEADS the primary key — so the same shape should be a PK seek. Measured
rather than assumed.

Five properties x 25 entities on `lead_nurture_grouped`, against the same five
values from the quads.
"""
import asyncio, os, re, statistics, sys, uuid
sys.path.insert(0, os.getcwd())
import asyncpg

S = "lead_nurture_grouped"
NS = "urn:acme:kg"
CORE, VITAL, AIMP, HALEY = (
    "http://vital.ai/ontology/vital-core#", "http://vital.ai/ontology/vital#",
    "http://vital.ai/ontology/vital-aimp#", "http://vital.ai/ontology/haley-ai-kg#")
PROPS = [f"{CORE}hasName", f"{HALEY}hasKGEntityType", f"{AIMP}hasObjectStatusType",
         f"{VITAL}hasObjectModificationDateTime", f"{AIMP}hasObjectCreationTime"]
_VG = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
_u = lambda s: uuid.uuid5(_VG, f"{s}\x00U")
_BUF = re.compile(r"shared hit=(\d+)(?: read=(\d+))?")


def _root(text):
    m = _BUF.search(text)
    return int(m.group(1)) + int(m.group(2) or 0)


async def measure(conn, sql, *args):
    for _ in range(2):
        await conn.fetch(sql, *args)
    t, b, rows = [], [], 0
    for _ in range(5):
        txt = "\n".join(r[0] for r in await conn.fetch(
            f"EXPLAIN (ANALYZE, BUFFERS) {sql}", *args))
        t.append(float(re.search(r"Execution Time: ([\d.]+) ms", txt).group(1)))
        b.append(_root(txt))
        rows = int(re.search(r"actual time=[\d.]+\.\.[\d.]+ rows=(\d+)", txt).group(1))
    return statistics.median(t), statistics.median(b), rows


async def main():
    c = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                              password="testpass", database="sparql_sql_graph")
    ctx, ent = _u(f"urn:{S}"), _u(f"{NS}:entity:Lead")
    ss = _u(f"{NS}:slot:CompanyName")
    t_ess, t_eps = f"{S}_entity_slot_sort", f"{S}_entity_prop_sort"
    path = (await c.fetchrow(
        f"SELECT frame_type_path FROM {t_ess} WHERE slot_type_uuid=$1 AND "
        f"context_uuid=$2 LIMIT 1", ss, ctx))["frame_type_path"]
    page = [r[0] for r in await c.fetch(
        f"SELECT entity_uuid FROM {t_ess} WHERE context_uuid=$1 AND entity_type_uuid=$2 "
        f"AND frame_type_path=$3 AND slot_type_uuid=$4 "
        f"ORDER BY value_text COLLATE \"C\", entity_uuid LIMIT 25 OFFSET 1000",
        ctx, ent, path, ss)]
    props = [_u(p) for p in PROPS]

    print(f"  {'variant':<46}{'ms':>9}{'buffers':>10}{'rows':>7}")

    prop_sql = (f"SELECT entity_uri, property_uuid, value_all "
                f"FROM {t_eps} WHERE context_uuid=$1 AND entity_uuid=ANY($2::uuid[]) "
                f"AND property_uuid=ANY($3::uuid[])")
    ms, buf, n = await measure(c, prop_sql, ctx, page, props)
    print(f"  {'property projection, 5 columns':<46}{ms:>9.2f}{buf:>10}{n:>7}")

    quad_sql = (f"SELECT q.subject_uuid, q.predicate_uuid, t.term_text "
                f"FROM {S}_rdf_quad q JOIN {S}_term t ON t.term_uuid=q.object_uuid "
                f"WHERE q.context_uuid=$1 AND q.subject_uuid=ANY($2::uuid[]) "
                f"AND q.predicate_uuid=ANY($3::uuid[])")
    ms, buf, n = await measure(c, quad_sql, ctx, page, props)
    print(f"  {'the same 5 values from the quads':<46}{ms:>9.2f}{buf:>10}{n:>7}")

    both = (f"SELECT entity_uri AS u, property_uuid::text AS k, value_all AS v "
            f"FROM {t_eps} WHERE context_uuid=$1 AND entity_uuid=ANY($2::uuid[]) "
            f"AND property_uuid=ANY($3::uuid[])")
    ms, buf, n = await measure(c, both, ctx, page, props)
    print(f"  {'(same, as one statement with the slots below)':<46}{ms:>9.2f}{buf:>10}{n:>7}")

    # Agreement: the table is a mirror, so disagreement means the numbers above
    # compare two different answers.
    tab = {(r["entity_uri"], r["property_uuid"]): sorted(r["value_all"])
           for r in await c.fetch(prop_sql, ctx, page, props)}
    ref = {}
    for r in await c.fetch(quad_sql, ctx, page, props):
        ref.setdefault((r["subject_uuid"], r["predicate_uuid"]), []).append(r["term_text"])
    uri_of = {r["entity_uuid"]: r["entity_uri"] for r in await c.fetch(
        f"SELECT DISTINCT entity_uuid, entity_uri FROM {t_eps} "
        f"WHERE entity_uuid=ANY($1::uuid[])", page)}
    bad = sum(1 for (e, p), v in ref.items()
              if tab.get((uri_of.get(e), p)) != sorted(v))
    print(f"\n  pairs: table {len(tab)}  quads {len(ref)}  disagreeing: {bad}")
    await c.close()

asyncio.run(main())
