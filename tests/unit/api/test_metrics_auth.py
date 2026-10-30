"""The metrics routes require a token and read access to the space.

`slow_query_log` carries query text, so these routes expose as much as the
queries do. Every case is run against both routes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Header, HTTPException
from starlette.testclient import TestClient

from vitalgraph.endpoint.metrics_endpoint import MetricsEndpoint

USERS = {
    "admin": {"username": "a", "role": "admin", "spaces": {}},
    "reader": {"username": "r", "role": "reader", "spaces": {"sp_mine": "r"}},
    "wildcard": {"username": "w", "role": "user", "spaces": {"*": "rw"}},
    "nobody": {"username": "n", "role": "user", "spaces": {}},
}
ROUTES = ["/api/metrics?space_id=sp_mine", "/api/metrics/slow?space_id=sp_mine"]


async def fake_auth(authorization: str = Header(default="")):
    user = USERS.get(authorization.removeprefix("Bearer "))
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@pytest.fixture()
def endpoint():
    ep = MetricsEndpoint(api=None, auth_dependency=fake_auth)
    ep._get_collector = lambda: _collector
    return ep


_collector = AsyncMock()
_collector.get_slow_log.return_value = [{"query_text": "SELECT 'private'"}]
_collector.get_realtime_series.return_value = {
    "timestamps": [], "series": {},
    "totals": {"total_requests": 0, "total_errors": 0, "avg_latency_ms": 0},
}


@pytest.fixture()
def client(endpoint):
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api")
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_collector():
    _collector.reset_mock()


def bearer(name):
    return {"Authorization": f"Bearer {name}"}


@pytest.mark.parametrize("route", ROUTES)
class TestAccess:
    def test_no_token_is_refused_and_reads_nothing(self, client, route):
        assert client.get(route).status_code == 401
        _collector.get_slow_log.assert_not_called()
        _collector.get_realtime_series.assert_not_called()

    def test_a_bad_token_is_refused(self, client, route):
        assert client.get(route, headers=bearer("forged")).status_code == 401

    def test_a_user_without_the_space_is_refused_and_reads_nothing(self, client, route):
        assert client.get(route, headers=bearer("nobody")).status_code == 403
        _collector.get_slow_log.assert_not_called()
        _collector.get_realtime_series.assert_not_called()

    @pytest.mark.parametrize("name", ["admin", "reader", "wildcard"])
    def test_read_access_to_the_space_is_enough(self, client, route, name):
        assert client.get(route, headers=bearer(name)).status_code == 200


def test_a_reader_cannot_read_another_space_slow_log(client):
    response = client.get("/api/metrics/slow?space_id=sp_other", headers=bearer("reader"))
    assert response.status_code == 403
    assert "private" not in response.text
