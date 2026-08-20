"""Driving from a criterion requires a criterion the driver can carry.

`issues/111`. `_try_selective_driven` pages from a selective criterion instead of
the entity anchor, and picks that criterion by `_leaf_rows`. But `_leaf_rows`
deliberately counts THREE things:

  * constant leaves the BGP itself binds, and
  * `range_stats` and `text_stats` — measurements of FILTERs that sit ABOVE the
    join, keyed by predicate precisely because the FILTER and the predicate it
    constrains live at different levels.

Counting all three is right for the semi-join gate, which decides whether to
PROBE a subtree. It is wrong for deciding whether to DRIVE from it, because
`emit_bgp_anchor` emits the BGP's constant leaves and NOT the filter. Driving on
a filter-derived count reproduces the row count without the predicate that
produced it.

The result is not a slow query, it is a wrong one. Measured on
`sp_lead_synth_100k`, `MQLRating >= 99` with a 60,000-row page:

    before   60,000 rows returned, 1,017 match   — `num_val` and `99` both
                                                   absent from the generated SQL
    after     1,017 rows returned, 1,017 match

THE GUARD EXISTED AND DID NOT COVER THIS. The unmeasured branch already says it:

    A text criterion is a pushed FILTER, so driving from its BGP drops the ILIKE
    entirely — measured: `contains 'ZZQQXX'` returned 25 rows for a substring
    matching nothing.

That guard fires when the count is MISSING. A numeric range has the same shape
and `range_stats` gives it a number, so it walked through the guard written for
it. `_emit_two_phase`, which learned this earlier, pushes the filters and refuses
if any survive; `_try_selective_driven` was added afterwards and inherited
neither.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot, AliasGenerator, KIND_BGP,
)
from vitalgraph.db.sparql_sql.semijoin import _leaf_rows

SPACE = "test_space"
PRED = "11111111-1111-5111-8111-111111111111"


def _bgp_with_predicate():
    """A BGP binding one constant predicate leaf — the shape both stats key on."""
    b = PlanV2(kind=KIND_BGP,
               tables=[TableRef(ref_id="q0", kind="quad",
                                table_name=f"{SPACE}_rdf_quad", alias="q0")],
               var_slots={"v": VarSlot(name="v",
                                       positions=[("q0", "object_uuid")])})
    b.leaf_terms[("q0", "predicate_uuid")] = ("http://ex/mql", "U")
    return b


class _Aliases(AliasGenerator):
    def __init__(self, *, quad=None, rng=None, txt=None):
        super().__init__()
        self.quad_stats = quad if quad is not None else {(PRED, "x"): 50_000}
        self.range_stats = rng or {}
        self.text_stats = txt or {}
        self.constants = {("http://ex/mql", "U"): "c0"}
        self.resolved_constants = {"c0": PRED}


class TestFilterDerivedCountsAreSeparable:

    def test_a_range_is_counted_by_default(self):
        """The semi-join gate needs this: it decides whether to PROBE, and a
        filter above the join is exactly what makes probing worth it."""
        a = _Aliases(rng={(PRED, ">=", 99): 990})
        assert _leaf_rows(_bgp_with_predicate(), a) == 990

    def test_a_range_is_excluded_when_asked(self):
        a = _Aliases(rng={(PRED, ">=", 99): 990})
        assert _leaf_rows(_bgp_with_predicate(), a, filter_derived=False) != 990

    def test_a_text_match_is_counted_by_default(self):
        a = _Aliases(txt={(PRED, "term_text LIKE '%zz%'"): 3})
        assert _leaf_rows(_bgp_with_predicate(), a) == 3

    def test_a_text_match_is_excluded_when_asked(self):
        """Same shape as the range, and the reason the guard was written."""
        a = _Aliases(txt={(PRED, "term_text LIKE '%zz%'"): 3})
        assert _leaf_rows(_bgp_with_predicate(), a, filter_derived=False) != 3

    def test_constant_leaves_survive_both_ways(self):
        """A constant criterion binds object_uuid INSIDE the BGP, so the driver
        does carry it. That case must keep working — it is what the whole
        optimisation was built for (WV: 5,585 ms -> 159 ms).

        It needs a (predicate, object) PAIR: `_leaf_rows` looks up `quad_stats`
        by both columns of the same alias, which is exactly what makes a constant
        criterion carryable and a filter not."""
        OBJ = "22222222-2222-5222-8222-222222222222"
        bgp = _bgp_with_predicate()
        bgp.leaf_terms[("q0", "object_uuid")] = ("urn:state:WV", "U")
        a = _Aliases(quad={(PRED, OBJ): 848})
        a.constants[("urn:state:WV", "U")] = "c1"
        a.resolved_constants["c1"] = OBJ
        assert _leaf_rows(bgp, a, filter_derived=False) == 848

    def test_default_is_unchanged_for_every_existing_caller(self):
        import inspect
        sig = inspect.signature(_leaf_rows)
        assert sig.parameters["filter_derived"].default is True, (
            "the semi-join gate calls this positionally and must keep counting "
            "filters; only the DRIVING decision opts out")


class TestTheDrivingSiteOptsOut:

    def test_selective_driven_measures_the_driver_without_filters(self):
        import inspect
        from vitalgraph.db.sparql_sql import emit_slice
        src = inspect.getsource(emit_slice._try_selective_driven)
        driver = [l for l in src.splitlines() if "driver_n = _leaf_rows" in l]
        assert driver, "_try_selective_driven no longer measures the driver here"
        assert "filter_derived=False" in driver[0], (
            "driving on a filter-derived count returns rows that do not satisfy "
            "the criterion")

    def test_the_anchor_still_counts_everything(self):
        """Only the DRIVER side is restricted. The anchor is probed, not driven,
        so filter-derived selectivity is legitimate there."""
        import inspect
        from vitalgraph.db.sparql_sql import emit_slice
        src = inspect.getsource(emit_slice._try_selective_driven)
        anchor = [l for l in src.splitlines() if "anchor_n = _leaf_rows" in l]
        assert anchor and "filter_derived=False" not in anchor[0]
