#!/usr/bin/env python3
"""One-time repair of frame form types and frame groupings — `issues/257`, step 4.

THE RULE (decided 2026-10-03, `issues/256` / `issues/257`). `hasFrameGraphURI`
IS the frame graph, and a frame update or upsert REPLACES it (`issues/256`), so
a wrong grouping now loses or keeps data:

    KGFrame                 hasFrameGraphURI = ITSELF, and an explicit
                            hasKGFormType
    Edge_hasKGSlot          hasFrameGraphURI = its source frame
    a slot                  hasFrameGraphURI = the frame whose Edge_hasKGSlot
                            links it
    Edge_hasKGFrame         NO hasFrameGraphURI (structural links are in no
                            frame's graph)

FORM TYPE FIRST (option 2). A frame without `hasKGFormType` is classified by
grouping: no `hasFrameGraphURI` -> Assertion, has one -> Aspect. Giving every
frame its self-grouping would FLIP every unset-and-ungrouped frame from
Assertion to Aspect. So step 1 writes the classification each frame has TODAY
as an explicit value, and only then does anything touch groupings. Nothing
reclassifies.

THROUGH THE SERVER, BY SPARQL UPDATE (decided 2026-10-03). Every change goes
through `/api/graphs/sparql/update`, which takes the grouping locks in the
write's transaction and re-derives the edge, frame_slot, slot-sort and
prop-sort tables for the subjects it touches. Nothing here touches the
database directly. Two cautions from that path's own code: an edge-table sync
failure after an update is logged as non-critical, not raised; and under heavy
concurrent writes its lock acquisition can give up and proceed unlocked
(`issues/174`). Run it in a quiet window.

BOUNDED. Each step SELECTs up to `--batch` subjects that break the rule, fixes
exactly those with one UPDATE (`VALUES`), and repeats until none remain, so
every UPDATE has a fixed size. A step whose SELECT keeps returning the same
subjects is stopped and reported rather than looped on.

DRY RUN BY DEFAULT. Without `--apply` it only counts what each step would
change: that count IS the census, in the rule's own terms. With `--apply` it
counts, repairs, and counts again; every count after must be 0.

For the very large GENERATED spaces (`sp_lead_synth_100k`, 50M quads),
regenerating from the fixed generators may be cheaper than repairing.

    python scripts/repair_frame_groupings.py --space lead_test
    python scripts/repair_frame_groupings.py --space lead_test --apply

Talks to the server named by LOCAL_CLIENT_SERVER_URL (or --server).
"""

from __future__ import annotations

import argparse
import re
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KG = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"
PREFIX = f"PREFIX haley: <{KG}>\nPREFIX vital: <{VC}>\n"
ASSERTION = f"<{KG}KGFormType_Assertion>"
ASPECT = f"<{KG}KGFormType_Aspect>"

