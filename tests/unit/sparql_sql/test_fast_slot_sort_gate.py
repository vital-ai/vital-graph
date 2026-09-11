"""What `fast_slot_sort` agrees to sort, and what it must refuse.

`issues/096`. Sibling of `test_fast_slot_filter_gate`, and it exists because the
sort gate had NO unit test while the filter gate did. That gap is not
hypothetical: `issues/172` moved frame criteria from declined to served, and the
prose in `096` went on saying they declined until 2026-09-11, which is long
enough for the list to have been used to pick work.

Two different reasons to decline are mixed together here, and they are not
equally negotiable:

  WRONG ANSWER  — no frame hop. A slot hanging directly off an entity is not in
                  `entity_slot_sort` at all, so serving it from frame-borne rows
                  returns a plausible, wrongly-ordered page with no error.
  WRONG PLAN    — no entity type. The index cannot be probed on its leading
                  columns, so the "fast" path would scan the whole table.

`entity_uris` gets its own test below. It is the shape measured at 87x WORSE
when the slot end is pinned, so the direction gate planned in `096` reads it as
its first and exact test — which only works while this gate keeps declining it
and letting it reach the general pipeline.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.fast_slot_sort import can_serve

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
TEXT = HALEY + "KGTextSlot"


class _Sort:
    def __init__(self, sort_type="entity_frame_slot", slot_type="urn:s",
                 slot_class_uri=TEXT, frame_path=("urn:f",)):
        self.sort_type, self.slot_type = sort_type, slot_type
        self.slot_class_uri = slot_class_uri
        self.frame_path = list(frame_path)


class _Crit:
    def __init__(self, **kw):
        self.entity_type = kw.pop("entity_type", "urn:e")
        self.sort_criteria = kw.pop("sort_criteria", [_Sort()])
        for a in ("frame_criteria", "vector_criteria", "multi_vector_criteria",
                  "geo_criteria", "entity_property_filters", "entity_uris",
                  "slot_criteria", "search_string"):
            setattr(self, a, kw.pop(a, None))
        assert not kw, kw


def test_the_production_shape_is_served():
    assert can_serve(_Crit())


@pytest.mark.parametrize("sort_type", ["entity_frame_slot", "frame_slot"])
def test_both_sort_types_are_served(sort_type):
    assert can_serve(_Crit(sort_criteria=[_Sort(sort_type=sort_type)]))


# --- wrong answer if served -------------------------------------------------

def test_a_slot_directly_on_the_entity_is_refused():
    """Not in the table. Serving it is a wrong page, not a slow one."""
    assert not can_serve(_Crit(sort_criteria=[_Sort(frame_path=())]))


# --- wrong plan if served ---------------------------------------------------

def test_no_entity_type_is_refused():
    assert not can_serve(_Crit(entity_type=None))


# --- outside what the table stores ------------------------------------------

def test_no_sort_criteria_is_refused():
    assert not can_serve(_Crit(sort_criteria=[]))


def test_a_second_sort_key_is_refused():
    """The index orders ONE value column; a second key would re-sort the page."""
    assert not can_serve(_Crit(sort_criteria=[_Sort(), _Sort(slot_type="urn:b")]))


def test_an_unknown_sort_type_is_refused():
    assert not can_serve(_Crit(sort_criteria=[_Sort(sort_type="entity_property")]))


def test_no_slot_type_is_refused():
    assert not can_serve(_Crit(sort_criteria=[_Sort(slot_type=None)]))


def test_a_value_lane_the_table_does_not_split_on_is_refused():
    assert not can_serve(_Crit(sort_criteria=[_Sort(slot_class_uri=HALEY + "KGGeoSlot")]))


# --- criteria the sort path does not carry ----------------------------------

def test_entity_uris_is_refused_and_the_direction_gate_depends_on_it():
    """The 87x regression shape in `096`, and the gate's first test.

    Pinning the slot end for a sort already pinned to one entity measured 222 ->
    133,067 buffers, 0.7 ms -> 60.8 ms. The gate avoids that by reading
    `entity_uris` directly rather than comparing statistics — exact, syntactic,
    no `rdf_stats` round trip. That only ever runs if this gate declines first.
    """
    assert not can_serve(_Crit(entity_uris=["urn:e:1"]))


def test_entity_property_filters_are_refused():
    assert not can_serve(_Crit(entity_property_filters=[object()]))


@pytest.mark.parametrize("attr", ["vector_criteria", "multi_vector_criteria",
                                  "geo_criteria", "slot_criteria",
                                  "search_string"])
def test_criteria_the_table_cannot_answer_are_refused(attr):
    assert not can_serve(_Crit(**{attr: ["x"]}))


# --- the 172 correction, pinned so the prose cannot drift back --------------

def test_an_equality_frame_criterion_IS_served():
    """`issues/172`. This was a decline, and `096` described it as one until
    2026-09-11. Serving a FILTERED, SORTED list is the main list view; when
    neither gate took it, it fell to the general pipeline and did not finish in
    120 s on a 74.2M-quad space."""
    from vitalgraph.db.sparql_sql.fast_slot_filter import _eq_criteria

    class _Slot:
        slot_type, slot_class_uri, value, comparator = "urn:s2", TEXT, "v", "eq"

    class _Frame:
        frame_type, slot_criteria, frame_criteria = "urn:f", [_Slot()], []

    c = _Crit(frame_criteria=[_Frame()])
    assert _eq_criteria(c.frame_criteria), "precondition: parses as an equality"
    assert can_serve(c)
