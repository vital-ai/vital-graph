"""What `fast_slot_filter` agrees to answer, and what it must refuse.

`issues/161`. The table answers this shape ~300x faster than the BGP join, so
the pressure is all toward serving MORE. Every decline here exists because
serving it would produce a WRONG answer rather than a slow one, and a wrong
filter is invisible: it returns a subset with a plausible count and no error.
"""

from __future__ import annotations

from vitalgraph.db.sparql_sql.fast_slot_filter import (
    _eq_criteria, can_serve_filter)

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
TEXT = HALEY + "KGTextSlot"
NUM = HALEY + "KGIntegerSlot"


class _Slot:
    def __init__(self, slot_type="urn:s", slot_class_uri=TEXT, value="v",
                 comparator="eq"):
        self.slot_type, self.slot_class_uri = slot_type, slot_class_uri
        self.value, self.comparator = value, comparator


class _Frame:
    def __init__(self, frame_type="urn:f", slot_criteria=None,
                 frame_criteria=None):
        self.frame_type = frame_type
        self.slot_criteria = slot_criteria or []
        self.frame_criteria = frame_criteria or []


class _Crit:
    def __init__(self, **kw):
        self.entity_type = kw.pop("entity_type", "urn:e")
        self.frame_criteria = kw.pop("frame_criteria", None)
        for a in ("sort_criteria", "vector_criteria", "multi_vector_criteria",
                  "geo_criteria", "entity_property_filters", "entity_uris",
                  "search_string"):
            setattr(self, a, kw.pop(a, None))


def test_the_production_shape_is_served():
    assert can_serve_filter(_Crit(frame_criteria=[_Frame(slot_criteria=[_Slot()])]))


def test_a_conjunction_of_equalities_is_served():
    c = _Crit(frame_criteria=[_Frame(slot_criteria=[_Slot(slot_type="urn:a")]),
                              _Frame(slot_criteria=[_Slot(slot_type="urn:b")])])
    assert can_serve_filter(c)
    assert len(_eq_criteria(c.frame_criteria)) == 2


def test_a_non_equality_comparator_refuses_the_WHOLE_query():
    """Not just that conjunct — the whole query.

    The index answers equality. Serving the eq conjuncts and silently dropping a
    `gte` would return a SUPERSET, which is the wrong answer in the direction
    that looks most plausible.
    """
    c = _Crit(frame_criteria=[_Frame(slot_criteria=[_Slot(slot_type="urn:a")]),
                              _Frame(slot_criteria=[
                                  _Slot(slot_type="urn:b", comparator="gte")])])
    assert _eq_criteria(c.frame_criteria) is None
    assert not can_serve_filter(c)


def test_no_entity_type_refuses():
    """Without it the index cannot be probed on its leading columns.

    Measured: probing slot_type+value alone was 5.36s against 271ms with the
    full prefix. A 'served' query that scans the table is not a fast path.
    """
    assert not can_serve_filter(
        _Crit(entity_type=None, frame_criteria=[_Frame(slot_criteria=[_Slot()])]))


def test_a_frame_with_no_type_refuses():
    """frame_type is part of the stored path; without it the probe is unanchored."""
    c = _Crit(frame_criteria=[_Frame(frame_type=None, slot_criteria=[_Slot()])])
    assert not can_serve_filter(c)


def test_an_unknown_slot_class_refuses():
    """No lane means no column to compare — guessing one would compare nothing."""
    c = _Crit(frame_criteria=[
        _Frame(slot_criteria=[_Slot(slot_class_uri="urn:not:a:slot:class")])])
    assert not can_serve_filter(c)


def test_a_sort_belongs_to_the_other_path():
    c = _Crit(frame_criteria=[_Frame(slot_criteria=[_Slot()])],
              sort_criteria=[object()])
    assert not can_serve_filter(c)


def test_criteria_the_table_knows_nothing_about_refuse():
    for attr in ("vector_criteria", "geo_criteria", "entity_property_filters",
                 "entity_uris", "search_string"):
        c = _Crit(frame_criteria=[_Frame(slot_criteria=[_Slot()])], **{attr: ["x"]})
        assert not can_serve_filter(c), attr


def test_no_frame_criteria_is_not_this_path():
    assert not can_serve_filter(_Crit(frame_criteria=None))


def test_a_nested_frame_contributes_its_whole_path():
    """The table stores the ordered type path and matches it whole.

    A nested criterion must extend the parent's path, not replace it — matching
    only the leaf would return rows for that slot under ANY parent frame, which
    is a different question with a bigger answer.
    """
    c = _Crit(frame_criteria=[
        _Frame(frame_type="urn:outer",
               frame_criteria=[_Frame(frame_type="urn:inner",
                                      slot_criteria=[_Slot()])])])
    parsed = _eq_criteria(c.frame_criteria)
    assert parsed is not None
    assert parsed[0][0] == ["urn:outer", "urn:inner"]


def test_a_numeric_slot_keeps_its_lane():
    parsed = _eq_criteria([_Frame(slot_criteria=[_Slot(slot_class_uri=NUM,
                                                       value=65)])])
    assert parsed[0][2] == "num"
    assert parsed[0][3] == 65
