"""The 6-table frame traversal that `frame_entity` exists to collapse.

`rewrite_frame_entity_table` replaces six quad tables

    2 edge         frame --hasEdgeSource/hasEdgeDestination--> slot
    2 slot_type    slot --hasKGSlotType--> <urn:hasSourceEntity> / <...Destination>
    2 slot_value   slot --hasEntitySlotValue--> entity

with one row of `{space}_frame_entity(frame_uuid, source_entity_uuid,
dest_entity_uuid, context_uuid)`. That is the shape a CRITERIA query has: one
that filters across many frames by what sits at each end, rather than fetching
one known frame's slots.

`issues/048` is the standing record. Two things there make this worth pinning
down with tests rather than prose:

  * the rewrite once emitted SQL PostgreSQL rejected outright — `missing
    FROM-clause entry for table "mv0"` — because it collapsed the six tables
    while a constraint still referenced a collapsed alias;
  * the guard added for that makes the rewrite DECLINE on any slot-node
    constraint, and `frame_entity` holds a slot no column, so the canonical
    query (which says `?sourceSlot a KGEntitySlot`) is exactly the case that
    declines. The table is therefore correct, populated, and unread.

So these tests assert the CONTRACT rather than which branch is taken: whichever
way the rewrite goes, the answer must be the same and the SQL must run. That way
they keep passing when the rewrite is taught to handle slot constraints — the
open work in 048 — and fail if it starts collapsing something it should not.

The fixture is deliberately tiny and built here rather than borrowed from a
development space: `frame_entity` is populated in one space of 79, so a test
that depended on finding one would silently skip.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from rdflib import URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX, SIDECAR_URL

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
EX = "http://example.org/fe/"

SRC_ROLE = "urn:hasSourceEntity"
DST_ROLE = "urn:hasDestinationEntity"

# Three frames, so a criteria query has something to filter ACROSS. Frame 0 and
# 1 share a source entity; frame 2 is disjoint. That makes "frames whose source
# is e0" a question with a non-trivial answer — 2 of 3 — rather than all or one.
FRAMES = [
    ("f0", "e0", "e1"),
    ("f1", "e0", "e2"),
    ("f2", "e3", "e4"),
]

# A hypernym-style chain, which is what a synset traversal walks:
#
#     c0 --h0--> c1 --h1--> c2 --h2--> c3
#                  \--h1b--> b1
#
# The branch at c1 is the point. Depth 2 from c0 must return BOTH c2 and b1, and
# depth 3 must return ONLY c3 — b1 is a dead end, so a traversal that quietly
# carries short paths forward, or that joins hops on the frame rather than on
# the shared entity, gives itself away here. A straight line would not catch it.
CHAIN = [
    ("h0", "c0", "c1"),
    ("h1", "c1", "c2"),
    ("h1b", "c1", "b1"),
    ("h2", "c2", "c3"),
]

# Criteria ON THE FRAME, which is what decides whether a hop is followed. In
# wordnet the only such criterion is the traversal type (hypernym vs hyponym);
# production data filters on values — "score >= 100", "created in this range" —
# so both are modelled here.
#
# Chosen so each criterion selects a DIFFERENT path out of c1, which is the
# branch point. A filter that were silently ignored would return the union, and
# every one of these tests would notice:
#
#     h0   HYPERNYM  score 150  2026-01-15     c0 -> c1
#     h1   HYPERNYM  score  50  2026-06-15     c1 -> c2
#     h1b  HYPONYM   score 200  2026-03-01     c1 -> b1
#     h2   HYPERNYM  score 300  2026-09-01     c2 -> c3
HYPERNYM = "urn:Edge_WordnetHypernym"
HYPONYM = "urn:Edge_WordnetHyponym"
FRAME_SCORE = f"{HALEY}hasKGFrameScore"
FRAME_DATE = f"{HALEY}hasKGFrameDate"

FRAME_CRITERIA = {
    "h0":  (HYPERNYM, 150, "2026-01-15T00:00:00Z"),
    "h1":  (HYPERNYM, 50, "2026-06-15T00:00:00Z"),
    "h1b": (HYPONYM, 200, "2026-03-01T00:00:00Z"),
    "h2":  (HYPERNYM, 300, "2026-09-01T00:00:00Z"),
}

ALL_FRAMES = FRAMES + CHAIN


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def collapse_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}fe_{uuid.uuid4().hex[:8]}")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def seeded(collapse_space, space_impl):
    """Build the connection shape: entity -> frame -> slot -> entity."""
    graph = URIRef(f"urn:{collapse_space}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)

    def U(x):
        return URIRef(x)

    quads = []

    def add(s, p, o):
        quads.append((U(s), U(p), U(o), graph))

    entities = {e for _f, s, d in ALL_FRAMES for e in (s, d)}
    for e in sorted(entities):
        add(f"{EX}{e}", RDF_TYPE, f"{HALEY}KGEntity")
        add(f"{EX}{e}", f"{VITAL}vitaltype", f"{HALEY}KGEntity")

    from rdflib import Literal, XSD

    def add_lit(s, p, value, datatype):
        quads.append((U(s), U(p), Literal(value, datatype=datatype), graph))

    for fname, src, dst in ALL_FRAMES:
        frame = f"{EX}{fname}"
        add(frame, RDF_TYPE, f"{HALEY}KGFrame")
        add(frame, f"{VITAL}vitaltype", f"{HALEY}KGFrame")
        if fname in FRAME_CRITERIA:
            ftype, score, when = FRAME_CRITERIA[fname]
            add(frame, f"{HALEY}hasKGFrameType", ftype)
            add_lit(frame, FRAME_SCORE, score, XSD.integer)
            add_lit(frame, FRAME_DATE, when, XSD.dateTime)
        for role, ent, tag in ((SRC_ROLE, src, "s"), (DST_ROLE, dst, "d")):
            slot = f"{EX}{fname}_slot_{tag}"
            edge = f"{EX}{fname}_edge_{tag}"
            add(slot, RDF_TYPE, f"{HALEY}KGEntitySlot")
            add(slot, f"{VITAL}vitaltype", f"{HALEY}KGEntitySlot")
            add(slot, f"{HALEY}hasKGSlotType", role)
            add(slot, f"{HALEY}hasEntitySlotValue", f"{EX}{ent}")
            add(edge, RDF_TYPE, f"{HALEY}Edge_hasKGSlot")
            add(edge, f"{VITAL}vitaltype", f"{HALEY}Edge_hasKGSlot")
            add(edge, f"{VITAL}hasEdgeSource", frame)
            add(edge, f"{VITAL}hasEdgeDestination", slot)

    await backend.add_rdf_quads_batch(collapse_space, quads)
    return collapse_space, str(graph)


# ---------------------------------------------------------------------------
# The criteria query: filter ACROSS frames by what sits at each end
# ---------------------------------------------------------------------------

def _criteria_query(graph: str, source_entity: str, *, slot_typed: bool) -> str:
    """The 6-table traversal.

    `slot_typed` adds `?sourceSlot a KGEntitySlot` — a constraint on the SLOT
    node. `frame_entity` has no slot column, so this is the constraint that
    cannot be remapped after the collapse and the one the rewrite declines on.
    The canonical query in the reference SPARQL has it.
    """
    src_type = f"?sourceSlot a <{HALEY}KGEntitySlot> ." if slot_typed else ""
    dst_type = f"?destSlot a <{HALEY}KGEntitySlot> ." if slot_typed else ""
    return f"""
    SELECT DISTINCT ?frame ?destEntity WHERE {{ GRAPH <{graph}> {{
        ?frame a <{HALEY}KGFrame> .

        ?sourceEdge <{VITAL}hasEdgeSource> ?frame .
        ?sourceEdge <{VITAL}hasEdgeDestination> ?sourceSlot .
        {src_type}
        ?sourceSlot <{HALEY}hasKGSlotType> <{SRC_ROLE}> .
        ?sourceSlot <{HALEY}hasEntitySlotValue> <{source_entity}> .

        ?destEdge <{VITAL}hasEdgeSource> ?frame .
        ?destEdge <{VITAL}hasEdgeDestination> ?destSlot .
        {dst_type}
        ?destSlot <{HALEY}hasKGSlotType> <{DST_ROLE}> .
        ?destSlot <{HALEY}hasEntitySlotValue> ?destEntity .
    }} }}"""


async def _sql_for(conn, space_id: str, sparql: str) -> str:
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    assert cr.ok, f"SPARQL failed to compile: {cr.error}\n{sparql}"
    return (await generate_sql(cr, space_id, conn=conn)).sql


def _disable_rewrite(monkeypatch):
    """Turn the frame_entity rewrite off for one query.

    Patch the DEFINING module, not `generator`: `generate_sql` imports the
    function inside the function body, so the name is looked up in
    `rewrite_frame_entity_table` at call time and a patch on the generator's
    namespace has no effect. Doing that produced a differential test that
    compared the rewritten plan against itself and passed — which is why every
    caller of this asserts the SQL really changed.
    """
    import vitalgraph.db.sparql_sql.rewrite_frame_entity_table as mod
    monkeypatch.setattr(mod, "rewrite_frame_entity_table",
                        lambda plan, aliases, space_id: plan)


async def _rows(conn, space_id, sparql):
    sql = await _sql_for(conn, space_id, sparql)
    return sql, await conn.fetch(sql)


def _pairs(rows):
    """(frame, destEntity) as comparable text, whatever the column names."""
    out = set()
    for r in rows:
        vals = [str(v) for v in r.values() if isinstance(v, str) and v.startswith(EX)]
        if len(vals) >= 2:
            out.add((vals[0], vals[1]))
    return out


class TestTheCollapseShape:
    """What the query must ANSWER, independent of which plan is chosen."""

    @pytest.mark.parametrize("slot_typed", [False, True],
                             ids=["no-slot-constraint", "slot-typed"])
    async def test_the_criteria_query_is_correct(self, seeded, pg_conn, slot_typed):
        """Two of three frames have e0 as their source; the third must not
        appear, and each must bring its own destination.

        Asserted for both shapes because they take different paths through the
        rewrite — one is collapsible, the other declines — and a rewrite is only
        worth having if both give the same answer.
        """
        space_id, graph = seeded
        _sql, rows = await _rows(
            pg_conn, space_id, _criteria_query(graph, f"{EX}e0", slot_typed=slot_typed))
        pairs = _pairs(rows)

        assert len(pairs) == 2, f"expected frames f0 and f1, got {sorted(pairs)}"
        assert {p[0] for p in pairs} == {f"{EX}f0", f"{EX}f1"}
        assert {p[1] for p in pairs} == {f"{EX}e1", f"{EX}e2"}, (
            "each frame must carry its OWN destination — mixing them is the "
            "failure a collapse gets wrong by joining on the frame alone")

    async def test_a_source_with_one_frame_returns_one(self, seeded, pg_conn):
        """Guards against a collapse that drops the source constraint and
        returns every frame — which still looks plausible on a fixture where
        most frames match."""
        space_id, graph = seeded
        _sql, rows = await _rows(
            pg_conn, space_id, _criteria_query(graph, f"{EX}e3", slot_typed=False))
        pairs = _pairs(rows)
        assert pairs == {(f"{EX}f2", f"{EX}e4")}, sorted(pairs)

    async def test_an_absent_source_returns_nothing(self, seeded, pg_conn):
        space_id, graph = seeded
        _sql, rows = await _rows(
            pg_conn, space_id, _criteria_query(graph, f"{EX}nope", slot_typed=False))
        assert _pairs(rows) == set()


class TestTheRewriteContract:
    """`issues/048`: fire correctly, or decline leaving no trace."""

    @pytest.mark.parametrize("slot_typed", [False, True],
                             ids=["no-slot-constraint", "slot-typed"])
    async def test_the_sql_runs(self, seeded, pg_conn, slot_typed):
        """The original defect was invalid SQL — `missing FROM-clause entry for
        table "mv0"` — from collapsing the six tables while a constraint still
        named a collapsed alias. A half-applied rewrite is worse than none, so
        this asserts the statement PLANS as well as returning rows."""
        space_id, graph = seeded
        sql = await _sql_for(
            pg_conn, space_id, _criteria_query(graph, f"{EX}e0", slot_typed=slot_typed))
        await pg_conn.execute(f"EXPLAIN {sql}")

    async def test_rewrite_on_and_off_agree(self, seeded, pg_conn, monkeypatch):
        """The differential. Whether the rewrite fires must not change the
        answer — that is the whole basis for having it.

        Driven by disabling the pass, so this compares the two plans of the SAME
        query rather than two queries believed equivalent.
        """
        space_id, graph = seeded
        sparql = _criteria_query(graph, f"{EX}e0", slot_typed=False)

        _sql_on, rows_on = await _rows(pg_conn, space_id, sparql)

        _disable_rewrite(monkeypatch)
        sql_off, rows_off = await _rows(pg_conn, space_id, sparql)
        assert "frame_entity" not in sql_off, "the rewrite was not disabled"

        assert _pairs(rows_on) == _pairs(rows_off), (
            "the frame_entity rewrite changed the answer")

    async def test_a_slot_constraint_is_not_silently_dropped(self, seeded, pg_conn):
        """`frame_entity` has no slot column, so a slot-node constraint cannot
        be carried through a collapse. It must be honoured by declining — never
        discarded to make the collapse possible.

        Asserted through behaviour: constrain the slot to a type NOTHING has. If
        the constraint survives, the answer is empty; if a collapse dropped it,
        rows come back and the query silently ignored what it was asked.
        """
        space_id, graph = seeded
        sparql = f"""
        SELECT DISTINCT ?frame WHERE {{ GRAPH <{graph}> {{
            ?frame a <{HALEY}KGFrame> .
            ?sourceEdge <{VITAL}hasEdgeSource> ?frame .
            ?sourceEdge <{VITAL}hasEdgeDestination> ?sourceSlot .
            ?sourceSlot a <{HALEY}KGTextSlot> .
            ?sourceSlot <{HALEY}hasKGSlotType> <{SRC_ROLE}> .
            ?sourceSlot <{HALEY}hasEntitySlotValue> <{EX}e0> .
        }} }}"""
        _sql, rows = await _rows(pg_conn, space_id, sparql)
        assert len(rows) == 0, (
            "the slots here are KGEntitySlot, so constraining them to "
            "KGTextSlot must match nothing; rows mean the constraint was lost")


class TestWhetherTheTableIsUsed:
    """Records the CURRENT state so a change is visible, without asserting it
    must stay that way — making the rewrite fire on this shape is open work."""

    async def test_report_frame_entity_usage(self, seeded, pg_conn):
        space_id, graph = seeded
        used = {}
        for label, typed in (("plain", False), ("slot-typed", True)):
            sql = await _sql_for(pg_conn, space_id,
                                 _criteria_query(graph, f"{EX}e0", slot_typed=typed))
            used[label] = "frame_entity" in sql

        rows = await pg_conn.fetch(
            f"SELECT count(*) AS n FROM {space_id}_frame_entity")
        populated = rows[0]["n"] if rows else 0

        print(f"\nframe_entity rows: {populated}")
        print(f"rewrite reaches frame_entity — plain: {used['plain']}, "
              f"slot-typed: {used['slot-typed']}")

        assert not used["slot-typed"], (
            "the rewrite collapsed a query carrying a slot-node constraint. "
            "That is either the open work in issues/048 finally done — in which "
            "case delete this assertion — or the guard has regressed and the "
            "'missing FROM-clause entry' defect is back. The behavioural tests "
            "above tell you which.")


def _both_ends_variable_query(graph: str) -> str:
    """The same 6 tables, but with BOTH slot values left as variables.

    This is the shape the detector actually accepts. It matters because the
    difference from `_criteria_query` is one term — whether the source entity is
    a variable or a constant — and that term decides whether the collapse
    happens at all.
    """
    return f"""
    SELECT DISTINCT ?frame ?srcEntity ?destEntity WHERE {{ GRAPH <{graph}> {{
        ?frame a <{HALEY}KGFrame> .

        ?sourceEdge <{VITAL}hasEdgeSource> ?frame .
        ?sourceEdge <{VITAL}hasEdgeDestination> ?sourceSlot .
        ?sourceSlot <{HALEY}hasKGSlotType> <{SRC_ROLE}> .
        ?sourceSlot <{HALEY}hasEntitySlotValue> ?srcEntity .

        ?destEdge <{VITAL}hasEdgeSource> ?frame .
        ?destEdge <{VITAL}hasEdgeDestination> ?destSlot .
        ?destSlot <{HALEY}hasKGSlotType> <{DST_ROLE}> .
        ?destSlot <{HALEY}hasEntitySlotValue> ?destEntity .
    }} }}"""


class TestTheCollapseActuallyHappening:
    """The rewrite DOES fire — on a narrower shape than 048 suggests.

    It requires both slot values to be VARIABLES. `_find_slot_groups` reads the
    entity from `quad_object_var`, so a slot value pinned to a constant yields
    no entity variable, the group is skipped, and the frame ends up with only
    one of its two groups — logged as "no frame variable carries BOTH a source
    and a dest group".
    """

    async def test_it_fires_when_both_ends_are_variables(self, seeded, pg_conn):
        space_id, graph = seeded
        sql = await _sql_for(pg_conn, space_id, _both_ends_variable_query(graph))
        assert "frame_entity" in sql, (
            "the 6-table pattern with both ends free is the case the rewrite "
            "was built for; if it stopped firing here the table is entirely "
            "dead rather than merely under-used")

    async def test_collapsing_gives_the_same_answer(self, seeded, pg_conn, monkeypatch):
        """The differential on the shape that actually collapses — the one that
        matters, since this is the plan the rewrite substitutes."""
        space_id, graph = seeded
        sparql = _both_ends_variable_query(graph)

        sql_on, rows_on = await _rows(pg_conn, space_id, sparql)
        assert "frame_entity" in sql_on

        _disable_rewrite(monkeypatch)
        sql_off, rows_off = await _rows(pg_conn, space_id, sparql)
        assert "frame_entity" not in sql_off, "the rewrite was not disabled"

        def triples(rows):
            return {tuple(sorted(str(v) for v in r.values()
                                 if isinstance(v, str) and v.startswith(EX)))
                    for r in rows}

        assert triples(rows_on) == triples(rows_off), (
            "collapsing 6 tables into frame_entity changed the answer")
        assert len(rows_on) == len(ALL_FRAMES), (
            f"every frame has a source and a dest, so all {len(ALL_FRAMES)} "
            f"must appear; got {len(rows_on)}")

    async def test_pinning_one_end_to_a_constant_prevents_the_collapse(
            self, seeded, pg_conn):
        """Records the limitation, because it is the shape a real criteria query
        has — "frames whose source is X" — and it is exactly the one that does
        NOT collapse.

        Not asserted as desirable. If the detector learns to treat a constant
        end as a filter on the collapsed row, this flips, and the differential
        tests above are what will say whether the new plan is correct.
        """
        space_id, graph = seeded
        sql = await _sql_for(
            pg_conn, space_id, _criteria_query(graph, f"{EX}e0", slot_typed=False))
        assert "frame_entity" not in sql, (
            "the constant-ended criteria query now collapses — good, but "
            "update this test and confirm the differential still holds")


# ---------------------------------------------------------------------------
# Multi-hop: the synset traversal shape
# ---------------------------------------------------------------------------

def _hop(n: int, from_var: str, to_var: str) -> str:
    """One entity -> frame -> entity hop, as its own 6 tables.

    Both slot values stay VARIABLES, because that is what the group detector
    requires; a hop with a constant end is not recognised as a group at all.
    The start entity is pinned by FILTER instead, which constrains the same
    thing without turning the slot value into a constant.
    """
    return f"""
        ?f{n} a <{HALEY}KGFrame> .
        ?se{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?se{n} <{VITAL}hasEdgeDestination> ?ss{n} .
        ?ss{n} <{HALEY}hasKGSlotType> <{SRC_ROLE}> .
        ?ss{n} <{HALEY}hasEntitySlotValue> {from_var} .
        ?de{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?de{n} <{VITAL}hasEdgeDestination> ?ds{n} .
        ?ds{n} <{HALEY}hasKGSlotType> <{DST_ROLE}> .
        ?ds{n} <{HALEY}hasEntitySlotValue> {to_var} ."""


def _chain_query(graph: str, start: str, depth: int) -> str:
    """Follow `depth` frames from `start`, projecting the far end.

    Each hop is an independent 6-table group sharing only the entity variable
    with its neighbour — so a depth-3 traversal is 18 quad tables, and a
    complete collapse is three frame_entity rows.
    """
    hops = "".join(_hop(i + 1, f"?ent{i}", f"?ent{i + 1}") for i in range(depth))
    return f"""
    SELECT DISTINCT ?ent{depth} WHERE {{ GRAPH <{graph}> {{
        {hops}
        FILTER(?ent0 = <{start}>)
    }} }}"""


def _reached(rows):
    return {str(v) for r in rows for v in r.values()
            if isinstance(v, str) and v.startswith(EX)}


class TestMultiHopTraversal:
    """Depth 2 and 3, the shape a synset walk has.

    `issues/048` counts joins by depth — 6 quad joins at depth 1, 8 at depth 2 —
    so depth is the axis the whole argument for this table sits on, and it had
    no coverage at any depth.
    """

    async def test_depth_1(self, seeded, pg_conn):
        space_id, graph = seeded
        _sql, rows = await _rows(pg_conn, space_id, _chain_query(graph, f"{EX}c0", 1))
        assert _reached(rows) == {f"{EX}c1"}

    async def test_depth_2_follows_the_branch(self, seeded, pg_conn):
        """c1 has TWO outgoing frames, so depth 2 reaches both. A traversal that
        joined hops on the frame rather than the shared entity would return one,
        or the cross product."""
        space_id, graph = seeded
        _sql, rows = await _rows(pg_conn, space_id, _chain_query(graph, f"{EX}c0", 2))
        assert _reached(rows) == {f"{EX}c2", f"{EX}b1"}

    async def test_depth_3_excludes_the_dead_end(self, seeded, pg_conn):
        """Only c2 continues; b1 is a dead end. Returning b1 here would mean the
        traversal carried a SHORT path forward and reported it at full depth —
        the error that looks like a plausible answer."""
        space_id, graph = seeded
        _sql, rows = await _rows(pg_conn, space_id, _chain_query(graph, f"{EX}c0", 3))
        assert _reached(rows) == {f"{EX}c3"}

    async def test_depth_3_from_a_dead_end_is_empty(self, seeded, pg_conn):
        space_id, graph = seeded
        _sql, rows = await _rows(pg_conn, space_id, _chain_query(graph, f"{EX}b1", 3))
        assert _reached(rows) == set()

    @pytest.mark.parametrize("depth", [1, 2, 3])
    async def test_every_hop_collapses(self, seeded, pg_conn, depth):
        """The saving is PER HOP — that is the claim in 048's join table — so a
        depth-3 traversal should reach frame_entity three times, not once.

        A single reference would mean only the first hop collapsed and the rest
        stayed as raw quad joins, which is the failure that still looks like a
        working optimisation.
        """
        space_id, graph = seeded
        sql = await _sql_for(pg_conn, space_id, _chain_query(graph, f"{EX}c0", depth))
        joins = sql.count(f"{space_id}_frame_entity")
        assert joins == depth, (
            f"depth {depth} collapsed {joins} hop(s); each hop is its own "
            f"6-table group and each should become one frame_entity join")

    @pytest.mark.parametrize("depth", [2, 3])
    async def test_collapsed_and_uncollapsed_agree(self, seeded, pg_conn,
                                                   monkeypatch, depth):
        """The differential at depth. Multi-hop is where a collapse can go wrong
        without looking wrong: the joins between hops are what it rewrites, and
        a hop joined on the wrong column still returns plausible entities."""
        space_id, graph = seeded
        sparql = _chain_query(graph, f"{EX}c0", depth)

        sql_on, rows_on = await _rows(pg_conn, space_id, sparql)
        assert f"{space_id}_frame_entity" in sql_on

        _disable_rewrite(monkeypatch)
        sql_off, rows_off = await _rows(pg_conn, space_id, sparql)
        assert f"{space_id}_frame_entity" not in sql_off, "rewrite not disabled"

        assert _reached(rows_on) == _reached(rows_off), (
            f"depth {depth}: collapsing changed which entities are reachable")

    async def test_the_collapse_removes_joins(self, seeded, pg_conn, monkeypatch):
        """Record the reduction rather than assume it: 6 quad tables per hop
        against one frame_entity row."""
        space_id, graph = seeded
        sparql = _chain_query(graph, f"{EX}c0", 3)

        sql_on = await _sql_for(pg_conn, space_id, sparql)
        _disable_rewrite(monkeypatch)
        sql_off = await _sql_for(pg_conn, space_id, sparql)

        quad_on = sql_on.count(f"{space_id}_rdf_quad")
        quad_off = sql_off.count(f"{space_id}_rdf_quad")
        print(f"\ndepth 3 — rdf_quad references: {quad_off} -> {quad_on}, "
              f"frame_entity joins: {sql_on.count(f'{space_id}_frame_entity')}")
        assert quad_on < quad_off, (
            f"the collapse did not reduce quad-table joins ({quad_off} -> "
            f"{quad_on}); it is meant to replace 6 tables per hop with 1")


# ---------------------------------------------------------------------------
# Criteria-filtered traversal — which hops are followed at all
# ---------------------------------------------------------------------------

def _filtered_chain(graph: str, start: str, depth: int, *, hop_filter: str) -> str:
    """A chain where every hop must ALSO satisfy `hop_filter` on its frame.

    This is what a real traversal looks like. An unfiltered walk follows every
    edge and is rarely the question anyone asks; the criterion on the frame —
    its type, a score threshold, a date range — is what decides which paths are
    taken, and it is applied per hop rather than to the endpoints.
    """
    # `hop_filter` is a TEMPLATE using {n}: every variable it introduces must be
    # numbered per hop. Sharing one `?sc` across hops silently requires a single
    # score to satisfy every hop at once, which no path can, and the query
    # returns empty for a reason that has nothing to do with the data.
    hops = "".join(
        _hop(i + 1, f"?ent{i}", f"?ent{i + 1}") + hop_filter.format(n=i + 1)
        for i in range(depth))
    return f"""
    SELECT DISTINCT ?ent{depth} WHERE {{ GRAPH <{graph}> {{
        {hops}
        FILTER(?ent0 = <{start}>)
    }} }}"""


class TestCriteriaFilteredTraversal:
    """The criterion on the frame decides which hops are followed.

    wordnet can only express one kind — the traversal type — so these model the
    value criteria production data uses: a numeric threshold and a date range.
    Each selects a DIFFERENT path out of the branch at c1, so a criterion that
    were dropped would return the union and be caught here rather than passing
    as a plausible answer.
    """

    async def test_frame_type_selects_one_branch(self, seeded, pg_conn):
        """c1 has a HYPERNYM hop to c2 and a HYPONYM hop to b1. Following only
        hypernyms must reach c2 and not b1 — the wordnet criterion."""
        space_id, graph = seeded
        q = _filtered_chain(graph, f"{EX}c0", 2,
                            hop_filter=f'\n        ?f{{n}} <{HALEY}hasKGFrameType> <{HYPERNYM}> .')
        _sql, rows = await _rows(pg_conn, space_id, q)
        assert _reached(rows) == {f"{EX}c2"}, (
            "a dropped type criterion would also return b1, reached by the "
            "hyponym edge")

    async def test_a_numeric_threshold_selects_the_other_branch(self, seeded, pg_conn):
        """score >= 100 admits h0 (150) and h1b (200) but rejects h1 (50), so
        the walk goes to b1 — the opposite branch from the type filter. Two
        criteria over the same graph giving different answers is what shows each
        is actually applied."""
        space_id, graph = seeded
        q = _filtered_chain(graph, f"{EX}c0", 2,
                            hop_filter=f'\n        ?f{{n}} <{FRAME_SCORE}> ?sc{{n}} . FILTER(?sc{{n}} >= 100)')
        _sql, rows = await _rows(pg_conn, space_id, q)
        assert _reached(rows) == {f"{EX}b1"}

    async def test_a_threshold_nothing_meets_stops_the_walk(self, seeded, pg_conn):
        space_id, graph = seeded
        q = _filtered_chain(graph, f"{EX}c0", 2,
                            hop_filter=f'\n        ?f{{n}} <{FRAME_SCORE}> ?sc{{n}} . FILTER(?sc{{n}} >= 10000)')
        _sql, rows = await _rows(pg_conn, space_id, q)
        assert _reached(rows) == set()

    async def test_a_date_range_selects_by_when_the_hop_applies(self, seeded, pg_conn):
        """h0 (Jan) and h1b (Mar) fall inside; h1 (Jun) does not. So the walk
        reaches b1 and not c2 — the same shape a "created between" filter has."""
        space_id, graph = seeded
        q = _filtered_chain(
            graph, f"{EX}c0", 2,
            hop_filter=(f'\n        ?f{{n}} <{FRAME_DATE}> ?wh{{n}} . '
                        f'FILTER(?wh{{n}} >= "2026-01-01T00:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime> '
                        f'&& ?wh{{n}} <= "2026-04-01T00:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>)'))
        _sql, rows = await _rows(pg_conn, space_id, q)
        assert _reached(rows) == {f"{EX}b1"}

    async def test_criteria_apply_per_hop_not_just_the_first(self, seeded, pg_conn):
        """Depth 3 along the hypernym path: h0, h1 and h2 are all hypernyms, so
        c3 is reachable. Reject h2 by score and the walk must stop at depth 2 —
        proving the criterion is evaluated on the LAST hop too, not only where
        the traversal starts.
        """
        space_id, graph = seeded
        hyp = f'\n        ?f{{n}} <{HALEY}hasKGFrameType> <{HYPERNYM}> .'
        _sql, rows = await _rows(pg_conn, space_id,
                                 _filtered_chain(graph, f"{EX}c0", 3, hop_filter=hyp))
        assert _reached(rows) == {f"{EX}c3"}

        # h2 scores 300; excluding it must leave depth 3 unreachable.
        strict = hyp + f'\n        ?f{{n}} <{FRAME_SCORE}> ?sc{{n}} . FILTER(?sc{{n}} < 300)'
        _sql2, rows2 = await _rows(pg_conn, space_id,
                                   _filtered_chain(graph, f"{EX}c0", 3, hop_filter=strict))
        assert _reached(rows2) == set(), (
            "the criterion was not applied to the final hop")

    @pytest.mark.parametrize("depth", [2, 3])
    async def test_the_collapse_survives_a_frame_criterion(self, seeded, pg_conn, depth):
        """A criterion on the FRAME can be carried through the collapse —
        frame_entity keeps frame_uuid, so the constraint still has a column to
        land on. Contrast the slot-node constraint, which has none and makes the
        rewrite decline entirely.

        Recorded because it is the difference between a filtered traversal that
        can use this table and one that cannot.
        """
        space_id, graph = seeded
        q = _filtered_chain(graph, f"{EX}c0", depth,
                            hop_filter=f'\n        ?f{{n}} <{HALEY}hasKGFrameType> <{HYPERNYM}> .')
        sql = await _sql_for(pg_conn, space_id, q)
        assert sql.count(f"{space_id}_frame_entity") == depth, (
            "a frame-level criterion should not cost the collapse; if this "
            "fails, filtered traversal has lost the table entirely")

    @pytest.mark.parametrize("depth", [2, 3])
    async def test_filtered_traversal_agrees_collapsed_or_not(
            self, seeded, pg_conn, monkeypatch, depth):
        """The differential that matters most: a criterion decides which paths
        exist, so a collapse that mis-associates a frame with its endpoints
        returns a WRONG SET rather than a slow one."""
        space_id, graph = seeded
        q = _filtered_chain(graph, f"{EX}c0", depth,
                            hop_filter=f'\n        ?f{{n}} <{HALEY}hasKGFrameType> <{HYPERNYM}> .')

        sql_on, rows_on = await _rows(pg_conn, space_id, q)
        assert f"{space_id}_frame_entity" in sql_on

        _disable_rewrite(monkeypatch)
        sql_off, rows_off = await _rows(pg_conn, space_id, q)
        assert f"{space_id}_frame_entity" not in sql_off, "rewrite not disabled"

        assert _reached(rows_on) == _reached(rows_off), (
            f"depth {depth}: the collapse changed which paths the criterion "
            f"admits")
