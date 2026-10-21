"""The sort tables index a bounded `value_key`, and the readers decline past it.

`issues/283`: `entity_slot_sort`, `entity_prop_sort` and `frame_prop_sort`
btree-indexed the whole `value_text` (and GIN-indexed `value_all`), both capped
near 2.7 KB, so one long value failed the write that carried it:

    index row size 3320 exceeds btree version 4 maximum 2704 for index
    "idx_<space>_ess_text"

The indexes now cover `left(value_text, VALUE_KEY_CHARS)`. That is exact for
every literal shorter than the key and inexact for the rest, so these pin both
halves: nothing indexes the unbounded column, and every fast path that compares
against the key DECLINES a literal it cannot answer. A served-but-inexact
comparison is a wrong answer; a decline is only a slower one.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

import pytest

from vitalgraph.db.sparql_sql.sort_value_key import (
    VALUE_KEY_CHARS, VALUE_KEY_COLUMN, fits_value_key)
from vitalgraph.db.sparql_sql.space_names import space_prefix

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
TEXT = HALEY + "KGTextSlot"
LONG_TEXT = HALEY + "KGLongTextSlot"
SHORT = "x" * (VALUE_KEY_CHARS - 1)
AT_BOUND = "x" * VALUE_KEY_CHARS
SPACE = "sp_x"


class TestTheBound:

    def test_one_under_fits_and_the_bound_itself_does_not(self):
        # At exactly VALUE_KEY_CHARS the key holds the whole literal, but a
        # LONGER stored value cut to the same length would compare equal to it.
        assert fits_value_key(SHORT)
        assert not fits_value_key(AT_BOUND)

    def test_characters_not_bytes(self):
        # PostgreSQL's left() counts characters; so must the guard, or a
        # multibyte literal is judged by a length the column never applied.
        assert fits_value_key("é" * (VALUE_KEY_CHARS - 1))

    def test_a_list_fits_only_if_every_element_does(self):
        assert fits_value_key(["a", SHORT])
        assert not fits_value_key(["a", AT_BOUND])

    def test_the_worst_case_key_fits_a_btree_entry(self):
        # 4 bytes per character is UTF-8's ceiling; the btree cap is 2,704.
        assert VALUE_KEY_CHARS * 4 <= 1024 < 2704


class TestTheSchema:

    @pytest.fixture(scope="class")
    def ddl(self):
        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        sch = SparqlSQLSchema()
        return (sch.create_space_tables_sql(SPACE),
                sch.create_space_indexes_sql(SPACE))

    @pytest.mark.parametrize("table", ["entity_slot_sort", "entity_prop_sort",
                                       "frame_prop_sort"])
    def test_each_sort_table_generates_the_key(self, ddl, table):
        tables, _ = ddl
        stmt = next(s for s in tables
                    if f"CREATE TABLE IF NOT EXISTS {space_prefix(SPACE)}_{table} " in s)
        assert (f"{VALUE_KEY_COLUMN} TEXT GENERATED ALWAYS AS "
                f"(left(value_text, {VALUE_KEY_CHARS})) STORED") in stmt

    def test_no_index_on_a_sort_table_covers_the_unbounded_text(self, ddl):
        _, indexes = ddl
        offenders = [s for s in indexes
                     if re.search(rf"ON {space_prefix(SPACE)}_(entity_slot|entity_prop|frame_prop)_sort\b", s)
                     and "value_text" in s]
        assert not offenders, (
            "a btree over value_text fails the write of any value past ~2.7 KB:\n  "
            + "\n  ".join(offenders))

    @pytest.mark.parametrize("suffix", ["ess_text", "eps_text", "eps_any_text",
                                        "eps_text_desc", "fps_text",
                                        "fps_any_text", "fps_form_text"])
    def test_every_text_index_is_on_the_key(self, ddl, suffix):
        _, indexes = ddl
        stmt = next(s for s in indexes
                    if f"INDEX IF NOT EXISTS idx_{space_prefix(SPACE)}_{suffix} " in s)
        assert f'{VALUE_KEY_COLUMN} COLLATE "C"' in stmt


class TestValueAllIsBounded:

    @pytest.mark.parametrize("mod", ["sync_entity_prop_sort", "sync_frame_prop_sort"])
    def test_the_derivation_bounds_each_element(self, mod):
        import importlib
        m = importlib.import_module(f"vitalgraph.db.sparql_sql.{mod}")
        sql = m._select_rows(SPACE, "TRUE")
        assert (f"array_agg(DISTINCT left(t.term_text, {VALUE_KEY_CHARS})) "
                f"AS value_all") in sql


class TestTheSlotFilterDeclines:

    @staticmethod
    def _crit(value, cls=TEXT):
        from types import SimpleNamespace as NS
        slot = NS(slot_type="urn:s", slot_class_uri=cls, value=value,
                  comparator="eq")
        frame = NS(frame_type="urn:f", negate=False, slot_criteria=[slot],
                   frame_criteria=[])
        return NS(entity_type="urn:e", frame_criteria=[frame])

    def test_a_short_text_value_is_served_on_the_key(self):
        from vitalgraph.db.sparql_sql.fast_slot_filter import _build, can_serve_filter
        c = self._crit(SHORT)
        assert can_serve_filter(c)
        sql, _args = _build(SPACE, "urn:g", c)
        assert "value_key = $5" in sql

    def test_a_value_at_the_bound_declines(self):
        from vitalgraph.db.sparql_sql.fast_slot_filter import (
            can_serve_filter, filter_decline_reason)
        c = self._crit(AT_BOUND)
        assert not can_serve_filter(c)
        assert "issues/283" in filter_decline_reason(c)

    def test_the_sorted_filter_declines_too(self):
        # `fast_slot_sort.can_serve` reads the same criteria through
        # `_eq_criteria`; a long value must not reach `_filter_exists`.
        from vitalgraph.db.sparql_sql.fast_slot_filter import _eq_criteria
        assert _eq_criteria(self._crit(AT_BOUND).frame_criteria) is None


class TestTheSlotSortReadsTheKey:

    def test_the_text_lane_orders_by_the_key(self):
        from vitalgraph.db.sparql_sql.fast_slot_sort import _LANE_SQL
        col, mn, mx = _LANE_SQL["text"]
        assert col == "value_key"
        assert mn == 'MIN(value_key COLLATE "C")'
        assert mx == 'MAX(value_key COLLATE "C")'


class TestThePropSortDeclines:

    def test_entity_listing_declines_a_long_status(self):
        from vitalgraph.db.sparql_sql.fast_prop_sort import _filter_terms
        assert _filter_terms({"status": SHORT}) is not None
        assert _filter_terms({"status": AT_BOUND}) is None

    def test_frame_listing_declines_a_long_frame_type(self):
        from vitalgraph.db.sparql_sql.fast_frame_prop_sort import _filter_terms
        assert _filter_terms({"frame_type_uri": "urn:t"}) is not None
        assert _filter_terms({"frame_type_uri": AT_BOUND}) is None

    def test_a_text_sort_reads_the_key(self):
        from vitalgraph.db.sparql_sql.fast_prop_sort import build_page_sql
        sql, _ = build_page_sql(SPACE, [], "http://vital.ai/ontology/vital-core#hasName",
                                descending=False)
        assert 's.value_key COLLATE "C" ASC' in sql
        assert "value_text" not in sql

    def test_a_frame_text_sort_reads_the_key(self):
        from vitalgraph.db.sparql_sql.fast_frame_prop_sort import build_frame_page_sql
        sql, _ = build_frame_page_sql(SPACE, [], "http://vital.ai/ontology/vital-core#hasName",
                                      descending=True)
        assert 's.value_key COLLATE "C" DESC' in sql
        assert "value_text" not in sql


@dataclass
class _Target:
    slot_type: str = "urn:slot"
    frame_type: Optional[str] = None
    kind: Optional[str] = None


@dataclass
class _Fts:
    text: str = "saved"
    index_name: str = "message_content"
    targets: List[_Target] = field(default_factory=lambda: [_Target()])


@dataclass
class _Filter:
    property_uri: str
    operator: str
    value: Any


@dataclass
class _FtsCriteria:
    entity_property_filters: Optional[List[_Filter]] = None
    entity_type: Optional[str] = "urn:e"
    fts_criteria: Optional[_Fts] = field(default_factory=_Fts)


class TestTheFtsFramePathDeclines:

    NAME = "http://vital.ai/ontology/vital-core#hasName"

    def test_a_short_name_filter_is_served_on_the_key(self):
        from vitalgraph.db.sparql_sql.fast_fts_frame import (
            _build, fts_frame_decline_reason)
        c = _FtsCriteria([_Filter(self.NAME, "eq", SHORT)])
        c.graph_uri = "urn:g"
        assert fts_frame_decline_reason(c) is None
        sql, _ = _build(SPACE, c, f"{space_prefix(SPACE)}_fts_m", "english", for_count=False,
                        cap=None, page_size=10, offset=0)
        assert 'e.value_key COLLATE "C" =' in sql

    def test_a_long_name_filter_declines(self):
        from vitalgraph.db.sparql_sql.fast_fts_frame import fts_frame_decline_reason
        c = _FtsCriteria([_Filter(self.NAME, "eq", AT_BOUND)])
        assert "too long" in (fts_frame_decline_reason(c) or "")


class TestComponentIntersectGuards:

    def test_the_probe_is_skipped_for_a_long_literal(self):
        # Source-level: reaching the call site needs a compiled BGP. The guard
        # must sit before the SQL is built, or a long literal is compared
        # against a prefix that cannot tell it from its neighbours.
        from vitalgraph.db.sparql_sql import component_intersect
        src = inspect.getsource(component_intersect)
        guard = src.index("if not fits_value_key(value):")
        emit = src.index('f"AND value_key COLLATE')
        assert guard < emit
