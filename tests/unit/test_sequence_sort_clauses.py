"""Unit tests for KGSparqlUtils.build_sort_clauses.

Every frame/slot builder routes its ORDER BY through this helper, so the
ordering contract is asserted once here rather than six times downstream.
Because the fix lives in the emitted SPARQL rather than in the shared ORDER BY
emitter, a builder that bypasses this helper silently reverts to lexical
ordering and DESC-nulls-first — which is exactly what these tests guard.

Contract (planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md §3):

    OPTIONAL { ?x <seq_prop> ?seq }
    BIND(IF(BOUND(?seq), 0, 1) AS ?missing)
    BIND(xsd:integer(?seq)     AS ?seq_num)
    ORDER BY ?missing <DIR>(?seq_num) ?anchor
"""

from __future__ import annotations

import pytest

from vitalgraph.kg_impl.kg_sparql_utils import KGSparqlUtils
from vitalgraph.model.kgframes_model import (
    _FRAME_SORT_PROPERTIES,
    _SLOT_SORT_PROPERTIES,
    _FRAME_SEQUENCE_PROPERTY,
    _SLOT_SEQUENCE_PROPERTY,
    validate_sort_params,
)

pytestmark = pytest.mark.unit

NAME_PROP = "http://vital.ai/ontology/vital-core#hasName"


class TestNoSort:
    """No sort_by → anchor ordering, which is still a total order."""

    def test_defaults_to_anchor_order(self):
        patterns, projection, order = KGSparqlUtils.build_sort_clauses("?frame", None)
        assert patterns == ""
        assert projection == ""
        assert order == "ORDER BY ?frame"

    def test_accepts_bare_anchor_name(self):
        """Anchor may be given with or without the leading '?'."""
        _, _, order = KGSparqlUtils.build_sort_clauses("frame", None)
        assert order == "ORDER BY ?frame"


class TestSequenceSort:
    """Sequence properties get the three-key numeric construct."""

    @pytest.mark.parametrize("prop", [
        _FRAME_SEQUENCE_PROPERTY, _SLOT_SEQUENCE_PROPERTY,
    ])
    def test_emits_all_three_keys_ascending(self, prop):
        patterns, projection, order = KGSparqlUtils.build_sort_clauses("?frame", prop, "asc")

        assert f"OPTIONAL {{ ?frame <{prop}> ?sort_val . }}" in patterns
        assert "BIND(IF(BOUND(?sort_val), 0, 1) AS ?sort_missing)" in patterns
        assert "BIND(xsd:integer(?sort_val) AS ?sort_num)" in patterns
        assert projection == "?sort_missing ?sort_num"
        assert order == "ORDER BY ?sort_missing ?sort_num ?frame"

    def test_descending_inverts_only_the_sequence_key(self, ):
        """The missing-flag must stay ASC or unsequenced rows lead on DESC."""
        _, _, order = KGSparqlUtils.build_sort_clauses(
            "?frame", _FRAME_SEQUENCE_PROPERTY, "desc")

        assert order == "ORDER BY ?sort_missing DESC(?sort_num) ?frame"
        assert "DESC(?sort_missing)" not in order

    def test_missing_flag_is_the_leading_key(self):
        """Unsequenced-last depends on the flag sorting before the value."""
        _, _, order = KGSparqlUtils.build_sort_clauses(
            "?slot", _SLOT_SEQUENCE_PROPERTY, "desc")
        terms = order.replace("ORDER BY ", "").split()
        assert terms[0] == "?sort_missing"

    def test_anchor_is_the_final_tiebreaker(self):
        """Duplicate sequence values still need a total order for paging."""
        for order_dir in ("asc", "desc"):
            _, _, order = KGSparqlUtils.build_sort_clauses(
                "?slot", _SLOT_SEQUENCE_PROPERTY, order_dir)
            assert order.rstrip().endswith("?slot")

    def test_uses_bound_not_truthiness(self):
        """Sequence 0 is a real value — a truthy test would misplace singletons."""
        patterns, _, _ = KGSparqlUtils.build_sort_clauses(
            "?frame", _FRAME_SEQUENCE_PROPERTY)
        assert "BOUND(?sort_val)" in patterns

    def test_var_prefix_avoids_collisions(self):
        """Two sorts in one query must not reuse variable names."""
        p1, _, o1 = KGSparqlUtils.build_sort_clauses(
            "?frame", _FRAME_SEQUENCE_PROPERTY, var_prefix="fsort")
        p2, _, o2 = KGSparqlUtils.build_sort_clauses(
            "?slot", _SLOT_SEQUENCE_PROPERTY, var_prefix="ssort")
        assert "?fsort_num" in o1 and "?ssort_num" in o2
        assert "fsort" not in p2 and "ssort" not in p1


