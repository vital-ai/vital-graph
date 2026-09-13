"""A slot range criterion drives from `entity_slot_sort`, but only when narrow.

`issues/111`. A KGQuery range criterion leaves the planner nothing selective to
start from: half the query becomes one Hash Join and a fifth a sequential scan of
all 1.66M edge rows, to return 1,017 rows. `{space}_entity_slot_sort` answers the
same question with an Index Only Scan on `idx_ess_num` in 2 ms, so the range also
narrows the SLOT against that table.

WHY THE SLOT AND NOT THE ENTITY. `entity_slot_sort` is keyed on
`(slot_uuid, context_uuid)`, and that row carries the slot's type and value — so
"slots of type T with value >= L" is exactly what the surrounding chain already
requires of `?slot`. The constraint cannot change the answer. Anchoring on the
ENTITY instead would need `frame_type_path` matched exactly, since the index is
keyed on the whole array, and a near-miss admits entities reached by a different
path — wrong rows, not slow ones.

THE GATE IS THE WHOLE THING. Measured on sp_lead_synth_100k:

    >= 99.9    145 matches   1,886 ms ->    16 ms
    >= 99    1,017 matches   1,877 ms ->    61 ms
    >= 90    9,907 matches       77 ms -> TIMED OUT, ungated

The loose end already has a plan that works and a 9,907-row IN list destroys it.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot, AliasGenerator, KIND_BGP,
)
from vitalgraph.db.sparql_sql.slot_sort_range import (
    slot_range_constraint, VALUE_LANE, RANGE_OPS, SLOT_TYPE_PRED,
)

SPACE = "sp_test"
H = "http://vital.ai/ontology/haley-ai-kg#"
TYPE_PRED_U = "aaaaaaaa-0000-5000-8000-000000000001"
SLOT_TYPE_U = "aaaaaaaa-0000-5000-8000-000000000002"
VAL_PRED_U = "aaaaaaaa-0000-5000-8000-000000000003"


def _make(*, matches=1000, slot_total=100000, value_pred=f"{H}hasDoubleSlotValue",
          slot_type_const=True, op=">="):
    """A BGP shaped like `?slot hasKGSlotType <T> ; has<X>SlotValue ?v`."""
    al = AliasGenerator()
    al.constants = {(SLOT_TYPE_PRED, "U", None, None): "c_0",
                    ("urn:slot:MQL", "U", None, None): "c_1",
                    (value_pred, "U", None, None): "c_2"}
    al.resolved_constants = {"c_0": TYPE_PRED_U, "c_1": SLOT_TYPE_U,
                             "c_2": VAL_PRED_U}
    al.quad_stats = {(TYPE_PRED_U, SLOT_TYPE_U): slot_total}
    al.pred_stats = {VAL_PRED_U: 3_900_000}     # every double slot in the space
    al.range_stats = {(VAL_PRED_U, op, 99): matches}

    b = PlanV2(kind=KIND_BGP,
               tables=[TableRef(ref_id="q0", kind="quad",
                                table_name=f"{SPACE}_rdf_quad", alias="q0"),
                       TableRef(ref_id="q1", kind="quad",
                                table_name=f"{SPACE}_rdf_quad", alias="q1")],
               var_slots={"slot": VarSlot(name="slot",
                                          positions=[("q0", "subject_uuid"),
                                                     ("q1", "subject_uuid")]),
                          "val": VarSlot(name="val",
                                         positions=[("q1", "object_uuid")])})
    # q0: ?slot hasKGSlotType <T>     q1: ?slot has<X>SlotValue ?val
    b.leaf_terms[("q0", "predicate_uuid")] = (SLOT_TYPE_PRED, "U")
    b.leaf_terms[("q1", "predicate_uuid")] = (value_pred, "U")
    if slot_type_const:
        # The real generator names constants `c_0`, `c_1`, ... and
        # `_OBJ_RE` is written for that; `c1` silently matches nothing.
        b.tagged_constraints.append(("q0", "q0.object_uuid = __CONST_c_1__"))
    return b, al


class TestItFiresWhenNarrow:

    def test_a_narrow_range_produces_a_constraint(self):
        bgp, al = _make(matches=1000, slot_total=100_000)   # 1.0%
        got = slot_range_constraint(bgp, al, SPACE, "val", ">=", 99)
        assert got is not None
        alias, sql = got
        assert alias == "q0"
        assert f"{SPACE}_entity_slot_sort" in sql
        assert "slot_uuid" in sql, "it must anchor on the slot, not the entity"
        assert "value_num >= 99" in sql
        assert "__CONST_c_1__" in sql, "the slot type must be pinned"

    def test_it_never_mentions_frame_type_path(self):
        """Anchoring on the slot is what makes the path irrelevant. If a future
        change starts matching the path, it has to match it EXACTLY or it admits
        entities reached another way."""
        bgp, al = _make(matches=1000)
        _, sql = slot_range_constraint(bgp, al, SPACE, "val", ">=", 99)
        assert "frame_type_path" not in sql


class TestTheGate:

    def test_a_loose_range_declines(self):
        """9,907 of 100,000 is 9.9%. Ungated this timed out where the existing
        plan took 77 ms."""
        bgp, al = _make(matches=9907, slot_total=100_000)
        assert slot_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None

    def test_the_denominator_is_the_slot_type_not_the_value_predicate(self):
        """`pred_stats` for hasDoubleSlotValue counts EVERY double slot in the
        space — 3.9M against MQLRating's 100,000. Read that way, 9,907 matches
        looks like 0.25% and sails through, which is exactly what happened: the
        loose threshold still timed out with the gate in place."""
        bgp, al = _make(matches=9907, slot_total=100_000)
        assert al.pred_stats[VAL_PRED_U] == 3_900_000
        assert 9907 / al.pred_stats[VAL_PRED_U] < 0.05, "would pass the wrong gate"
        assert 9907 / 100_000 > 0.05, "and fails the right one"
        assert slot_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None

    def test_unmeasured_declines(self):
        """Without a count there is no telling the 118x case from the timeout."""
        bgp, al = _make(matches=1000)
        al.range_stats = {}
        assert slot_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None

    def test_a_missing_slot_total_declines(self):
        bgp, al = _make(matches=1000)
        al.quad_stats = {}
        assert slot_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None


class TestWhatItRefusesToTouch:

    def test_an_unknown_value_predicate_declines(self):
        """Defaulting an unknown lane would compare the wrong column — a date
        against `value_num`."""
        bgp, al = _make(matches=1000, value_pred=f"{H}hasSomeNewSlotValue")
        assert slot_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None

    def test_a_text_lane_is_not_offered(self):
        """`value_text` has its own index and its own collation question; this
        covers the ordering lanes only."""
        assert "value_text" not in set(VALUE_LANE.values())

    def test_equality_declines(self):
        """Equality already reaches the term semi-join with an accurate estimate
        and is the shape the criterion gate is built around."""
        assert "=" not in RANGE_OPS
        bgp, al = _make(matches=1000, op="=")
        assert slot_range_constraint(bgp, al, SPACE, "val", "=", 99) is None

    def test_an_unpinned_slot_type_declines(self):
        """Without a constant type there is no set to look up, and guessing one
        would exclude rows the query should return."""
        bgp, al = _make(matches=1000, slot_type_const=False)
        assert slot_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None

    def test_an_unknown_variable_declines(self):
        bgp, al = _make(matches=1000)
        assert slot_range_constraint(bgp, al, SPACE, "nosuch", ">=", 99) is None


class TestEveryOrderingComparatorIsCovered:

    @pytest.mark.parametrize("op", sorted(RANGE_OPS))
    def test_each_emits_its_own_operator(self, op):
        bgp, al = _make(matches=1000, op=op)
        got = slot_range_constraint(bgp, al, SPACE, "val", op, 99)
        assert got is not None and f"value_num {op} 99" in got[1]


# ---------------------------------------------------------------------------
# The ENTITY-anchored narrowing (`issues/111`)
# ---------------------------------------------------------------------------

from vitalgraph.db.sparql_sql.slot_sort_range import (      # noqa: E402
    entity_range_constraint, VITALTYPE_URI,
)
from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (  # noqa: E402
    ENTITY_FRAME_EDGE_URI,
)

VITALTYPE_U = "aaaaaaaa-0000-5000-8000-000000000004"
ENTITY_TYPE = f"{H}KGEntity"


def _with_vitaltype(bgp, al, *, subjects):
    """Add one `?subj vitaltype <type>` quad per (var, type_uri) in `subjects`."""
    for i, (var, type_uri) in enumerate(subjects):
        a = f"v{i}"
        bgp.tables.append(TableRef(ref_id=a, kind="quad",
                                   table_name=f"{SPACE}_rdf_quad", alias=a))
        bgp.leaf_terms[(a, "predicate_uuid")] = (VITALTYPE_URI, "U")
        bgp.leaf_terms[(a, "object_uuid")] = (type_uri, "U")
        bgp.var_slots[var] = VarSlot(name=var, positions=[(a, "subject_uuid")])
    return bgp, al


class TestTheEntityNarrowing:

    def test_it_fires_and_projects_the_entity(self):
        bgp, al = _make(matches=1000, slot_total=100_000)
        _with_vitaltype(bgp, al, subjects=[("entity", ENTITY_TYPE)])
        got = entity_range_constraint(bgp, al, SPACE, "val", ">=", 99)
        assert got is not None
        alias, sql = got
        assert alias == "v0", "it must anchor on the ENTITY's quad, not the slot's"
        assert "SELECT entity_uuid FROM" in sql
        assert "value_num >= 99" in sql

    def test_it_never_mentions_frame_type_path(self):
        """The set must stay a SUPERSET of the answer. `frame_type_path` is the
        column `issues/111` warns returns WRONG ROWS on a near-miss, and
        narrowing by it is not needed to make the set small."""
        bgp, al = _make(matches=1000)
        _with_vitaltype(bgp, al, subjects=[("entity", ENTITY_TYPE)])
        _, sql = entity_range_constraint(bgp, al, SPACE, "val", ">=", 99)
        assert "frame_type_path" not in sql
        assert "entity_type_uuid" not in sql
        assert "context_uuid" not in sql

    def test_it_declines_when_only_walk_edges_are_typed(self):
        """Every edge on the walk carries a vitaltype quad too. Mistaking one for
        the entity would intersect two disjoint populations and return NOTHING,
        so a shape with no entity must decline rather than pick."""
        bgp, al = _make(matches=1000)
        _with_vitaltype(bgp, al,
                        subjects=[("frame_edge_0", ENTITY_FRAME_EDGE_URI)])
        assert entity_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None

    def test_it_declines_when_the_entity_is_ambiguous(self):
        bgp, al = _make(matches=1000)
        _with_vitaltype(bgp, al, subjects=[("entity", ENTITY_TYPE),
                                           ("other", f"{H}KGDocument")])
        assert entity_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None

    def test_a_loose_range_declines_here_too(self):
        """It inherits the selectivity gate: a 9,907-row IN list destroys a plan
        that already works, which is why the slot narrowing is gated at all."""
        bgp, al = _make(matches=9907, slot_total=100_000)     # 9.9%
        _with_vitaltype(bgp, al, subjects=[("entity", ENTITY_TYPE)])
        assert entity_range_constraint(bgp, al, SPACE, "val", ">=", 99) is None
