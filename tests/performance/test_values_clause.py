"""`VALUES` must cost about what the equivalent `FILTER` costs.

`issues/087`. A `VALUES` block naming URIs used to emit `NULL::uuid` for every
row, so the join could not compare term identities and fell back to casting both
sides to text — which meant scanning the term table. Measured on
`sp_lead_synth_100k`, same question three ways:

    VALUES ?s { <uri> }        21,789.8 ms   ->   0.2 ms
    VALUES, 2 URIs              6,240.5 ms   ->   0.4 ms
    VALUES, 20 URIs            57,591.3 ms   ->   4.0 ms
    <uri> ?p ?o (control)           0.3 ms        0.2 ms

The fix has three parts, and all three are needed: register the constants during
COLLECT so the first materialization pass resolves them; emit the resolved uuid
instead of NULL; and let the join drop its `IS NULL` compatibility guards when
every row of the block bound the variable to a constant that resolved, which is
what turns the condition back into an equijoin.

WHY THIS FILE EXISTS. No performance test used `VALUES` at all — the comparator
sweep, the growth curves and the paging benches all express constants as
literals or filters — which is how a 70,000x gap went unnoticed. It gates the
RATIO against an equivalent query rather than a timing, because the ratio is the
property that broke and it does not move with the machine.

It also pins the CORRECTNESS case that makes the optimisation safe: a URI absent
from the term table must match NOTHING. Its uuid resolves to NULL, and a NULL
uuid reads as "unbound", which under SPARQL compatibility joins with EVERYTHING.
That is a wrong answer rather than a slow one, so it is asserted here alongside
the timings.
"""

from __future__ import annotations

import time

import pytest

from .lead_fixtures import SYNTH, require_usable
from .test_kgquery_growth_curve import SIDECAR_URL, skip_no_pg

FIXTURES = SYNTH

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# A VALUES list of URIs against the same question written with a literal
# subject. The fix brings them to parity (0.2 vs 0.2 ms); 50 leaves room for a
# noisy laptop and for the list being longer than one, while catching any return
# to text-comparison, which was five orders of magnitude.
VALUES_RATIO_ALARM = 50.0


async def _run(conn, space, sparql):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    if not cr.ok:
        pytest.fail(f"VALUES query failed to compile: {cr.error}")
    gen = await generate_sql(cr, space, conn=conn)
    if not gen.ok:
        pytest.fail(f"VALUES query failed to generate SQL: {gen.error}")

    await conn.fetch(gen.sql)                      # warm
    runs, rows = [], []
    for _ in range(3):
        t0 = time.perf_counter()
        rows = await conn.fetch(gen.sql)
        runs.append((time.perf_counter() - t0) * 1000.0)
    return sorted(runs)[1], rows


async def _a_subject(conn, fx):
    """Any subject URI in the fixture, so the test does not hard-code data."""
    return await conn.fetchval(
        f"SELECT t.term_text FROM {fx.space}_rdf_quad q "
        f"JOIN {fx.space}_term t ON t.term_uuid = q.subject_uuid "
        f"WHERE t.term_type = 'U' LIMIT 1")


@pytest.mark.bench("query.values.vs_literal_subject")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_values_costs_what_a_literal_subject_costs(perf_conn, perf_record, fx):
    """The RATIO is the measurement — it is what the defect moved."""
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)
    subj = await _a_subject(perf_conn, fx)
    if not subj:
        pytest.skip(f"{fx.label}: no URI subject to query")

    values_ms, values_rows = await _run(perf_conn, fx.space,
        f"SELECT ?p ?o WHERE {{ GRAPH <{fx.graph}> {{ "
        f"VALUES ?s {{ <{subj}> }} ?s ?p ?o }} }}")
    literal_ms, literal_rows = await _run(perf_conn, fx.space,
        f"SELECT ?p ?o WHERE {{ GRAPH <{fx.graph}> {{ <{subj}> ?p ?o }} }}")

    ratio = values_ms / literal_ms if literal_ms else 0.0
    perf_record(kind="sql", dataset=fx.space,
                metrics={"values_ms": round(values_ms, 2),
                         "literal_subject_ms": round(literal_ms, 2),
                         "values_ratio": round(ratio, 1)},
                notes="VALUES vs an equivalent literal subject — issues/087")

    assert len(values_rows) == len(literal_rows), (
        f"VALUES returned {len(values_rows)} rows where the same question with "
        f"a literal subject returned {len(literal_rows)} — the two spellings "
        f"must agree")
    assert ratio < VALUES_RATIO_ALARM, (
        f"VALUES is {ratio:.0f}x the same query with a literal subject "
        f"({values_ms:.1f}ms vs {literal_ms:.1f}ms). The constants are probably "
        f"not being materialized to term uuids again, so the join is comparing "
        f"text and scanning the term table (issues/087).")


