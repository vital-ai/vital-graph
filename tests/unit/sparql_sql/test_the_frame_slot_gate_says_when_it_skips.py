"""The frame-slot collapse must say when it does not fire.

`issues/195`: an unfiltered depth-2 `entity -> frame -> entity` walk planned at
19,282,929,239,712 and never returned. The cause was DATA — the perf fixtures
had never been migrated to `frame_slot`, so the collapse could not fire.
Migrating them took the same plan to 47.77. It took a DAY to find, and the
decision record is why. In full, for the failing query:

    fired    = ['frame_type_absorbable']
    declined = {'slot_type_tautology': 'constraint excludes rows, or unknown'}

`frame_slot_rewrite` appears in NEITHER. Every precondition inside
`rewrite_frame_slot_table` records a decline — there are six — but the gate in
FRONT of it, `if _fs_ready:`, had a bare skip with no `else`. So a plan where
the collapse never ran read exactly like a plan where it ran and had nothing to
do. Had it logged `declined: frame_slot table absent`, that would have been a
one-line diagnosis (`issues/197` defect 3).

A SILENT DECLINE READS EXACTLY LIKE A SATISFIED CHECK. Fourth instance of that
shape here, after `issues/081` (a gate disabled by an absent value),
`issues/188` (a metric with no rule) and `issues/167` (an allow-list read as a
block-list).

These cells pin the CHAIN, in the three links it is made of, without a database
— because what is being pinned is the wiring, not the SQL:

    absent table  ->  ensure returns False  ->  the gate declines, visibly
"""

from __future__ import annotations

import ast
import inspect

import pytest

from vitalgraph.db.sparql_sql import declines, generator
from vitalgraph.db.sparql_sql import ensure_frame_slot_table as ensure_mod
from vitalgraph.db.sparql_sql.rewrite_frame_slot_table import FE

pytestmark = pytest.mark.unit


# --- link 1: an absent table answers False -------------------------------

@pytest.mark.asyncio
async def test_an_absent_table_is_not_ready(monkeypatch):
    """No table in `information_schema` means the collapse may not fire."""
    ensure_mod.reset_ready_cache()

    async def _no_such_table(sql, params=None, conn=None, conn_params=None):
        return []                      # the existence probe finds nothing

    monkeypatch.setattr("vitalgraph.db.sparql_sql.db_provider.execute_query",
                        _no_such_table)
    assert await ensure_mod.ensure_frame_slot_table("sp", conn=object()) is False


# --- link 2: the gate has an else, and it declines ------------------------

def _fs_ready_gate() -> ast.If:
    """The `if _fs_ready:` statement in the generator, as parsed source."""
    tree = ast.parse(inspect.getsource(generator))
    for node in ast.walk(tree):
        if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "_fs_ready"):
            return node
    pytest.fail("no `if _fs_ready:` gate in generator.py — if the gate moved, "
                "this test has to move with it rather than silently pass")


def test_the_gate_does_not_skip_in_silence():
    """Structural, because the failure mode IS the absence of a statement.

    A test that only asserted "the collapse did not fire" would have passed
    throughout `issues/195`. The thing that was missing was the saying-so, so
    that is what is asserted: the gate has an `else`, and the `else` declines.
    """
    gate = _fs_ready_gate()
    assert gate.orelse, (
        "`if _fs_ready:` has no else branch, so a query that skips the "
        "frame-slot collapse entirely produces no decision record for it — "
        "indistinguishable from one where the collapse had nothing to do. "
        "That cost issues/195 a day.")

    src = "\n".join(ast.unparse(s) for s in gate.orelse)
    assert "decline" in src, (
        f"the else branch exists but records nothing: {src!r}")
    assert "space_id" in src, (
        "the decline does not name the space, and 'absent for which space' is "
        f"the next question every time: {src!r}")


# --- link 3: that decline reaches the decision record ---------------------

def test_the_decline_lands_under_the_rules_own_name():
    """`frame_slot_rewrite` is the name a reader greps for.

    The gate declines through `FE`, the same rule object the six preconditions
    inside the rewrite use, so the skip appears in the record beside them
    rather than under a second name nobody would look for.
    """
    with declines.collecting() as log:
        FE.decline("frame_slot table absent or empty", space_id="sp")

    assert log, "the decline was swallowed"
    assert [e.rule for e in log.entries] == ["frame_slot_rewrite"]
    assert log.entries[0].facts == {"space_id": "sp"}
