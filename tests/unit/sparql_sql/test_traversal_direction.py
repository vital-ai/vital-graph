"""Which end to drive a traversal from (issues/090).

Re-measured 2026-08-16 on a 5.1M-quad space, both arms returning the same 2,863
rows:

    entity end OPEN (2,863 entities, 5,726 slots of the type)
        anchor-driven   2,452,092 buffers   537.1 ms
        end-driven        338,252 buffers    58.4 ms     9.2x

    entity pinned to ONE uri
        anchor-driven           542 buffers   0.2 ms
        end-driven              601 buffers   1.0 ms     4.2x the other way

So direction cannot be a convention. It follows the smaller end, and both sizes
come from statistics already loaded: a pinned end is 1 by definition, a
constrained end is one rdf_stats lookup.

THE DISTINCTION THIS RESTS ON. A PINNED end is fixed to one value. A
CONSTRAINED end carries a type predicate against a constant — `?slot
hasKGSlotType <CompanyName>` — and admits a SET. The gate previously recognised
only the first, so a query constrained at one end and open at the other was
declined as "neither end pinned" and the better direction was invisible.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.traversal_chain import ChainLink, TraversalChain
from vitalgraph.db.sparql_sql.traversal_decision import (
    choose_direction, decide, _end_sizes,
)

SLOT_TYPE = ("pred-uuid-hasKGSlotType", "obj-uuid-CompanyName")
ENT_TYPE = ("pred-uuid-hasKGEntityType", "obj-uuid-KGLead")

# What rdf_stats would answer for those pairs, from the measured space.
PAIR_ROWS = {SLOT_TYPE: 5_726, ENT_TYPE: 2_863}


def _chain(depth=2, *, head=False, tail=False, head_c=None, tail_c=None):
    links = [ChainLink(ref_id=f"q{i}", kind="frame_entity",
                       source_col="source_entity_uuid", dest_col="dest_entity_uuid")
             for i in range(depth)]
    return TraversalChain(links=links, pinned_head=head, pinned_tail=tail,
                          head_constraint=head_c, tail_constraint=tail_c)


class TestEndSizes:

    def test_a_pinned_end_is_one_row(self):
        assert _end_sizes(_chain(head=True), PAIR_ROWS)[0] == 1

    def test_a_constrained_end_is_priced_from_stats(self):
        assert _end_sizes(_chain(tail_c=SLOT_TYPE), PAIR_ROWS)[1] == 5_726

    def test_an_open_end_is_unknown_not_large(self):
        """Unknown must not be compared as if it were a big number.

        Treating absent as large would make an open end always lose, which is
        how a direction gets chosen on no evidence.
        """
        assert _end_sizes(_chain(), PAIR_ROWS) == (None, None)

    def test_a_constraint_with_no_statistic_is_unknown(self):
        assert _end_sizes(_chain(tail_c=("p", "o")), PAIR_ROWS)[1] is None


class TestChooseDirection:

    def test_the_measured_case_drives_from_the_tail(self):
        """2,863 entities vs 5,726 slots... and the ENTITY end is open.

        This is the shape that measured 9.2x: the entity end carries no
        constraint the gate can price, the slot end does, so the slot end is
        the only known driving set.
        """
        chain = _chain(tail_c=SLOT_TYPE)
        assert choose_direction(chain, PAIR_ROWS) == "tail"

    def test_a_pinned_entity_beats_a_constrained_slot(self):
        """The 4.2x-the-other-way case, and the reason this is not a convention.

        One row beats 5,726 of them, so a pinned head wins even though the tail
        is constrained — which is exactly the regression 096 refused to ship.
        """
        chain = _chain(head=True, tail_c=SLOT_TYPE)
        assert choose_direction(chain, PAIR_ROWS) == "head"

    def test_the_smaller_constrained_end_wins(self):
        chain = _chain(head_c=ENT_TYPE, tail_c=SLOT_TYPE)   # 2,863 vs 5,726
        assert choose_direction(chain, PAIR_ROWS) == "head"
        flipped = _chain(head_c=SLOT_TYPE, tail_c=ENT_TYPE)
        assert choose_direction(flipped, PAIR_ROWS) == "tail"

    def test_a_tie_prefers_the_head(self):
        """Arbitrary but fixed: head is the emittable direction today, so a tie
        should not send the query down the path that cannot be built."""
        same = {("p", "o"): 100}
        assert choose_direction(_chain(head_c=("p", "o"), tail_c=("p", "o")), same) == "head"

    def test_no_knowable_end_gives_no_direction(self):
        assert choose_direction(_chain(), PAIR_ROWS) is None

    def test_one_knowable_end_is_used(self):
        assert choose_direction(_chain(head=True), PAIR_ROWS) == "head"
        assert choose_direction(_chain(tail_c=SLOT_TYPE), PAIR_ROWS) == "tail"

    def test_without_statistics_a_constrained_end_is_not_guessed(self):
        """No stats means no price means no basis to choose."""
        assert choose_direction(_chain(tail_c=SLOT_TYPE), None) is None


class TestDecideUsesIt:

    CRIT = dict(criterion_rows=100, predicate_rows=47_488)

    def test_a_constrained_end_is_now_a_driving_set(self):
        """Previously declined as "neither end pinned" — the whole 090 gap."""
        d = decide(_chain(3, tail_c=SLOT_TYPE), pair_rows=PAIR_ROWS, **self.CRIT)
        assert d.hop_wise is True
        assert d.direction == "tail"

    def test_an_open_chain_still_declines(self):
        d = decide(_chain(3), pair_rows=PAIR_ROWS, **self.CRIT)
        assert d.hop_wise is False
        assert "no driving set" in d.reason

    def test_the_direction_is_reported_in_the_reason(self):
        """The reason string is how a decision gets diagnosed against a slow
        query; a direction that is chosen but not stated is not much better
        than one that is not chosen."""
        d = decide(_chain(3, head=True), pair_rows=PAIR_ROWS, **self.CRIT)
        assert "driving from head" in d.reason

    def test_pinned_head_still_decides_head_without_statistics(self):
        """No regression for the case that already worked: a pinned end needs
        no stats to be priced at 1."""
        d = decide(_chain(3, head=True), **self.CRIT)
        assert d.hop_wise is True and d.direction == "head"
