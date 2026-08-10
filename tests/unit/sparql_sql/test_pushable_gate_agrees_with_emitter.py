"""The semi-join gate and the filter emitter must accept the SAME expressions.

`semijoin` drops a variable from `needed` on the promise that `filter_pushdown`
will consume its FILTER. The two failure directions look nothing alike:

  gate accepts, emitter declines -> variable gone, value compiles to NULL.
      Loud: UnresolvedVariableError (issues/023, 027).
  gate declines, emitter accepts -> filter IS pushed, answer CORRECT, and the
      plan silently reverts to a blocking sort. Cost becomes O(match set),
      which then correlates with the data and reads as a data-shape problem.

The second is the dangerous one. It is how the datetime range cells spent
several rounds of analysis filed as "near-total match sets; nothing to be done"
when the gate simply tested `_numeric_literal` while the emitter had been
widened to accept datetimes:

    gte/DateTime   TIMED OUT ->     36 ms
    gt/DateTime    TIMED OUT ->     70 ms
    lte/DateTime    12,183 ms ->    86 ms

Fourth instance of the same drift (issues/054, 058, the contains fold, this).
These tests assert AGREEMENT rather than any particular answer, so they keep
holding if the set of pushable expressions is widened or narrowed later.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, LiteralNode,
)
from vitalgraph.db.sparql_sql import filter_pushdown as fp
from vitalgraph.db.sparql_sql.semijoin import _pushable_range_var

XSD = "http://www.w3.org/2001/XMLSchema#"


def _lit(value, dt=None):
    return ExprValue(node=LiteralNode(value=value, datatype=dt))


def _cmp(op, left, right):
    return ExprFunction(name=op, args=[left, right])


V = ExprVar(var="val")

RANGE_OPS = ["lt", "le", "gt", "ge",
             "lessthan", "greaterthan", "lessthanorequal", "greaterthanorequal"]

OPERANDS = [
    ("integer", _lit("5", XSD + "integer")),
    ("double", _lit("5.0", XSD + "double")),
    ("decimal", _lit("5.0", XSD + "decimal")),
    ("plain number", _lit("5")),
    ("dateTime", _lit("2024-01-01T00:00:00Z", XSD + "dateTime")),
    ("date", _lit("2024-01-01", XSD + "date")),
    ("non-numeric string", _lit("hello")),
]


class TestRangeGateMatchesEmitter:

    @pytest.mark.parametrize("op", RANGE_OPS)
    @pytest.mark.parametrize("label,operand", OPERANDS, ids=[o[0] for o in OPERANDS])
    def test_gate_and_emitter_agree_var_on_left(self, op, label, operand):
        expr = _cmp(op, V, operand)
        assert _pushable_range_var(expr) == fp._numeric_var(expr), (
            f"gate and emitter disagree on ?v {op} {label}"
        )

    @pytest.mark.parametrize("op", RANGE_OPS)
    @pytest.mark.parametrize("label,operand", OPERANDS, ids=[o[0] for o in OPERANDS])
    def test_gate_and_emitter_agree_var_on_right(self, op, label, operand):
        expr = _cmp(op, operand, V)
        assert _pushable_range_var(expr) == fp._numeric_var(expr), (
            f"gate and emitter disagree on {label} {op} ?v"
        )

    def test_datetime_ranges_are_pushable_at_both_ends(self):
        """The specific regression: this returned None from the gate.

        Pinning the VALUE as well as the agreement, because agreement alone is
        also satisfied by both ends declining — which would silently return
        these cells to a blocking sort.
        """
        for op in ("lt", "le", "gt", "ge"):
            expr = _cmp(op, V, _lit("2024-01-01T00:00:00Z", XSD + "dateTime"))
            assert _pushable_range_var(expr) == "val", (
                f"?v {op} <dateTime> must be pushable — see issues/053"
            )

    def test_non_comparable_operand_is_pushable_at_neither_end(self):
        expr = _cmp("lt", V, _lit("hello"))
        assert _pushable_range_var(expr) is None
        assert fp._numeric_var(expr) is None
