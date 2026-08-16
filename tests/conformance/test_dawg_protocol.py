"""SPARQL 1.1 Protocol conformance — the 34 cases, against a live server.

`protocol` was the one DAWG category declined as "deferred" that tests something
we ACTUALLY SHIP: we serve SPARQL over HTTP, so these apply. Running them cost a
manifest parser and an HTTP client, and immediately paid.

TWO DIFFERENT QUESTIONS, KEPT APART. This file answers both, and conflating them
is what would make it useless:

  1. Do we CRASH on a standard protocol request?   -- a bug. Now fixed.
  2. Are we protocol-CONFORMANT?                   -- a feature. Largely not.

`test_no_server_faults` is question 1, it applies to every case, and it PASSES.
When first measured, 22 of 34 standard protocol requests returned HTTP 500 --
not "unsupported", a server fault -- all through one un-encoded validation
handler (`vitalgraph/main/main.py`, see `tests/unit/test_validation_error_handler.py`).
That test stays green forever regardless of what we decide about question 2.

`test_protocol_case` is question 2, and 22 cases are xfail with a specific
reason. Those reasons are a design decision, not a backlog: see
`planning/planning_sparql_features/dawg_conformance_coverage.md`.

THE MAPPING IS GENEROUS ON PURPOSE. The manifest addresses a bare `/sparql` with
no auth and no dataset selector -- in the Protocol the endpoint IS the dataset.
The runner adds our `space_id` and a bearer token so that a failure means the
protocol BEHAVIOUR is wrong rather than just the URL. Every result carries the
mapping notes so no summary can imply we serve `/sparql`.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import List

import pytest

from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_protocol_parser import (
    ProtocolTestCase,
    assert_full_coverage,
    parse_protocol_manifest,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_protocol_runner import (
    ServerTarget,
    login,
    run_protocol_case,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    _PROJECT_ROOT / "vitalgraph_sparql_sql_dev" / "dawg_tests" / "sparql"
    / "sparql11" / "protocol" / "manifest.ttl"
)

# Read by test_dawg_coverage.py, which asserts every DAWG category is either
# run or declined in writing. `protocol` moved from DECLINED to here.
PROTOCOL_CATEGORIES = ["protocol"]

BASE_URL = os.getenv("VG_PROTOCOL_BASE_URL", "http://localhost:8001")
SPACE_ID = os.getenv("VG_PROTOCOL_SPACE_ID", "wordnet_frames")
USERNAME = os.getenv("VG_PROTOCOL_USER", "admin")
PASSWORD = os.getenv("VG_PROTOCOL_PASSWORD", "admin")


def _server_available() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


HAS_SERVER = _server_available()

pytestmark = [
    pytest.mark.dawg,
    pytest.mark.skipif(
        not HAS_SERVER,
        reason=f"Requires a running VitalGraph server at {BASE_URL}",
    ),
    pytest.mark.skipif(not MANIFEST.exists(), reason="DAWG corpus not present"),
]


# The 22 cases we do not satisfy, grouped by WHY. Every one is "we do not
# implement the SPARQL Protocol", not "we break on it" -- that distinction is
# the whole point of keeping `test_no_server_faults` separate.
_NO_PROTOCOL_CONTENT_TYPES = (
    "we accept a JSON body ({\"query\": ...}); the Protocol sends "
    "application/sparql-query, application/sparql-update or "
    "application/x-www-form-urlencoded. Returns 422, correctly, for a body it "
    "was never built to take"
)
_NO_RESULTS_MEDIA_TYPE = (
    "returns application/json with our own envelope, not "
    "application/sparql-results+json"
)
_DOMAIN_OUTCOMES_ARE_200 = (
    "this project answers domain outcomes with HTTP 200 and the outcome in the "
    "body; the Protocol requires 4xx for a rejected query. A real conflict, and "
    "a decision rather than a defect -- see the planning doc"
)

XFAIL_PROTOCOL = {
    # -- body content types the Protocol mandates and we do not accept
    "query_post_form": _NO_PROTOCOL_CONTENT_TYPES,
    "query_post_direct": _NO_PROTOCOL_CONTENT_TYPES,
    "query_content_type_select": _NO_PROTOCOL_CONTENT_TYPES,
    "query_content_type_ask": _NO_PROTOCOL_CONTENT_TYPES,
    "query_content_type_construct": _NO_PROTOCOL_CONTENT_TYPES,
    "query_content_type_describe": _NO_PROTOCOL_CONTENT_TYPES,
    "query_dataset_default_graphs_post": _NO_PROTOCOL_CONTENT_TYPES,
    "query_dataset_named_graphs_post": _NO_PROTOCOL_CONTENT_TYPES,
    "query_dataset_full": _NO_PROTOCOL_CONTENT_TYPES,
    "query_multiple_dataset": _NO_PROTOCOL_CONTENT_TYPES,
    "update_post_form": _NO_PROTOCOL_CONTENT_TYPES,
    "update_post_direct": _NO_PROTOCOL_CONTENT_TYPES,
    "update_base_uri": _NO_PROTOCOL_CONTENT_TYPES,
    "update_dataset_default_graph": _NO_PROTOCOL_CONTENT_TYPES,
    "update_dataset_default_graphs": _NO_PROTOCOL_CONTENT_TYPES,
    "update_dataset_named_graphs": _NO_PROTOCOL_CONTENT_TYPES,
    "update_dataset_full": _NO_PROTOCOL_CONTENT_TYPES,

    # -- correct status, wrong media type. The smallest gap here by far.
    "query_get": _NO_RESULTS_MEDIA_TYPE,
    "query_dataset_default_graphs_get": _NO_RESULTS_MEDIA_TYPE,
    "query_dataset_named_graphs_get": _NO_RESULTS_MEDIA_TYPE,

    # -- the convention conflict
    "bad_query_syntax": _DOMAIN_OUTCOMES_ARE_200,
    "bad_multiple_queries": (
        "repeated ?query= parameters are not rejected; the last wins. "
        + _DOMAIN_OUTCOMES_ARE_200
    ),
}


def _load() -> List[ProtocolTestCase]:
    if not MANIFEST.exists():
        return []
    return parse_protocol_manifest(MANIFEST)


_CASES = _load()


@pytest.fixture(scope="module")
def target() -> ServerTarget:
    token = login(BASE_URL, USERNAME, PASSWORD)
    return ServerTarget(base_url=BASE_URL, space_id=SPACE_ID, token=token)


class TestSPARQLProtocol:

    def test_manifest_fully_parsed(self):
        """The manifest is PROSE, and a prose parser degrades quietly.

        Every other DAWG category ships machine-readable files; this one
        describes each exchange in an `rdfs:comment`. One reformatted entry and
        the parser yields 33 cases instead of 34 — all passing, nothing to see.
        """
        assert_full_coverage(_CASES)

    @pytest.mark.parametrize("case", _CASES, ids=[c.name for c in _CASES])
    def test_no_server_faults(self, case: ProtocolTestCase, target: ServerTarget):
        """No standard protocol request may produce a 5xx. THIS IS THE ONE.

        Independent of whether we ever implement the Protocol: a request from a
        conformant SPARQL client must not crash the server. When first measured,
        22 of these 34 returned HTTP 500 — a caller's request reported as a
        server fault, which pages someone and pollutes error rates.

        A 422 here is a PASS. "We do not accept that content type" is a
        legitimate, honest answer; "Internal Server Error" is not.
        """
        result = run_protocol_case(case, target)

        if result.status == "ERROR":
            pytest.skip(f"transport failure, not a verdict: {result.detail}")

        assert result.http_status is not None
        assert result.http_status < 500, (
            f"{case.method} {case.path} returned {result.http_status}.\n"
            f"  A conformant SPARQL client sends this exact request. Whether we "
            f"support it is a design question; crashing on it is not.\n"
            f"  mapping: {'; '.join(result.mapping_notes)}"
        )

    @pytest.mark.parametrize("case", _CASES, ids=[c.name for c in _CASES])
    def test_protocol_case(self, case: ProtocolTestCase, target: ServerTarget):
        """Full conformance. 12 of 34 pass; the rest are xfail with a reason."""
        if case.name in XFAIL_PROTOCOL:
            pytest.xfail(XFAIL_PROTOCOL[case.name])

        result = run_protocol_case(case, target)
        if result.status == "ERROR":
            pytest.skip(f"transport failure: {result.detail}")

        assert result.status == "PASS", (
            f"{result.detail}\n"
            f"  {case.method} {case.path} -> HTTP {result.http_status}\n"
            f"  mapping: {'; '.join(result.mapping_notes)}"
        )

    def test_xfail_list_is_not_stale(self):
        """An xfail naming a case that no longer exists hides a coverage loss."""
        known = {c.name for c in _CASES}
        stale = sorted(set(XFAIL_PROTOCOL) - known)
        assert not stale, f"XFAIL_PROTOCOL names unknown cases: {stale}"
