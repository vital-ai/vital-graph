"""Seeding a space's missing datatypes must not renumber the ones it has.

`issues/126` left three PRODUCTION spaces holding positions 1..38 of a 40-entry
`STANDARD_DATATYPES`. Every id they hold is correct, so the checker called them
OK and the repair script skipped them — a space that is CORRECT BUT INCOMPLETE
was invisible to both tools.

It is not harmless. Nothing seeds a space after creation: the only seeding runs
inside `create_space_tables`, `migrate_space_schema.py` excludes the datatype
table by name as "primary data", and the three write paths
(`data_import_impl.py:85`, `emit_update.py:92`, `kg_server_properties.py:316`)
all append an unknown datatype with the NEXT SERIAL ID. So whichever missing
entry is stored first takes the lowest free id, and lands at its canonical
position only by luck of arrival order. For these three that is
`wktLiteral`/`geoLocation` at 39/40, which transpose if `geoLocation` arrives
first.

The top-up is therefore INSERT-only, and these cells pin that, because the
alternative is not theoretical. `plan_repair` renumbers non-standard URIs to sit
immediately after the standard block — correct when rewriting a table, wrong
here. On the test stack `dawg_test` carries seven non-standard datatypes at
11302-11308, and `plan_repair` proposed relocating them to 41-47; as an
INSERT-only top-up that would have re-inserted all seven as duplicates. Caught
by running it against a reproduction of the production shape rather than
against production.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name):
    sys.path.insert(0, os.path.join(_ROOT, "scripts"))
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_ROOT, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECK = _load("check_space_datatypes")
REPAIR = _load("repair_space_datatypes")


def _standard():
    from vitalgraph.db.sparql_sql.sparql_sql_schema import STANDARD_DATATYPES
    return [(i, uri) for i, (uri, _n) in enumerate(STANDARD_DATATYPES, start=1)]


class FakeConn:
    def __init__(self, rows, exposed=True):
        self.rows = rows
        self.exposed = exposed

    async def fetch(self, sql, *args):
        return [{"datatype_id": i, "datatype_uri": u} for i, u in self.rows]

    async def fetchval(self, sql, *args):
        return self.exposed


# --- the checker must see incompleteness at all ---------------------------

@pytest.mark.asyncio
async def test_a_truncated_tail_is_reported_not_called_ok():
    """The production shape: 1..38 correct, 39 and 40 never seeded."""
    status, detail = await CHECK.check_space(FakeConn(_standard()[:38]), "sp")
    assert status == CHECK.INCOMPLETE, (
        f"a space missing the tail of STANDARD_DATATYPES was reported "
        f"{status!r}; every id it holds is correct, which is exactly why this "
        f"passed as OK and stayed invisible: {detail}")
    assert "39, 40" in detail or "[39, 40]" in detail, detail


@pytest.mark.asyncio
async def test_a_gap_is_distinguished_from_a_tail():
    """A hole INSIDE the range is worse — an append lands in standard space."""
    rows = [(i, u) for i, u in _standard() if i != 12]
    status, detail = await CHECK.check_space(FakeConn(rows), "sp")
    assert status == CHECK.INCOMPLETE
    assert "GAP" in detail, (
        f"a missing id inside the standard range reads the same as a missing "
        f"tail, and they are not the same risk: {detail}")


@pytest.mark.asyncio
async def test_incompleteness_is_reported_even_without_the_generated_columns():
    """The `off-inert` downgrade is about WRONGNESS, which only matters if
    something reads the ids. Incompleteness is about the table and its
    SEQUENCE: the next append takes the lowest free id whether or not
    `num_val` exists, so the hazard does not depend on exposure."""
    status, _d = await CHECK.check_space(
        FakeConn(_standard()[:38], exposed=False), "sp")
    assert status == CHECK.INCOMPLETE


# --- the top-up must add only what is missing -----------------------------

@pytest.mark.asyncio
async def test_the_topup_adds_only_the_missing_standard_rows():
    add, seq_to = await REPAIR.plan_topup(FakeConn(_standard()[:38]), "sp")
    assert [i for i, _u in add] == [39, 40]
    assert seq_to == 40


@pytest.mark.asyncio
async def test_non_standard_rows_are_not_renumbered():
    """`dawg_test`'s shape. `plan_repair` would move these; `plan_topup` may not."""
    rows = _standard()[:38] + [(11302 + k, f"http://example.org/x{k}")
                               for k in range(7)]
    add, seq_to = await REPAIR.plan_topup(FakeConn(rows), "sp")

    assert [i for i, _u in add] == [39, 40], (
        f"the top-up is touching more than the two missing standard rows: {add}")
    added_uris = {u for _i, u in add}
    assert not any(u.startswith("http://example.org/x") for u in added_uris), (
        f"a non-standard uri is being re-inserted, which duplicates a row that "
        f"is already there: {add}")
    assert seq_to == 11308, (
        f"the sequence was set to {seq_to}, which is at or below an existing "
        f"id — the next append would collide with a row already present")


@pytest.mark.asyncio
async def test_an_occupied_standard_position_is_refused():
    """If something else holds a missing position, seeding needs a REMAP.

    That is `plan_repair`'s job, with `plan_repair`'s safeguards. Guessing here
    would write a row on top of a live id.
    """
    rows = _standard()[:38] + [(39, "http://example.org/squatter")]
    with pytest.raises(RuntimeError, match="remap rather than a top-up"):
        await REPAIR.plan_topup(FakeConn(rows), "sp")


@pytest.mark.asyncio
async def test_a_complete_space_needs_nothing():
    add, _seq = await REPAIR.plan_topup(FakeConn(_standard()), "sp")
    assert add == []
