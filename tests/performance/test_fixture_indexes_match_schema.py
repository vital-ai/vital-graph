"""Every benchmarked space must carry the indexes the schema actually creates.

Why this exists: `sp_lead_synth_10k` carried a hand-made
`idx_*_quad_ctx_pred_subj` that the schema never created, and had no
`idx_*_quad_ctx_pred` at all. Nothing noticed, because nothing compared a
fixture's indexes against the schema.

The consequences were not subtle. The `issues/040` O(page) gate
(`test_growth_ratio_equality`) passed on that fixture and failed on the same
data with schema-created indexes — 7.4x against 12.6x growth. So the headline
claim of `issues/040` was being certified against a configuration no deployed
space has. And the 10k-vs-100k growth comparison, the whole point of having two
scales, was run against different index sets.

A benchmark measures a configuration. If that configuration is not the one the
schema produces, the number is about nothing.

It compares *every* index the schema creates, across every table the schema
targets — quad and term alike. An earlier revision compared two names on the
quad table, which let `sp_lead_synth_100k` sit six indexes short (including
`term_num`, the one the numeric push-down exists to use) while this test passed
and a full comparator sweep reported timings from the degraded fixture.

Per index it checks the *key columns and their order*, which is what determines
whether an index can supply a scan order, and ignores storage parameters and
`IF NOT EXISTS`. It also flags extra `quad_ctx_pred*` indexes, since a
near-duplicate under a different name is how the original divergence hid.
"""

from __future__ import annotations

import re

import pytest

from .conftest import skip_no_pg
from .lead_fixtures import ALL, DUP

# loop_scope="session" to match the session-scoped perf_conn fixture — without
# it asyncpg's connection belongs to a different event loop than the test.
pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# Spaces the perf suite draws conclusions from. wordnet_frames carries the
# fastpath, covering-index and edge-traversal benches; the lead fixtures carry
# the KGQuery ones.
BENCHED_SPACES = sorted({fx.space for fx in ALL} | {DUP.space, "wordnet_frames"})

_CREATE_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>\w+)\s+ON\s+(?P<table>\S+?)\s*(?:USING\s+(?P<method>\w+)\s*)?"
    r"\((?P<cols>[^)]*)\)",
    re.IGNORECASE)


def _key_columns(defn: str):
    """Key columns of an index definition, in order. None if unparseable.

    Everything after INCLUDE is payload, not key — and the difference is the
    whole point here, since only key columns supply an ordering.
    """
    m = _CREATE_RE.search(defn.split("INCLUDE")[0])
    if not m:
        return None
    return tuple(c.strip().lower() for c in m.group("cols").split(","))


@pytest.mark.parametrize("space", BENCHED_SPACES)
async def test_benched_space_indexes_match_schema(perf_conn, space):
    """EVERY index `create_space_indexes_sql` builds is present, on every table.

    This used to compare two names on the quad table only. That was too narrow
    by exactly the amount that mattered: `sp_lead_synth_100k` was missing SIX
    indexes — `quad_sp`, `quad_subj`, `term_num`, `term_trgm`, `term_tt`,
    `term_type` — and this test passed against it while a full comparator sweep
    ran on the degraded fixture and produced numbers that were reported as
    results.

    The term table is where it hurt most. Without `term_tt`, resolving one
    predicate URI inside an EXISTS body seq-scanned 3.5M rows at 245 ms a time,
    which made a single probe cost 2.3 s; with it, 435 ms. Without `term_num`
    the numeric push-down has no index to push *to*, which is the entire
    mechanism `issues/040` certifies. A test that checks the quad table and
    stops cannot see any of that.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    exists = await perf_conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        f"{space}_rdf_quad")
    if not exists:
        pytest.skip(f"space {space} not present in this environment")

    # Every index the schema builds, keyed by name, carrying its target table.
    expected = {}
    for stmt in SparqlSQLSchema().create_space_indexes_sql(space):
        m = _CREATE_RE.search(stmt)
        if m:
            expected[m.group("name")] = (m.group("table"), _key_columns(stmt))

    assert expected, "schema produced no indexes to compare against"

    tables = sorted({t for t, _cols in expected.values()})
    actual = {r["indexname"]: r["indexdef"] for r in await perf_conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE schemaname='public' AND tablename = ANY($1::text[])", tables)}

    # A table the schema indexes but this space does not have is a different
    # kind of problem (an incomplete space), and reporting it as N missing
    # indexes would bury that. Skip those and say so.
    present_tables = {r["tablename"] for r in await perf_conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename = ANY($1::text[])", tables)}
    absent_tables = sorted(set(tables) - present_tables)

    # Column inventory, so a missing index can be told apart from an index that
    # CANNOT exist because the table predates the column it indexes. Those are
    # different problems: the first is repairable by creating the index, the
    # second means the table itself is an older schema version and no amount of
    # index creation will fix it.
    cols: dict = {}
    for r in await perf_conn.fetch(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name = ANY($1::text[])",
            tables):
        cols.setdefault(r["table_name"], set()).add(r["column_name"])

    mismatched, drifted = [], []
    for name, (table, want) in sorted(expected.items()):
        if table not in present_tables:
            continue
        if name not in actual:
            absent_cols = [c for c in (want or ())
                           if c and c not in cols.get(table, set())]
            if absent_cols:
                drifted.append(f"{table}: no column(s) {absent_cols} — the "
                               f"table is an older schema version, so "
                               f"{name} cannot be created")
            else:
                mismatched.append(
                    f"{name} on {table}: MISSING (schema creates it)")
        elif _key_columns(actual[name]) != want:
            mismatched.append(
                f"{name}: key columns {_key_columns(actual[name])} "
                f"but schema builds {want}")
    mismatched.extend(drifted)

    if absent_tables:
        mismatched.append(
            f"tables the schema indexes but this space lacks: {absent_tables}")

    # A near-duplicate under another name is how the original divergence hid:
    # the fixture had the right columns, under the wrong name, so every
    # by-name check passed while the schema index was absent entirely.
    strays = [n for n in actual
              if n.startswith(f"idx_{space}_quad_ctx_pred")
              and n != f"idx_{space}_quad_ctx_pred"]
    if strays:
        mismatched.append(f"non-schema index(es) present: {sorted(strays)}")

    assert not mismatched, (
        f"{space} indexes diverge from the schema, so benchmarks against it "
        f"describe a configuration no deployed space has:\n  "
        + "\n  ".join(mismatched)
        + f"\n\nRecreate them from the schema, which is the definition this "
          f"compares against:\n"
          f"    python scripts/ensure_space_indexes.py --space {space}")
