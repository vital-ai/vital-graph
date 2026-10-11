"""The client must not turn a failed entity count into zero — issue 228.

The server used to answer a cancelled count with HTTP 500, which the client
raised. It now answers HTTP 200 with `status=query_failed` and `count: 0` (the
domain-outcome contract), so `count_kgentities`, which returns a bare int, would
have read that as a confident zero. It raises instead, as the 500 did.
"""

import asyncio

import pytest

from vitalgraph.client.endpoint.kgentities_endpoint import KGEntitiesEndpoint
from vitalgraph.client.utils.client_utils import VitalGraphClientError


class _Resp:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def _endpoint(body):
    ep = KGEntitiesEndpoint.__new__(KGEntitiesEndpoint)
    ep._check_connection = lambda: None
    ep._get_server_url = lambda: "http://server"

    async def _make_request(method, url, **kw):
        return _Resp(body)
    ep._make_request = _make_request
    return ep


def test_a_failed_count_raises_rather_than_returning_zero():
    ep = _endpoint({"success": False, "status": "query_failed", "count": 0,
                    "message": "canceling statement due to statement timeout"})
    with pytest.raises(VitalGraphClientError, match="query_failed"):
        asyncio.run(ep.count_kgentities("sp", "urn:g"))


def test_a_genuine_zero_is_still_zero():
    ep = _endpoint({"success": True, "status": "empty", "count": 0})
    assert asyncio.run(ep.count_kgentities("sp", "urn:g")) == 0


def test_a_batch_where_every_count_failed_raises():
    ep = _endpoint({"success": False, "status": "query_failed", "message": "2 of 2 failed",
                    "counts": [{"label": "a", "count": 0, "error": "x"}]})
    with pytest.raises(VitalGraphClientError):
        asyncio.run(ep.batch_count_kgentities("sp", "urn:g", [{"label": "a"}]))


def test_a_partial_batch_returns_the_labels_with_their_errors():
    counts = [{"label": "a", "count": 3, "error": None},
              {"label": "b", "count": 0, "error": "statement timeout"}]
    ep = _endpoint({"success": False, "status": "partial", "counts": counts})
    assert asyncio.run(ep.batch_count_kgentities("sp", "urn:g", [{"label": "a"}, {"label": "b"}])) == counts