# Each step: what breaks the rule (a SELECT pattern binding ?x and ?g, plus
# ?f where the fix needs the owning frame), and how to fix one batch.
STEPS = [
    {
        "key": "1a",
        "name": "1a. form type: unset and grouped -> Aspect (today's default)",
        "vars": "?x ?g",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:KGFrame .
                    FILTER NOT EXISTS { ?x haley:hasKGFormType ?t }
                    FILTER EXISTS { ?x haley:hasFrameGraphURI ?o } }""",
        "update": f"""INSERT {{ GRAPH ?g {{ ?x haley:hasKGFormType {ASPECT} }} }}
                    WHERE {{ VALUES (?x ?g) {{ %s }} }}""",
    },
    {
        "key": "1b",
        "name": "1b. form type: unset and ungrouped -> Assertion (today's default)",
        "vars": "?x ?g",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:KGFrame .
                    FILTER NOT EXISTS { ?x haley:hasKGFormType ?t }
                    FILTER NOT EXISTS { ?x haley:hasFrameGraphURI ?o } }""",
        "update": f"""INSERT {{ GRAPH ?g {{ ?x haley:hasKGFormType {ASSERTION} }} }}
                    WHERE {{ VALUES (?x ?g) {{ %s }} }}""",
    },
    {
        "key": "2",
        "name": "2. frames grouped with themselves",
        "vars": "?x ?g",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:KGFrame .
                    FILTER ( NOT EXISTS { ?x haley:hasFrameGraphURI ?x }
                             || EXISTS { ?x haley:hasFrameGraphURI ?o FILTER (?o != ?x) } ) }""",
        "update": """DELETE { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }
                    INSERT { GRAPH ?g { ?x haley:hasFrameGraphURI ?x } }
                    WHERE { VALUES (?x ?g) { %s }
                            OPTIONAL { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } } }""",
    },
    {
        "key": "3",
        "name": "3. slot edges grouped with their source frame",
        "vars": "?x ?g ?f",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:Edge_hasKGSlot ;
                                  vital:hasEdgeSource ?f .
                    FILTER ( NOT EXISTS { ?x haley:hasFrameGraphURI ?f }
                             || EXISTS { ?x haley:hasFrameGraphURI ?o FILTER (?o != ?f) } ) }""",
        "update": """DELETE { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }
                    INSERT { GRAPH ?g { ?x haley:hasFrameGraphURI ?f } }
                    WHERE { VALUES (?x ?g ?f) { %s }
                            OPTIONAL { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } } }""",
    },
    {
        "key": "4",
        "name": "4. slots grouped with the frame that links them",
        "vars": "?x ?g ?f",
        # A slot linked from more than one frame has no single owner: it is
        # excluded here and reported by `shared_slots` instead of guessed at.
        "where": """GRAPH ?g { ?e vital:vitaltype haley:Edge_hasKGSlot ;
                                  vital:hasEdgeSource ?f ;
                                  vital:hasEdgeDestination ?x .
                    FILTER NOT EXISTS { ?e2 vital:vitaltype haley:Edge_hasKGSlot ;
                                            vital:hasEdgeDestination ?x ;
                                            vital:hasEdgeSource ?f2 . FILTER (?f2 != ?f) }
                    FILTER ( NOT EXISTS { ?x haley:hasFrameGraphURI ?f }
                             || EXISTS { ?x haley:hasFrameGraphURI ?o FILTER (?o != ?f) } ) }""",
        "update": """DELETE { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }
                    INSERT { GRAPH ?g { ?x haley:hasFrameGraphURI ?f } }
                    WHERE { VALUES (?x ?g ?f) { %s }
                            OPTIONAL { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } } }""",
    },
    {
        "key": "5",
        "name": "5. parent -> child edges carry no grouping",
        "vars": "?x ?g",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:Edge_hasKGFrame ;
                                  haley:hasFrameGraphURI ?o }""",
        "update": """DELETE { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }
                    WHERE { VALUES (?x ?g) { %s }
                            GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }""",
    },
]

SHARED_SLOTS = """SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { GRAPH ?g {
    ?e1 vital:vitaltype haley:Edge_hasKGSlot ; vital:hasEdgeDestination ?s ; vital:hasEdgeSource ?f1 .
    ?e2 vital:vitaltype haley:Edge_hasKGSlot ; vital:hasEdgeDestination ?s ; vital:hasEdgeSource ?f2 .
    FILTER (?f1 != ?f2) } }"""


# ---------------------------------------------------------------------------
# SQL DISCOVERY (--discover-sql). Reads only. On a production-sized space the
# whole-space SPARQL counts above exceed the server's 60s statement timeout
# (measured 2026-10-03: step 1a on the actions copy, cancelled at 55s even
# rewritten), and so would the batched SELECTs once few violators remain. This
# finds the EXACT violators once, in a read-only session with its own timeout;
# the WRITES still go through the server by SPARQL UPDATE, as decided.
# ---------------------------------------------------------------------------

# The term uuids are INLINED as literals. Taken from a one-row CTE (`k`), every
# filter became `predicate_uuid = k.vt`, a join condition the planner cannot
# push into the (predicate, object) index, and step 1a scanned the whole quad
# table: >5 minutes on a dev copy. Literals are what the SPARQL->SQL generator
# emits for the same reason.
def _uuid(uri: str) -> str:
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    return f"'{_generate_term_uuid(uri, 'U')}'::uuid"


_TERMS = {
    "vt": "http://vital.ai/ontology/vital-core#vitaltype",
    "frame": "http://vital.ai/ontology/haley-ai-kg#KGFrame",
    "sedge": "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot",
    "fedge": "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame",
    "src": "http://vital.ai/ontology/vital-core#hasEdgeSource",
    "dst": "http://vital.ai/ontology/vital-core#hasEdgeDestination",
    "fgu": "http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI",
    "form": "http://vital.ai/ontology/haley-ai-kg#hasKGFormType",
}


def _inline(sql: str) -> str:
    for key, uri in _TERMS.items():
        sql = re.sub(rf"\bk\.{key}\b", _uuid(uri), sql)
    return sql


# SET-BASED, not per-row probes. The first version checked every frame and
# slot with correlated EXISTS subqueries: three random index probes per row,
# ~180k buffers for 18.7k frames. Warm on dev that is under 2s; cold on
# production's gp3 volume it ran >10 minutes on one space and was cancelled.
# Here each predicate is read ONCE as a range and the steps are hash joins.
_SETS = """
 frames AS MATERIALIZED (SELECT subject_uuid AS x, context_uuid AS g FROM {Q}
           WHERE predicate_uuid = k.vt AND object_uuid = k.frame),
 grp    AS MATERIALIZED (SELECT subject_uuid AS x, context_uuid AS g, object_uuid AS o FROM {Q}
           WHERE predicate_uuid = k.fgu),
 sedge  AS MATERIALIZED (SELECT q.subject_uuid AS e, q.context_uuid AS g, s.object_uuid AS f, d.object_uuid AS s
           FROM {Q} q
           JOIN {Q} s ON s.subject_uuid = q.subject_uuid AND s.context_uuid = q.context_uuid
                     AND s.predicate_uuid = k.src
           JOIN {Q} d ON d.subject_uuid = q.subject_uuid AND d.context_uuid = q.context_uuid
                     AND d.predicate_uuid = k.dst
           WHERE q.predicate_uuid = k.vt AND q.object_uuid = k.sedge)"""

SQL = {
    "1a": """, formed AS (SELECT DISTINCT subject_uuid AS x, context_uuid AS g FROM {Q}
                         WHERE predicate_uuid = k.form)
      SELECT f.x, f.g FROM frames f
      WHERE NOT EXISTS (SELECT 1 FROM formed m WHERE m.x = f.x AND m.g = f.g)
        AND EXISTS (SELECT 1 FROM grp r WHERE r.x = f.x AND r.g = f.g)""",
    "1b": """, formed AS (SELECT DISTINCT subject_uuid AS x, context_uuid AS g FROM {Q}
                         WHERE predicate_uuid = k.form)
      SELECT f.x, f.g FROM frames f
      WHERE NOT EXISTS (SELECT 1 FROM formed m WHERE m.x = f.x AND m.g = f.g)
        AND NOT EXISTS (SELECT 1 FROM grp r WHERE r.x = f.x AND r.g = f.g)""",
    # Wrong unless the subject's ONLY grouping is the expected one.
    "2": """, have AS (SELECT r.x, r.g, bool_and(r.o = r.x) AS only_self FROM grp r
                       JOIN frames f ON f.x = r.x AND f.g = r.g GROUP BY r.x, r.g)
      SELECT f.x, f.g FROM frames f LEFT JOIN have h ON h.x = f.x AND h.g = f.g
      WHERE h.x IS NULL OR NOT h.only_self""",
    "3": """, have AS (SELECT r.x, r.g, bool_and(r.o = e.f) AS only_f FROM grp r
                       JOIN sedge e ON e.e = r.x AND e.g = r.g GROUP BY r.x, r.g)
      SELECT DISTINCT e.e, e.g, e.f FROM sedge e LEFT JOIN have h ON h.x = e.e AND h.g = e.g
      WHERE h.x IS NULL OR NOT h.only_f""",
    # One owner per slot; a slot linked from two frames is excluded.
    "4": """, owner AS (SELECT s, g, min(f::text)::uuid AS f FROM sedge GROUP BY s, g
                        HAVING count(DISTINCT f) = 1),
      have AS (SELECT r.x, r.g, bool_and(r.o = w.f) AS only_f FROM grp r
               JOIN owner w ON w.s = r.x AND w.g = r.g GROUP BY r.x, r.g)
      SELECT w.s, w.g, w.f FROM owner w LEFT JOIN have h ON h.x = w.s AND h.g = w.g
      WHERE h.x IS NULL OR NOT h.only_f""",
    "5": """, fedge AS (SELECT subject_uuid AS x, context_uuid AS g FROM {Q}
                        WHERE predicate_uuid = k.vt AND object_uuid = k.fedge)
      SELECT DISTINCT p.x, p.g FROM fedge p JOIN grp r ON r.x = p.x AND r.g = p.g""",
    "shared": """ SELECT count(*) FROM (SELECT s, g FROM sedge GROUP BY s, g
                   HAVING count(DISTINCT f) > 1) m""",
}


async def _sql_violators(conn, space, key) -> list:
    """The exact violators of one step, as URI tuples in the step's VALUES order."""
    q, t = f"{space}_rdf_quad", f"{space}_term"
    cols = ["x", "g", "f"] if key in ("3", "4") else ["x", "g"]
    inner = SQL[key].replace("{Q}", q)
    body = inner
    sel = ", ".join(f"t{c}.term_text" for c in cols)
    joins = " ".join(f"JOIN {t} t{c} ON t{c}.term_uuid = r.c{i}" for i, c in enumerate(cols))
    names = ", ".join(f"c{i}" for i in range(len(cols)))
    sql = _inline(f"WITH {_SETS.replace('{Q}', q)} {body}")
    rows = await conn.fetch(f"SELECT {sel} FROM ({sql}) r({names}) {joins}")
    return [tuple(r) for r in rows]


