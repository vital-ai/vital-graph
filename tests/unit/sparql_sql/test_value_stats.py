"""Range selectivity from an equi-depth histogram.

`rdf_stats` is a frequent-value list capped per predicate, so it answers
equality over a small value set exactly and a range over a large one not at all
— `occurred >= 2024-07-01` estimated 244 rows where the answer was 53,455
(`issues/090`). These histograms exist to answer the range case.

The estimate feeds a DECISION the generator makes — is this criterion selective
enough to be worth materialising the hop — so these tests are written against
that use. Exactness in the extreme tail is not the requirement and is not
achievable from bucket boundaries; not crossing the decision boundary is.

No database: `estimate_range` is a pure function over loaded boundaries.
"""

from __future__ import annotations

import datetime

import pytest

from vitalgraph.db.sparql_sql.sync_value_stats import (
    estimate_range, NUM, DT)

pytestmark = pytest.mark.unit

P = "11111111-1111-1111-1111-111111111111"

# A uniform 0..100 predicate over 1,000 rows, 10 buckets: boundaries every 10.
UNIFORM = {(P, NUM): {"bounds": [float(i * 10) for i in range(11)],
                      "total": 1000}}


class TestUniform:
    """Where the data is uniform the arithmetic should be near-exact, so an
    error here is a bug in the estimator rather than in the model."""

    @pytest.mark.parametrize("value,expected", [
        (0, 1000), (10, 900), (50, 500), (90, 100),
    ])
    def test_gte(self, value, expected):
        got = estimate_range(UNIFORM, P, NUM, ">=", value)
        assert abs(got - expected) <= max(1, expected * 0.05), (
            f">= {value}: got {got}, expected about {expected}")

    def test_lte_is_the_complement(self):
        assert estimate_range(UNIFORM, P, NUM, "<=", 50) == pytest.approx(500, abs=25)

    def test_interpolates_inside_a_bucket(self):
        """The point of storing boundaries. Counting whole buckets put
        `score >= 90` at 1 row where the answer was 1,547."""
        assert estimate_range(UNIFORM, P, NUM, ">=", 55) == pytest.approx(450, abs=25)

    def test_below_the_minimum_is_everything(self):
        assert estimate_range(UNIFORM, P, NUM, ">=", -5) == 1000

    def test_at_or_above_the_maximum_is_UNKNOWN(self):
        """Not zero, and no longer a fabricated 1 either.

        A threshold at or past the top boundary selects the mass sitting AT the
        maximum, and a quantile histogram does not record how big that mass is.
        The old code answered `max(1, 0)` — measured on graph_synth_100k, where
        `hasScore` runs 0..99 with 6,032 rows at exactly 99, that estimated ONE
        row for six thousand. A 6,000x underestimate, in the direction that
        makes a criterion look perfectly selective and get applied last.

        Continuous data hides it: ties at the maximum are negligible there, so
        this only bites on discrete values, which is most integer criteria.

        None sends the caller to the counted form, which is exact — and cheap
        precisely here, because a tail predicate matches few rows."""
        assert estimate_range(UNIFORM, P, NUM, ">=", 100) is None
        assert estimate_range(UNIFORM, P, NUM, ">=", 1000) is None

    def test_at_or_below_the_minimum_is_UNKNOWN(self):
        """The mirror: `<= min` selects the mass at the minimum."""
        assert estimate_range(UNIFORM, P, NUM, "<=", 0) is None
        assert estimate_range(UNIFORM, P, NUM, "<=", -5) is None

    def test_the_other_direction_at_an_extreme_is_still_answerable(self):
        """`>= min` is everything and `<= max` is everything; neither depends
        on the unrecorded tie mass, so neither goes unknown."""
        assert estimate_range(UNIFORM, P, NUM, ">=", -5) == 1000
        assert estimate_range(UNIFORM, P, NUM, "<=", 100) == 1000


class TestUnknownIsNotZero:
    """`None` means "no information". A caller that read a missing estimate as
    a small one would reproduce the defect this exists to fix."""

    def test_missing_predicate(self):
        assert estimate_range(UNIFORM, "no-such-uuid", NUM, ">=", 5) is None

    def test_missing_lane(self):
        assert estimate_range(UNIFORM, P, DT, ">=", 5) is None

    def test_too_few_boundaries(self):
        stats = {(P, NUM): {"bounds": [1.0], "total": 10}}
        assert estimate_range(stats, P, NUM, ">=", 5) is None

    def test_null_value(self):
        assert estimate_range(UNIFORM, P, NUM, ">=", None) is None

    def test_incomparable_value(self):
        """A dateTime against numeric boundaries must not raise, and must not
        invent a number."""
        assert estimate_range(
            UNIFORM, P, NUM, ">=", datetime.datetime(2025, 1, 1)) is None

    def test_unknown_operator(self):
        assert estimate_range(UNIFORM, P, NUM, "LIKE", 5) is None


class TestTimestamps:
    """The lane this was built for: 68,502 distinct values, 0.3% covered by
    rdf_stats."""

    def _stats(self):
        base = datetime.datetime(2023, 1, 1)
        return {(P, DT): {"bounds": [base + datetime.timedelta(days=i * 100)
                                     for i in range(11)],
                          "total": 1000}}

    def test_midpoint(self):
        got = estimate_range(self._stats(), P, DT, ">=",
                             datetime.datetime(2024, 5, 15))   # ~day 500 of 1000
        assert 400 <= got <= 600, got

    def test_ordering_is_monotonic(self):
        """Later cut-off, fewer rows. A sign error in the timestamp arithmetic
        would invert this and still return plausible-looking numbers."""
        s = self._stats()
        a = estimate_range(s, P, DT, ">=", datetime.datetime(2023, 6, 1))
        b = estimate_range(s, P, DT, ">=", datetime.datetime(2024, 6, 1))
        c = estimate_range(s, P, DT, ">=", datetime.datetime(2025, 6, 1))
        assert a > b > c, (a, b, c)


class TestSkew:
    """Boundaries close together mean rows concentrated there — that is what
    equi-depth encodes, and what equi-width would lose."""

    def _skewed(self):
        # Most rows in [0, 1); a long thin tail to 1000.
        return {(P, NUM): {"bounds": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5,
                                      0.6, 0.7, 0.8, 10.0, 1000.0],
                           "total": 1000}}

    def test_the_dense_region_is_not_underestimated(self):
        """`>= 0.5` covers half the buckets, so about half the rows, even
        though it is a thousandth of the VALUE range. Equi-width would report
        almost everything as being above 0.5."""
        got = estimate_range(self._skewed(), P, NUM, ">=", 0.5)
        assert 400 <= got <= 600, got

    def test_the_sparse_tail_is_small(self):
        """Exactness in the tail is not the requirement — staying on the right
        side of "this criterion is selective" is. Measured against real data,
        `weight >= 0.9` estimated 0.16% of rows where the truth was 0.004%:
        wrong by 35x and identical as a decision."""
        got = estimate_range(self._skewed(), P, NUM, ">=", 100.0)
        assert got < 100, f"{got} is not a selective-looking estimate"
