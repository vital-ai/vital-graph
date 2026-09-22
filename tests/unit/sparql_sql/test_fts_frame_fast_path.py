"""The FTS frame fast path serves from `entity_slot_sort`, or declines cleanly.

Measured on a 49.7M-quad space, 321,995-row message index (page of 25):

    broad `app` (118,935 matches)            pipeline  19,380 ms -> 1,128 ms
    broad + 30-day filter + date sort        pipeline 131,849 ms ->   680 ms
    `saved application` + filter + sort      pipeline 820,714 ms ->  ~7,000 ms
                                             (13.7 MINUTES, ordered rows and
                                              count identical either way)

The gate USED to be two-sided, declining a match set small enough for the
pipeline to inline (a 14-row phrase sorted by date: 115 ms there against
4,858 ms here). That inversion was a property of the test stack, not of the
data: re-measured on production, a filtered or sorted query is faster here at
every size, down to 72 matches (285 ms there against 44 ms here). So owner work
no longer declines at all; only PLAIN queries still have a size floor.

These tests pin the gate and the SQL contract. Equivalence itself is measured
against the pipeline on real data, not asserted here — a fast path that returns
a plausible subset is the failure mode this whole area keeps producing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

import pytest

from vitalgraph.db.sparql_sql.fast_fts_frame import (
    _build, _match_set_is_small, can_serve_fts_frame, fts_frame_decline_reason)

CREATED = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
NAME = "http://vital.ai/ontology/vital-core#hasName"
ENTITY_TYPE = "urn:acme:kg:entity:NurtureAction"
SENT = "urn:acme:kg:slot:MsgContent"
DRAFT = "urn:acme:kg:slot:GenMsgContent"


@dataclass
class _Target:
    slot_type: str
    frame_type: Optional[str] = None
    kind: Optional[str] = None


@dataclass
class _Fts:
    text: str = "saved"
    index_name: str = "message_content"
    targets: List[_Target] = field(default_factory=lambda: [_Target(SENT)])


@dataclass
class _Filter:
    property_uri: str
    operator: str
    value: Any


@dataclass
class _Sort:
    sort_type: str = "entity_property"
    property_uri: str = CREATED
    sort_order: str = "desc"


@dataclass
class _Criteria:
    entity_type: Optional[str] = ENTITY_TYPE
    fts_criteria: Optional[_Fts] = field(default_factory=_Fts)
    entity_property_filters: Optional[List[_Filter]] = None
    sort_criteria: Optional[List[_Sort]] = None
    slot_criteria: Any = None
    frame_criteria: Any = None
    frame_type: Any = None
    search_string: Any = None
    entity_uris: Any = None
    vector_criteria: Any = None
    multi_vector_criteria: Any = None
    geo_criteria: Any = None
    graph_uri: str = "urn:acme_kg"


def _sql(criteria, *, for_count=False, cap=None, page_size=25, offset=0) -> str:
    sql, _args = _build("sp", criteria, "sp_fts_message_content", "english",
                        for_count=for_count, cap=cap, page_size=page_size,
                        offset=offset)
    return sql


class TestTheGate:
    def test_it_serves_the_portal_shape(self):
        c = _Criteria(fts_criteria=_Fts(targets=[_Target(SENT, kind="sent"),
                                                 _Target(DRAFT, kind="draft")]),
                      entity_property_filters=[_Filter(CREATED, "gte", "2026-08-01T00:00:00Z")],
                      sort_criteria=[_Sort()])
        assert can_serve_fts_frame(c), fts_frame_decline_reason(c)

    def test_every_decline_says_why(self):
        """`issues/161`'s lesson: the paths differ by orders of magnitude, so a
        bare False is not actionable."""
        cases = {
            "no fts_criteria": _Criteria(fts_criteria=None),
            "no entity_type": _Criteria(entity_type=None),
            "slot_criteria present": _Criteria(slot_criteria=[object()]),
            "frame_type present": _Criteria(frame_type="urn:acme:kg:frame:MessageFrame"),
            "entity_uris present": _Criteria(entity_uris=["urn:e:1"]),
        }
        for expected, c in cases.items():
            assert fts_frame_decline_reason(c) == expected

    def test_it_declines_what_the_lanes_cannot_express(self):
        unregistered = _Criteria(entity_property_filters=[
            _Filter("urn:acme:not:registered", "eq", "x")])
        assert "unregistered" in fts_frame_decline_reason(unregistered)
        list_valued = _Criteria(entity_property_filters=[
            _Filter("http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList",
                    "has_any", ["a"])])
        assert fts_frame_decline_reason(list_valued) is not None
        bad_op = _Criteria(entity_property_filters=[_Filter(NAME, "contains", "x")])
        assert "not served here" in fts_frame_decline_reason(bad_op)
        two_sorts = _Criteria(sort_criteria=[_Sort(), _Sort()])
        assert fts_frame_decline_reason(two_sorts) == "more than one sort"
        slot_sort = _Criteria(sort_criteria=[_Sort(sort_type="slot_value")])
        assert "not served here" in fts_frame_decline_reason(slot_sort)


class TestTheSizeGate:
    """A filter or sort is served here at ANY match-set size.

    The size gate exists because a match set the pipeline INLINES is faster
    there. Measured on production that is not true once the query carries owner
    work: at 72 matches the pipeline is 285 ms against 44 ms here, and it only
    gets worse with size (4,600 matches: 17,979 ms against 312 ms). The portal's
    type-ahead is exactly the small end, one query per keystroke.
    """

    class _ExplodingConn:
        """The gate must not reach the database to answer this."""

        async def fetchval(self, *a, **k):  # pragma: no cover - must not run
            raise AssertionError("the size probe ran for a filter/sort shape")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("criteria", [
        _Criteria(sort_criteria=[_Sort()]),
        _Criteria(entity_property_filters=[_Filter(CREATED, "gte", "2026-08-01T00:00:00Z")]),
        _Criteria(sort_criteria=[_Sort()],
                  entity_property_filters=[_Filter(CREATED, "gte", "2026-08-01T00:00:00Z")]),
    ], ids=["sort", "filter", "both"])
    async def test_owner_work_never_declines_and_never_probes(self, criteria):
        small = await _match_set_is_small(
            self._ExplodingConn(), "sp_fts_message_content", "english", criteria)
        assert small is False


class TestTheSql:
    def test_the_page_is_distinct_on_the_frame(self):
        """One entity reaches a frame through several slots; `issues/223` is
        what counting those twice looks like."""
        assert "SELECT DISTINCT s.frame_uuid" in _sql(_Criteria())

    def test_unsorted_pages_follow_the_pipeline_order(self):
        sql = _sql(_Criteria())
        assert "ORDER BY s.frame_uuid" in sql, (
            "the pipeline synthesizes a frame-uuid order for an unsorted page; "
            "a different key here would make the two paths page differently")

    def test_a_sort_ties_on_the_frame_uri_text(self):
        sql = _sql(_Criteria(sort_criteria=[_Sort()]))
        assert "ORDER BY sort_val DESC, frame_uri ASC" in sql
        # The collation belongs on the SELECT alias: an ORDER BY output name is
        # only usable bare, so `frame_uri COLLATE "C"` resolves against input
        # columns and fails.
        assert 'ft.term_text COLLATE "C" AS frame_uri' in sql

    def test_a_date_bound_is_converted_not_cast(self):
        """`ed165956`: `::timestamp` ignores the offset, and `value_dt` is
        `vitalgraph_iso_to_utc(term_text)`."""
        sql = _sql(_Criteria(entity_property_filters=[
            _Filter(CREATED, "gte", "2026-08-01T00:00:00+05:00")]))
        assert "vitalgraph_iso_to_utc(" in sql and "::timestamp" not in sql
        assert "e.value_dt IS NOT NULL" in sql

    def test_every_target_slot_type_is_included(self):
        sql, args = _build("sp", _Criteria(fts_criteria=_Fts(
            targets=[_Target(SENT, kind="sent"), _Target(DRAFT, kind="draft")])),
            "sp_fts_message_content", "english", for_count=False, cap=None,
            page_size=25, offset=0)
        assert "s.slot_type_uuid = ANY(" in sql
        assert any(isinstance(a, list) and len(a) == 2 for a in args)

    def test_the_count_is_bounded_by_the_cap(self):
        sql = _sql(_Criteria(), for_count=True, cap=1000)
        assert "LIMIT 1001" in sql and "count(*)" in sql

    def test_the_search_text_is_a_parameter_not_interpolated(self):
        sql, args = _build("sp", _Criteria(fts_criteria=_Fts(text="o'brien \" --")),
                           "sp_fts_message_content", "english", for_count=False,
                           cap=None, page_size=25, offset=0)
        assert "o'brien" not in sql
        assert "o'brien \" --" in args
