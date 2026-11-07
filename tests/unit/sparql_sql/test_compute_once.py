"""`compute_once`: a `vg:` function's SQL runs once per row (`issues/333`).

The integration test (`tests/integration/test_vg_score_computed_once.py`)
checks the plan; this pins the helper's scope: `vg:` functions only, and
everything else passes through byte for byte.
"""

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprValue, ExprVar, LiteralNode,
)
from vitalgraph.db.sparql_sql.emit_extend import compute_once
from vitalgraph.db.sparql_sql.vg_functions import VG_HYBRID_SEARCH, VG_TEXT_SEARCH


def _vg(iri):
    return ExprFunction(name="", function_iri=iri, args=[
        ExprVar(var="s"), ExprValue(node=LiteralNode(value="樓梯")),
        ExprValue(node=LiteralNode(value="idx"))])


def test_a_vg_function_moves_into_a_lateral():
    join, ref = compute_once(_vg(VG_HYBRID_SEARCH), "(SELECT 1 FROM t LIMIT 1)", "x3")
    assert join == ("\nLEFT JOIN LATERAL (SELECT (SELECT 1 FROM t LIMIT 1) AS val "
                    "OFFSET 0) AS x3 ON true")
    assert ref == "x3.val"
    # OFFSET 0 is what stops PostgreSQL pulling it up and re-inlining it.
    assert "OFFSET 0" in join
    assert compute_once(_vg(VG_TEXT_SEARCH), "(SELECT 2)", "x4")[1] == "x4.val"


def test_anything_else_is_unchanged():
    other = ExprFunction(name="ucase", function_iri=None, args=[ExprVar(var="s")])
    assert compute_once(other, "UPPER(v0)", "x1") == ("", "UPPER(v0)")
    assert compute_once(ExprVar(var="s"), "v0", "x1") == ("", "v0")


def test_an_unsupported_vg_call_stays_null():
    assert compute_once(_vg(VG_HYBRID_SEARCH), "NULL", "x1") == ("", "NULL")
    assert compute_once(_vg(VG_HYBRID_SEARCH), "", "x1") == ("", "")
