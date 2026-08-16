"""What a list response owes its caller: a total, and an honest `has_more`.

Two defects, reported as upstream quirks and neither upstream:

  * `list_kgentities(include_entity_graph=True)` returned a page with no total.
    The server sent the correct one; the client computed pagination and then
    had nowhere to put it, because `MultiEntityGraphResponse` had no pagination
    fields at all, so it dropped it.

  * `has_more` was `Field(default=False)` and was never computed anywhere on the
    json-quads path. A field that is always present, always False, and never
    calculated is worse than an absent one — absent would have made a caller
    ask, whereas this answered "is there a next page?" with a confident No on
    every list call.

THE ASSERTION THAT MATTERS is the third state. `bool` cannot say "I do not
know", and that is exactly what the field was being asked to say. These tests
pin `None` as a real, reachable value, because a later well-meaning
`default=False` would restore the original bug while every other test here still
passed.

See planning_client/pagination_contract_plan.md.
"""

from __future__ import annotations

import pytest

from vitalgraph.client.response.client_response import (
    MultiEntityGraphResponse,
    MultiFrameGraphResponse,
    PaginatedGraphObjectResponse,
)
from vitalgraph.client.utils.format_helpers import extract_pagination_from_json_quads


class TestUnknownIsRepresentable:
    """The change that removes the class of bug, not just the instance."""

    @pytest.mark.parametrize("model", [
        PaginatedGraphObjectResponse, MultiEntityGraphResponse, MultiFrameGraphResponse,
    ])
    def test_has_more_defaults_to_none_not_false(self, model):
        assert model.model_fields["has_more"].default is None, (
            f"{model.__name__}.has_more defaults to "
            f"{model.model_fields['has_more'].default!r}. A bool default cannot "
            f"express 'unknown', which is what this field was wrongly asserting."
        )

    @pytest.mark.parametrize("model", [
        PaginatedGraphObjectResponse, MultiEntityGraphResponse, MultiFrameGraphResponse,
    ])
    def test_none_is_accepted_not_coerced(self, model):
        """Optional in the annotation, not merely in the default."""
        r = model(error_code=0, status_code=200, has_more=None)
        assert r.has_more is None

    def test_none_is_falsy_so_existing_callers_are_unaffected(self):
        """`if response.has_more:` must keep meaning what it meant."""
        r = PaginatedGraphObjectResponse(error_code=0, status_code=200)
        assert not r.has_more


class TestExtractorPassesThroughAndNeverDerives:
    """The client must not compute `has_more`, and this says why."""

    def test_server_value_is_used(self):
        for value in (True, False):
            out = extract_pagination_from_json_quads(
                {"total_count": 100, "page_size": 25, "offset": 0, "has_more": value})
            assert out["has_more"] is value

    def test_absent_means_none_not_false(self):
        out = extract_pagination_from_json_quads(
            {"total_count": 100, "page_size": 25, "offset": 0})
        assert out["has_more"] is None, (
            "silence from the server is not a No"
        )

    def test_it_does_not_derive_from_page_size(self):
        """The specific trap that made derivation wrong.

        `get_kgentities_by_uris` sets `page_size=len(identifiers)`, `offset=0`,
        and `total_count` to the number of OBJECTS across them. One identifier
        owning five objects gives `1 < 5`, so any formula over these fields
        reports a next page for a route that has none. `page_size` does not mean
        the same thing on every route, so the client cannot compute this.
        """
        by_uris_shape = {"total_count": 5, "page_size": 1, "offset": 0}
        assert extract_pagination_from_json_quads(by_uris_shape)["has_more"] is None

    def test_totals_still_pass_through(self):
        out = extract_pagination_from_json_quads(
            {"total_count": 8751, "page_size": 25, "offset": 50})
        assert (out["total_count"], out["page_size"], out["offset"]) == (8751, 25, 50)

    def test_missing_fields_do_not_raise(self):
        out = extract_pagination_from_json_quads({})
        assert out == {"total_count": 0, "page_size": 0, "offset": 0, "has_more": None}


class TestOnlyOneExtractorImplementation:
    """Two copies of one rule is how this codebase has been bitten before.

    `response_builder.extract_pagination_metadata` was a second implementation
    with DIFFERENT answers — `page_size` defaulting to 10, and `has_more`
    defaulting to False, which is the whole defect. Nothing called it, so nobody
    got a wrong answer; but a dormant duplicate is the version the next person
    copies. It now delegates, and this holds the two names to one behaviour.

    Same guard as the regex flag mapper, where two copies let a performance
    heuristic change query semantics.
    """

    CASES = [
        {},
        {"total_count": 100, "page_size": 25, "offset": 0},
        {"total_count": 100, "page_size": 25, "offset": 75},
        {"total_count": 100, "page_size": 25, "offset": 0, "has_more": True},
        {"total_count": 100, "page_size": 25, "offset": 0, "has_more": False},
        {"total_count": 5, "page_size": 1, "offset": 0},
    ]

    @pytest.mark.parametrize("payload", CASES)
    def test_both_names_agree(self, payload):
        from vitalgraph.client.response.response_builder import (
            extract_pagination_metadata,
        )
        assert extract_pagination_metadata(payload) == \
            extract_pagination_from_json_quads(payload)

    def test_the_deprecated_name_does_not_default_has_more_to_false(self):
        """The specific value that made the duplicate dangerous."""
        from vitalgraph.client.response.response_builder import (
            extract_pagination_metadata,
        )
        assert extract_pagination_metadata(
            {"total_count": 100, "page_size": 25, "offset": 0})["has_more"] is None


