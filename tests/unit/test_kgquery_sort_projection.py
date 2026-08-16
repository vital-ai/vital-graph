"""A generated ORDER BY may only name variables the query projects.

`issues/096`. `_build_sort_bindings` has three branches and only one of them
populated `select_vars`, so `entity_frame_slot` and `frame_slot` sorts emitted

    SELECT DISTINCT ?entity WHERE { ... ?slot p ?sort_val_0 . }
    ORDER BY ASC(?sort_val_0) ?entity

which is invalid SPARQL 1.1 (§15.1: under SELECT DISTINCT, ORDER BY may only use
projected variables) and became SQL ordering on a column the DISTINCT subquery
never selected — `column s0.v5 does not exist`. Jena compiled it, so nothing
failed until Postgres saw it.

THE INVARIANT IS THE POINT, not the three shapes. A per-shape test would have
been written for whichever sort someone was using at the time, and the branches
disagreeing on exactly this is what a per-shape test misses. `test_the_invariant`
below enumerates every sort_type the model declares, so a fourth branch added
later is covered without anyone remembering to come back here.

The second half of the fix is aggregation, and it is a correctness fix rather
than a tidiness one: a value reached through a frame or slot is many-per-entity,
so projecting it beside ?entity under DISTINCT yields one row PER VALUE. Measured
on `prod_kg`, 9,354 (entity-graph, slot-type) pairs hold more than one slot of
the same type — up to six — and one NurtureAction returned 4 rows for 1 entity.
A LIMIT 25 page of those is not 25 entities. See the integration test of the same
name for that half executed against real data.
"""

from __future__ import annotations

import re

import pytest

from vitalgraph.sparql.kg_query_builder import (
    EntityQueryCriteria,
    KGQueryCriteriaBuilder,
    SortCriteria,
)

pytestmark = pytest.mark.unit

TEXT_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
NAME = "http://vital.ai/ontology/vital-core#hasName"
FRAME = "urn:test:frame:Info"
SLOT = "urn:test:slot:Company"
GRAPH = "urn:test:graph"

# Every sort_type the dataclass documents (kg_query_builder.py:128). Listed
# here so a new one fails the invariant test until it is considered, rather
# than silently inheriting whichever branch it falls into.
ALL_SORT_TYPES = [
    "entity_frame_slot",
    "frame_slot",
    "source_frame_slot",
    "destination_frame_slot",
    "entity_property",
]


def sort_criteria(sort_type: str, order: str = "asc", priority: int = 1) -> SortCriteria:
    """A minimally-valid criterion of the given type."""
    if sort_type == "entity_property":
        return SortCriteria(sort_type, property_uri=NAME,
                            sort_order=order, priority=priority)
    return SortCriteria(sort_type, slot_type=SLOT, slot_class_uri=TEXT_SLOT,
                        # frame_slot is the no-frame-path branch; the rest walk one.
                        frame_path=[] if sort_type == "frame_slot" else [FRAME],
                        sort_order=order, priority=priority)


def order_by_vars(order_clause: str) -> set[str]:
    """Variables named anywhere in an ORDER BY clause."""
    return set(re.findall(r"\?(\w+)", order_clause))


def projected_names(select_vars: list[str]) -> set[str]:
    """The name each projection entry BINDS.

    `(MIN(?_sort_raw_0) AS ?sort_val_0)` projects `sort_val_0`, not
    `_sort_raw_0` — taking every variable in the string would let an
    unprojected ORDER BY variable pass by appearing inside an aggregate.
    """
    names = set()
    for v in select_vars:
        alias = re.search(r"AS\s+\?(\w+)\s*\)?$", v.strip())
        names.add(alias.group(1) if alias else v.strip().lstrip("?"))
    return names


class TestTheInvariant:
    """Whatever ORDER BY names, SELECT must project. Every sort type."""

    @pytest.mark.parametrize("sort_type", ALL_SORT_TYPES)
    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_order_by_variables_are_projected(self, sort_type, order):
        b = KGQueryCriteriaBuilder()
        _, select_vars, order_clause, _ = b._build_sort_bindings(
            [sort_criteria(sort_type, order)], anchor_var="entity")

        named = order_by_vars(order_clause) - {"entity"}   # anchor is the tiebreaker
        projected = projected_names(select_vars)

        assert named, f"{sort_type}/{order} produced an ORDER BY naming nothing"
        assert named <= projected, (
            f"{sort_type}/{order}: ORDER BY names {sorted(named - projected)} "
            f"which SELECT does not project (projects {sorted(projected)}). "
            f"This is issues/096 — invalid under SELECT DISTINCT per SPARQL 1.1 "
            f"§15.1, and 'column s0.vN does not exist' once it reaches SQL.")

    @pytest.mark.parametrize("sort_type", ALL_SORT_TYPES)
    def test_full_query_projects_what_it_orders_by(self, sort_type):
        """Same invariant, asserted on the emitted query rather than the parts.

        The parts can be right while the caller drops them — `select_extra` is
        interpolated separately from `order_by`, so this is not redundant.
        """
        b = KGQueryCriteriaBuilder()
        crit = EntityQueryCriteria(entity_type="urn:test:entity:Thing",
                                   sort_criteria=[sort_criteria(sort_type)])
        q = b.build_entity_query_sparql(crit, GRAPH, page_size=25, offset=0)

        select_line = q.split("WHERE")[0]
        order_line = [ln for ln in q.splitlines() if "ORDER BY" in ln][0]

        for var in order_by_vars(order_line) - {"entity"}:
            assert f"?{var}" in select_line, (
                f"{sort_type}: ORDER BY names ?{var}, absent from the "
                f"projection:\n{select_line.strip()}\n{order_line.strip()}")


