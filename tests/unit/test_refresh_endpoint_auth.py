"""The refresh endpoint must not require a valid ACCESS token.

Refresh exists to replace an expired access token. Guarding it with
`Depends(get_current_user)` — which verifies the Authorization header as an
ACCESS token — made it unusable in exactly that case, so every session died 30
minutes after login and the WebSocket reconnect loop reported "Invalid
authentication token" indefinitely. Nothing covered this route, which is why it
shipped.
"""
import inspect
import re

import pytest
from fastapi import HTTPException

from vitalgraph.auth.jwt_auth import JWTAuth
from vitalgraph.impl.vitalgraphapp_impl import VitalGraphAppImpl


class TestRefreshTokenIsNotAnAccessToken:
    """WHY the dependency was fatal, not merely redundant."""

    def setup_method(self):
        self.jwt = JWTAuth("secret-for-test")

    def test_refresh_token_is_rejected_as_an_access_token(self):
        # This is what `get_current_user` did to the header the frontend sends.
        refresh = self.jwt.create_refresh_token({"sub": "alice"})
        with pytest.raises(HTTPException) as exc:
            self.jwt.verify_token(refresh, "access")
        assert exc.value.status_code == 401

    def test_the_same_token_verifies_as_a_refresh_token(self):
        # ...while the handler's own check accepts it, so the credential was
        # always valid — only the guard in front of it disagreed.
        refresh = self.jwt.create_refresh_token({"sub": "alice"})
        assert self.jwt.verify_token(refresh, "refresh")["sub"] == "alice"

    def test_an_access_token_cannot_be_used_to_refresh(self):
        # Dropping the dependency must not let an access token stand in for a
        # refresh token: the type check inside the handler still rejects it.
        access = self.jwt.create_access_token({"sub": "alice"})
        with pytest.raises(HTTPException):
            self.jwt.verify_token(access, "refresh")


class TestRefreshRouteHasNoAccessTokenDependency:
    def test_wrapper_does_not_depend_on_get_current_user(self):
        src = inspect.getsource(VitalGraphAppImpl._init_auth_routes)
        # Non-greedy to the closing `):` of the def line, NOT `[^)]*` — the
        # first `)` belongs to `Body(..., embed=True)`, so a naive character
        # class stops before the parameter this test exists to catch, and the
        # guard passes with the bug present. It did.
        sig = re.search(r"async def refresh_token_wrapper\((.*?)\):\s*\n", src, re.S)
        assert sig, "refresh_token_wrapper not found — did the route move?"
        assert "get_current_user" not in sig.group(1), (
            "refresh requires a valid ACCESS token again — this makes it "
            "impossible to refresh an EXPIRED one, which is its only purpose")

    def test_logout_still_does_depend_on_it(self):
        # The guard belongs on routes that act for an authenticated user; this
        # asserts the fix was surgical rather than a blanket removal.
        src = inspect.getsource(VitalGraphAppImpl._init_auth_routes)
        sig = re.search(r"async def logout_wrapper\((.*?)\):\s*\n", src, re.S)
        assert sig and "get_current_user" in sig.group(1)
