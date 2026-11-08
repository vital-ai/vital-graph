"""Rarity-weighted `cjk` scoring: weights and the score expression (`issues/333` D2).

The ranking itself is measured on DRCD (`test_scripts/perf/issue333_drcd_eval.py`)
and checked on real rows in `tests/integration/test_cjk_rarity_ranking.py`; this
pins the pieces that turn statistics into SQL.
"""

import math

import pytest

from vitalgraph.db.sparql_sql.fts_languages import (
    CJK_TSV_STATISTICS, tsv_statistics_sql,
)
from vitalgraph.db.sparql_sql.fts_rarity import (
    _lexeme, cjk_weighted_coverage_sql, weights_from_rows,
)


def _row(term, freq, floor=0.001):
    return {"term": term, "freq": freq, "floor": floor}


class TestWeights:
    def test_a_rarer_pair_weighs_more(self):
        w = dict(weights_from_rows([_row("樓梯", 0.001), _row("那個", 0.3)]))
        assert w["樓梯"] == pytest.approx(math.log(1 / 0.001))
        assert w["那個"] == pytest.approx(math.log(1 / 0.3))
        assert w["樓梯"] > w["那個"]

    def test_a_pair_below_the_tracked_list_gets_the_floor(self):
        [(term, w)] = weights_from_rows([_row("樓梯", None, floor=0.0006)])
        assert w == pytest.approx(math.log(1 / 0.0006))

    def test_no_statistics_means_no_weights(self):
        """Then the arm keeps ts_rank_cd: no ANALYZE yet is not an error."""
        assert weights_from_rows([_row("樓梯", None, floor=None)]) is None
        assert weights_from_rows([]) is None

    def test_a_pair_in_every_row_still_divides(self):
        [(_t, w)] = weights_from_rows([_row("的人", 1.0)])
        assert w > 0

    def test_a_term_outside_the_cjk_class_is_dropped(self):
        assert weights_from_rows([_row("x'y", 0.1)]) is None
        assert [t for t, _w in weights_from_rows([_row("夢", 0.1), _row("a b", 0.1)])] == ["夢"]


class TestTheScore:
    def test_coverage_is_the_weighted_fraction(self):
        sql = cjk_weighted_coverage_sql("f.tsv", [("樓梯", 3.0), ("那個", 1.0)])
        assert sql == ("(((CASE WHEN f.tsv @@ '樓梯'::tsquery THEN 3.000000 ELSE 0 END) + "
                       "(CASE WHEN f.tsv @@ '那個'::tsquery THEN 1.000000 ELSE 0 END)) / 4.000000)")

    def test_only_cjk_terms_reach_sql(self):
        with pytest.raises(ValueError):
            _lexeme("'); DROP TABLE x; --")
        assert _lexeme("夢") == "'夢'::tsquery"


class TestStatisticsTarget:
    def test_raised_for_cjk_and_reset_without_it(self):
        assert tsv_statistics_sql("t", ["english", "cjk"]) == (
            f"ALTER TABLE t ALTER COLUMN tsv SET STATISTICS {CJK_TSV_STATISTICS}")
        assert tsv_statistics_sql("t", ["english"]) == (
            "ALTER TABLE t ALTER COLUMN tsv SET STATISTICS -1")