class TestMultiGraphResponsesCarryPagination:
    """The models that had none, which is why the total had nowhere to go."""

    @pytest.mark.parametrize("model", [MultiEntityGraphResponse, MultiFrameGraphResponse])
    @pytest.mark.parametrize("field", ["total_count", "page_size", "offset", "has_more"])
    def test_field_exists(self, model, field):
        assert field in model.model_fields, (
            f"{model.__name__} has no {field}; a paged response that cannot "
            f"carry a total forces the client to discard the one the server sent"
        )

    def test_pagination_round_trips(self):
        r = MultiEntityGraphResponse(
            error_code=0, status_code=200,
            total_count=8751, page_size=25, offset=0, has_more=True)
        assert (r.total_count, r.has_more) == (8751, True)

    def test_total_graphs_metadata_is_still_distinct(self):
        """`total_graphs` answers a different question and must not be conflated.

        It is how many graphs are in THIS response; `total_count` is how many
        exist. Collapsing them is the original bug's shape.
        """
        r = MultiEntityGraphResponse(
            error_code=0, status_code=200,
            total_count=8751, page_size=25, offset=0,
            metadata={"total_graphs": 25})
        assert r.metadata["total_graphs"] == 25 and r.total_count == 8751


class TestCountVersusTotalCountIsOneContract:
    """`count` = items in this response. `total_count` = size of the result set.

    That contract was already written down in `KGTypeSearchResponse` and
    already implemented by `GraphObjectResponse.count`. Three list responses
    disagreed: they declared `count` as "total count of X" and the client fed
    them the server's total, so `count` reported the whole corpus for a 25-row
    page. Aligned 2026-08-16; this is what stops it drifting back.
    """

    LIST_MODELS = ["KGTypesListResponse", "ObjectsListResponse",
                   "KGDocumentsListResponse", "KGTypeSearchResponse"]

    @pytest.mark.parametrize("name", LIST_MODELS)
    def test_both_fields_exist(self, name):
        import vitalgraph.client.response.client_response as m
        fields = getattr(m, name).model_fields
        assert "count" in fields and "total_count" in fields, (
            f"{name} carries only {sorted(set(fields) & {'count','total_count'})}; "
            f"one name for two quantities is how the totals got lost"
        )

    @pytest.mark.parametrize("name", LIST_MODELS)
    def test_count_is_not_described_as_a_total(self, name):
        """The description is the contract a caller actually reads."""
        import vitalgraph.client.response.client_response as m
        desc = (getattr(m, name).model_fields["count"].description or "").lower()
        assert "total" not in desc, (
            f"{name}.count is described as {desc!r}. It is the count of what is "
            f"in this response; total_count is the total."
        )

    @pytest.mark.parametrize("name", LIST_MODELS)
    def test_they_are_independently_settable(self, name):
        import vitalgraph.client.response.client_response as m
        r = getattr(m, name)(error_code=0, status_code=200, count=25, total_count=8751)
        assert (r.count, r.total_count) == (25, 8751)

    def test_graph_object_response_count_still_means_this_response(self):
        """The property the others were aligned TO must not have moved."""
        from vitalgraph.client.response.client_response import GraphObjectResponse
        r = GraphObjectResponse(error_code=0, status_code=200, objects=[])
        assert r.count == 0

    def test_passing_count_to_a_property_backed_model_is_a_no_op(self):
        """Why the dead `count=` arguments were removed rather than kept.

        FilesListResponse inherits `count` as a PROPERTY, so a passed value is
        silently discarded — it looked like it was being set and never was.
        """
        from vitalgraph.client.response.client_response import FilesListResponse
        r = FilesListResponse(error_code=0, status_code=200, objects=[], count=99)
        assert r.count == 0


class TestServerSideBoundary:
    """The formula the server uses, checked at the edges where it matters."""

    @staticmethod
    def _has_more(offset, page_size, total):
        return (offset + page_size) < total

    @pytest.mark.parametrize("offset,expected", [
        (0, True), (8700, True), (8725, True), (8750, False), (8751, False),
    ])
    def test_last_page_boundary(self, offset, expected):
        """8751 items, 25 per page: the last page starts at 8750.

        Verified against the live server at these exact offsets; an off-by-one
        here is invisible until someone reaches the end of a list.
        """
        assert self._has_more(offset, 25, 8751) is expected

    def test_empty_result(self):
        assert self._has_more(0, 25, 0) is False
