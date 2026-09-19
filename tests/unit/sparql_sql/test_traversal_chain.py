"""A multi-hop traversal must be recognisable AS a chain.

The pipeline detects each hop and never the chain. `rewrite_frame_slot_table`
collapses a hop's six tables into one row, per hop, so a depth-3 walk becomes
three references — and what links them exists only as ordinary join conditions.
Nothing reads those as a sequence, so no pass can order the joins to drive from
the pinned end or evaluate hop by hop, and PostgreSQL infers the shape from
thirty-odd tables with row estimates of 1 (`issues/090`).

This is the representation, and it is deliberately inert: it changes no SQL.
Tests therefore assert on what was DETECTED. A detector that silently finds
nothing is the failure mode of everything else in this area — correct, slower,
invisible — and results-only tests cannot see it.

Both traversal shapes are covered here rather than frames first. Implementing
one linkage of two is exactly how the slot-listing endpoint came to report "no
slots found" for frames that had them.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprValue, ExprVar, URINode)
from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot, KIND_BGP, KIND_FILTER, KIND_JOIN)
from vitalgraph.db.sparql_sql import traversal_chain
from vitalgraph.db.sparql_sql.traversal_chain import find_chains

pytestmark = pytest.mark.unit

EDGE = ("edge", "source_node_uuid", "dest_node_uuid")

# A SECOND one-row-per-hop kind, existing only for this module.
#
# `frame_entity` played this part until it was retired (`issues/183`) and its
# entry was removed from `_TRAVERSAL_KINDS` (`issues/197` defect 1). Keeping it
# here would have asserted that the detector still supports a shape production
# cannot produce — the dead-entry problem, moved into the tests.
#
# Dropping the second shape instead would lose what the parametrisation is FOR.
# `_TRAVERSAL_KINDS` is a LOOKUP TABLE, and with `edge` its only live entry a
# suite that exercises only `edge` cannot tell a map-driven detector from one
# that hardcodes the name — the detector would keep passing after someone
# inlined `"edge"` into a branch, and the next real kind would find nothing.
# That is the same failure the dead entry caused, in the other direction.
#
# So the second shape is SYNTHETIC: registered in the map by the fixture below
# and named nowhere in `vitalgraph/`. It asserts exactly the property that is
# still true — every kind in the map is handled the same way — and makes no
# claim about any table existing.
SYNTH = ("synth_hop", "source_synth_uuid", "dest_synth_uuid")


@pytest.fixture(autouse=True)
def _register_synth_kind(monkeypatch):
    """Put `SYNTH` in the map for the duration of one test, and take it out."""
    monkeypatch.setitem(
        traversal_chain._TRAVERSAL_KINDS, SYNTH[0], (SYNTH[1], SYNTH[2]))


def _chain_bgp(kind_cols, n_hops, prefix, pin_inline=False):
    """A BGP of `n_hops` traversal tables joined head to tail."""
    kind, src, dst = kind_cols
    tables, constraints, slots = [], [], {}
    for i in range(n_hops):
        ref = f"{prefix}{i}"
        tables.append(TableRef(ref_id=ref, kind=kind,
                               table_name=f"sp_{kind}", alias=ref))
        slots.setdefault(f"e{i}", VarSlot(name=f"e{i}", positions=[])
                         ).positions.append((ref, src))
        slots.setdefault(f"e{i+1}", VarSlot(name=f"e{i+1}", positions=[])
                         ).positions.append((ref, dst))
        if i:
            constraints.append(
                f"{prefix}{i}.{src} = {prefix}{i-1}.{dst}")
    bgp = PlanV2(kind=KIND_BGP, tables=tables, constraints=constraints,
                 var_slots=slots)
    if pin_inline:
        # As collect() records it: a constant term bound at that column. NOT as
        # a constraint string — detection reads the structural record, so a test
        # that fakes the SQL text would pass against a text-matching
        # implementation and prove nothing about this one.
        bgp.leaf_terms[(f"{prefix}0", src)] = ("urn:x:1", "U")
    return bgp


def _pinned_filter(child, var="e0"):
    return PlanV2(kind=KIND_FILTER, children=[child], filter_exprs=[
        ExprFunction(name="eq", args=[
            ExprVar(var=var), ExprValue(node=URINode(value="urn:x:1"))])])


class TestBothShapes:
    """Frames and KG relations differ in table and column names and in nothing
    else that matters, so neither may be special-cased."""

    @pytest.mark.parametrize("cols,prefix", [(SYNTH, "femv"), (EDGE, "mv")],
                             ids=["synth_hop", "edge"])
    def test_a_three_hop_chain_is_found_in_order(self, cols, prefix):
        chains = find_chains(_chain_bgp(cols, 3, prefix))
        assert len(chains) == 1
        assert chains[0].depth == 3
        assert [l.ref_id for l in chains[0].links] == [f"{prefix}{i}" for i in range(3)]

    @pytest.mark.parametrize("cols,prefix", [(SYNTH, "femv"), (EDGE, "mv")],
                             ids=["synth_hop", "edge"])
    def test_the_kind_is_reported(self, cols, prefix):
        assert find_chains(_chain_bgp(cols, 2, prefix))[0].kind == cols[0]


class TestPinning:
    """Which end is fixed decides which way a chain can be driven."""

    def test_a_filter_pins_the_head(self):
        """Read from the PARSED QUERY. push_filters runs during emit, so at
        detection time the constraint text has the chain's joins and not the
        pin; matching on text alone reports every query unpinned."""
        plan = _pinned_filter(_chain_bgp(SYNTH, 3, "femv"))
        c = find_chains(plan)[0]
        assert c.pinned_head is True
        assert c.pinned_tail is False

    def test_an_inline_constant_pins_the_head_too(self):
        """A query written with the term in the triple rather than as a FILTER
        is the same question and must be detected the same way."""
        c = find_chains(_chain_bgp(SYNTH, 2, "femv", pin_inline=True))[0]
        assert c.pinned_head is True

    def test_no_pin_is_reported_as_none(self):
        c = find_chains(_chain_bgp(SYNTH, 2, "femv"))[0]
        assert (c.pinned_head, c.pinned_tail) == (False, False)

    def test_a_filter_on_the_far_end_pins_the_tail(self):
        plan = _pinned_filter(_chain_bgp(SYNTH, 3, "femv"), var="e3")
        c = find_chains(plan)[0]
        assert c.pinned_tail is True
        assert c.pinned_head is False

    def test_both_ends_can_be_pinned(self):
        """A reachability question. Recorded rather than collapsed to one flag,
        because the shorter side is the one worth driving from and that needs
        the depth."""
        inner = _pinned_filter(_chain_bgp(SYNTH, 3, "femv"), var="e0")
        c = find_chains(_pinned_filter(inner, var="e3"))[0]
        assert c.pinned_head and c.pinned_tail


class TestWhatIsNotAChain:

    def test_unrelated_tables_are_not_linked(self):
        """Two references that share no variable are not a hop sequence.
        Pairing by position in the table list would invent a chain the query
        does not contain."""
        bgp = _chain_bgp(SYNTH, 1, "femv")
        bgp.tables.append(TableRef(ref_id="femv9", kind=SYNTH[0],
                                   table_name="sp_synth_hop", alias="femv9"))
        chains = find_chains(bgp)
        assert all(c.depth == 1 for c in chains), [str(c) for c in chains]
        assert len(chains) == 2

    def test_a_bgp_with_no_traversal_tables_yields_nothing(self):
        plan = PlanV2(kind=KIND_BGP,
                      tables=[TableRef(ref_id="q0", kind="quad",
                                       table_name="sp_rdf_quad", alias="q0")])
        assert find_chains(plan) == []

    def test_a_single_hop_is_a_chain_of_one(self):
        """The depth-1 frame case — the immediate one in production — is not a
        special case, it is the degenerate chain."""
        c = find_chains(_chain_bgp(SYNTH, 1, "femv"))[0]
        assert c.depth == 1


class TestTraversal:

    def test_chains_below_a_join_are_found(self):
        left = _chain_bgp(SYNTH, 2, "femv")
        right = _chain_bgp(EDGE, 3, "mv")
        chains = find_chains(PlanV2(kind=KIND_JOIN, children=[left, right]))
        assert [c.depth for c in chains] == [3, 2], "longest first"
        assert {c.kind for c in chains} == {SYNTH[0], "edge"}

    def test_a_cycle_still_reports_its_links(self):
        """A chain that loops has no head, so the head-first walk never starts.
        Reporting nothing would be a silent miss — the failure mode this whole
        pass exists to avoid."""
        # A real cycle, expressed structurally: the variable at femv1's
        # destination is the SAME one at femv0's source, so every link has a
        # predecessor and the head-first walk has nowhere to start. Appending a
        # constraint string instead would leave a plain 2-chain and the test
        # would pass without ever exercising this.
        bgp = _chain_bgp(SYNTH, 2, "femv")
        bgp.var_slots["e0"].positions.append(("femv1", "dest_synth_uuid"))
        del bgp.var_slots["e2"]
        chains = find_chains(bgp)
        assert chains, "a cyclic chain reported nothing at all"
        assert sum(c.depth for c in chains) == 2, (
            f"both links must be accounted for, got {[str(c) for c in chains]}")
