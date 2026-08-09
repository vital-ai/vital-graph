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

This test is deliberately narrow: it checks the *key columns and their order*,
which is what determines whether an index can supply a scan order, and ignores
storage parameters and `IF NOT EXISTS`. It also flags extra `quad_ctx_pred*`
indexes, since a near-duplicate under a different name is how the original
divergence hid.
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
    r"(?P<name>\w+)\s+ON\s+\S+\s*(?:USING\s+(?P<method>\w+)\s*)?\((?P<cols>[^)]*)\)",
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
    """The space's quad indexes match what `create_space_indexes_sql` builds."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    exists = await perf_conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        f"{space}_rdf_quad")
    if not exists:
        pytest.skip(f"space {space} not present in this environment")

    actual = {r["indexname"]: r["indexdef"] for r in await perf_conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE schemaname='public' AND tablename = $1", f"{space}_rdf_quad")}

    expected = {}
    for stmt in SparqlSQLSchema().create_space_indexes_sql(space):
        m = _CREATE_RE.search(stmt)
        if m and m.group("name") in {f"idx_{space}_quad_ctx_pred",
                                     f"idx_{space}_quad_po"}:
            expected[m.group("name")] = _key_columns(stmt)

    assert expected, "schema produced no quad indexes to compare against"

    mismatched = []
    for name, want in expected.items():
        if name not in actual:
            mismatched.append(f"{name}: MISSING (schema creates it)")
        elif _key_columns(actual[name]) != want:
            mismatched.append(
                f"{name}: key columns {_key_columns(actual[name])} "
                f"but schema builds {want}")

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
        + f"\n\nRun: python scripts/migrate_quad_ctx_pred_index.py "
          f"--space {space} --create-missing")