async def census_sql(conn, space) -> tuple:
    found, out = {}, {}
    for step in STEPS:
        found[step["key"]] = await _sql_violators(conn, space, step["key"])
        out[step["name"]] = len(found[step["key"]])
    q = f"{space}_rdf_quad"
    out["slots linked from more than one frame (not repaired)"] = await conn.fetchval(
        _inline(f"WITH {_SETS.replace('{Q}', q)} " + SQL["shared"].replace("{Q}", q)))
    return out, found


async def _current_groupings(conn, space, pairs) -> dict:
    """{(subject, graph): [hasFrameGraphURI values]} for the given subjects, by URI."""
    if not pairs:
        return {}
    t, q = f"{space}_term", f"{space}_rdf_quad"
    rows = await conn.fetch(
        f"""SELECT ts.term_text AS x, tg.term_text AS g, tob.term_text AS o
            FROM unnest($1::text[], $2::text[]) AS v(x, g)
            JOIN {t} ts ON ts.term_text = v.x AND ts.term_type = 'U'
            JOIN {t} tg ON tg.term_text = v.g AND tg.term_type = 'U'
            JOIN {q} r ON r.subject_uuid = ts.term_uuid AND r.context_uuid = tg.term_uuid
                      AND r.predicate_uuid = {_uuid(_TERMS["fgu"])}
            JOIN {t} tob ON tob.term_uuid = r.object_uuid""",
        [p[0] for p in pairs], [p[1] for p in pairs])
    out: dict = {}
    for r in rows:
        out.setdefault((r["x"], r["g"]), []).append(r["o"])
    return out


