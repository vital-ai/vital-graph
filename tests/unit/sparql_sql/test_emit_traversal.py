"""Hop-wise emission: what it partitions, and everything it refuses.

`emit_traversal` rewrites the shape of a traversal query, so the thing worth
pinning is not the SQL text but the two properties the rewrite depends on:

  * every table lands in exactly one hop, and a table that cannot be assigned
    unambiguously makes the whole thing decline rather than guess;
  * every constraint is emitted exactly once. Dropping one silently WIDENS the
    answer, and a traversal that returns a superset looks like a working query.

Correctness against real data lives in
`tests/performance/test_graph_traversal_fixture.py`, which compares against a
BFS over the generated edge list. These are the structural checks that do not
need a database, plus the refusals — which is where this class of pass has gone
wrong before, by declining silently and being merely slow.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.ir import PlanV2, TableRef, VarSlot, KIND_BGP
from vitalgraph.db.sparql_sql.traversal_chain import ChainLink, TraversalChain
from vitalgraph.db.sparql_sql.emit_traversal import (
    MIN_EMIT_DEPTH, emit_hop_wise, partition_hops, _refs)

pytestmark = pytest.mark.unit

CTX = "'ctx'::uuid"


def _fe(i):
    return TableRef(ref_id=f"femv{i}", kind="frame_entity",
                    table_name="s_frame_entity", alias=f"femv{i}")


def _q(name):
    return TableRef(ref_id=name, kind="quad", table_name="s_rdf_quad", alias=name)


def _plan(depth=3, criteria=True):
    """A depth-N frame walk: each hop is femv{i} + a type check + a criterion.

    Mirrors what `rewrite_frame_entity_table` actually leaves behind — the
    criterion table joins the TYPE table, not the link, so a hop is only
    recoverable by walking the constraint graph rather than by adjacency.
    """
    tables, tagged, slots = [], [], {}
    for i in range(depth):
        tables.append(_fe(i))
        tagged.append((f"femv{i}", f"femv{i}.context_uuid = {CTX}"))
        if i == 0:
            tagged.append((f"femv0", f"femv0.source_entity_uuid = 'pin'::uuid"))
        else:
            tagged.append((f"femv{i}",
                           f"femv{i}.source_entity_uuid = femv{i-1}.dest_entity_uuid"))
        slots[f"e{i+1}"] = VarSlot(name=f"e{i+1}",
                                   positions=[(f"femv{i}", "dest_entity_uuid")])
        if criteria:
            ty, cr = _q(f"qt{i}"), _q(f"qc{i}")
            tables += [ty, cr]
            tagged.append((f"qt{i}", f"qt{i}.predicate_uuid = 'a'::uuid "
                                     f"AND femv{i}.frame_uuid = qt{i}.subject_uuid"))
            tagged.append((f"qc{i}", f"qc{i}.subject_uuid = qt{i}.subject_uuid "
                                     f"AND qc{i}.object_uuid = 'v'::uuid"))
            slots[f"c{i}"] = VarSlot(name=f"c{i}",
                                     positions=[(f"qc{i}", "object_uuid")])
    return PlanV2(kind=KIND_BGP, tables=tables, tagged_constraints=tagged,
                  var_slots=slots)


def _chain(depth=3, head=True, tail=False):
    return TraversalChain(
        links=[ChainLink(ref_id=f"femv{i}", kind="frame_entity",
                         source_col="source_entity_uuid",
                         dest_col="dest_entity_uuid") for i in range(depth)],
        pinned_head=head, pinned_tail=tail)


def _names(plan):
    return {v: f"v{i}" for i, v in enumerate(plan.var_slots)}


class TestPartitioning:

    def test_each_hop_gets_its_own_link_and_criterion_tables(self):
        plan = _plan(3)
        groups = partition_hops(plan, _chain(3), plan.tables)
        assert groups is not None
        assert [g.link_alias for g in groups] == ["femv0", "femv1", "femv2"]
        for i, g in enumerate(groups):
            assert {t.alias for t in g.tables} == {f"femv{i}", f"qt{i}", f"qc{i}"}

    def test_the_link_is_placed_first(self):
        """What the measured plan did. The pin sits on the link and its estimate
        is real, so it is the one table that should drive the hop."""
        groups = partition_hops(_plan(3), _chain(3), _plan(3).tables)
        assert all(g.tables[0].alias == g.link_alias for g in groups)

    def test_a_criterion_two_joins_away_still_lands_in_its_hop(self):
        """`qc{i}` touches only `qt{i}`, never the link. Assignment has to be a
        walk of the constraint graph; adjacency alone would strand it."""
        groups = partition_hops(_plan(3), _chain(3), _plan(3).tables)
        assert "qc1" in {t.alias for t in groups[1].tables}

    def test_every_constraint_is_emitted_exactly_once(self):
        """A dropped constraint widens the answer, which reads as a working
        query returning a superset."""
        plan = _plan(3)
        groups = partition_hops(plan, _chain(3), plan.tables)
        emitted = [c for g in groups for c in g.where + g.crit_where]
        emitted += [c for g in groups for conds in g.on_map.values() for c in conds]
        assert sorted(emitted) == sorted(s for _o, s in plan.tagged_constraints)

    def test_the_pin_lands_on_the_first_hop(self):
        groups = partition_hops(_plan(3), _chain(3), _plan(3).tables)
        assert any("'pin'::uuid" in c for c in groups[0].where)


class TestItDeclines:
    """Each of these leaves the flat path untouched. Correct, and slower."""

    def test_a_table_bridging_two_hops(self):
        """A constraint tying hop 0's criterion to hop 2's would make the table
        belong to both. Putting it in either changes which rows survive."""
        plan = _plan(3)
        plan.tagged_constraints.append(("qc0", "qc0.object_uuid = qc2.object_uuid"))
        assert partition_hops(plan, _chain(3), plan.tables) is None

    def test_a_disconnected_island(self):
        plan = _plan(2)
        plan.tables.append(_q("lonely"))
        plan.tagged_constraints.append(("lonely", "lonely.predicate_uuid = 'x'::uuid"))
        assert partition_hops(plan, _chain(2), plan.tables) is None

    def test_no_tagged_constraints(self):
        plan = _plan(2)
        plan.tagged_constraints = []
        assert partition_hops(plan, _chain(2), plan.tables) is None

    def test_a_chain_whose_links_are_not_bgp_tables(self):
        plan = _plan(2)
        assert partition_hops(plan, _chain(4), plan.tables) is None

    def test_a_tail_only_pin(self):
        """Driving from a tail pin means walking the chain backwards, which is a
        different emission and is unmeasured. The decision reports tail pins as
        eligible; emitting a FORWARD walk for one would drive from the wrong
        end, so this refuses rather than silently doing the wrong thing."""
        plan = _plan(3)
        got = emit_hop_wise(plan, _chain(3, head=False, tail=True),
                            plan.tables, _names(plan))
        assert got is None


class TestDepthOne:
    """Depth 1 qualifies, and did not until the criteria were fenced.

    With a hop emitted as one join there was no lateral to place at depth 1, so
    hop-wise would have produced the SAME SQL it replaced. Once each hop's
    criteria sit behind its link, one hop has a structure of its own — and it is
    the biggest win measured: 158 ms -> 0.4 ms on a boolean criterion, 31 ms ->
    0.2 ms on a numeric one. Same mechanism as every other depth: a pinned
    constant that ought to drive, and does not without the fence.
    """

    def test_it_emits(self):
        plan = _plan(1)
        sql = emit_hop_wise(plan, _chain(1), plan.tables, _names(plan))
        assert sql is not None
        assert MIN_EMIT_DEPTH == 1

    def test_the_criteria_are_fenced_behind_the_link(self):
        plan = _plan(1)
        sql = emit_hop_wise(plan, _chain(1), plan.tables, _names(plan))
        assert sql.count("CROSS JOIN LATERAL") == 1
        assert "OFFSET 0" in sql
        assert sql.index("AS femv0") < sql.index("CROSS JOIN LATERAL")

    def test_a_lone_link_with_no_criteria_is_not_worth_emitting(self):
        """Nothing to fence and nothing to sequence — it would be the same SQL,
        and reporting it as hop-wise would be false in the logs."""
        plan = _plan(1, criteria=False)
        assert emit_hop_wise(plan, _chain(1), plan.tables, _names(plan)) is None


class TestEmittedShape:

    def test_hops_nest_rather_than_sequence(self):
        """Sequential laterals cannot see the aliases INSIDE an earlier one, so
        `femv2.source_entity_uuid = femv1.dest_entity_uuid` would have to be
        rewritten to name a projected column. Nesting keeps every enclosing
        alias in scope and the constraint is emitted verbatim."""
        plan = _plan(3)
        sql = emit_hop_wise(plan, _chain(3), plan.tables, _names(plan))
        # nested: hop2's opening paren comes before hop1's closing alias
        assert sql.index(") AS hop2") < sql.index(") AS hop1")
        assert "femv2.source_entity_uuid = femv1.dest_entity_uuid" in sql

    def test_the_link_is_alone_in_its_hop_s_FROM(self):
        """The 55x regression. Listing the link first is not enough — inside a
        hop PostgreSQL reorders freely, and on a boolean criterion it drove from
        `hasActive = true` (13,198 rows) and applied the pinned entity as a
        FILTER on the inner side: 3.4M buffers. `score >= 50` on the same shape
        happened to pick the link, so the old form was lucky rather than right.

        A lateral makes the dependency one-way. Nothing may be joined to the
        link before its lateral opens."""
        plan = _plan(3)
        sql = emit_hop_wise(plan, _chain(3), plan.tables, _names(plan))
        for i in range(3):
            after = sql[sql.index(f"AS femv{i}") + 1:]
            nxt = after[:after.index("\n", after.index("\n") + 1)]
            assert "JOIN" not in nxt.split("CROSS JOIN LATERAL")[0], (
                f"something is joined to femv{i} ahead of its lateral")

    def test_criteria_and_hops_are_each_fenced(self):
        """Unfenced, PostgreSQL flattens the lateral back into the join and
        re-picks the order this exists to override — 16.1 ms against 0.2 ms at
        depth 3. One fence per criterion group and one per hop below the first:
        2*depth - 1 at depth 3."""
        plan = _plan(3)
        sql = emit_hop_wise(plan, _chain(3), plan.tables, _names(plan))
        assert sql.count("CROSS JOIN LATERAL") == 5
        assert sql.count("OFFSET 0") == 5

    def test_a_hop_with_no_criterion_tables_still_emits(self):
        """Not every hop carries a criterion; the chain must not break on one
        that does not."""
        plan = _plan(2, criteria=False)
        sql = emit_hop_wise(plan, _chain(2), plan.tables, _names(plan))
        assert sql is not None and "femv1" in sql
        assert "crit0" not in sql

    def test_variables_bound_deeper_are_projected_all_the_way_up(self):
        """A variable bound in the innermost hop has to surface as a column of
        the outermost SELECT, or the term JOINs above it reference nothing."""
        plan = _plan(3)
        names = _names(plan)
        sql = emit_hop_wise(plan, _chain(3), plan.tables, names)
        head = sql[:sql.index("FROM")]
        for var in plan.var_slots:
            assert f"{names[var]}__uuid" in head, f"{var} never reaches the top"


class TestRefExtraction:
    """Which aliases a constraint mentions decides which hop it lands in."""

    def test_a_longer_alias_is_not_matched_by_a_shorter_one(self):
        """`f"{a}." in sql` — the substring test used elsewhere — reports `q1`
        for `xq1.col` and would assign the constraint to the wrong hop."""
        assert _refs("xq1.col = 'x'", {"q1", "xq1"}) == {"xq1"}

    def test_unknown_qualifiers_are_ignored(self):
        """Table names and subquery aliases appear in constraint SQL too."""
        assert _refs("q1.o IN (SELECT t.term_uuid FROM s_term t)", {"q1"}) == {"q1"}
