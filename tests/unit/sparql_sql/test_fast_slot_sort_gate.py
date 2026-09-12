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

import re

import pytest

from vitalgraph.db.sparql_sql.fast_slot_sort import (
    MAX_SORT_KEYS, _prop_filter_exists, can_serve, entity_prop_filters,
    sort_keys)

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
TEXT = HALEY + "KGTextSlot"
_STATUS = "http://vital.ai/ontology/vital-aimp#hasObjectStatusType"
_ACTIVE = "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"


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


def test_a_second_sort_key_IS_served():
    """Served since 2026-09-11 as N conditional aggregates over one scan.

    Was a decline, on the reasoning that "the index orders ONE value column".
    Measured on cardiff_kg, page 25: the declined two-key sort cost 1,405,617
    buffers / 778.5 ms through the general pipeline, against 165 buffers /
    3.6 ms served here with zero heap fetches.
    """
    assert can_serve(_Crit(sort_criteria=[_Sort(), _Sort(slot_type="urn:b")]))


def test_keys_are_ordered_by_priority_not_declaration():
    """A page ordered by the right values in the wrong precedence is a WRONG
    page that looks entirely plausible, so this must match the builder's own
    `sorted(sort_criteria, key=priority)`."""
    a = _Sort(slot_type="urn:a"); a.priority = 2
    b = _Sort(slot_type="urn:b"); b.priority = 1
    assert [k.slot_type for k in sort_keys(_Crit(sort_criteria=[a, b]))] == \
        ["urn:b", "urn:a"]


def test_equal_priorities_keep_declaration_order():
    """Python's sort is stable and the builder relies on it too."""
    a, b = _Sort(slot_type="urn:a"), _Sort(slot_type="urn:b")
    assert [k.slot_type for k in sort_keys(_Crit(sort_criteria=[a, b]))] == \
        ["urn:a", "urn:b"]


def test_more_keys_than_the_cap_are_refused():
    keys = [_Sort(slot_type=f"urn:{i}") for i in range(MAX_SORT_KEYS + 1)]
    assert not can_serve(_Crit(sort_criteria=keys))


def test_keys_under_DIFFERENT_frame_paths_are_refused():
    """`frame_type_path` is a leading index column matched as a whole array.
    Two paths would need an OR of (slot_type, path) pairs and give up the
    index-only scan, so this falls back rather than serving it slowly."""
    assert not can_serve(_Crit(sort_criteria=[
        _Sort(slot_type="urn:a", frame_path=("urn:f1",)),
        _Sort(slot_type="urn:b", frame_path=("urn:f2",))]))


def test_one_bad_key_refuses_the_WHOLE_query():
    """Every key is checked, not just the first — a served page built from a
    partially-understood sort would be ordered by the wrong thing."""
    assert not can_serve(_Crit(sort_criteria=[
        _Sort(), _Sort(slot_type="urn:b", slot_class_uri=HALEY + "KGGeoSlot")]))
    assert not can_serve(_Crit(sort_criteria=[
        _Sort(), _Sort(slot_type=None)]))


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


class _Prop:
    def __init__(self, property_uri=_STATUS, operator="eq", value=_ACTIVE):
        self.property_uri, self.operator, self.value = property_uri, operator, value


def test_an_equality_on_a_URI_valued_property_IS_served():
    """Served since 2026-09-11. Measured on cardiff_kg: a broad status filter
    with a slot sort was 1,007,597 buffers / 548.9 ms through the general
    pipeline, against ~15 ms here."""
    assert can_serve(_Crit(entity_property_filters=[_Prop()]))


def test_a_non_equality_operator_is_refused():
    assert not can_serve(_Crit(entity_property_filters=[_Prop(operator="contains")]))


@pytest.mark.parametrize("prop", [
    "http://vital.ai/ontology/vital-core#hasName",                  # string
    "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime",    # dateTime
    "http://vital.ai/ontology/vital-core#nonesuch",                 # undeclared
])
def test_a_property_that_is_not_URI_valued_is_refused(prop):
    """A literal's term uuid folds in lang and a space-local numeric datatype
    id. Guessing it wrong does not error — it matches no term, and the page
    comes back EMPTY but well formed. So only URI values, whose hash is
    unambiguous, are served."""
    assert not can_serve(_Crit(entity_property_filters=[_Prop(property_uri=prop)]))


def test_one_unservable_filter_refuses_the_WHOLE_query():
    """Applying some filters and ignoring the rest returns a superset with a
    plausible count and no error."""
    assert not can_serve(_Crit(entity_property_filters=[
        _Prop(), _Prop(property_uri="http://vital.ai/ontology/vital-core#hasName")]))


def test_a_non_string_value_is_refused():
    assert not can_serve(_Crit(entity_property_filters=[_Prop(value=["a", "b"])]))


def test_a_filter_object_without_an_operator_is_refused():
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


# --- the generic-plan defence -----------------------------------------------

def test_the_property_constants_are_INLINED_not_bound():
    """A bound parameter here costs 100x after five executions.

    asyncpg prepares every statement and PostgreSQL switches to a GENERIC plan
    on the sixth execution. A generic plan cannot see the value, so it cannot
    know the predicate matches 8,755 rows, and it reverts to a nested loop.
    Measured on one connection, same statement: ~10 ms for executions 1-5, then
    ~1,180 ms for 6 onward, permanently — and a pooled server keeps prepared
    statements across requests.

    So this asserts the SHAPE of the emitted SQL, because the cost of getting it
    wrong does not show up in any correctness test and does not appear until the
    sixth call.
    """
    args = ["ctx"]
    sql = _prop_filter_exists("sp", entity_prop_filters(
        _Crit(entity_property_filters=[_Prop()])), args)
    assert "::uuid" in sql, "constants must be inlined as literals"
    assert args == ["ctx"], (
        f"nothing may be appended to args — a $n placeholder is the generic-plan "
        f"bug this guards. got {args!r}")
    import re
    # $1 is the context and stays bound; no OTHER placeholder may appear.
    assert not set(re.findall(r"\$(\d+)", sql)) - {"1"}, sql


def test_each_filter_gets_its_own_alias():
    """Two filters on one query must not collide on the subquery alias."""
    props = entity_prop_filters(_Crit(entity_property_filters=[
        _Prop(), _Prop(property_uri=_ENTITY_TYPE, value="urn:t:E")]))
    sql = _prop_filter_exists("sp", props, ["ctx"])
    assert sql.count("EXISTS") == 2
    aliases = set(re.findall(r"FROM sp_rdf_quad (\w+)", sql))
    assert len(aliases) == 2, f"aliases collide: {aliases}"
