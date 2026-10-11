"""Location no longer enters candidate generation; it breaks ties at scoring.

`issues/248`. Geo was folded into the name shingles as three whole-string tokens,
which added a fixed +3 to intersection and union for every same-city pair:
`'Aur Trdaing Corp'` was rank 1 by name and ABSENT with geo, two unrelated
same-city businesses rose +133% in Jaccard, and a true pair with patchy location
data scored BELOW its no-geo baseline. These pin the issue's own measurements.
"""

from __future__ import annotations

import pytest

from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex
from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
from vitalgraph.vectorization.fuzzy_core import geo_agreement

pytestmark = [pytest.mark.unit]

TAMPA = {"country": "US", "region": "FL", "locality": "Tampa"}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


@pytest.fixture(params=["pg", "memory"])
def idx(request):
    if request.param == "pg":
        i = EntityFuzzyIndexPG.__new__(EntityFuzzyIndexPG)
        EntityFuzzyIndexPG.__init__(i, pool=None)
    else:
        i = EntityFuzzyIndex.__new__(EntityFuzzyIndex)
        i.shingle_k = 3
    return i


def test_geo_does_not_change_the_shingles(idx):
    assert idx._name_shingles("Aur Trading Corp", TAMPA) == \
        idx._name_shingles("Aur Trading Corp", {})


def test_the_true_pair_scores_the_same_whatever_the_geo(idx):
    """Measured in the issue: 0.556 no geo, 0.619 agreeing, 0.478 disagreeing."""
    q, t = "Aur Trdaing Corp", "Aur Trading Corp"
    base = _jaccard(idx._name_shingles(q, {}), idx._name_shingles(t, {}))
    agree = _jaccard(idx._name_shingles(q, TAMPA), idx._name_shingles(t, TAMPA))
    disagree = _jaccard(idx._name_shingles(q, TAMPA),
                        idx._name_shingles(t, {"country": "US", "region": "GA",
                                               "locality": "Atlanta"}))
    assert base == pytest.approx(0.556, abs=0.001)
    assert agree == base and disagree == base


def test_an_identical_name_with_patchy_location_is_still_identical(idx):
    """Was 0.870: one record missing `locality` stopped looking identical."""
    a = idx._name_shingles("Tropical Smoothie Cafe", TAMPA)
    b = idx._name_shingles("Tropical Smoothie Cafe", {"country": "US", "region": "FL"})
    assert _jaccard(a, b) == 1.0


def test_unrelated_same_city_businesses_get_no_lift(idx):
    """Was +133% (0.049 -> 0.114): the floor rose under every same-city pair."""
    plain = _jaccard(idx._name_shingles("Beach Runners Landscaping", {}),
                     idx._name_shingles("Zenith Dental", {}))
    tampa = _jaccard(idx._name_shingles("Beach Runners Landscaping", TAMPA),
                     idx._name_shingles("Zenith Dental", TAMPA))
    assert tampa == plain


def test_geo_agreement_counts_only_stated_and_equal_fields():
    assert geo_agreement(TAMPA, TAMPA) == 3
    assert geo_agreement(TAMPA, {"country": "us", "region": " fl "}) == 2
    assert geo_agreement(TAMPA, {"country": "US", "region": "GA", "locality": "Tampa"}) == 2
    assert geo_agreement({}, TAMPA) == 0, "missing location is no signal, not a mismatch"


def test_geo_breaks_a_tie_and_only_a_tie():
    """Two equally named candidates: the one in the query's city ranks first.
    A better NAME match still outranks a geo match."""
    i = EntityFuzzyIndexPG.__new__(EntityFuzzyIndexPG)
    EntityFuzzyIndexPG.__init__(i, pool=None)
    candidates = {
        "elsewhere": {"primary_name": "Acme Plumbing", "alias_names": [],
                      "country": "US", "region": "GA", "locality": "Atlanta"},
        "local": {"primary_name": "Acme Plumbing", "alias_names": [], **TAMPA},
        # 94.6 against the query, where the two above score 100: a worse NAME in
        # the query's own city must still rank below them. (A one-letter typo
        # such as "Acme Plumbng" is NOT worse here: 96 plus the phonetic bonus
        # caps at 100, a genuine tie, which geo then rightly breaks.)
        "worse_name_local": {"primary_name": "Apex Plumbing", "alias_names": [], **TAMPA},
    }
    res = i.score_candidates({"primary_name": "Acme Plumbing", **TAMPA},
                             candidates, limit=10, min_score=0)
    order = [r["entity_id"] for r in res]
    assert order[-1] == "worse_name_local", "geo must not outvote a better name match"
    assert order.index("local") < order.index("elsewhere"), (
        "between equal name scores, the candidate in the query's location wins")
    scores = {r["entity_id"]: r["score"] for r in res}
    assert scores["local"] == scores["elsewhere"], "geo must not change the score itself"
