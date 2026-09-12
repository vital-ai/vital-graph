"""Every derived table the query path PLANS AGAINST must be analyzed.

`issues/096`. `_maybe_analyze_aux_tables` exists because these tables are
populated by BULK LOAD, where autovacuum's insert tracking is unreliable — so a
table it omits may carry no statistics at all, indefinitely.

`entity_slot_sort` was omitted, and that is not theoretical: found 2026-09-11
with 3,877,000 rows and `last_analyze` NULL on one space, and 304,923 rows never
analyzed on another, where the planner then estimated `rows=1` for it. Plans
that join it were being chosen blind.

This is the SECOND defect in that one list — the first silently skipped all five
tables on every bulk write (see `TestNoCodeIndexesARetiredKey`). Both were
invisible at runtime: one logged as non-fatal, this one logged nothing at all,
because a missing ANALYZE has no error to report. Hence a static check.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

# The derived tables a query plan joins against, so their statistics decide the
# plan. NOT every table in the schema: `term` and `rdf_quad` are analyzed by
# autovacuum on ordinary write traffic, and the config/mapping tables are small
# enough that a bad estimate cannot produce a bad join order.
MUST_BE_ANALYZED = {"edge", "frame_slot", "entity_slot_sort"}


def _analyzed_keys():
    """The `t[...]` keys assigned to `tables` in `_maybe_analyze_aux_tables`.

    Read from the AST rather than by importing and calling, because the function
    is async, needs a live pool, and returns early at three separate guards
    before the list is ever used.
    """
    root = pathlib.Path(__file__).resolve().parents[3]
    src = root / "vitalgraph" / "kg_impl" / "kg_backend_utils.py"
    tree = ast.parse(src.read_text())
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name != "_maybe_analyze_aux_tables":
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            if not any(getattr(tgt, "id", None) == "tables" for tgt in node.targets):
                continue
            if not isinstance(node.value, ast.List):
                continue
            return {e.slice.value for e in node.value.elts
                    if isinstance(e, ast.Subscript)
                    and isinstance(e.slice, ast.Constant)}
    return None


def test_the_list_was_found():
    """Guards the guard: a rename would otherwise make every assertion vacuous."""
    assert _analyzed_keys(), (
        "could not read the `tables` list out of `_maybe_analyze_aux_tables` — "
        "this test silently passes nothing if that is not fixed")


@pytest.mark.parametrize("key", sorted(MUST_BE_ANALYZED))
def test_a_planned_against_table_is_analyzed(key):
    assert key in _analyzed_keys(), (
        f"{key!r} is joined by the query path but never ANALYZEd. These tables "
        f"are bulk-loaded, so autovacuum may never give them statistics and the "
        f"planner will estimate rows=1 — which is how a sorted page ends up in "
        f"a nested loop over the whole population.")


def test_every_analyzed_key_actually_exists():
    """A retired key here is a KeyError that skips the WHOLE list, not one
    table — the failure mode of `issues/183`."""
    live = set(SparqlSQLSchema.get_table_names("X"))
    assert _analyzed_keys() <= live, (
        f"analyzed but not a real table: {_analyzed_keys() - live}")
