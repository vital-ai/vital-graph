"""The WebSocket must authorize a token by the same rules as the HTTP path.

It used to verify the token and then require a `user` row of its own. On a
deployment whose `user` table is still empty — which production is — `admin`
authenticates as the first-run bootstrap admin: login succeeds and every REST
call works through the bootstrap fallback, while the WebSocket rejected the
same fresh token with "Invalid authentication token" on every connect.
"""
import pytest
from fastapi import HTTPException

from vitalgraph.auth.vitalgraph_auth import VitalGraphAuth
from vitalgraph.websocket.websocket_handler import ConnectionManager


class EmptyUserDB:
    """A deployment whose `user` table has no rows."""
    async def get_user_by_username(self, username): return None
    async def get_user_spaces(self, user_id): return {}
    async def count_active_admins(self): return 0


class PopulatedUserDB:
    def __init__(self, token_version=0):
        self._tv = token_version

    async def get_user_by_username(self, username):
        return {"user_id": 1, "username": username, "is_active": True,
                "role": "admin", "token_version": self._tv}
    async def get_user_spaces(self, user_id): return {}
    async def count_active_admins(self): return 1


class FakeWS:
    class client:
        host, port = "10.0.0.1", 1234


def _auth(db, bootstrap=True):
    a = VitalGraphAuth("secret-for-test", db_impl=db)
    if bootstrap:
        a.set_bootstrap_admin("admin", "pw")
    return a


def _token(auth, username="admin", token_version=0):
    return auth.create_tokens({
        "username": username, "full_name": "", "email": "", "role": "admin",
        "spaces": {}, "token_version": token_version})["access_token"]


class TestWebSocketAcceptsWhatHTTPAccepts:
    @pytest.mark.asyncio
    async def test_bootstrap_admin_can_open_a_socket_with_no_user_row(self):
        # THE PRODUCTION CASE. Was rejected on every connect.
        auth = _auth(EmptyUserDB())
        cm = ConnectionManager(auth)
        assert await cm.connect(FakeWS(), _token(auth)) == "admin"

    @pytest.mark.asyncio
    async def test_a_real_db_user_still_connects(self):
        auth = _auth(PopulatedUserDB(), bootstrap=False)
        cm = ConnectionManager(auth)
        assert await cm.connect(FakeWS(), _token(auth, "alice")) == "alice"


class TestWebSocketStillRejectsWhatHTTPRejects:
    @pytest.mark.asyncio
    async def test_garbage_token_is_refused(self):
        cm = ConnectionManager(_auth(EmptyUserDB()))
        assert await cm.connect(FakeWS(), "not-a-jwt") is None

    @pytest.mark.asyncio
    async def test_token_signed_with_another_secret_is_refused(self):
        other = VitalGraphAuth("a-different-secret", db_impl=EmptyUserDB())
        cm = ConnectionManager(_auth(EmptyUserDB()))
        assert await cm.connect(FakeWS(), _token(other)) is None

    @pytest.mark.asyncio
    async def test_a_revoked_token_is_refused(self):
        # The old path never checked token_version, so a revoked token could
        # still open a socket. Delegating fixed that; this pins it.
        auth = _auth(PopulatedUserDB(token_version=5), bootstrap=False)
        cm = ConnectionManager(auth)
        assert await cm.connect(FakeWS(), _token(auth, "alice", token_version=1)) is None

    @pytest.mark.asyncio
    async def test_unknown_user_with_no_bootstrap_is_refused(self):
        auth = _auth(EmptyUserDB(), bootstrap=False)
        cm = ConnectionManager(auth)
        assert await cm.connect(FakeWS(), _token(auth, "nobody")) is None