class TestNonSequenceSort:
    """Ordinary properties keep the simpler lexical construct."""

    def test_lexical_sort_has_no_numeric_cast(self):
        patterns, projection, order = KGSparqlUtils.build_sort_clauses("?frame", NAME_PROP)

        assert f"OPTIONAL {{ ?frame <{NAME_PROP}> ?sort_val . }}" in patterns
        assert "xsd:integer" not in patterns
        assert "BOUND" not in patterns
        assert projection == "?sort_val"
        assert order == "ORDER BY ?sort_val ?frame"

    def test_lexical_descending(self):
        _, _, order = KGSparqlUtils.build_sort_clauses("?frame", NAME_PROP, "desc")
        assert order == "ORDER BY DESC(?sort_val) ?frame"

    def test_anchor_still_tiebreaks(self):
        _, _, order = KGSparqlUtils.build_sort_clauses("?frame", NAME_PROP, "desc")
        assert order.rstrip().endswith("?frame")


class TestSortPropertyRegistries:
    """The allow-lists actually contain the sequence properties."""

    def test_frame_sequence_is_sortable(self):
        assert _FRAME_SEQUENCE_PROPERTY in _FRAME_SORT_PROPERTIES

    def test_slot_sequence_is_sortable(self):
        assert _SLOT_SEQUENCE_PROPERTY in _SLOT_SORT_PROPERTIES

    def test_both_sequences_are_recognized_as_numeric(self):
        """A property in an allow-list but not SEQUENCE_PROPERTIES would sort
        lexically — the silent-failure mode this pairing guards."""
        assert _FRAME_SEQUENCE_PROPERTY in KGSparqlUtils.SEQUENCE_PROPERTIES
        assert _SLOT_SEQUENCE_PROPERTY in KGSparqlUtils.SEQUENCE_PROPERTIES

    def test_sequence_is_not_filterable(self):
        """Sequence is sortable only — there is no integer operator set."""
        from vitalgraph.model.kgframes_model import _FILTERABLE_FRAME_PROPERTIES
        assert _FRAME_SEQUENCE_PROPERTY not in _FILTERABLE_FRAME_PROPERTIES


class TestValidateSortParams:
    """Validation returns a message (→ INVALID_REQUEST body), never raises."""

    def test_none_is_valid(self):
        assert validate_sort_params(None, "asc", _FRAME_SORT_PROPERTIES) is None

    def test_allowed_property_is_valid(self):
        assert validate_sort_params(
            _FRAME_SEQUENCE_PROPERTY, "desc", _FRAME_SORT_PROPERTIES) is None

    def test_unknown_property_rejected(self):
        msg = validate_sort_params(
            "http://example.org/nope", "asc", _FRAME_SORT_PROPERTIES)
        assert msg and "not a sortable property" in msg

    def test_bad_sort_order_rejected(self):
        msg = validate_sort_params(None, "sideways", _FRAME_SORT_PROPERTIES)
        assert msg and "asc" in msg and "desc" in msg

    def test_slot_label_names_the_slot_param(self):
        """Error text must name the parameter the caller actually passed."""
        msg = validate_sort_params(
            "http://example.org/nope", "asc", _SLOT_SORT_PROPERTIES,
            "slot_sort_by")
        assert msg and "slot_sort_by" in msg

        msg = validate_sort_params(
            None, "sideways", _SLOT_SORT_PROPERTIES, "slot_sort_by")
        assert msg and "slot_sort_order" in msg

    def test_case_insensitive_order(self):
        assert validate_sort_params(None, "DESC", _FRAME_SORT_PROPERTIES) is None


