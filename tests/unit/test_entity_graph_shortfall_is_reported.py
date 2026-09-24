"""A short entity-graph page reports which URIs are missing.

`issues/229`. Both loops in `list_entities_with_graph` were a bare `if objs:`
with no else, so a page whose graphs failed to load came back as a shorter list
inside an HTTP 200 and the caller had no way to distinguish it from a page whose
entities genuinely have none. In production that dropped 113 of 500 entities out
of a bulk copy which reported complete success.

Two properties are pinned here:

  * a URI asked for and not returned is RECORDED, in both the batched path and
    the per-entity fallback;
  * `incomplete` is a THREE-valued answer. False means checked-and-complete,
    None means nobody checked. Collapsing None to False is the same mistake as
    answering `has_more=False` when no one counted, which the quad model calls
    out by name.
"""

import pytest

from vitalgraph.kg_impl.kgentity_list_impl import ListEntitiesResult


def test_result_defaults_are_unknown_not_complete():
    """A result nobody annotated must not claim to be complete."""
    r = ListEntitiesResult(entities=[], total_count=0)
    assert r.incomplete is None, "None means unchecked; False would be a claim"
    assert r.missing_uris == []


def test_complete_result_is_explicitly_false():
    r = ListEntitiesResult(entities=[], total_count=2, missing_uris=[],
                           incomplete=False)
    assert r.incomplete is False
    assert r.missing_uris == []


def test_short_result_names_the_missing_uris():
    r = ListEntitiesResult(entities=[], total_count=3,
                           missing_uris=["urn:e:2"], incomplete=True)
    assert r.incomplete is True
    assert r.missing_uris == ["urn:e:2"]


def test_missing_uris_are_not_shared_between_results():
    """default_factory, not a mutable default — two results must not alias."""
    a = ListEntitiesResult(entities=[], total_count=0)
    b = ListEntitiesResult(entities=[], total_count=0)
    a.missing_uris.append("urn:e:1")
    assert b.missing_uris == []


# --------------------------------------------------------------------------
# the response envelope
# --------------------------------------------------------------------------

def test_quad_response_carries_the_shortfall():
    from vitalgraph.model.quad_model import QuadResponse
    r = QuadResponse(total_count=5, results=[], page_size=10, offset=0,
                     incomplete=True, missing_uris=["urn:e:9"])
    assert r.incomplete is True
    assert r.missing_uris == ["urn:e:9"]


def test_quad_response_shortfall_defaults_to_unknown():
    from vitalgraph.model.quad_model import QuadResponse
    r = QuadResponse(total_count=5, results=[], page_size=10, offset=0)
    assert r.incomplete is None
    assert r.missing_uris == []


@pytest.mark.parametrize("missing,expected", [([], False), (["urn:e:1"], True)])
def test_incomplete_tracks_missing(missing, expected):
    r = ListEntitiesResult(entities=[], total_count=1, missing_uris=missing,
                           incomplete=bool(missing))
    assert r.incomplete is expected
