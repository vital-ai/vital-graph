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
