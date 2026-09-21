"""A dateTime slot equality is served from the table, by VALUE, against real rows.

The probe bound the criterion value straight against `value_dt`, so asyncpg
typed the parameter as a timestamp and refused the ISO string a KGQuery
criterion carries (`SlotCriteria.value` is `Optional[Any]`, and JSON has no
dates). Both callers caught that at DEBUG and declined, so a dated slot filter
has never been served by this table -- it fell to the BGP join measured ~300x
slower, correctly, and silently.

Serving it raises a question binding never had to answer: WHICH ROWS MATCH.
`value_dt` is normalised to UTC, so one instant matches however it was written;
and XSD makes a timezoned and an untimezoned dateTime INCOMPARABLE, so the probe
carries the general pipeline's timezone-agreement guard. The cells below pin
both, because both are wrong-answer directions rather than slow ones:

    stored                          bound 2026-06-23T14:00:00.000Z
    2026-06-23T14:00:00Z            match      -- same instant
    2026-06-23T09:00:00-05:00       match      -- same instant, written apart
    2026-06-23T14:00:00             NO match   -- incomparable, no offset given
    2026-06-24T14:00:00Z            NO match   -- different instant

Rows are written straight into `{space}_entity_slot_sort` -- the shape
`test_filter_plus_sort_is_served` uses -- with `value_dt` derived by
`vitalgraph_iso_to_utc` exactly as the maintenance path derives it from
`term.dt_val`. Deriving it any other way here would test the fixture rather than
the code.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

_KG = "http://vital.ai/ontology/haley-ai-kg#"
DT_SLOT = _KG + "KGDateTimeSlot"
NUM_SLOT = _KG + "KGDoubleSlot"
GRAPH = "urn:dt:graph"
ETYPE = "urn:dt:entity:E"
FRAME = "urn:dt:frame:F"
SLOT = "urn:dt:slot:when"
AMOUNT = "urn:dt:slot:amount"

STORED = [
    ("urn:dt:e:utc",      "2026-06-23T14:00:00Z"),
    ("urn:dt:e:offset",   "2026-06-23T09:00:00-05:00"),
    ("urn:dt:e:naive",    "2026-06-23T14:00:00"),
    ("urn:dt:e:next_day", "2026-06-24T14:00:00Z"),
]


def _criteria(value, slot_type=SLOT, slot_class_uri=DT_SLOT):
    from vitalgraph.sparql.kg_query_builder import (
        EntityQueryCriteria, FrameCriteria, SlotCriteria)
    c = EntityQueryCriteria(entity_type=ETYPE, entity_uris=None,
                            frame_criteria=[], use_edge_pattern=True)
    c.frame_criteria = [FrameCriteria(
        frame_type=FRAME,
        slot_criteria=[SlotCriteria(slot_type=slot_type,
                                    slot_class_uri=slot_class_uri,
                                    value=value, comparator="eq")])]
    return c


async def _seed(pg_conn, sp):
    """One entity per stored form, plus a numeric slot on the first of them."""
    from vitalgraph.db.sparql_sql.fast_slot_filter import _term_uuid
    ctx, ent_t = _term_uuid(GRAPH), _term_uuid(ETYPE)
    fpath = [_term_uuid(FRAME)]
    when, amount = _term_uuid(SLOT), _term_uuid(AMOUNT)

    # DETERMINISTIC slot and frame uuids. `test_space` outlives a single test,
    # so a fixture keyed on `uuid.uuid4()` re-seeds rather than re-asserts: the
    # second cell to run saw two rows per entity, the seventh saw seven. That is
    # a fixture bug, but the duplicates it produced are also a REAL shape (an
    # entity with two frames of the same type, each carrying the value), which
    # is what `test_an_entity_matching_twice_is_one_entity` now pins.
    for e_uri, lexical in STORED:
        e = _term_uuid(e_uri)
        await pg_conn.execute(
            f"INSERT INTO {sp}_term (term_uuid, term_text, term_type)"
            f" VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", e, e_uri)
        # `value_dt` from `vitalgraph_iso_to_utc`, which is what `term.dt_val`
        # is -- the fixture must not invent its own normalisation.
        await pg_conn.execute(
            f"INSERT INTO {sp}_entity_slot_sort (slot_uuid, context_uuid,"
            f" entity_uuid, frame_uuid, entity_type_uuid, frame_type_path,"
            f" slot_type_uuid, value_text, value_dt)"
            f" VALUES ($1,$2,$3,$4,$5,$6,$7,$8, vitalgraph_iso_to_utc($8))"
            f" ON CONFLICT DO NOTHING",
            _term_uuid(e_uri + "#when"), ctx, e, _term_uuid(e_uri + "#frame"),
            ent_t, fpath, when, lexical)

    await pg_conn.execute(
        f"INSERT INTO {sp}_entity_slot_sort (slot_uuid, context_uuid,"
        f" entity_uuid, frame_uuid, entity_type_uuid, frame_type_path,"
        f" slot_type_uuid, value_text, value_num)"
        f" VALUES ($1,$2,$3,$4,$5,$6,$7,'3.5',3.5) ON CONFLICT DO NOTHING",
        _term_uuid(STORED[0][0] + "#amount"), ctx, _term_uuid(STORED[0][0]),
        _term_uuid(STORED[0][0] + "#frame"), ent_t, fpath, amount)


async def _served(pg_conn, sp, criteria):
    """(page, count) -- both, because a request waits for both."""
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        fast_slot_filter_count, fast_slot_filter_page)
    page = await fast_slot_filter_page(pg_conn, sp, GRAPH, criteria, 50, 0)
    count = await fast_slot_filter_count(pg_conn, sp, GRAPH, criteria)
    return page, count


@pytest.mark.parametrize("bound,expected", [
    # The instant, written three ways: all select the two timezoned rows that
    # ARE that instant, and neither the untimezoned one nor the next day.
    ("2026-06-23T14:00:00.000Z", ["urn:dt:e:offset", "urn:dt:e:utc"]),
    ("2026-06-23T14:00:00Z", ["urn:dt:e:offset", "urn:dt:e:utc"]),
    ("2026-06-23T09:00:00-05:00", ["urn:dt:e:offset", "urn:dt:e:utc"]),
    # An untimezoned bound is comparable only with an untimezoned value.
    ("2026-06-23T14:00:00", ["urn:dt:e:naive"]),
    ("2026-06-24T14:00:00Z", ["urn:dt:e:next_day"]),
    # A real instant that nothing carries: served, and EMPTY.
    ("2026-06-25T14:00:00Z", []),
])
async def test_a_dated_equality_selects_by_value(pg_conn, test_space,
                                                 bound, expected):
    await _seed(pg_conn, test_space)
    page, count = await _served(pg_conn, test_space, _criteria(bound))

    assert page is not None, (
        f"the PAGE declined {bound!r} -- which is what binding the string "
        f"against the TIMESTAMP column did, every time, at DEBUG")
    assert count is not None, f"the COUNT declined {bound!r}"
    assert sorted(page) == sorted(expected)
    assert count == len(expected), f"count {count} != {len(expected)}"


async def test_a_float_valued_numeric_equality_is_served(pg_conn, test_space):
    """The other lane the old comment named and the code did not convert.

    A JSON number arrives as a float and `value_num` is NUMERIC, so this bound
    raised the identical DataError and declined identically.
    """
    await _seed(pg_conn, test_space)
    page, count = await _served(
        pg_conn, test_space,
        _criteria(3.5, slot_type=AMOUNT, slot_class_uri=NUM_SLOT))

    assert page is not None and count is not None, "a float bound still declines"
    assert page == ["urn:dt:e:utc"]
    assert count == 1


async def test_a_value_that_is_not_a_date_declines_rather_than_answering_empty(
        pg_conn, test_space):
    """`vitalgraph_iso_to_utc` returns NULL for a non-ISO value.

    Compared against NULL the probe matches nothing, so serving it would be a
    confident EMPTY answer. The general pipeline can still match such a literal
    lexically, so the only safe response is to decline and let it.
    """
    await _seed(pg_conn, test_space)
    page, count = await _served(pg_conn, test_space, _criteria("last tuesday"))
    assert page is None and count is None


async def test_a_negated_frame_criterion_is_not_served_as_a_positive_one(
        pg_conn, test_space):
    """It asked for the entities WITHOUT the pattern and would have got theirs.

    `negate` compiles to `FILTER NOT EXISTS` on the general path. This one
    ignored the flag entirely, so the answer was the complement of the question.
    """
    await _seed(pg_conn, test_space)
    c = _criteria("2026-06-23T14:00:00Z")
    c.frame_criteria[0].negate = True

    page, count = await _served(pg_conn, test_space, c)
    assert page is None and count is None, (
        "a negated criterion must decline; served as an equality probe it "
        "returns exactly the entities the caller asked to exclude")


async def test_an_entity_matching_twice_is_one_entity(pg_conn, test_space):
    """One entity, TWO frames of the same type both carrying the value.

    The table holds a row per SLOT, so that entity has two matching rows. A
    single criterion is a single arm and therefore not an INTERSECT, so nothing
    deduplicated it: the count is `count(*)` over the arm and the page selects
    straight from it. The entity was counted twice and returned twice.

    Not an exotic shape -- two Campaign frames on one lead, both ACTIVE, is the
    production case this path was built for. The page repeating a URI is
    visible; the count being double is not, and it is the number the caller
    pages against.
    """
    from vitalgraph.db.sparql_sql.fast_slot_filter import _term_uuid
    sp = test_space
    await _seed(pg_conn, sp)
    ctx, ent_t = _term_uuid(GRAPH), _term_uuid(ETYPE)
    twice = "urn:dt:e:twice"
    e = _term_uuid(twice)
    await pg_conn.execute(
        f"INSERT INTO {sp}_term (term_uuid, term_text, term_type)"
        f" VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", e, twice)
    for n in ("one", "two"):
        await pg_conn.execute(
            f"INSERT INTO {sp}_entity_slot_sort (slot_uuid, context_uuid,"
            f" entity_uuid, frame_uuid, entity_type_uuid, frame_type_path,"
            f" slot_type_uuid, value_text, value_dt)"
            f" VALUES ($1,$2,$3,$4,$5,$6,$7,$8, vitalgraph_iso_to_utc($8))"
            f" ON CONFLICT DO NOTHING",
            _term_uuid(f"{twice}#{n}"), ctx, e, _term_uuid(f"{twice}#frame:{n}"),
            ent_t, [_term_uuid(FRAME)], _term_uuid(SLOT), "2026-06-23T14:00:00Z")

    page, count = await _served(pg_conn, sp, _criteria("2026-06-23T14:00:00Z"))

    assert page is not None and count is not None
    assert page.count(twice) == 1, f"the entity is returned twice: {page}"
    assert sorted(page) == ["urn:dt:e:offset", "urn:dt:e:twice", "urn:dt:e:utc"]
    assert count == 3, (
        f"count {count} != 3 -- a `count(*)` over the arm counts SLOT rows, "
        f"and the caller pages against that number")
