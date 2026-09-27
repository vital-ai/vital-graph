"""`GET /api/spaces/config` returns the config document, or says why not — issue 233.

The export itself is covered against a real database in
`tests/integration/test_config_export.py`. What is pinned here is the ENDPOINT's
contract, which is the part a caller depends on and which no database is needed
to check:

* a domain failure is an HTTP 200 with a status in the body, never a raised
  exception — the convention every other handler in this file follows, and the
  one an operator tool relies on to tell "no pool" from "no such space";
* `include_secrets` defaults to FALSE and is actually threaded through, because
  the default response is the one that ends up pasted into a ticket.
"""

from __future__ import annotations

import pytest

from vitalgraph.endpoint.spaces_endpoint import SpacesEndpoint

pytestmark = [pytest.mark.unit]


class _Conn:
    async def fetch(self, *_a):
        return []


class _Acquire:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *_a):
        return False


class _Pool:
    def acquire(self):
        return _Acquire()


class _Api:
    def __init__(self, pool=None):
        self._pool = pool


def _endpoint(pool):
    return SpacesEndpoint(api=_Api(pool), auth_dependency=lambda: {})


class TestItReturnsTheDocument:

    async def test_success_carries_the_config(self):
        res = await _endpoint(_Pool()).get_space_config("sp")
        assert res["status"] == "found"
        assert res["config"]["source_space_id"] == "sp"
        assert res["config"]["version"] >= 1

    async def test_every_config_table_being_absent_is_still_a_success(self):
        """A stub whose every read returns nothing stands in for the oldest
        possible space. An empty config is a fact about the space, not an error."""
        res = await _endpoint(_Pool()).get_space_config("sp")
        assert res["status"] == "found"
        assert res["config"]["mappings"] == []


class TestFailuresAreDomainOutcomes:

    async def test_no_pool_is_a_200_with_a_message(self):
        res = await _endpoint(None).get_space_config("sp")
        assert res["status"] == "query_failed"
        assert "pool" in res["message"].lower()

    async def test_a_broken_pool_does_not_raise(self):
        """Read-only or not, the handler is the boundary: a driver error has to
        arrive as a status a caller can branch on."""
        class _Boom:
            def acquire(self):
                raise RuntimeError("pool is closed")

        res = await _endpoint(_Boom()).get_space_config("sp")
        assert res["status"] == "query_failed"
        assert "pool is closed" in res["message"]


class TestSecretsDefaultToRedacted:

    async def test_the_flag_reaches_the_exporter(self, monkeypatch):
        seen = {}

        async def _fake(conn, space_id, *, include_secrets=False):
            seen["include_secrets"] = include_secrets
            return {"version": 1, "source_space_id": space_id}

        import vitalgraph.db.sparql_sql.config_export as C
        monkeypatch.setattr(C, "export_space_config", _fake)

        await _endpoint(_Pool()).get_space_config("sp")
        assert seen["include_secrets"] is False, "the safe default must survive"

        await _endpoint(_Pool()).get_space_config("sp", include_secrets=True)
        assert seen["include_secrets"] is True, "the opt-in must be threaded"

    async def test_the_route_declares_the_safe_default(self):
        """FastAPI silently drops an undeclared query parameter, so a route that
        forgot `include_secrets` would ignore it and always redact — the safe
        direction, but it would look like the flag was broken."""
        routes = {r.path: r for r in _endpoint(_Pool()).router.routes}
        assert "/spaces/config" in routes
        import inspect
        sig = inspect.signature(routes["/spaces/config"].endpoint)
        assert "include_secrets" in sig.parameters
        assert sig.parameters["include_secrets"].default.default is False


class TestTheDiffRoute:
    """`issues/233` step 2's surface. The comparison itself is covered in
    `tests/unit/test_config_diff.py`; this pins the handler's contract."""

    async def test_a_valid_document_is_compared(self, monkeypatch):
        async def _fake(conn, space_id, document):
            return {"differs": False, "sections": {}, "space_id": space_id}
        import vitalgraph.db.sparql_sql.config_diff as D
        monkeypatch.setattr(D, "diff_space_config", _fake)

        res = await _endpoint(_Pool()).diff_space_config(
            "sp", {"version": 1, "mappings": []})
        assert res["status"] == "found"
        assert res["diff"]["differs"] is False

    async def test_a_body_that_is_not_a_document_is_rejected_as_a_domain_outcome(self):
        """Not an exception and not a 422 — the caller most likely to send the
        wrong body is a script, and it needs a status it can branch on."""
        for body in ({}, {"mappings": []}, "not a dict", None):
            res = await _endpoint(_Pool()).diff_space_config("sp", body)
            assert res["status"] == "invalid_request", body
            assert "version" in res["message"]

    async def test_no_pool_is_a_domain_outcome(self):
        res = await _endpoint(None).diff_space_config("sp", {"version": 1})
        assert res["status"] == "query_failed"

    async def test_the_route_is_a_post_that_requires_only_read(self):
        """A POST that changes nothing must not demand write access, or the
        people auditing a config cannot run it."""
        import inspect
        routes = {r.path: r for r in _endpoint(_Pool()).router.routes}
        assert "/spaces/config/diff" in routes
        route = routes["/spaces/config/diff"]
        assert "POST" in route.methods
        src = inspect.getsource(route.endpoint)
        assert "require_space_read" in src
        assert "require_space_write" not in src


