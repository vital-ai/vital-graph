"""A multi-hop traversal must be recognisable AS a chain.

The pipeline detects each hop and never the chain. `rewrite_frame_entity_table`
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
from vitalgraph.db.sparql_sql.traversal_chain import find_chains

pytestmark = pytest.mark.unit

FE = ("frame_entity", "source_entity_uuid", "dest_entity_uuid")
EDGE = ("edge", "source_node_uuid", "dest_node_uuid")


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
    if pin_inline:
        constraints.append(
            f"{prefix}0.{src} = '11111111-2222-3333-4444-555555555555'::uuid")
    return PlanV2(kind=KIND_BGP, tables=tables, constraints=constraints,
                  var_slots=slots)


def _pinned_filter(child, var="e0"):
    return PlanV2(kind=KIND_FILTER, children=[child], filter_exprs=[
        ExprFunction(name="eq", args=[
            ExprVar(var=var), ExprValue(node=URINode(value="urn:x:1"))])])


class TestBothShapes:
    """Frames and KG relations differ in table and column names and in nothing
    else that matters, so neither may be special-cased."""

    @pytest.mark.parametrize("cols,prefix", [(FE, "femv"), (EDGE, "mv")],
                             ids=["frame_entity", "edge"])
    def test_a_three_hop_chain_is_found_in_order(self, cols, prefix):
        chains = find_chains(_chain_bgp(cols, 3, prefix))
        assert len(chains) == 1
        assert chains[0].depth == 3
        assert [l.ref_id for l in chains[0].links] == [f"{prefix}{i}" for i in range(3)]

    @pytest.mark.parametrize("cols,prefix", [(FE, "femv"), (EDGE, "mv")],
                             ids=["frame_entity", "edge"])
    def test_the_kind_is_reported(self, cols, prefix):
        assert find_chains(_chain_bgp(cols, 2, prefix))[0].kind == cols[0]


class TestPinning:
    """Which end is fixed decides which way a chain can be driven."""

    def test_a_filter_pins_the_head(self):
        """Read from the PARSED QUERY. push_filters runs during emit, so at
        detection time the constraint text has the chain's joins and not the
        pin; matching on text alone reports every query unpinned."""
        plan = _pinned_filter(_chain_bgp(FE, 3, "femv"))
        c = find_chains(plan)[0]
        assert c.pinned_head is True
        assert c.pinned_tail is False

    def test_an_inline_constant_pins_the_head_too(self):
        """A query written with the term in the triple rather than as a FILTER
        is the same question and must be detected the same way."""
        c = find_chains(_chain_bgp(FE, 2, "femv", pin_inline=True))[0]
        assert c.pinned_head is True

    def test_no_pin_is_reported_as_none(self):
        c = find_chains(_chain_bgp(FE, 2, "femv"))[0]
        assert (c.pinned_head, c.pinned_tail) == (False, False)

    def test_a_filter_on_the_far_end_pins_the_tail(self):
        plan = _pinned_filter(_chain_bgp(FE, 3, "femv"), var="e3")
        c = find_chains(plan)[0]
        assert c.pinned_tail is True
        assert c.pinned_head is False

    def test_both_ends_can_be_pinned(self):
        """A reachability question. Recorded rather than collapsed to one flag,
        because the shorter side is the one worth driving from and that needs
        the depth."""
        inner = _pinned_filter(_chain_bgp(FE, 3, "femv"), var="e0")
        c = find_chains(_pinned_filter(inner, var="e3"))[0]
        assert c.pinned_head and c.pinned_tail


class TestWhatIsNotAChain:

    def test_unrelated_tables_are_not_linked(self):
        """Two references that share no variable are not a hop sequence.
        Pairing by position in the table list would invent a chain the query
        does not contain."""
        bgp = _chain_bgp(FE, 1, "femv")
        bgp.tables.append(TableRef(ref_id="femv9", kind="frame_entity",
                                   table_name="sp_frame_entity", alias="femv9"))
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
        c = find_chains(_chain_bgp(FE, 1, "femv"))[0]
        assert c.depth == 1


class TestTraversal:

    def test_chains_below_a_join_are_found(self):
        left = _chain_bgp(FE, 2, "femv")
        right = _chain_bgp(EDGE, 3, "mv")
        chains = find_chains(PlanV2(kind=KIND_JOIN, children=[left, right]))
        assert [c.depth for c in chains] == [3, 2], "longest first"
        assert {c.kind for c in chains} == {"frame_entity", "edge"}

    def test_a_cycle_still_reports_its_links(self):
        """A chain that loops has no head, so the head-first walk never starts.
        Reporting nothing would be a silent miss — the failure mode this whole
        pass exists to avoid."""
        bgp = _chain_bgp(FE, 2, "femv")
        bgp.constraints.append(
            "femv0.source_entity_uuid = femv1.dest_entity_uuid")
        chains = find_chains(bgp)
        assert chains, "a cyclic chain reported nothing at all"
        assert sum(c.depth for c in chains) >= 2