class TestAggregationWhereTheValueIsManyPerAnchor:
    """Frame/slot sorts must collapse to one row per anchor."""

    @pytest.mark.parametrize("sort_type", [
        "entity_frame_slot", "frame_slot",
        "source_frame_slot", "destination_frame_slot"])
    def test_frame_and_slot_sorts_aggregate(self, sort_type):
        b = KGQueryCriteriaBuilder()
        _, select_vars, _, requires_group_by = b._build_sort_bindings(
            [sort_criteria(sort_type)], anchor_var="entity")

        assert requires_group_by, (
            f"{sort_type} reaches its value through a to-many edge; without "
            f"GROUP BY an anchor with two matching slots occupies two rows of "
            f"the page")
        assert any("MIN(" in v or "MAX(" in v for v in select_vars), (
            f"{sort_type} projects {select_vars} — expected an aggregate")

    def test_single_valued_entity_property_does_not_aggregate(self):
        """One triple on the anchor is already one row; GROUP BY would only cost.

        Guards against 'fixing' this by aggregating everything unconditionally.
        """
        b = KGQueryCriteriaBuilder()
        _, select_vars, _, requires_group_by = b._build_sort_bindings(
            [sort_criteria("entity_property")], anchor_var="entity")

        assert not requires_group_by
        assert select_vars == ["?sort_val_0"]

    @pytest.mark.parametrize("order,expected", [("asc", "MIN"), ("desc", "MAX")])
    def test_aggregate_matches_the_sort_direction(self, order, expected):
        """Order each anchor by the value that determines its position.

        MAX for ascending would sort an anchor by a value that is not where it
        actually sits, so two anchors could swap places.
        """
        b = KGQueryCriteriaBuilder()
        _, select_vars, _, _ = b._build_sort_bindings(
            [sort_criteria("entity_frame_slot", order)], anchor_var="entity")

        assert select_vars[0].startswith(f"({expected}("), (
            f"{order} should aggregate with {expected}, got {select_vars[0]}")

    def test_the_aggregated_variable_is_the_one_bound_in_the_where_clause(self):
        """`(MIN(?_sort_raw_0) AS ?sort_val_0)` requires the pattern to bind
        `?_sort_raw_0` — aggregating a variable nothing binds yields no rows."""
        b = KGQueryCriteriaBuilder()
        patterns, select_vars, _, _ = b._build_sort_bindings(
            [sort_criteria("entity_frame_slot")], anchor_var="entity")

        inner = re.search(r"\((?:MIN|MAX)\(\?(\w+)\)", select_vars[0]).group(1)
        assert any(f"?{inner} ." in p for p in patterns), (
            f"projection aggregates ?{inner}, which no pattern binds: {patterns}")


class TestMixedCriteria:
    """One aggregated criterion forces the others, or the query is invalid."""

    def test_a_frame_sort_promotes_an_entity_property_sort(self):
        """GROUP BY ?entity forbids projecting any other variable bare.

        This is the case the old per-criterion decision could not represent: it
        emitted `(MIN(...) AS ?sort_val_0) ?sort_val_1` under GROUP BY ?entity.
        """
        b = KGQueryCriteriaBuilder()
        _, select_vars, _, requires_group_by = b._build_sort_bindings(
            [sort_criteria("entity_frame_slot", "asc", priority=1),
             sort_criteria("entity_property", "desc", priority=2)],
            anchor_var="entity")

        assert requires_group_by
        bare = [v for v in select_vars if v.startswith("?")]
        assert not bare, (
            f"{bare} projected bare under GROUP BY ?entity — every projected "
            f"variable must be the group key or an aggregate")

    def test_priority_orders_the_criteria(self):
        b = KGQueryCriteriaBuilder()
        _, _, order_clause, _ = b._build_sort_bindings(
            [sort_criteria("entity_property", "asc", priority=2),
             sort_criteria("entity_frame_slot", "desc", priority=1)],
            anchor_var="entity")
        # priority 1 first: the frame sort, descending.
        assert order_clause.startswith("ORDER BY DESC(?sort_val_0) ASC(?sort_val_1)")


