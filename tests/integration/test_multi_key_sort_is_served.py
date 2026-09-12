"""A multi-key sorted page must be served, and must be ORDERED CORRECTLY.

`issues/096`. `can_serve` declined `len(sort_criteria) != 1`, so a two-key list
view — sort by company, then by lead id — fell to the general pipeline. Measured
on `cardiff_kg`, page 25: 1,405,617 buffers / 778.5 ms there, against 165
buffers / 3.6 ms served from `entity_slot_sort` with zero heap fetches. N keys
are N conditional aggregates over ONE index-only scan, not N-1 joins, and the
served time is flat in the key count (4.4 / 2.7 / 3.0 ms at one, two, three).

THE ASSERTIONS THAT MATTER ARE THE ORDERING ONES. A fast page in the wrong
precedence is worse than the slow one it replaces because it looks right. The
tie cases below exist because a first pass against real data agreed on every
page while never exercising the second key at all: `CompanyName` had 2,855
distinct values over 2,863 entities, so almost nothing tied and the tiebreak was
never reached. Every multi-key case here ties on the first key deliberately.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.asyncio(loop_scope="session")

_KG = "http://vital.ai/ontology/haley-ai-kg#"
_G = "urn:mk:graph"
_E = "urn:mk:entity:E"
# A SEPARATE entity type for the precedence fixture. `test_space` is shared, so
# loading those rows under `_E` changed the counts the population tests assert.
_E2 = "urn:mk:entity:E2"
_F = "urn:mk:frame:F"
_A, _B = "urn:mk:slot:A", "urn:mk:slot:B"
_STATUS = "http://vital.ai/ontology/vital-aimp#hasObjectStatusType"
_ACTIVE = "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
_ARCHIVED = "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ARCHIVED"


def _sort(slot, order="asc", priority=1):
    from vitalgraph.sparql.kg_query_builder import SortCriteria
    return SortCriteria(sort_type="entity_frame_slot", slot_type=slot,
                        slot_class_uri=_KG + "KGTextSlot", frame_path=[_F],
                        sort_order=order, priority=priority)


def _criteria(*keys, entity_type=_E):
    from vitalgraph.sparql.kg_query_builder import EntityQueryCriteria
    return EntityQueryCriteria(entity_type=entity_type, entity_uris=None,
                               frame_criteria=[], use_edge_pattern=True,
                               sort_criteria=list(keys))


async def _load(pg_conn, sp):
    """Four entities TIED on A, ordered only by B, plus one missing B."""
    from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid
    ctx, ent_t = _term_uuid(_G), _term_uuid(_E)
    fpath = [_term_uuid(_F)]
    a, b = _term_uuid(_A), _term_uuid(_B)

    people = [("urn:mk:e:1", "tie", "d"), ("urn:mk:e:2", "tie", "b"),
              ("urn:mk:e:3", "tie", "a"), ("urn:mk:e:4", "tie", "c"),
              ("urn:mk:e:no_b", "tie", None)]
    rows = []
    for e_uri, a_val, b_val in people:
        e = _term_uuid(e_uri)
        await pg_conn.execute(
            f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", e, e_uri)
        rows.append((uuid.uuid4(), ctx, e, uuid.uuid4(), ent_t, fpath, a, a_val))
        if b_val is not None:
            rows.append((uuid.uuid4(), ctx, e, uuid.uuid4(), ent_t, fpath, b, b_val))
    await pg_conn.executemany(
        f"INSERT INTO {sp}_entity_slot_sort (slot_uuid, context_uuid, entity_uuid,"
        f" frame_uuid, entity_type_uuid, frame_type_path, slot_type_uuid, value_text)"
        f" VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT DO NOTHING", rows)
    return ctx


async def _page(pg_conn, sp, crit, n=10, off=0):
    from vitalgraph.db.sparql_sql.fast_slot_sort import fast_slot_sort_page
    return await fast_slot_sort_page(pg_conn, sp, _G, crit, n, off)


# The gate itself is pinned in `tests/unit/sparql_sql/test_fast_slot_sort_gate.py`;
# what needs a database is whether the page it agrees to serve is CORRECT.


# --- ordering, on data that TIES on the first key --------------------------

async def test_the_second_key_breaks_the_tie(pg_conn, test_space):
    await _load(pg_conn, test_space)
    got = await _page(pg_conn, test_space, _criteria(_sort(_A), _sort(_B, priority=2)))
    assert got == ["urn:mk:e:3", "urn:mk:e:2", "urn:mk:e:4", "urn:mk:e:1"], (
        "every entity has A='tie', so B alone decides the order (a,b,c,d)")


async def test_the_second_key_direction_is_its_own(pg_conn, test_space):
    await _load(pg_conn, test_space)
    got = await _page(pg_conn, test_space,
                      _criteria(_sort(_A), _sort(_B, "desc", priority=2)))
    assert got == ["urn:mk:e:1", "urn:mk:e:4", "urn:mk:e:2", "urn:mk:e:3"], (
        "DESC on the second key must not be taken from the first")


async def _load_disagreeing(pg_conn, sp):
    """Two entities whose A-order and B-order are OPPOSITE.

    The tie fixture cannot test precedence: with A constant, leading on A or on
    B gives the same page, so the assertion holds whichever key leads. That was
    a real vacuous test here — mutating `sort_keys` to use declaration order
    left it green — and this fixture is what makes precedence observable.
    """
    from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid
    ctx, ent_t = _term_uuid(_G), _term_uuid(_E2)
    fpath = [_term_uuid(_F)]
    a, b = _term_uuid(_A), _term_uuid(_B)
    rows = []
    for e_uri, a_val, b_val in (("urn:mk:d:1", "b", "a"), ("urn:mk:d:2", "a", "b")):
        e = _term_uuid(e_uri)
        await pg_conn.execute(
            f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", e, e_uri)
        rows += [(uuid.uuid4(), ctx, e, uuid.uuid4(), ent_t, fpath, a, a_val),
                 (uuid.uuid4(), ctx, e, uuid.uuid4(), ent_t, fpath, b, b_val)]
    await pg_conn.executemany(
        f"INSERT INTO {sp}_entity_slot_sort (slot_uuid, context_uuid, entity_uuid,"
        f" frame_uuid, entity_type_uuid, frame_type_path, slot_type_uuid, value_text)"
        f" VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT DO NOTHING", rows)


async def _only_d(pg_conn, sp, crit):
    return await _page(pg_conn, sp, crit, n=50)


async def test_priority_decides_which_key_leads(pg_conn, test_space):
    """Declared B-then-A, prioritised A-then-B — the page must follow PRIORITY.

    A and B order these two entities oppositely, so declaration order and
    priority order give different pages and the assertion can tell them apart.
    """
    await _load_disagreeing(pg_conn, test_space)
    got = await _only_d(pg_conn, test_space,
                        _criteria(_sort(_B, priority=2), _sort(_A, priority=1),
                                  entity_type=_E2))
    assert got == ["urn:mk:d:2", "urn:mk:d:1"], (
        "A leads (a<b => d:2 first); following declaration order would lead on "
        "B and return d:1 first")


async def test_the_same_keys_with_priorities_SWAPPED_reverse_the_page(pg_conn, test_space):
    """The other half of the pair: same two criteria, priorities exchanged."""
    await _load_disagreeing(pg_conn, test_space)
    got = await _only_d(pg_conn, test_space,
                        _criteria(_sort(_B, priority=1), _sort(_A, priority=2),
                                  entity_type=_E2))
    assert got == ["urn:mk:d:1", "urn:mk:d:2"], "B leads (a<b => d:1 first)"


# --- presence: the pipeline's semantics, not a choice ----------------------

async def test_an_entity_missing_the_SECOND_key_is_absent(pg_conn, test_space):
    """`_build_sort_bindings` emits every sort pattern as a REQUIRED triple, so
    the pipeline drops such an entity. Serving it — via an outer join, say —
    would return a row the query being imitated does not."""
    await _load(pg_conn, test_space)
    got = await _page(pg_conn, test_space, _criteria(_sort(_A), _sort(_B, priority=2)))
    assert "urn:mk:e:no_b" not in got
    single = await _page(pg_conn, test_space, _criteria(_sort(_A)))
    assert "urn:mk:e:no_b" in single, (
        "it must still appear when only A is sorted on, or the exclusion above "
        "is just a missing row rather than the required-triple semantics")


async def test_the_count_matches_the_page_population(pg_conn, test_space):
    """A count disagreeing with its own page offers a last page that does not
    exist, and nothing errors."""
    from vitalgraph.db.sparql_sql.fast_slot_sort import fast_slot_sort_count
    await _load(pg_conn, test_space)
    two = _criteria(_sort(_A), _sort(_B, priority=2))
    assert await fast_slot_sort_count(pg_conn, test_space, _G, two) == 4
    assert await fast_slot_sort_count(
        pg_conn, test_space, _G, _criteria(_sort(_A))) == 5


async def test_paging_partitions_the_result(pg_conn, test_space):
    """Pages must partition the set, not overlap or drop."""
    await _load(pg_conn, test_space)
    c = _criteria(_sort(_A), _sort(_B, priority=2))
    first = await _page(pg_conn, test_space, c, n=2, off=0)
    second = await _page(pg_conn, test_space, c, n=2, off=2)
    assert first == ["urn:mk:e:3", "urn:mk:e:2"]
    assert second == ["urn:mk:e:4", "urn:mk:e:1"]
    assert not set(first) & set(second)


# --- entity-property filters, served via a quad-table EXISTS ----------------

async def _load_with_status(pg_conn, sp):
    """The tie fixture's four entities, two ACTIVE and two ARCHIVED.

    A filter that matches EVERYTHING cannot detect a dropped filter — on real
    data `hasObjectStatusType` had exactly one value across all 8,755 quads, so
    the first version of this check would have passed with the filter ignored.
    Here the split is deliberate.
    """
    from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid
    await _load(pg_conn, sp)
    ctx, pred = _term_uuid(_G), _term_uuid(_STATUS)
    rows = []
    for e_uri, status in (("urn:mk:e:1", _ACTIVE), ("urn:mk:e:2", _ARCHIVED),
                          ("urn:mk:e:3", _ACTIVE), ("urn:mk:e:4", _ARCHIVED)):
        rows.append((_term_uuid(e_uri), pred, _term_uuid(status), ctx))
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", rows)


def _with_status(value, *keys):
    from vitalgraph.sparql.kg_query_builder import EntityPropertyFilter
    c = _criteria(*keys)
    c.entity_property_filters = [EntityPropertyFilter(
        property_uri=_STATUS, operator="eq", value=value)]
    return c


async def test_the_property_filter_is_actually_applied(pg_conn, test_space):
    """The assertion a silently-dropped filter would fail."""
    await _load_with_status(pg_conn, test_space)
    got = await _page(pg_conn, test_space,
                      _with_status(_ACTIVE, _sort(_A), _sort(_B, priority=2)))
    assert got == ["urn:mk:e:3", "urn:mk:e:1"], (
        "only the two ACTIVE entities, still ordered by B (a < d)")


async def test_the_other_value_returns_the_COMPLEMENT(pg_conn, test_space):
    """Paired with the test above so neither passes on a filter stuck to one
    answer."""
    await _load_with_status(pg_conn, test_space)
    got = await _page(pg_conn, test_space,
                      _with_status(_ARCHIVED, _sort(_A), _sort(_B, priority=2)))
    assert got == ["urn:mk:e:2", "urn:mk:e:4"]


async def test_a_value_matching_nothing_returns_an_empty_page(pg_conn, test_space):
    await _load_with_status(pg_conn, test_space)
    got = await _page(pg_conn, test_space,
                      _with_status("urn:mk:status:nonesuch", _sort(_A)))
    assert got == []


async def test_the_count_follows_the_property_filter(pg_conn, test_space):
    from vitalgraph.db.sparql_sql.fast_slot_sort import fast_slot_sort_count
    await _load_with_status(pg_conn, test_space)
    n = await fast_slot_sort_count(pg_conn, test_space, _G,
                                   _with_status(_ACTIVE, _sort(_A)))
    assert n == 2, "the count must be drawn from the same filtered population"
