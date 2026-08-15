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
    # The head is a VARIABLE pinned by a FILTER, which is how the pipeline
    # actually emits `FILTER(?e0 = <start>)`. Without it here the pin's own
    # filter looks like a filter on an intermediate variable.
    slots["e0"] = VarSlot(name="e0",
                          positions=[("femv0", "source_entity_uuid")])
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


class TestDedupPrecondition:
    """`dedup_feasible` is a CORRECTNESS gate, not an optimisation heuristic.

    Deduplicating between hops destroys path multiplicity, and multiplicity is
    sometimes the answer: `SELECT ?e3` without DISTINCT returns one row per
    path — 501,538 of them on the wordnet depth-3 walk — where dedup returns
    3,108. So every refusal here is the difference between a right and a wrong
    answer, which is why they are tested one at a time rather than through the
    emitted SQL.
    """

    @staticmethod
    def _tree(*kinds, depth=3, project=("e3",), filters=None, order=None):
        """A plan: the given modifier kinds stacked above a depth-N traversal."""
        from vitalgraph.db.sparql_sql.ir import (
            KIND_PROJECT, KIND_DISTINCT, KIND_SLICE, KIND_FILTER, KIND_ORDER,
            KIND_GROUP)
        node = _plan(depth)
        for k in reversed(kinds):
            parent = PlanV2(kind=k, children=[node])
            if k == KIND_PROJECT:
                parent.project_vars = list(project)
            if k == KIND_FILTER:
                parent.filter_exprs = list(filters or [])
            if k == KIND_ORDER:
                parent.order_conditions = list(order or [])
            node = parent
        return node

    def _feasible(self, tree, text=None, depth=3):
        from vitalgraph.db.sparql_sql.emit_traversal import dedup_feasible
        return dedup_feasible(tree, _chain(depth), text)

    def test_project_distinct_over_a_traversal_is_allowed(self):
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT, KIND_DISTINCT
        got = self._feasible(self._tree(KIND_DISTINCT, KIND_PROJECT))
        assert got is not None
        _final, surviving = got
        assert "e3" in surviving

    def test_without_DISTINCT_it_refuses(self):
        """`SELECT ?e3` returns a row per path. Deduplicating would answer a
        different question, and it is the one refusal that cannot be recovered
        from downstream."""
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT
        assert self._feasible(self._tree(KIND_PROJECT)) is None

    def test_an_aggregate_refuses(self):
        """COUNT(*) over the paths is a count OF the multiplicity."""
        from vitalgraph.db.sparql_sql.ir import (KIND_PROJECT, KIND_DISTINCT,
                                                 KIND_GROUP)
        assert self._feasible(
            self._tree(KIND_DISTINCT, KIND_GROUP, KIND_PROJECT)) is None

    def test_an_order_by_a_surviving_variable_is_allowed(self):
        """`LIMIT` introduces an ORDER sorting by the projected variable, so
        refusing ORDER outright refused every PAGED traversal — measured at
        1,554 ms for `LIMIT 25` against 78.9 ms for the same walk unlimited.

        An ORDER re-arranges rows; it cannot observe how many paths produced
        one. What matters is only that its sort keys survive."""
        from vitalgraph.db.sparql_sql.ir import (KIND_PROJECT, KIND_DISTINCT,
                                                 KIND_ORDER)
        got = self._feasible(self._tree(KIND_DISTINCT, KIND_ORDER, KIND_PROJECT,
                                        order=[("e3", "ASC")]))
        assert got is not None and "e3" in got[1]

    def test_an_order_by_a_discarded_variable_refuses(self):
        """Sorting on a column dedup nulls would order the answer by nothing."""
        from vitalgraph.db.sparql_sql.ir import (KIND_PROJECT, KIND_DISTINCT,
                                                 KIND_ORDER)
        assert self._feasible(
            self._tree(KIND_DISTINCT, KIND_ORDER, KIND_PROJECT,
                       order=[("c1", "ASC")])) is None

    def test_an_order_by_an_expression_is_walked(self):
        """A sort key arrives as a bare name OR an expression; both must be
        read, or an expression over a discarded variable slips through."""
        from vitalgraph.db.sparql_sql.ir import (KIND_PROJECT, KIND_DISTINCT,
                                                 KIND_ORDER)
        from vitalgraph.db.jena_sparql.jena_types import ExprFunction, ExprVar
        key = ExprFunction(name="lcase", args=[ExprVar(var="c1")])
        assert self._feasible(
            self._tree(KIND_DISTINCT, KIND_ORDER, KIND_PROJECT,
                       order=[(key, "ASC")])) is None

    def test_projecting_an_intermediate_variable_refuses(self):
        """`?e1` does not survive a set of depth-3 entities."""
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT, KIND_DISTINCT
        assert self._feasible(
            self._tree(KIND_DISTINCT, KIND_PROJECT, project=("e1",))) is None

    def test_projecting_a_criterion_variable_refuses(self):
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT, KIND_DISTINCT
        assert self._feasible(
            self._tree(KIND_DISTINCT, KIND_PROJECT, project=("c0",))) is None

    def test_the_pin_filter_is_allowed(self):
        """The filter above a traversal is normally the pin itself. A filter is
        row-wise, so it cannot observe multiplicity — what matters is that the
        variable it reads survives, and the pinned head is carried through."""
        from vitalgraph.db.sparql_sql.ir import (KIND_PROJECT, KIND_DISTINCT,
                                                 KIND_FILTER)
        from vitalgraph.db.jena_sparql.jena_types import (
            ExprFunction, ExprValue, ExprVar, URINode)
        pin = ExprFunction(name="eq", args=[
            ExprVar(var="e0"), ExprValue(node=URINode(value="urn:start"))])
        got = self._feasible(self._tree(KIND_DISTINCT, KIND_PROJECT, KIND_FILTER,
                                        filters=[pin]))
        assert got is not None, "the pin must not disqualify its own traversal"

    def test_a_filter_on_an_intermediate_variable_refuses(self):
        """That column is NULL after dedup, so the filter would drop every row
        rather than fail visibly."""
        from vitalgraph.db.sparql_sql.ir import (KIND_PROJECT, KIND_DISTINCT,
                                                 KIND_FILTER)
        from vitalgraph.db.jena_sparql.jena_types import (
            ExprFunction, ExprValue, ExprVar, LiteralNode)
        f = ExprFunction(name="gt", args=[
            ExprVar(var="c1"), ExprValue(node=LiteralNode(value="5", datatype=None))])
        assert self._feasible(
            self._tree(KIND_DISTINCT, KIND_PROJECT, KIND_FILTER, filters=[f])) is None

    def test_only_the_final_destination_and_the_head_survive(self):
        """The SURVIVING set is narrower than "bound by the last hop", and the
        difference cost a wrong answer.

        `emit_dedup_chain` projects exactly two things — the final link's DEST
        column and the pinned head. A criterion value bound on one of the last
        hop's QUAD tables is emitted NULL, because a set of entities does not
        remember what it was filtered by. Treating those as surviving let one
        keep its term JOIN, which inner-joined against the NULL and dropped
        every row: 0 answers where 16 were expected, on 46 of 120 cases.
        """
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT, KIND_DISTINCT
        final, surviving = self._feasible(self._tree(KIND_DISTINCT, KIND_PROJECT))
        assert surviving == {"e3", "e0"}, (
            "only the final destination and the pinned head are projected")
        assert "c2" in final, "the last hop does BIND a criterion variable..."
        assert "c2" not in surviving, "...but it does not survive dedup"

    def test_text_on_an_intermediate_variable_no_longer_refuses(self):
        """It narrows instead, and the caller suppresses the term JOIN.

        Refusing was over-broad: `text_needed_vars` is computed BEFORE
        push-down, so a per-hop criterion is marked text-needed because a FILTER
        mentions it. By emit time that filter has become a constraint inside the
        hop and the variable is unused — but the stale set still named it, and
        every FILTERED traversal declined on a variable nothing reads.
        """
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT, KIND_DISTINCT
        tree = self._tree(KIND_DISTINCT, KIND_PROJECT)
        got = self._feasible(tree, text={"e3", "c1"})
        assert got is not None, "a stale text flag must not refuse"
        assert "c1" not in got[1], (
            "c1 must not be reported as surviving, or its term JOIN would be "
            "emitted against a NULL")

    def test_depth_one_refuses(self):
        """One hop has no multiplicity between hops to collapse; the outer
        DISTINCT already does that work."""
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT, KIND_DISTINCT
        assert self._feasible(
            self._tree(KIND_DISTINCT, KIND_PROJECT, depth=1), depth=1) is None

    def test_two_bgps_refuse(self):
        """A second BGP means something joins to this one, and a row dedup
        drops may be a row that joins."""
        from vitalgraph.db.sparql_sql.ir import KIND_PROJECT, KIND_DISTINCT, KIND_JOIN
        tree = self._tree(KIND_DISTINCT, KIND_PROJECT)
        joined = PlanV2(kind=KIND_JOIN, children=[_plan(3), _plan(2)])
        tree.children[0].children = [joined]
        assert self._feasible(tree) is None