class TestRelationSortRegistry:
    """hasListIndex is the ordering key for KG relations (step 6)."""

    def test_list_index_is_sortable_for_relations(self):
        from vitalgraph.model.kgrelations_model import (
            _RELATION_SORT_PROPERTIES, _RELATION_LIST_INDEX_PROPERTY)
        assert _RELATION_LIST_INDEX_PROPERTY in _RELATION_SORT_PROPERTIES

    def test_list_index_gets_the_numeric_construct(self):
        """It is an integer on VITAL_Edge, so it must not sort lexically.

        A property in the allow-list but missing from SEQUENCE_PROPERTIES would
        silently sort as text — 1,10,11,2 instead of 1,2,10,11.
        """
        from vitalgraph.model.kgrelations_model import _RELATION_LIST_INDEX_PROPERTY
        assert _RELATION_LIST_INDEX_PROPERTY in KGSparqlUtils.SEQUENCE_PROPERTIES

        patterns, projection, order = KGSparqlUtils.build_sort_clauses(
            "?s", _RELATION_LIST_INDEX_PROPERTY, "asc")
        assert "BIND(xsd:integer(?sort_val) AS ?sort_num)" in patterns
        assert "BIND(IF(BOUND(?sort_val), 0, 1) AS ?sort_missing)" in patterns
        assert projection == "?sort_missing ?sort_num"
        assert order == "ORDER BY ?sort_missing ?sort_num ?s"

    def test_unindexed_relations_sort_last_in_both_directions(self):
        from vitalgraph.model.kgrelations_model import _RELATION_LIST_INDEX_PROPERTY
        for direction in ("asc", "desc"):
            _, _, order = KGSparqlUtils.build_sort_clauses(
                "?s", _RELATION_LIST_INDEX_PROPERTY, direction)
            assert order.replace("ORDER BY ", "").split()[0] == "?sort_missing"

    def test_relation_sort_validation(self):
        from vitalgraph.model.kgrelations_model import (
            _RELATION_SORT_PROPERTIES, _RELATION_LIST_INDEX_PROPERTY)
        assert validate_sort_params(
            _RELATION_LIST_INDEX_PROPERTY, "desc", _RELATION_SORT_PROPERTIES) is None
        msg = validate_sort_params(
            "http://example.org/nope", "asc", _RELATION_SORT_PROPERTIES)
        assert msg and "not a sortable property" in msg


class TestReorderToMatch:
    """The shared order-restoration helper (§9c)."""

    class _Obj:
        def __init__(self, uri):
            self.URI = uri

    def test_reorders_to_the_given_sequence(self):
        objs = [self._Obj("c"), self._Obj("a"), self._Obj("b")]
        out = KGSparqlUtils.reorder_to_match(objs, ["a", "b", "c"])
        assert [o.URI for o in out] == ["a", "b", "c"]

    def test_unknown_uris_are_appended_not_dropped(self):
        objs = [self._Obj("c"), self._Obj("a")]
        out = KGSparqlUtils.reorder_to_match(objs, ["a"])
        assert [o.URI for o in out] == ["a", "c"]

    def test_empty_inputs_are_passthrough(self):
        assert KGSparqlUtils.reorder_to_match([], ["a"]) == []
        objs = [self._Obj("a")]
        assert KGSparqlUtils.reorder_to_match(objs, []) is objs

    def test_frames_endpoint_delegates_to_the_shared_helper(self):
        """KGFramesEndpoint._reorder_to_match must not drift from this one."""
        from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
        objs = [self._Obj("b"), self._Obj("a")]
        assert [o.URI for o in KGFramesEndpoint._reorder_to_match(objs, ["a", "b"])] \
            == ["a", "b"]