class TestPatternOrder:
    """The slot constraints lead, and the frame walk runs inward-out.

    This is a performance property expressed as pattern order, so it has no
    visible effect on results and nothing else would catch its loss. Measured on
    `prod_kg` (KGLead sorted by CompanyName, 2,863 entities): 507,492 buffers
    anchor-first against 423,742 slot-first, and identical (222) when the query
    is pinned to a single entity — so it is a win on the broad case and free on
    the narrow one. Interleaved timing puts it at 1.08x; the buffer count is the
    stabler figure.

    Anchor-first lets the frame->slot fan-out materialise before anything
    narrows it: each KGLeadInfoFrame carries ~24 slots, so the value predicate
    was probed 68,683 times to keep 2,863 rows.
    """

    def _patterns(self, frame_path):
        b = KGQueryCriteriaBuilder()
        sc = SortCriteria("entity_frame_slot", slot_type=SLOT,
                          slot_class_uri=TEXT_SLOT, frame_path=frame_path)
        patterns, _, _, _ = b._build_sort_bindings([sc], anchor_var="entity")
        return patterns

    def test_slot_type_and_value_come_first(self):
        patterns = self._patterns([FRAME])
        assert f"<{SLOT}>" in patterns[0], (
            f"the slot-type constraint must lead; got {patterns[0]}")
        assert "SlotValue" in patterns[1], (
            f"the slot value must follow its type constraint; got {patterns[1]}")

    def test_the_anchor_hop_comes_last(self):
        """?entity is the widest end, so it should be reached, not started from."""
        patterns = self._patterns([FRAME])
        anchor_hops = [i for i, p in enumerate(patterns) if "?entity" in p]
        assert anchor_hops, "the walk never reaches the anchor"
        assert max(anchor_hops) == len(patterns) - 1, (
            f"the anchor hop should be the final pattern; patterns={patterns}")

    def test_a_two_hop_path_is_emitted_inward_out(self):
        """Deepest frame first, so each hop narrows the previous one."""
        patterns = self._patterns(["urn:test:frame:Outer", "urn:test:frame:Inner"])
        joined = "\n".join(patterns)
        assert joined.index("Inner") < joined.index("Outer"), (
            "the frame nearest the slot must be constrained first")

    def test_the_chain_still_connects_end_to_end(self):
        """Reordering must not break the joins it reorders.

        Every intermediate variable has to be bound by some other pattern, or
        the walk is severed and the query silently matches nothing.
        """
        patterns = self._patterns(["urn:test:frame:Outer", "urn:test:frame:Inner"])
        joined = " ".join(patterns)
        for var in ("sort_slot_0", "sort_frame_0_0", "sort_frame_0_1"):
            assert joined.count(f"?{var}") >= 2, (
                f"?{var} appears once — the chain is severed at that hop")
        assert "?entity" in joined


class TestGeneratedQueryShape:
    """What the caller actually emits, for the shape that was broken."""

    def test_frame_slot_sort_emits_group_by_not_distinct(self):
        b = KGQueryCriteriaBuilder()
        crit = EntityQueryCriteria(entity_type="urn:test:entity:Thing",
                                   sort_criteria=[sort_criteria("entity_frame_slot")])
        q = b.build_entity_query_sparql(crit, GRAPH, page_size=25, offset=0)

        assert "GROUP BY ?entity" in q
        assert "SELECT DISTINCT" not in q, (
            "DISTINCT alongside GROUP BY is the shape that duplicated entities")
        assert "(MIN(?_sort_raw_0) AS ?sort_val_0)" in q

    def test_unsorted_query_is_untouched(self):
        """No sort criteria must still mean no ORDER BY and no GROUP BY.

        `issues/075`: an invented `ORDER BY ?entity` sorts on URI TEXT and was
        measured 117x more expensive while selecting a different page.
        """
        b = KGQueryCriteriaBuilder()
        crit = EntityQueryCriteria(entity_type="urn:test:entity:Thing",
                                   sort_criteria=None)
        q = b.build_entity_query_sparql(crit, GRAPH, page_size=25, offset=0)

        assert "ORDER BY" not in q
        assert "GROUP BY" not in q
        assert "SELECT DISTINCT" in q

    def test_count_query_keeps_the_sort_join_without_projecting_it(self):
        """The count must exclude entities lacking the sort value, and must not
        inherit the projection — it counts, it does not order."""
        b = KGQueryCriteriaBuilder()
        crit = EntityQueryCriteria(entity_type="urn:test:entity:Thing",
                                   sort_criteria=[sort_criteria("entity_frame_slot")])
        q = b.build_entity_count_query_sparql(crit, GRAPH)

        assert f"<{SLOT}>" in q, "count dropped the sort join, so it will overcount"
        assert "ORDER BY ?sort_val_0" not in q
        assert "MIN(" not in q
