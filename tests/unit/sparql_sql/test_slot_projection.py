"""Resolving and assembling a slot-value projection (`issues/208`).

The SQL half of this is measured, not argued: 0.76 ms and 1,163 buffers for a
25-entity page and eight columns on a 74.5M-quad fixture, against 57.65 ms and
62,953 buffers for the same eight values from the quads. What these tests pin is
everything AROUND the probe, because that is where a projection turns a slow
answer into a wrong one:

  * a column that cannot be answered declines the WHOLE projection, since a
    partially applied one is a blank column and a blank column reads as
    "no value set";
  * a row counts for a column only when its frame_type_path matches WHOLE —
    the wrong-rows failure `component_intersect.py:39` records;
  * several slots of one type come back as several values, because an entity
    carrying six of them is real (9,354 such pairs on `prod_kg`, 1,200 on
    `kg_load_test`) and picking one silently would be a decision the caller
    never made;
  * the lane follows the caller's `slot_class_uri`, which is the whole design
    decision here — the table does not record which value predicate produced a
    row, so nothing else can decide it.
"""

from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid
from vitalgraph.db.sparql_sql.slot_projection import (
    project_slot_values, resolve_columns)
from vitalgraph.model.kgqueries_model import SlotProjection

_KG = "http://vital.ai/ontology/haley-ai-kg#"
_F1, _F2 = "urn:t:frame:Outer", "urn:t:frame:Inner"
_OTHER = "urn:t:frame:Elsewhere"
_SLOT = "urn:t:slot:Name"
_E = "urn:t:e:1"


def _col(alias="name", path=(_F1, _F2), slot=_SLOT, cls="KGTextSlot"):
    return SlotProjection(alias=alias, frame_path=list(path), slot_type=slot,
                          slot_class_uri=_KG + cls)


class _Conn:
    """Returns the rows it was given, and records the arguments it was asked with."""

    def __init__(self, rows):
        self._rows = rows
        self.args = None

    async def fetch(self, sql, *args):
        self.args = args
        return self._rows


def _row(path, slot=_SLOT, text=None, num=None, dt=None, entity=_E):
    return {"entity_uuid": _term_uuid(entity),
            "frame_type_path": [_term_uuid(f) for f in path],
            "slot_type_uuid": _term_uuid(slot),
            "value_text": text, "value_num": num, "value_dt": dt}


def test_resolve_maps_the_class_to_a_lane():
    cols = resolve_columns([_col(cls="KGDoubleSlot"), _col(alias="when", cls="KGDateTimeSlot")])
    assert [c.lane for c in cols] == ["num", "dt"]


def test_one_unanswerable_column_declines_the_whole_projection():
    """A partial projection is a blank column, which looks like a missing value."""
    class _Raw:
        alias, slot_type, slot_class_uri = "x", "urn:t:slot:X", "urn:not:a:slot:class"
        frame_path = [_F1]

    assert resolve_columns([_col(), _Raw()]) is None


def test_no_projection_is_not_an_empty_projection():
    assert resolve_columns(None) is None
    assert resolve_columns([]) is None


async def test_a_value_under_a_different_frame_path_is_not_the_column():
    """The failure this would otherwise produce is a plausible wrong value.

    Same slot type, different path: a slot of this type genuinely exists under
    `Elsewhere`, and counting it would put another frame's value in this column.
    """
    conn = _Conn([_row((_F1, _F2), text="right"),
                  _row((_OTHER,), text="wrong")])
    out = await project_slot_values(conn, "sp", "urn:g", [_E], resolve_columns([_col()]))

    assert out[_E]["name"] == ["right"]


async def test_every_alias_is_present_even_with_no_value():
    """An absent KEY cannot be told from a column that was never asked for."""
    conn = _Conn([])
    cols = resolve_columns([_col(), _col(alias="other", slot="urn:t:slot:Other")])
    out = await project_slot_values(conn, "sp", "urn:g", [_E], cols)

    assert out == {_E: {"name": [], "other": []}}


async def test_several_slots_of_one_type_all_come_back():
    """Measured real: 1,200 pairs on `kg_load_test`, up to 3; 9,354 on prod_kg.

    Sorted, so two identical requests render them in the same order.
    """
    conn = _Conn([_row((_F1, _F2), text="b"), _row((_F1, _F2), text="a"),
                  _row((_F1, _F2), text="c")])
    out = await project_slot_values(conn, "sp", "urn:g", [_E], resolve_columns([_col()]))

    assert out[_E]["name"] == ["a", "b", "c"]


async def test_the_lane_comes_from_the_class_the_caller_named():
    """The design decision, pinned.

    One row carrying BOTH a text and a numeric value: which one this column
    returns is decided by `slot_class_uri` and by nothing else, because the
    table does not record which predicate produced the row.
    """
    row = _row((_F1, _F2), text="12", num=12)
    as_text = await project_slot_values(
        _Conn([row]), "sp", "urn:g", [_E], resolve_columns([_col(cls="KGTextSlot")]))
    as_num = await project_slot_values(
        _Conn([row]), "sp", "urn:g", [_E], resolve_columns([_col(cls="KGDoubleSlot")]))

    assert as_text[_E]["name"] == ["12"]
    assert as_num[_E]["name"] == [12]


async def test_the_probe_is_entity_led_and_asks_for_the_page_only():
    """Entity-led is what makes seven frame paths cost ONE probe.

    Pins the arguments rather than the SQL text: context, the page's entity
    uuids, and the slot types -- no frame path in the WHERE, which is what
    would force one arm per path (measured 5x slower).
    """
    conn = _Conn([])
    cols = resolve_columns([_col(), _col(alias="two", path=(_OTHER,),
                                         slot="urn:t:slot:Two")])
    await project_slot_values(conn, "sp", "urn:g", [_E, "urn:t:e:2"], cols)

    ctx, entities, slots = conn.args
    assert ctx == _term_uuid("urn:g")
    assert set(entities) == {_term_uuid(_E), _term_uuid("urn:t:e:2")}
    assert set(slots) == {_term_uuid(_SLOT), _term_uuid("urn:t:slot:Two")}


async def test_an_entity_not_on_the_page_is_ignored():
    """The probe is by uuid; a row for another entity must not invent a key."""
    conn = _Conn([_row((_F1, _F2), text="x", entity="urn:t:e:stranger")])
    out = await project_slot_values(conn, "sp", "urn:g", [_E], resolve_columns([_col()]))

    assert out == {_E: {"name": []}}