@pytest.mark.bench("query.values.list_growth")
@pytest.mark.parametrize("fx", FIXTURES[-1:], ids=[FIXTURES[-1].label])
async def test_a_longer_values_list_does_not_explode(perf_conn, perf_record, fx):
    """Cost should follow the LIST, not the space.

    Before the fix a 20-URI list cost 57,591 ms against 21,790 ms for one — the
    work was proportional to the term and edge tables, so adding URIs multiplied
    a scan rather than adding lookups.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)
    subjects = [r["t"] for r in await perf_conn.fetch(
        f"SELECT t.term_text AS t FROM {fx.space}_rdf_quad q "
        f"JOIN {fx.space}_term t ON t.term_uuid = q.subject_uuid "
        f"WHERE t.term_type = 'U' LIMIT 20")]
    if len(subjects) < 20:
        pytest.skip(f"{fx.label}: fewer than 20 URI subjects available")

    one_ms, _ = await _run(perf_conn, fx.space,
        f"SELECT ?p ?o WHERE {{ GRAPH <{fx.graph}> {{ "
        f"VALUES ?s {{ <{subjects[0]}> }} ?s ?p ?o }} }}")
    many = " ".join(f"<{s}>" for s in subjects)
    many_ms, many_rows = await _run(perf_conn, fx.space,
        f"SELECT ?s ?p ?o WHERE {{ GRAPH <{fx.graph}> {{ "
        f"VALUES ?s {{ {many} }} ?s ?p ?o }} }}")

    perf_record(kind="sql", dataset=fx.space,
                metrics={"values_1_ms": round(one_ms, 2),
                         "values_20_ms": round(many_ms, 2),
                         "values_growth": round(many_ms / one_ms, 1) if one_ms else 0},
                notes="VALUES cost against list length — issues/087")

    assert many_rows, "the 20-URI list matched nothing; the fixture changed"
    assert many_ms < one_ms * 200, (
        f"20 URIs cost {many_ms:.1f}ms against {one_ms:.1f}ms for one. Cost "
        f"should follow the list, not multiply a scan of the space.")


@pytest.mark.parametrize("fx", FIXTURES[-1:], ids=[FIXTURES[-1].label])
async def test_an_absent_uri_matches_nothing(perf_conn, fx):
    """The correctness case that makes the whole optimisation safe.

    A URI absent from the term table resolves to a NULL uuid. NULL reads as
    "unbound", and an unbound variable is compatible with ANY value under SPARQL
    join semantics — so the fast path must refuse to claim term identity here,
    or this query returns the entire graph instead of nothing.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    _, rows = await _run(perf_conn, fx.space,
        f"SELECT ?p ?o WHERE {{ GRAPH <{fx.graph}> {{ "
        f"VALUES ?s {{ <urn:definitely:not:in:this:graph:087> }} ?s ?p ?o }} }}")
    assert rows == [], (
        f"a VALUES naming an absent URI returned {len(rows)} rows and must "
        f"return none — a NULL uuid was read as 'unbound' and matched "
        f"everything (issues/087)")


@pytest.mark.parametrize("fx", FIXTURES[-1:], ids=[FIXTURES[-1].label])
async def test_a_mixed_present_and_absent_list_returns_only_the_present(
        perf_conn, fx):
    """`VALUES` is a union of alternatives: the present URI still matches."""
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)
    subj = await _a_subject(perf_conn, fx)
    if not subj:
        pytest.skip(f"{fx.label}: no URI subject to query")

    _, mixed = await _run(perf_conn, fx.space,
        f"SELECT ?s ?p ?o WHERE {{ GRAPH <{fx.graph}> {{ VALUES ?s {{ "
        f"<{subj}> <urn:definitely:not:in:this:graph:087> }} ?s ?p ?o }} }}")
    _, only = await _run(perf_conn, fx.space,
        f"SELECT ?s ?p ?o WHERE {{ GRAPH <{fx.graph}> {{ "
        f"VALUES ?s {{ <{subj}> }} ?s ?p ?o }} }}")

    assert len(mixed) == len(only), (
        f"a list of one present and one absent URI returned {len(mixed)} rows; "
        f"the present URI alone returns {len(only)}. An absent alternative must "
        f"contribute nothing and remove nothing.")
