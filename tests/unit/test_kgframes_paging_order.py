"""Unit tests: every paged KGFrames query carries an ORDER BY.

A LIMIT/OFFSET over an unordered result set is not stable — SQL gives no
ordering guarantee without an ORDER BY, so successive pages may repeat or
skip subjects.  These tests assert on the generated SPARQL text, so they need
no database and no server.

Step 1 of planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md.
"""

from __future__ import annotations

import re

import pytest

from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint

pytestmark = pytest.mark.unit

SEQ_FRAME = "http://vital.ai/ontology/haley-ai-kg#hasFrameSequence"
SEQ_SLOT = "http://vital.ai/ontology/haley-ai-kg#hasSlotSequence"


@pytest.fixture
def endpoint():
    """KGFramesEndpoint with no wiring — query builders are pure functions."""
    return KGFramesEndpoint(space_manager=None, auth_dependency=None)


def _assert_ordered_before_limit(sparql: str):
    """ORDER BY must be present AND precede LIMIT to actually bound a page."""
    assert "ORDER BY" in sparql, f"query has no ORDER BY:\n{sparql}"
    assert "LIMIT" in sparql, f"query has no LIMIT:\n{sparql}"
    assert sparql.index("ORDER BY") < sparql.index("LIMIT"), (
        f"ORDER BY must precede LIMIT:\n{sparql}"
    )


class TestFramesWithSlotsOrdering:
    """_build_frames_with_slots_query — the unstable-paging bug."""

    def _build(self, endpoint, **kw):
        params = dict(
            backend=None, space_id="sp", graph_id="g", frame_uri=None,
            entity_uri=None, parent_uri=None, search=None, kGSlotType=None,
            page_size=10, offset=0,
        )
        params.update(kw)
        return endpoint._build_frames_with_slots_query(**params)

    def test_has_order_by_before_limit(self, endpoint):
        """The paged frames+slots query is ordered."""
        _assert_ordered_before_limit(self._build(endpoint))

    def test_orders_by_the_projected_variable(self, endpoint):
        """ORDER BY must name ?subject — the DISTINCT projection variable.

        Ordering on anything else would not give a total order over the rows
        actually returned.
        """
        sparql = self._build(endpoint)
        assert re.search(r"ORDER BY\s+\?subject", sparql), sparql

    def test_ordering_survives_filters(self, endpoint):
        """Filters must not displace the ORDER BY."""
        for kw in (
            {"frame_uri": "http://example.org/f1"},
            {"kGSlotType": "http://example.org/SlotType"},
            {"entity_uri": "http://example.org/e1"},
        ):
            _assert_ordered_before_limit(self._build(endpoint, **kw))

    def test_offset_is_emitted_after_limit(self, endpoint):
        """Sanity: the page window itself is still intact."""
        sparql = self._build(endpoint, page_size=25, offset=50)
        assert "LIMIT 25" in sparql
        assert "OFFSET 50" in sparql


