"""Projecting DIRECT entity properties, from the quads (`issues/208`).

The sibling of `test_slot_projection`, and the differences are the point:

  * It reads the QUADS, not `entity_prop_sort`. Measured at 0.31 ms against
    that table's 0.07 ms for five columns over a 25-entity page — noise beside
    the slot half's 0.76 ms — and the quads cannot be stale, so this half needs
    no coverage gate and cannot render a column blank because a derived table
    fell behind. It also reaches every property rather than the seven
    `SORTABLE_PROPERTY_URIS` maintains.
  * There is no lane and no declared datatype. A quad carries its object
    directly, so the lexical form IS the value; `SlotProjection` needs a slot
    class only because the sort table splits values across three columns.

What is the SAME is what matters for a caller: every alias present for every
entity, values as a sorted list, and one bad column declining the whole
projection rather than returning a blank one.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid
from vitalgraph.db.sparql_sql.property_projection import (
    project_property_values, resolve_property_columns)
from vitalgraph.model.kgqueries_model import PropertyProjection

_NAME = "http://vital.ai/ontology/vital-core#hasName"
_STATUS = "http://vital.ai/ontology/vital-aimp#hasObjectStatusType"
_E = "urn:t:e:1"


def _col(alias="name", prop=_NAME):
    return PropertyProjection(alias=alias, property_uri=prop)


class _Conn:
    def __init__(self, rows):
        self._rows = rows
        self.args = None

    async def fetch(self, sql, *args):
        self.args = args
        return self._rows


def _row(prop, text, entity=_E):
    return {"subject_uuid": _term_uuid(entity),
            "predicate_uuid": _term_uuid(prop), "term_text": text}


def test_resolve_needs_an_alias_and_a_property():
    class _Raw:
        alias, property_uri = "x", ""

    assert resolve_property_columns([_Raw()]) is None
    assert resolve_property_columns(None) is None
    assert resolve_property_columns([]) is None


async def test_values_come_back_per_alias():
    conn = _Conn([_row(_NAME, "Acme"), _row(_STATUS, "urn:status:Active")])
    cols = resolve_property_columns([_col(), _col("status", _STATUS)])
    out = await project_property_values(conn, "sp", "urn:g", [_E], cols)

    assert out == {_E: {"name": ["Acme"], "status": ["urn:status:Active"]}}


async def test_every_alias_is_present_even_with_no_value():
    conn = _Conn([])
    out = await project_property_values(
        conn, "sp", "urn:g", [_E], resolve_property_columns([_col()]))

    assert out == {_E: {"name": []}}


async def test_a_multi_valued_property_returns_every_value_sorted():
    """The quad probe's order is by object uuid — a hash, arbitrary to a reader."""
    conn = _Conn([_row(_NAME, "c"), _row(_NAME, "a"), _row(_NAME, "b")])
    out = await project_property_values(
        conn, "sp", "urn:g", [_E], resolve_property_columns([_col()]))

    assert out[_E]["name"] == ["a", "b", "c"]


async def test_two_aliases_may_name_the_same_property():
    """Nothing forbids it, and the probe must not drop one of them."""
    conn = _Conn([_row(_NAME, "Acme")])
    cols = resolve_property_columns([_col("a"), _col("b")])
    out = await project_property_values(conn, "sp", "urn:g", [_E], cols)

    assert out == {_E: {"a": ["Acme"], "b": ["Acme"]}}


async def test_the_probe_is_subject_led_and_bounded_by_the_page():
    conn = _Conn([])
    cols = resolve_property_columns([_col(), _col("status", _STATUS)])
    await project_property_values(conn, "sp", "urn:g", [_E, "urn:t:e:2"], cols)

    ctx, subjects, preds = conn.args
    assert ctx == _term_uuid("urn:g")
    assert set(subjects) == {_term_uuid(_E), _term_uuid("urn:t:e:2")}
    assert set(preds) == {_term_uuid(_NAME), _term_uuid(_STATUS)}


async def test_a_quad_for_another_entity_is_ignored():
    conn = _Conn([_row(_NAME, "x", entity="urn:t:e:stranger")])
    out = await project_property_values(
        conn, "sp", "urn:g", [_E], resolve_property_columns([_col()]))

    assert out == {_E: {"name": []}}