def _ground_update(step_key, chunk, current) -> str:
    """DELETE DATA / INSERT DATA for exactly these subjects: no WHERE clause.

    A DELETE/INSERT ... WHERE { VALUES ... OPTIONAL {...} } of 50 slots took
    ~30s on a dev copy and exceeded the 60s statement timeout on production,
    after its lock planning found no groupings and it ran unserialised. The
    old values are already known from the SQL discovery, so the update names
    the exact triples."""
    fgu = f"<{KG}hasFrameGraphURI>"
    dels, ins = [], []
    for r in chunk:
        x, g = r[0], r[1]
        if step_key in ("1a", "1b"):
            ft = ASPECT if step_key == "1a" else ASSERTION
            ins.append((g, f"<{x}> <{KG}hasKGFormType> {ft} ."))
            continue
        target = None if step_key == "5" else (x if step_key == "2" else r[2])
        for old in current.get((x, g), []):
            if old != target:
                dels.append((g, f"<{x}> {fgu} <{old}> ."))
        if target and target not in current.get((x, g), []):
            ins.append((g, f"<{x}> {fgu} <{target}> ."))

    def block(op, items):
        if not items:
            return ""
        by_g: dict = {}
        for g, triple in items:
            by_g.setdefault(g, []).append(triple)
        return f"{op} DATA {{ " + " ".join(
            f"GRAPH <{g}> {{ {' '.join(ts)} }}" for g, ts in by_g.items()) + " }"
    return " ;\n".join(b for b in (block("DELETE", dels), block("INSERT", ins)) if b)


