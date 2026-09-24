"""The client passes the server's shortfall fields through to its caller.

`issues/229` taught the server to say "you asked for 100, here are 87" via
`incomplete` and `missing_uris`. That fix is worth nothing to the consumer that
most needs it -- the portal reaches VitalGraph through the Resource API, which
uses the published client package -- if the client drops the fields on the way
past.

`extract_pagination_from_json_quads` WHITELISTS what it forwards, and the
response models are pydantic with the default `extra='ignore'`, so a field the
server grows is discarded TWICE over unless both are told about it. Both sites
are pinned here.

The three-valued contract is the part worth guarding: `None` means the server
did not say, and must never be normalised to `False`, which is a claim that the
answer is whole. `has_more` on these same models carries a comment about
exactly that mistake being shipped once already.
"""

import pytest

from vitalgraph.client.response.client_response import (
    MultiEntityGraphResponse, MultiFrameGraphResponse,
    PaginatedGraphObjectResponse)
from vitalgraph.client.utils.format_helpers import (
    extract_pagination_from_json_quads as extract)

BASE = dict(status_code=200, error_code=0)


# --------------------------------------------------------------------------
# the extractor
# --------------------------------------------------------------------------

def test_shortfall_is_forwarded():
    p = extract({"total_count": 5, "page_size": 10, "offset": 0,
                 "incomplete": True, "missing_uris": ["urn:e:1"]})
    assert p["incomplete"] is True
    assert p["missing_uris"] == ["urn:e:1"]


def test_verified_complete_is_forwarded_as_false():
    p = extract({"total_count": 5, "page_size": 10, "offset": 0,
                 "incomplete": False, "missing_uris": []})
    assert p["incomplete"] is False


def test_a_server_that_cannot_say_yields_none_not_false():
    """An older server omits the fields. Unknown must stay unknown."""
    p = extract({"total_count": 5, "page_size": 10, "offset": 0})
    assert p["incomplete"] is None, "None is the absence of an answer, not 'no'"
    assert p["missing_uris"] == []


def test_null_missing_uris_becomes_a_list():
    p = extract({"total_count": 0, "page_size": 0, "offset": 0,
                 "missing_uris": None})
    assert p["missing_uris"] == []


# --------------------------------------------------------------------------
# the response models — every class that is handed **pagination
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cls,extra", [
    (PaginatedGraphObjectResponse, {"objects": []}),
    (MultiEntityGraphResponse, {"graph_list": []}),
    (MultiFrameGraphResponse, {"graph_list": []}),
])
def test_models_keep_the_fields(cls, extra):
    """pydantic's default extra='ignore' drops undeclared keys silently, so a
    model that is handed the pagination dict must DECLARE these."""
    p = extract({"total_count": 1, "page_size": 1, "offset": 0,
                 "incomplete": True, "missing_uris": ["urn:x"]})
    m = cls(**BASE, **p, **extra)
    assert m.incomplete is True
    assert m.missing_uris == ["urn:x"]


@pytest.mark.parametrize("cls,extra", [
    (PaginatedGraphObjectResponse, {"objects": []}),
    (MultiEntityGraphResponse, {"graph_list": []}),
    (MultiFrameGraphResponse, {"graph_list": []}),
])
def test_models_default_to_unknown(cls, extra):
    m = cls(**BASE, total_count=0, page_size=0, offset=0, **extra)
    assert m.incomplete is None
    assert m.missing_uris == []


def test_missing_uris_is_not_shared_between_instances():
    a = PaginatedGraphObjectResponse(**BASE, total_count=0, page_size=0,
                                     offset=0, objects=[])
    b = PaginatedGraphObjectResponse(**BASE, total_count=0, page_size=0,
                                     offset=0, objects=[])
    a.missing_uris.append("urn:e:1")
    assert b.missing_uris == []
