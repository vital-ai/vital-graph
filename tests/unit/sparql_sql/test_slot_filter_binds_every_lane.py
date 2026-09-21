"""A slot criterion carries JSON, and every lane must be able to bind it.

`SlotCriteria.value` is `Optional[Any]`, so what arrives from the API is
whatever the client sent -- a STRING for a date, an int or a FLOAT for a number
-- while `value_dt` is TIMESTAMP and `value_num` is NUMERIC. The probe bound the
value straight against the column, so asyncpg typed the parameter from the
column and refused it:

    asyncpg.exceptions.DataError: invalid input for query argument $5:
        '2026-06-23T14:00:00.000Z' (expected a datetime.date or
        datetime.datetime instance, got 'str')

Both `fast_slot_filter_count` and `fast_slot_filter_page` catch that at DEBUG
and return None, so the answer stayed correct and the query fell to the BGP
join this path measures ~300x faster than. Nothing was wrong except the speed,
and nothing said so: a decline and a crash-then-decline look identical from
outside.

Two lanes were affected and the old comment named both -- "a caller may hand us
a string for either" -- while the code converted neither.

THE DATE LANE IS NOT JUST A CONVERSION. `value_dt` is normalised to UTC
(`vitalgraph_iso_to_utc`), and XSD makes a timezoned and an untimezoned dateTime
INCOMPARABLE, so the probe carries the same timezone-agreement guard the general
pipeline's `_eq_cond` does. Without it, normalising declares them equal, which
is a wrong MATCH rather than a missing one.
"""

from __future__ import annotations

from decimal import Decimal

from vitalgraph.db.sparql_sql.fast_slot_filter import (
    _build, _eq_criteria, can_serve_filter, filter_decline_reason)

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
TEXT = HALEY + "KGTextSlot"
NUM = HALEY + "KGDoubleSlot"
DT = HALEY + "KGDateTimeSlot"
Z = "2026-06-23T14:00:00.000Z"


class _Slot:
    def __init__(self, value, slot_class_uri=DT, slot_type="urn:s",
                 comparator="eq"):
        self.slot_type, self.slot_class_uri = slot_type, slot_class_uri
        self.value, self.comparator = value, comparator


class _Frame:
    def __init__(self, slot_criteria=None, frame_type="urn:f", negate=False,
                 frame_criteria=None):
        self.frame_type, self.negate = frame_type, negate
        self.slot_criteria = slot_criteria or []
        self.frame_criteria = frame_criteria or []


class _Crit:
    def __init__(self, frame_criteria, entity_type="urn:e"):
        self.entity_type, self.frame_criteria = entity_type, frame_criteria
        for a in ("sort_criteria", "vector_criteria", "multi_vector_criteria",
                  "geo_criteria", "entity_property_filters", "entity_uris",
                  "search_string"):
            setattr(self, a, None)


def _one(value, cls=DT):
    return _Crit([_Frame(slot_criteria=[_Slot(value, slot_class_uri=cls)])])


def _sql_and_args(value, cls=DT):
    c = _one(value, cls)
    assert can_serve_filter(c), (
        f"{value!r} on {cls.rsplit('#')[-1]} must be servable: "
        f"{filter_decline_reason(c)}")
    built = _build("sp_x", "urn:g", c)
    assert built is not None
    return built


class TestTheDateLane:

    def test_an_iso_string_is_served_rather_than_crashing_the_bind(self):
        sql, args = _sql_and_args(Z)
        assert Z in args, (
            "the bound reaches the driver as a str; binding it against the "
            "TIMESTAMP column is what asyncpg refused")
        assert "vitalgraph_iso_to_utc($5)" in sql, (
            "it must be normalised by the function `value_dt` was derived "
            f"with, so one instant matches however it was written:\n{sql}")

    def test_the_parameter_is_never_cast_to_the_column_type(self):
        sql, _ = _sql_and_args(Z)
        assert "$5::timestamp" not in sql.lower(), (
            "a cast types the parameter and puts the DataError straight back")

    def test_a_timezoned_bound_requires_a_timezoned_value(self):
        sql, _ = _sql_and_args(Z)
        assert "IS true" in sql, (
            "XSD makes a timezoned and an untimezoned dateTime incomparable; "
            "without the guard, normalising declares them equal and the probe "
            f"returns a row the pipeline would not:\n{sql}")

    def test_an_untimezoned_bound_requires_an_untimezoned_value(self):
        sql, _ = _sql_and_args("2026-06-23T14:00:00")
        assert "IS false" in sql, (
            f"the guard must follow the bound's own form:\n{sql}")

    def test_the_guard_reads_the_lexical_form_already_in_the_row(self):
        sql, _ = _sql_and_args(Z)
        assert "value_text ~" in sql, (
            "`value_text` holds `term_text` for every row whatever its lane, "
            "so the guard costs no join")

    def test_a_value_that_is_not_a_date_declines_the_whole_query(self):
        """NOT served as empty.

        `vitalgraph_iso_to_utc` returns NULL for anything that is not strict
        ISO, so an unparseable bound would compare against NULL and match
        nothing -- a confident empty answer where the general pipeline can
        still match the literal lexically. Declining sends it there.
        """
        c = _one("last tuesday")
        assert _eq_criteria(c.frame_criteria) is None
        assert not can_serve_filter(c)
        assert "outside its lane" in (filter_decline_reason(c) or "")

    def test_a_date_only_bound_is_still_a_date(self):
        sql, args = _sql_and_args("2026-06-23")
        assert "2026-06-23" in args and "vitalgraph_iso_to_utc" in sql


