"""A slot group is emitted as a MATERIALIZED CTE from its slot type, only when cheaper.

`issues/293`. "Entities of type T with slot S" was planned from the entity:
each entity's `hasKGGraphURI` probe returned its whole graph (~1,000 members
on production UW decisions), estimated at ~10 rows, and the slot type filtered
afterwards. `slot_group_cte` emits the slot's leaves (graph link, slot type,
value) as one CTE driven from the slot type, computed once.

These pin the GATE and the REWRITE OF REFERENCES. A CTE taken when the pinned
set is large materialises a big set to replace a cheap probe. A reference left
pointing at an alias that moved into the CTE is a SQL error. Rows are checked
end to end on the prod-shaped fixture (`uw_prodshape`) by the issue's A/B.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from vitalgraph.db.sparql_sql.ir import AliasGenerator, KIND_BGP, PlanV2, TableRef, VarSlot
from vitalgraph.db.sparql_sql.reorder_bgp import reorder_joins
from vitalgraph.db.sparql_sql.slot_group_cte import (
    NAME, apply_groups, find_groups, mean_fanout,
)

HK = "http://vital.ai/ontology/haley-ai-kg#"
P_GRAPH = "u-graph"
TABLE = "vgs_test_rdf_quad"


def _shape(*, entity_typed=True, slot_type_const=True):
    """?d hasKGEntityType <T> . ?s hasKGGraphURI ?d ; hasKGSlotType <S> ; hasTextSlotValue ?v ."""
    aliases = ("q0", "q1", "q2", "q3") if entity_typed else ("q1", "q2", "q3")
    tables = [TableRef(ref_id=a, kind="quad", table_name=TABLE, alias=a) for a in aliases]
    b = PlanV2(kind=KIND_BGP, tables=tables, var_slots={
        "d": VarSlot(name="d", positions=([("q0", "subject_uuid")] if entity_typed else [])
                     + [("q1", "object_uuid")]),
        "s": VarSlot(name="s", positions=[("q1", "subject_uuid"), ("q2", "subject_uuid"),
                                          ("q3", "subject_uuid")]),
        "v": VarSlot(name="v", positions=[("q3", "object_uuid")]),
    })
    b.tagged_constraints = [
        ("q1", "q1.predicate_uuid = __CONST_c_2__"), ("q1", "q1.context_uuid = __CONST_c_9__"),
        ("q2", "q2.subject_uuid = q1.subject_uuid"),
        ("q2", "q2.predicate_uuid = __CONST_c_3__"), ("q2", "q2.context_uuid = __CONST_c_9__"),
        ("q3", "q3.subject_uuid = q1.subject_uuid"),
        ("q3", "q3.predicate_uuid = __CONST_c_5__"), ("q3", "q3.context_uuid = __CONST_c_9__"),
    ]
    if slot_type_const:
        b.tagged_constraints.append(("q2", "q2.object_uuid = __CONST_c_4__"))
        b.leaf_terms[("q2", "object_uuid")] = ("urn:S", "U")
    if entity_typed:
        b.tagged_constraints = [
            ("q0", "q0.predicate_uuid = __CONST_c_0__"), ("q0", "q0.object_uuid = __CONST_c_1__"),
            ("q0", "q0.context_uuid = __CONST_c_9__"),
            ("q1", "q1.object_uuid = q0.subject_uuid"),
        ] + b.tagged_constraints
        b.leaf_terms[("q0", "predicate_uuid")] = (HK + "hasKGEntityType", "U")
        b.leaf_terms[("q0", "object_uuid")] = ("urn:T", "U")
    b.leaf_terms[("q1", "predicate_uuid")] = (HK + "hasKGGraphURI", "U")
    b.leaf_terms[("q2", "predicate_uuid")] = (HK + "hasKGSlotType", "U")
    b.leaf_terms[("q3", "predicate_uuid")] = (HK + "hasTextSlotValue", "U")
    return b


def _ctx(*, graphs=1_000, members=1_000):
    a = AliasGenerator()
    a.quad_stats = {(P_GRAPH, f"g{i}"): members for i in range(graphs)}
    a.pred_stats = {P_GRAPH: graphs * members}
    return SimpleNamespace(aliases=a)


def _uuid_of(term):
    return {HK + "hasKGGraphURI": P_GRAPH}.get(term[0])


def _decisions(ctx):
    return [d for d in ctx.aliases.plan_decisions.decisions if d.name == NAME]


def test_the_issue_293_shape_becomes_one_group():
    plan, ctx = _shape(), _ctx()
    card = {"q0": 1_159, "q1": 1_000_000, "q2": 9_318, "q3": 2_000_000}
    (g,) = find_groups(plan, ctx, plan.tables, card, _uuid_of)
    assert g.aliases == {"q1", "q2", "q3"} and g.pin == "q2" and g.pinned == 9_318
    assert _decisions(ctx)[0].fired


def test_the_rewrite_moves_the_group_into_a_cte_and_renames_references():
    plan, ctx = _shape(), _ctx()
    card = {"q0": 1_159, "q1": 1_000_000, "q2": 9_318, "q3": 2_000_000}
    groups = find_groups(plan, ctx, plan.tables, card, _uuid_of)
    cols = ["q0.subject_uuid AS d__uuid", "q3.object_uuid AS v__uuid"]
    tables, tagged, new_cols, new_card, cte = apply_groups(
        groups, plan.tables, plan.tagged_constraints, cols, card, reorder_joins)
    name = groups[0].name

    assert [t.alias for t in tables] == ["q0", name]
    assert new_cols == ["q0.subject_uuid AS d__uuid", f"{name}.q3__object_uuid AS v__uuid"]
    assert new_card[name] == 9_318 and "q1" not in new_card
    # The link to the entity is applied OUTSIDE the CTE, on its column.
    assert (name, f"{name}.q1__object_uuid = q0.subject_uuid") in tagged
    # Nothing outside still names an alias that moved inside.
    outside = " ".join(s for _, s in tagged) + " ".join(new_cols)
    for a in ("q1", "q2", "q3"):
        assert not re.search(rf"\b{a}\.", outside)
    # Inside: driven from the pin, materialised, with the group's own constraints.
    assert cte.startswith(f"WITH {name} AS MATERIALIZED (")
    assert f"FROM {TABLE} AS q2" in cte
    assert "q2.object_uuid = __CONST_c_4__" in cte
    assert "q0." not in cte


def test_a_pin_larger_than_the_expansion_is_left_alone():
    """10 entities x 100 members is 1,000 probes; materialising 50,000 slots is worse."""
    plan, ctx = _shape(), _ctx(graphs=10_000, members=100)
    card = {"q0": 10, "q1": 1_000_000, "q2": 50_000, "q3": 2_000_000}
    assert find_groups(plan, ctx, plan.tables, card, _uuid_of) == []
    (d,) = _decisions(ctx)
    assert not d.fired and "not clearly smaller" in d.reason


def test_without_an_anchor_the_bound_is_the_whole_predicate():
    """An OPTIONAL field: ?d comes from outside the BGP."""
    plan, ctx = _shape(entity_typed=False), _ctx()
    card = {"q1": 1_000_000, "q2": 1_159, "q3": 2_000_000}
    (g,) = find_groups(plan, ctx, plan.tables, card, _uuid_of)
    tables, *_ = apply_groups([g], plan.tables, plan.tagged_constraints,
                              ["q3.object_uuid AS v__uuid"], card, reorder_joins)
    assert [t.alias for t in tables] == [g.name]      # the whole BGP is the group


def test_only_a_constant_object_leaf_anchors_the_entity():
    """Another leaf binding ?d with a VARIABLE object (e.g. a second group's
    graph link) is priced at its whole predicate and anchors nothing. Counted as
    an anchor, it hid that ?d comes from outside, and the BGP was not
    materialised: naics_for_category went 3,292 -> 3,815,428 loops."""
    plan, ctx = _shape(), _ctx()
    del plan.leaf_terms[("q0", "object_uuid")]       # ?d hasKGEntityType ?any
    card = {"q0": 2_000_000, "q1": 1_000_000, "q2": 9_318, "q3": 2_000_000}
    (g,) = find_groups(plan, ctx, plan.tables, card, _uuid_of)
    assert g.detail["anchor"] is None


def test_an_unpinned_slot_is_declined():
    """`?s hasKGSlotType ?any`: every member is priced at its whole predicate."""
    plan, ctx = _shape(slot_type_const=False), _ctx()
    card = {"q0": 1_159, "q1": 1_000_000, "q2": 2_000_000, "q3": 2_000_000}
    assert find_groups(plan, ctx, plan.tables, card, _uuid_of) == []
    (d,) = _decisions(ctx)
    assert not d.fired and "not clearly smaller" in d.reason


def test_an_fts_pinned_member_drives_the_group():
    """KGQuery text search: the slot type is broad, the FTS match is narrow."""
    plan, ctx = _shape(), _ctx()
    card = {"q0": 1_159, "q1": 1_000_000, "q2": 400_000, "q3": 14}
    (g,) = find_groups(plan, ctx, plan.tables, card, _uuid_of)
    assert g.pin == "q3" and g.pinned == 14


def _with_frame_and_code(plan):
    """Add the reason-code slot, linked to the kind slot through a frame ?f:
    q4: ?s hasFrameGraphURI ?f    q5: ?c hasFrameGraphURI ?f    q6: ?c hasTextSlotValue ?code
    """
    for a in ("q4", "q5", "q6"):
        plan.tables.append(TableRef(ref_id=a, kind="quad", table_name=TABLE, alias=a))
    plan.var_slots["s"].positions.append(("q4", "subject_uuid"))
    plan.var_slots["f"] = VarSlot(name="f", positions=[("q4", "object_uuid"), ("q5", "object_uuid")])
    plan.var_slots["c"] = VarSlot(name="c", positions=[("q5", "subject_uuid"), ("q6", "subject_uuid")])
    plan.var_slots["code"] = VarSlot(name="code", positions=[("q6", "object_uuid")])
    plan.tagged_constraints += [
        ("q4", "q4.subject_uuid = q1.subject_uuid"), ("q4", "q4.predicate_uuid = __CONST_c_6__"),
        ("q5", "q5.object_uuid = q4.object_uuid"), ("q5", "q5.predicate_uuid = __CONST_c_6__"),
        ("q6", "q6.subject_uuid = q5.subject_uuid"), ("q6", "q6.predicate_uuid = __CONST_c_7__"),
    ]
    plan.leaf_terms[("q4", "predicate_uuid")] = (HK + "hasFrameGraphURI", "U")
    plan.leaf_terms[("q5", "predicate_uuid")] = (HK + "hasFrameGraphURI", "U")
    plan.leaf_terms[("q6", "predicate_uuid")] = (HK + "hasTextSlotValue", "U")
    return plan


_CARD7 = {"q0": 1_159, "q1": 1_000_000, "q2": 6_950, "q3": 2_000_000,
          "q4": 3_000_000, "q5": 3_000_000, "q6": 2_000_000}


def test_a_values_restricted_code_reaching_the_slot_by_frame_declines():
    """all_of: VALUES ?code { two codes } reaches the kind slot through the
    reason frame without crossing ?d, so PostgreSQL never expands a graph and
    the CTE would only add the cost of materialising every kind slot
    (380 ms -> 1,220 ms measured before this rule)."""
    plan, ctx = _with_frame_and_code(_shape()), _ctx()
    ctx.aliases.values_bound_vars = {"code": 2}
    assert find_groups(plan, ctx, plan.tables, dict(_CARD7), _uuid_of) == []
    (d,) = _decisions(ctx)
    assert not d.fired and "without the graph link" in d.reason


def test_a_values_restriction_reachable_only_through_d_still_fires():
    """The same VALUES, but the only path to the slot crosses ?d: that IS the
    expansion, and the group must still be materialised (category_page's
    fields)."""
    plan, ctx = _shape(), _ctx()
    plan.tables.append(TableRef(ref_id="q9", kind="quad", table_name=TABLE, alias="q9"))
    plan.var_slots["d"].positions.append(("q9", "subject_uuid"))
    plan.var_slots["code"] = VarSlot(name="code", positions=[("q9", "object_uuid")])
    plan.leaf_terms[("q9", "predicate_uuid")] = (HK + "hasTextSlotValue", "U")
    ctx.aliases.values_bound_vars = {"code": 2}
    card = dict(_CARD7, q9=2_000_000)
    (g,) = find_groups(plan, ctx, plan.tables, card, _uuid_of)
    assert g.pin == "q2"


def test_values_on_the_slots_own_value_declines():
    plan, ctx = _shape(), _ctx()
    ctx.aliases.values_bound_vars = {"v": 3}
    card = {"q0": 1_159, "q1": 1_000_000, "q2": 9_318, "q3": 2_000_000}
    assert find_groups(plan, ctx, plan.tables, card, _uuid_of) == []


def test_values_bound_vars_reads_tables_anywhere_in_the_plan():
    from vitalgraph.db.sparql_sql.slot_group_cte import values_bound_vars
    table = PlanV2(kind="table", values_vars=["code", "k"],
                   values_rows=[{"code": "a", "k": None}, {"code": "b", "k": "x"}])
    root = PlanV2(kind="join", children=[PlanV2(kind=KIND_BGP), table])
    assert values_bound_vars(root) == {"code": 2, "k": 1}


def test_no_statistics_declines_rather_than_guessing():
    plan = _shape()
    ctx = SimpleNamespace(aliases=AliasGenerator())
    card = {"q0": 1_159, "q2": 9_318}
    assert find_groups(plan, ctx, plan.tables, card, _uuid_of) == []


def test_mean_fanout_reads_only_its_own_predicate():
    stats = {("p", "a"): 10, ("p", "b"): 30, ("other", "a"): 1_000}
    assert mean_fanout(stats, "p") == 20
    assert mean_fanout(stats, "missing") is None
