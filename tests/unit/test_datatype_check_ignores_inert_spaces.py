"""A datatype-id sweep must not fail on a space that cannot act on the ids.

`issues/126`: four helpers derived `datatype_id` values positionally from
`STANDARD_DATATYPES`, and three spaces never seeded those rows.
`check_space_datatypes.py` finds them and exits 1 so it can gate a pipeline.

Measured 2026-09-18 while repairing those three: the sweep also reports six
`vitalgraph2__` spaces on the host `vitalgraphdb`, 29 differing ids each, one
carrying 3.4M terms. All six are a LEGACY schema — partitioned term tables with
NO `num_val`/`dt_val` generated columns. Those columns are the only thing left
that reads a datatype id positionally; the query side resolves per space through
`ctx.dt_ids_for_uris` (category A, resolved 2026-08-23). So in those spaces the
ids are wrong and nothing whatsoever acts on them, and repairing would have
remapped millions of rows to correct a value no code reads.

Two failure modes, and the check has to avoid both:

  * exit 1 where there is no defect — a gate that cries wolf is a gate somebody
    turns off, and then it is not there for the space that IS broken.
  * skipping a space that IS exposed, which is the original bug wearing a
    different hat.

So exposure is measured per space from `pg_attribute.attgenerated`, not assumed
from the schema version or the space name.

A fake connection rather than a database, because what is pinned is the
DECISION — off-and-inert versus off-and-exposed — not any SQL.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _checker():
    """Load `scripts/check_space_datatypes.py`, which is not an importable pkg."""
    path = os.path.join(_ROOT, "scripts", "check_space_datatypes.py")
    sys.path.insert(0, os.path.join(_ROOT, "scripts"))
    spec = importlib.util.spec_from_file_location("check_space_datatypes", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _checker()


class FakeConn:
    """`rows` is the datatype table; `exposed` drives the generated-column probe."""

    def __init__(self, rows, exposed: bool):
        self.rows = rows
        self.exposed = exposed

    async def fetch(self, sql, *args):
        return [{"datatype_id": i, "datatype_uri": u} for i, u in self.rows]

    async def fetchval(self, sql, *args):
        assert "attgenerated" in sql, sql
        return self.exposed


def _standard():
    from vitalgraph.db.sparql_sql.sparql_sql_schema import STANDARD_DATATYPES
    return [(i, uri) for i, (uri, _n) in enumerate(STANDARD_DATATYPES, start=1)]


@pytest.mark.asyncio
async def test_correct_ids_are_ok_either_way():
    for exposed in (True, False):
        status, _d = await M.check_space(FakeConn(_standard(), exposed), "sp")
        assert status == M.OK


@pytest.mark.asyncio
async def test_shifted_ids_fail_when_the_space_can_act_on_them():
    """The defect the sweep exists for: ids shifted AND generated columns."""
    shifted = [(i + 5, uri) for i, uri in _standard()]
    status, detail = await M.check_space(FakeConn(shifted, exposed=True), "sp")
    assert status == M.WRONG_ID, detail


@pytest.mark.asyncio
async def test_shifted_ids_are_inert_without_the_generated_columns():
    """Same table, no `num_val`/`dt_val`: reported, not counted as a failure."""
    shifted = [(i + 5, uri) for i, uri in _standard()]
    status, detail = await M.check_space(FakeConn(shifted, exposed=False), "sp")
    assert status == M.NOT_EXPOSED, detail
    assert "no generated columns" in detail, (
        f"the line does not say WHY it was downgraded, so a reader cannot tell "
        f"an inert space from one the sweep forgot: {detail!r}")


@pytest.mark.asyncio
async def test_an_unseeded_table_is_inert_without_the_generated_columns():
    """The empty case downgrades too — it reaches a different return."""
    assert (await M.check_space(FakeConn([], exposed=True), "sp"))[0] == M.EMPTY
    assert (await M.check_space(FakeConn([], exposed=False), "sp"))[0] == M.NOT_EXPOSED


@pytest.mark.asyncio
async def test_a_space_missing_xsd_string_is_inert_without_them_too():
    """`sp_geo_test`'s shape: id 1 is geoLocation. Exposed, it is the real bug."""
    geo = [(1, "http://vital.ai/ontology/vital-core#geoLocation"),
           (2, "http://www.opengis.net/ont/geosparql#wktLiteral")]
    assert (await M.check_space(FakeConn(geo, True), "sp"))[0] == M.MISSING_STRING
    assert (await M.check_space(FakeConn(geo, False), "sp"))[0] == M.NOT_EXPOSED


def test_inert_is_not_counted_as_a_failure():
    """Structural: `NOT_EXPOSED` must not reach the `bad` list that sets exit 1.

    Asserted on the source because the alternative is standing up two whole
    clusters, and the thing at risk is one branch.
    """
    import inspect
    src = inspect.getsource(M.main)
    assert "NOT_EXPOSED" in src, (
        "main() does not mention NOT_EXPOSED, so an inert space is being "
        "counted as off and the sweep exits 1 where nothing is wrong")
    before, after = src.split("NOT_EXPOSED", 1)
    assert "bad.append" not in after.split("elif")[0], (
        "the NOT_EXPOSED branch appends to `bad`, which is what sets exit 1")