async def _repair_from_list(client, space, step, rows, batch, conn=None) -> int:
    from vitalgraph.model.sparql_model import SPARQLUpdateRequest
    fixed = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        current = (await _current_groupings(conn, space, [(r[0], r[1]) for r in chunk])
                   if step["key"] not in ("1a", "1b") else {})
        update = _ground_update(step["key"], chunk, current)
        if not update:
            continue
        resp = await client.sparql.execute_sparql_update(
            space, SPARQLUpdateRequest(update=update))
        if getattr(resp, "error", None) or getattr(resp, "is_success", True) is False:
            raise RuntimeError(f"{step['name']}: update failed: "
                               f"{getattr(resp, 'error', None) or getattr(resp, 'message', resp)}")
        fixed += len(chunk)
        print(f"      {step['key']} batch of {len(chunk)} written ({fixed}/{len(rows)})", flush=True)
    return fixed


async def _sql_conn(prefix: str, use_ssl: bool):
    import asyncpg
    import ssl as _ssl
    ctx = None
    if use_ssl:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
    conn = await asyncpg.connect(
        host=os.environ[f"{prefix}_DB_HOST"], port=int(os.environ.get(f"{prefix}_DB_PORT", "5432")),
        database=os.environ[f"{prefix}_DB_NAME"], user=os.environ[f"{prefix}_DB_USER"],
        password=os.environ[f"{prefix}_DB_PASSWORD"], ssl=ctx, timeout=30,
        command_timeout=None)
    await conn.execute("SET default_transaction_read_only = on")
    await conn.execute("SET statement_timeout = '30min'")
    return conn


def _bindings(resp) -> list:
    results = getattr(resp, "results", None) or {}
    return results.get("bindings", []) if isinstance(results, dict) else []


async def _select(client, space, query) -> list:
    from vitalgraph.model.sparql_model import SPARQLQueryRequest
    resp = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=PREFIX + query))
    if getattr(resp, "error", None):
        raise RuntimeError(f"query failed: {resp.error}")
    return _bindings(resp)


async def _count(client, space, step) -> int:
    rows = await _select(client, space, f"SELECT (COUNT(*) AS ?n) WHERE {{ {step['where']} }}")
    return int(rows[0]["n"]["value"]) if rows else 0


async def _repair_step(client, space, step, batch) -> int:
    from vitalgraph.model.sparql_model import SPARQLUpdateRequest
    names = step["vars"].split()
    fixed, last = 0, None
    while True:
        rows = await _select(client, space,
                             f"SELECT DISTINCT {step['vars']} WHERE {{ {step['where']} }} LIMIT {batch}")
        if not rows:
            return fixed
        key = tuple(sorted(tuple(r[n.lstrip('?')]["value"] for n in names) for r in rows))
        if key == last:
            raise RuntimeError(f"{step['name']}: the same {len(rows)} subject(s) still break "
                               f"the rule after an update; stopping rather than looping")
        last = key
        values = " ".join("(" + " ".join(f"<{r[n.lstrip('?')]['value']}>" for n in names) + ")"
                          for r in rows)
        resp = await client.sparql.execute_sparql_update(
            space, SPARQLUpdateRequest(update=PREFIX + step["update"] % values))
        if getattr(resp, "error", None) or getattr(resp, "is_success", True) is False:
            raise RuntimeError(f"{step['name']}: update failed: "
                               f"{getattr(resp, 'error', None) or getattr(resp, 'message', resp)}")
        fixed += len(rows)
        print(f"      {step['name'][:2]} batch of {len(rows)} written ({fixed} so far)", flush=True)