class TestTheApplyRoute:
    """`issues/233` step 3's surface. Merge semantics are covered against a real
    database; this pins the handler contract and the auth asymmetry."""

    async def test_a_change_reports_updated_and_a_no_change_reports_no_op(
            self, monkeypatch):
        """A caller polling toward a desired state has to tell "I changed it"
        from "it already matched"."""
        import vitalgraph.db.sparql_sql.config_apply as A
        for changed, expected in ((True, "updated"), (False, "no_op")):
            async def _fake(conn, space_id, document, *, dry_run=False,
                            replace=False, _c=changed):
                return {"changed": _c, "created": [], "updated": []}
            monkeypatch.setattr(A, "apply_space_config", _fake)
            res = await _endpoint(_Pool()).apply_space_config(
                "sp", {"version": 1})
            assert res["status"] == expected

    async def test_a_refusal_is_a_domain_outcome_not_a_500(self, monkeypatch):
        """Nothing was written, and the reason is the useful part — a 500 would
        lose it and invite a retry."""
        import vitalgraph.db.sparql_sql.config_apply as A

        async def _refuse(conn, space_id, document, *, dry_run=False,
                          replace=False):
            raise A.ConfigApplyRefused("carries redacted secrets: x.api_key")
        monkeypatch.setattr(A, "apply_space_config", _refuse)

        res = await _endpoint(_Pool()).apply_space_config("sp", {"version": 1})
        assert res["status"] == "invalid_request"
        assert "api_key" in res["message"]

    async def test_a_bad_body_is_rejected(self):
        res = await _endpoint(_Pool()).apply_space_config("sp", {"no": "version"})
        assert res["status"] == "invalid_request"

    async def test_the_dry_run_flag_is_threaded(self, monkeypatch):
        seen = {}
        import vitalgraph.db.sparql_sql.config_apply as A

        async def _fake(conn, space_id, document, *, dry_run=False,
                        replace=False):
            seen["dry_run"] = dry_run
            return {"changed": False}
        monkeypatch.setattr(A, "apply_space_config", _fake)

        await _endpoint(_Pool()).apply_space_config("sp", {"version": 1})
        assert seen["dry_run"] is False
        await _endpoint(_Pool()).apply_space_config("sp", {"version": 1},
                                                   dry_run=True)
        assert seen["dry_run"] is True

    async def test_apply_requires_write_where_diff_requires_read(self):
        """The asymmetry is the point: auditing a config must not need write, and
        changing one must. A dry run still needs write, because otherwise the
        permission depends on a query parameter the caller picks."""
        import inspect
        routes = {r.path: r for r in _endpoint(_Pool()).router.routes}
        apply_src = inspect.getsource(routes["/spaces/config/apply"].endpoint)
        diff_src = inspect.getsource(routes["/spaces/config/diff"].endpoint)
        assert "require_space_write" in apply_src
        assert "require_space_write" not in diff_src
        assert "require_space_read" in diff_src


class TestTheReplaceFlag:
    """`issues/233` step 4. The flag destroys embeddings, so its default and its
    plumbing are worth pinning separately from the behaviour."""

    async def test_replace_defaults_to_false(self, monkeypatch):
        """The destructive behaviour must not be what you get by not thinking."""
        seen = {}
        import vitalgraph.db.sparql_sql.config_apply as A

        async def _fake(conn, space_id, document, *, dry_run=False, replace=False):
            seen["replace"] = replace
            return {"changed": False}
        monkeypatch.setattr(A, "apply_space_config", _fake)

        await _endpoint(_Pool()).apply_space_config("sp", {"version": 1})
        assert seen["replace"] is False

    async def test_replace_is_threaded_when_asked_for(self, monkeypatch):
        seen = {}
        import vitalgraph.db.sparql_sql.config_apply as A

        async def _fake(conn, space_id, document, *, dry_run=False, replace=False):
            seen.update(replace=replace, dry_run=dry_run)
            return {"changed": False}
        monkeypatch.setattr(A, "apply_space_config", _fake)

        await _endpoint(_Pool()).apply_space_config(
            "sp", {"version": 1}, dry_run=True, replace=True)
        assert seen == {"replace": True, "dry_run": True}

    async def test_the_route_declares_replace_defaulting_to_false(self):
        """FastAPI drops an undeclared query parameter silently, so a route that
        forgot `replace` would ignore it — safe here, but it would look broken."""
        import inspect
        routes = {r.path: r for r in _endpoint(_Pool()).router.routes}
        sig = inspect.signature(routes["/spaces/config/apply"].endpoint)
        assert "replace" in sig.parameters
        assert sig.parameters["replace"].default.default is False