class TestOrderByNotAlongsideDistinct:
    """An ORDER BY in the same SELECT as a DISTINCT is silently DROPPED.

    The backend then returns subject/URI order while appearing to have
    sorted — which is how sort_by went unnoticed as broken. Any sorted query
    must put the DISTINCT in an inner subquery and the ORDER BY outside it.
    """

    def _assert_distinct_is_subselected(self, sparql: str):
        assert "SELECT DISTINCT" in sparql, sparql
        distinct_at = sparql.index("SELECT DISTINCT")
        order_at = sparql.index("ORDER BY")
        # the DISTINCT must open a nested select that closes before ORDER BY
        assert order_at > distinct_at, sparql
        between = sparql[distinct_at:order_at]
        assert between.count("}") > between.count("{"), (
            "the DISTINCT subquery must be closed before ORDER BY:\n" + sparql
        )

    def test_sorted_frame_list_subselects_the_distinct(self, endpoint):
        sparql = endpoint._build_list_frames_query(
            backend=None, space_id="sp", graph_id="g", search=None,
            page_size=10, offset=0, sort_by=SEQ_FRAME,
        )
        self._assert_distinct_is_subselected(sparql)

    def test_unsorted_frame_list_subselects_the_distinct(self, endpoint):
        """Same shape with no sort_by, so the two paths cannot diverge."""
        sparql = endpoint._build_list_frames_query(
            backend=None, space_id="sp", graph_id="g", search=None,
            page_size=10, offset=0,
        )
        self._assert_distinct_is_subselected(sparql)

    def test_sorted_frame_slots_subselects_the_distinct(self, endpoint):
        sparql = endpoint._build_get_frame_slots_query(
            "g", "http://example.org/f1", sort_by=SEQ_SLOT, page_size=5,
        )
        self._assert_distinct_is_subselected(sparql)

    def test_sort_keys_are_projected_out_of_the_subquery(self, endpoint):
        """Sort keys must survive the inner DISTINCT to reach the ORDER BY."""
        sparql = endpoint._build_list_frames_query(
            backend=None, space_id="sp", graph_id="g", search=None,
            page_size=10, offset=0, sort_by=SEQ_FRAME,
        )
        inner = sparql[sparql.index("SELECT DISTINCT"):sparql.index("WHERE", sparql.index("SELECT DISTINCT"))]
        assert "?sort_missing" in inner, inner
        assert "?sort_num" in inner, inner


class TestListFramesOrdering:
    """_build_list_frames_query — already ordered; guard against regression."""

    def _build(self, endpoint, **kw):
        params = dict(
            backend=None, space_id="sp", graph_id="g", search=None,
            page_size=10, offset=0,
        )
        params.update(kw)
        return endpoint._build_list_frames_query(**params)

    def test_default_ordering_present(self, endpoint):
        _assert_ordered_before_limit(self._build(endpoint))

    def test_sort_by_ordering_present(self, endpoint):
        """An explicit sort_by still emits ORDER BY ahead of LIMIT."""
        sparql = self._build(
            endpoint, sort_by="http://vital.ai/ontology/vital-core#hasName")
        _assert_ordered_before_limit(sparql)


class TestPageSizeBounds:
    """GET /kgframes/kgslots bounds page_size like its sibling endpoints.

    Asserted on the route declaration rather than over HTTP so it needs no
    running server.  An unbounded page_size lets one request pull the whole
    graph, which is the other half of the step 1 fix.
    """

    def _constraints(self, endpoint, path: str, method: str, name: str) -> dict:
        """Return {'ge': n, 'le': n} declared on a route's query parameter.

        FastAPI/Pydantic v2 keeps ge/le in FieldInfo.metadata as annotated_types
        markers rather than as plain attributes.
        """
        import inspect
        endpoint._setup_routes()
        for route in endpoint.router.routes:
            if getattr(route, "path", None) == path and method in getattr(
                    route, "methods", set()):
                param = inspect.signature(route.endpoint).parameters[name]
                out = {}
                for marker in getattr(param.default, "metadata", []):
                    for key in ("ge", "le"):
                        if hasattr(marker, key):
                            out[key] = getattr(marker, key)
                return out
        pytest.skip(f"route {method} {path} not registered on this instance")

    def test_frames_with_slots_page_size_bounded(self, endpoint):
        c = self._constraints(
            endpoint, "/kgframes/kgslots", "GET", "page_size")
        assert c.get("ge") == 1, f"page_size must be at least 1, got {c}"
        assert c.get("le") == 1000, (
            f"page_size must be capped at 1000 like sibling endpoints, got {c}"
        )

    def test_frames_with_slots_offset_non_negative(self, endpoint):
        c = self._constraints(endpoint, "/kgframes/kgslots", "GET", "offset")
        assert c.get("ge") == 0, f"offset must be non-negative, got {c}"


class TestListSlotsOrdering:
    """_build_list_slots_query — already ordered; guard against regression."""

    def test_has_order_by_before_limit(self, endpoint):
        sparql = endpoint._build_list_slots_query(
            backend=None, space_id="sp", graph_id="g", frame_uri=None,
            page_size=10, offset=0,
        )
        _assert_ordered_before_limit(sparql)