class TestTheNumericLane:

    def test_a_float_binds_as_a_decimal(self):
        """`value_num` is NUMERIC, and a JSON number arrives as a float."""
        _sql, args = _sql_and_args(3.5, NUM)
        assert Decimal("3.5") in args, f"expected a Decimal, got {args!r}"

    def test_a_numeric_string_binds_too(self):
        _sql, args = _sql_and_args("3.5", NUM)
        assert Decimal("3.5") in args

    def test_an_int_binds(self):
        _sql, args = _sql_and_args(7, NUM)
        assert Decimal(7) in args

    def test_a_non_numeric_value_declines_the_whole_query(self):
        c = _one("banana", NUM)
        assert _eq_criteria(c.frame_criteria) is None
        assert not can_serve_filter(c)

    def test_a_non_finite_value_declines(self):
        """`NaN` is a valid Decimal that matches nothing, which is not an answer."""
        assert not can_serve_filter(_one("NaN", NUM))
        assert not can_serve_filter(_one(float("inf"), NUM))


class TestTheTextLaneIsUnchanged:

    def test_a_text_value_still_binds_as_text(self):
        sql, args = _sql_and_args("v1", TEXT)
        assert "v1" in args
        assert "value_text = $5" in sql, (
            f"the text lane needs no normalisation and must not gain any:\n{sql}")


class TestAConjunctionBindsEveryArm:

    def test_a_date_and_a_number_and_a_string_together(self):
        c = _Crit([_Frame(slot_criteria=[
            _Slot(Z, DT, "urn:a"), _Slot(2, NUM, "urn:b"),
            _Slot("v", TEXT, "urn:c")])])
        assert can_serve_filter(c), filter_decline_reason(c)
        sql, args = _build("sp_x", "urn:g", c)
        assert sql.count("INTERSECT") == 2
        assert [a for a in args if isinstance(a, Decimal)] == [Decimal(2)]
        assert Z in args and "v" in args

    def test_one_unbindable_arm_declines_all_three(self):
        """A conjunction is served only when EVERY conjunct is.

        Dropping the arm that cannot bind would return a SUPERSET, which is the
        wrong answer in the direction that looks most plausible.
        """
        c = _Crit([_Frame(slot_criteria=[
            _Slot(Z, DT, "urn:a"), _Slot("banana", NUM, "urn:b")])])
        assert not can_serve_filter(c)


class TestTheSortPathBindsTheSameWay:
    """`fast_slot_sort` applies these same criteria to the same table.

    It calls `_eq_criteria` for its own EXISTS clauses, so it inherits the lane
    conversion — and it used to emit a bare `= $n`, which put the DataError
    straight back for a date. A filtered list and the SAME list with a sort on it
    would then disagree about whether a dated criterion is servable, which is
    `issues/172` all over again: two fast paths each declining the other's input.
    """

    def _exists(self, value, cls=DT):
        from vitalgraph.db.sparql_sql.fast_slot_sort import _filter_exists
        args = ["ctx", "ent"]
        sql = _filter_exists(
            "sp_t", _Crit([_Frame(slot_criteria=[_Slot(value, slot_class_uri=cls)])]),
            args)
        return sql, args[2:]

    def test_the_sort_path_normalises_a_date_too(self):
        sql, args = self._exists(Z)
        assert "vitalgraph_iso_to_utc($5)" in sql, (
            f"the sorted half of a filtered list still casts its bound:\n{sql}")
        assert Z in args

    def test_the_sort_path_carries_the_timezone_guard(self):
        sql, _ = self._exists(Z)
        assert "value_text ~" in sql and "IS true" in sql, (
            f"both halves must agree on which rows match:\n{sql}")

    def test_the_guard_is_qualified_by_the_alias_it_probes(self):
        """The clause is a correlated EXISTS over an alias, not a bare table."""
        sql, _ = self._exists(Z)
        assert "(f4.value_text ~" in sql, (
            f"an unqualified `value_text` here is ambiguous:\n{sql}")

    def test_the_other_lanes_are_untouched(self):
        sql, args = self._exists("v1", TEXT)
        assert "value_text = $5" in sql and "iso_to_utc" not in sql
        sql, args = self._exists(2, NUM)
        assert "value_num = $5" in sql and Decimal(2) in args
