"""`semijoin.needed_texts` — measuring how selective a text criterion is.

`issues/070`. A text match binds no constant object, so `needed_pairs` sees
nothing for it and the leaf reads as UNMEASURED. Unmeasured means "keep the
current plan", and the current plan probes the text once per candidate — so a
substring matching nothing was discovered one entity at a time, walking the
whole space. Measured on `sp_lead_synth_100k`: `contains 'ZZQQXX'` went from
>120s to 1ms once the count existed.

The condition string these produce is what the count runs against, so it has to
be built exactly as `filter_pushdown` builds the predicate the query will use.
Estimating one predicate and running another is the failure mode these tests
exist to prevent.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, LiteralNode,
)
from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot, KIND_BGP, KIND_FILTER,
)
from vitalgraph.db.sparql_sql.semijoin import needed_texts


SPACE = "test_space"
PRED_TEXT = "http://example.org/name"


class _Aliases:
    """Minimal stand-in for the two maps `_term_uuid` reads.

    `constants[(text, type)]` gives a column name and
    `resolved_constants[col]` gives the uuid — the structural lookup that
    replaced regex-parsing the emitted SQL.
    """

    def __init__(self):
        self.constants = {(PRED_TEXT, "U"): "c0"}
        self.resolved_constants = {"c0": "pred-uuid-1"}
        self.quad_stats = {}


def _fn(name: str, var: str, literal: str, ci: bool = False) -> ExprFunction:
    v = ExprVar(var=var)
    lit = ExprValue(node=LiteralNode(value=literal))
    if ci:
        v = ExprFunction(name="lcase", args=[v])
        lit = ExprFunction(name="lcase", args=[lit])
    return ExprFunction(name=name, args=[v, lit])


def _plan(*exprs) -> PlanV2:
    bgp = PlanV2(
        kind=KIND_BGP,
        tables=[TableRef(ref_id="q0", kind="quad",
                         table_name=f"{SPACE}_rdf_quad", alias="q0")],
        var_slots={"x": VarSlot(name="x", positions=[("q0", "object_uuid")])},
        leaf_terms={("q0", "predicate_uuid"): (PRED_TEXT, "U")},
    )
    return PlanV2(kind=KIND_FILTER, children=[bgp], filter_exprs=list(exprs))


def _conds(out):
    return sorted(cond for _pred, cond in out)


class TestPatternShape:
    """The SQL must match what `filter_pushdown` emits, anchors included."""

    def test_contains_is_wrapped_both_sides(self):
        out = needed_texts(_plan(_fn("contains", "x", "CAT")), _Aliases())
        assert _conds(out) == ["term_text LIKE '%CAT%'"]

    def test_strstarts_anchors_left(self):
        out = needed_texts(_plan(_fn("strstarts", "x", "CA")), _Aliases())
        assert _conds(out) == ["term_text LIKE 'CA%'"]

    def test_strends_anchors_right(self):
        out = needed_texts(_plan(_fn("strends", "x", "CA")), _Aliases())
        assert _conds(out) == ["term_text LIKE '%CA'"]

    def test_case_folded_operands_produce_ilike(self):
        """KGQuery emits CONTAINS(LCASE(?v), LCASE("x")) — the common shape."""
        out = needed_texts(_plan(_fn("contains", "x", "cat", ci=True)), _Aliases())
        assert _conds(out) == ["term_text ILIKE '%cat%'"]

    @pytest.mark.parametrize("needle", ["X", "XQ"])
    def test_a_short_needle_is_kept_away_from_the_trigram_index(self, needle):
        """Under 3 characters there is no usable trigram for an INFIX match.

        show_trgm('XQ') is {"  x"," xq","xq "} — every one of them PADDED, and
        padding only holds at a word boundary. An infix match may land mid-word,
        so none can be required, and the GIN index degenerates into scanning
        itself: 10,467,626 index rows and 12,613ms to find nothing on a 10.4M-row
        term table. Concatenating '' keeps the answer and takes the index out of
        the picture. Measured end to end: 11,151ms -> 210ms.

        The estimate must use the SAME form as the query, or this probe pays
        that 12.6s itself.
        """
        out = needed_texts(_plan(_fn("contains", "x", needle)), _Aliases())
        assert _conds(out) == [f"(term_text || '') LIKE '%{needle}%'"]

    @pytest.mark.parametrize("op,expected", [
        ("strstarts", "term_text LIKE 'XQ%'"),
        ("strends",   "term_text LIKE '%XQ'"),
    ])
    def test_anchored_patterns_keep_the_index_at_any_length(self, op, expected):
        """Anchored matches keep the padding, so the trigram stays usable.

        Measured on a 2-character needle: 'XQ%' 1.0ms, '%XQ' 0.03ms, against
        12,613ms for the infix form. Applying the short-needle rule to these
        would throw away a working index scan.
        """
        out = needed_texts(_plan(_fn(op, "x", "XQ")), _Aliases())
        assert _conds(out) == [expected]

    def test_the_predicate_is_carried(self):
        """The count is over (predicate, matching terms), not terms alone."""
        out = needed_texts(_plan(_fn("contains", "x", "CA")), _Aliases())
        assert [p for p, _ in out] == ["pred-uuid-1"]


class TestWhatIsDeliberatelyExcluded:

    def test_regex_is_not_measured(self):
        """pg_trgm serves SOME regexes, and which depends on the pattern.

        A count that silently fell back to a sequential scan would cost more
        than the plan decision it informs, so regex stays unmeasured and the
        caller keeps the plan it already had.
        """
        expr = ExprFunction(name="regex", args=[
            ExprVar(var="x"), ExprValue(node=LiteralNode(value="^CA.*"))])
        assert needed_texts(_plan(expr), _Aliases()) == set()

    def test_a_metacharacter_in_the_needle_is_escaped(self):
        """CONTAINS(?x, "50%") must not become a wildcard.

        Over-matching here is a WRONG COUNT, which produces a wrong plan
        choice — and it would silently look like a very common substring.
        """
        out = needed_texts(_plan(_fn("contains", "x", "50%")), _Aliases())
        cond = _conds(out)[0]
        assert "50" in cond
        assert cond != "term_text LIKE '%50%%'", "the % was left as a wildcard"

    def test_no_text_filter_yields_nothing(self):
        expr = ExprFunction(name="eq", args=[
            ExprVar(var="x"), ExprValue(node=LiteralNode(value="CA"))])
        assert needed_texts(_plan(expr), _Aliases()) == set()