async def census(client, space) -> dict:
    out = {}
    for step in STEPS:
        out[step["name"]] = await _count(client, space, step)
    rows = await _select(client, space, SHARED_SLOTS)
    out["slots linked from more than one frame (not repaired)"] = (
        int(rows[0]["n"]["value"]) if rows else 0)
    return out


def _print(label, counts):
    print(f"  {label}:")
    for k, v in counts.items():
        print(f"    {v:>10,}  {k}")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", required=True, action="append",
                    help="space to census/repair; repeat for several")
    ap.add_argument("--apply", action="store_true", help="write; without it, count only")
    ap.add_argument("--batch", type=int, default=500,
                    help="subjects per UPDATE. 925 slots in one update took ~90s "
                         "on a 309k-slot space (the update path re-evaluates its "
                         "bindings per lock pass)")
    ap.add_argument("--form-batch", type=int, default=500,
                    help="subjects per UPDATE for steps 1a/1b, which only INSERT a "
                         "form type (52,700 at 500 per update ran cleanly on a dev "
                         "copy). --batch governs the regrouping steps, whose "
                         "DELETE/INSERT ran past the 60s statement timeout at 500")
    ap.add_argument("--timeout", type=float, default=600,
                    help="client read timeout and request budget, seconds. The "
                         "client's default (30s) gives up on an update the server "
                         "then COMMITS, and does not retry a write, so a timed-out "
                         "batch ends the run with the batch applied")
    ap.add_argument("--server", help="server URL (overrides the profile's)")
    ap.add_argument("--discover-sql", metavar="PREFIX",
                    help="find violators by READ-ONLY SQL against the database in "
                         "PREFIX_DB_HOST/_PORT/_NAME/_USER/_PASSWORD, instead of by "
                         "SPARQL counts (which time out on production-sized spaces). "
                         "Writes still go through the server by SPARQL UPDATE")
    ap.add_argument("--discover-sql-ssl", action="store_true", help="SSL for that connection")
    a = ap.parse_args()
    profile = os.environ.get("VITALGRAPH_CLIENT_ENVIRONMENT", "local").upper()
    if a.server:
        os.environ[f"{profile}_CLIENT_SERVER_URL"] = a.server
    os.environ[f"{profile}_CLIENT_TIMEOUT"] = str(a.timeout)
    os.environ[f"{profile}_CLIENT_REQUEST_BUDGET"] = str(a.timeout)

    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    client = VitalGraphClient()
    await client.open()
    rc = 0
    try:
        print(f"server: {os.environ.get(profile + '_CLIENT_SERVER_URL')} ({profile} profile)  "
              f"mode: {'APPLY' if a.apply else 'dry run (counts only)'}")
        sqlconn = (await _sql_conn(a.discover_sql, a.discover_sql_ssl)
                   if a.discover_sql else None)
        if sqlconn:
            print(f"discovery: read-only SQL via {a.discover_sql}_DB_*")
        for space in a.space:
            print(f"\n== {space}")
            t0 = time.monotonic()
            if sqlconn:
                before, found = await census_sql(sqlconn, space)
            else:
                before, found = await census(client, space), None
            _print("before", before)
            if not a.apply:
                continue
            for step in STEPS:
                if before[step["name"]]:
                    print(f"    {step['name']}")
                    if found is not None:
                        # Steps are ordered: 1a/1b decide form type from the
                        # grouping BEFORE step 2 changes it, so each later step
                        # is re-discovered after the earlier ones have run.
                        rows = await _sql_violators(sqlconn, space, step["key"])
                        size = a.form_batch if step["key"] in ("1a", "1b") else a.batch
                        await _repair_from_list(client, space, step, rows, size, sqlconn)
                    else:
                        await _repair_step(client, space, step,
                                           a.form_batch if step["key"] in ("1a", "1b") else a.batch)
            after = (await census_sql(sqlconn, space))[0] if sqlconn else await census(client, space)
            _print("after", after)
            left = {k: v for k, v in after.items() if v and "not repaired" not in k}
            if left:
                print(f"  NOT CLEAN: {left}")
                rc = 1
            print(f"  {time.monotonic() - t0:.1f}s")
    finally:
        await client.close()
        if a.discover_sql and 'sqlconn' in locals() and sqlconn:
            await sqlconn.close()
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
