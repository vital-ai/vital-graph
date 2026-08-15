"""Declines are recorded, carry their facts, and cannot read a later stage.

The third test is the one with a history. `dedup_feasible` asked about filters
at a stage before `push_filters` had removed them, declined every FILTERED
traversal, and cost 1-3 s per hub-start walk against ~100 ms deduplicated. It
was found by measuring, not by failing. The `reads` declaration exists to make
that class fail at import instead, and this asserts it does.
"""

import asyncio

import pytest

from vitalgraph.db.sparql_sql import declines
from vitalgraph.db.sparql_sql.declines import (
    STAGES, Decline, DeclineLog, Rule, StageOrderError, collecting)

# Importing these registers their rules, which the whole-registry test walks.
# Enumerated explicitly rather than relying on whatever the run has imported —
# a registry check that silently examines nothing is the failure it exists to
# prevent.
from vitalgraph.db.sparql_sql import (  # noqa: F401
    emit_traversal, rewrite_edge_table, rewrite_frame_entity_table,
    traversal_decision)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def test_decline_is_recorded_with_its_facts():
    r = Rule("t_record", stage="emit_bgp", reads=("collect",))
    with collecting() as log:
        assert r.decline("projection is not confined to what survives",
                         projected=["e3", "score"], allowed=["e3"]) is None
    assert len(log) == 1
    entry = log.entries[0]
    assert entry.rule == "t_record"
    assert entry.stage == "emit_bgp"
    assert entry.facts == {"projected": ["e3", "score"], "allowed": ["e3"]}
    # The facts must reach the rendered form: a reason alone says a rule fired,
    # the values say which variable to go look at.
    assert "score" in str(entry)


def test_decline_outside_a_collector_is_a_silent_no_op():
    """A pass stays unit-testable with no fixture and no setup."""
    r = Rule("t_noop", stage="emit_bgp")
    assert not declines.active()
    assert r.decline("nothing is collecting") is None  # must not raise


def test_log_groups_and_summarises():
    a = Rule("t_a", stage="emit_bgp")
    b = Rule("t_b", stage="edge_rewrite")
    with collecting() as log:
        a.decline("first")
        b.decline("second")
        a.decline("third")
    assert len(log) == 3
    assert [d.detail for d in log.for_rule("t_a")] == ["first", "third"]
    assert set(log.by_rule()) == {"t_a", "t_b"}
    # Order is the order they happened — a decline late in the pipeline usually
    # only makes sense next to the earlier one that caused it.
    assert [d.detail for d in log] == ["first", "second", "third"]
    assert "first" in log.summary()


def test_empty_log_is_falsey_and_says_so():
    with collecting() as log:
        pass
    assert not log
    assert log.summary() == "no declines"


def test_collectors_nest_without_leaking():
    """An EXISTS body's declines belong to the body, not the outer query."""
    r = Rule("t_nest", stage="emit_bgp")
    with collecting() as outer:
        r.decline("outer")
        with collecting() as inner:
            r.decline("inner")
        r.decline("outer again")
    assert [d.detail for d in inner] == ["inner"]
    assert [d.detail for d in outer] == ["outer", "outer again"]


def test_concurrent_tasks_do_not_see_each_others_declines():
    """ContextVar, not a module global — two queries generating at once."""
    r = Rule("t_conc", stage="emit_bgp")

    async def one(tag, delay):
        with collecting() as log:
            r.decline(f"{tag}-first")
            await asyncio.sleep(delay)
            r.decline(f"{tag}-second")
            return [d.detail for d in log]

    async def both():
        return await asyncio.gather(one("a", 0.02), one("b", 0.0))

    a, b = asyncio.run(both())
    assert a == ["a-first", "a-second"]
    assert b == ["b-first", "b-second"]


# ---------------------------------------------------------------------------
# Declared reads — the mechanical check
# ---------------------------------------------------------------------------

def test_a_rule_may_not_read_a_later_stage():
    """The real bug, replayed as a declaration.

    A traversal precondition that runs at `traversal_decision` and consults
    what `push_filters` will do is asking about a fact that does not exist
    yet. This is what it cost when it shipped instead of raising.
    """
    with pytest.raises(StageOrderError) as exc:
        Rule("t_too_early", stage="traversal_decision",
             reads=("push_filters",))
    assert "push_filters" in str(exc.value)
    assert "does not exist yet" in str(exc.value)


def test_a_rule_may_not_read_its_own_stage():
    """Same stage is not "already run" — it is the one running."""
    with pytest.raises(StageOrderError):
        Rule("t_self", stage="edge_rewrite", reads=("edge_rewrite",))


def test_an_unknown_stage_name_is_rejected():
    with pytest.raises(ValueError, match="not a pipeline stage"):
        Rule("t_unknown_read", stage="emit_bgp", reads=("filter_pushdown",))
    with pytest.raises(ValueError, match="not a pipeline stage"):
        Rule("t_unknown_stage", stage="somewhere", reads=())


def test_reading_a_strictly_earlier_stage_is_fine():
    r = Rule("t_ok", stage="emit_bgp",
             reads=("collect", "traversal_decision", "push_filters"))
    assert r.reads == ("collect", "traversal_decision", "push_filters")


def test_every_declared_rule_in_the_pipeline_is_ordered():
    """Whole-registry sweep, so a new rule cannot be added unchecked."""
    rules = declines.all_rules()
    names = {r.name for r in rules}
    # The four modules imported above must actually have registered.
    assert {"hop_partition", "hop_wise", "dedup_chain", "traversal_shape",
            "edge_rewrite", "frame_entity_rewrite"} <= names
    order = {s: i for i, s in enumerate(STAGES)}
    for r in rules:
        for read in r.reads:
            assert order[read] < order[r.stage], (
                f"{r.name} runs at {r.stage} but reads {read}")


def test_the_traversal_rules_declare_the_dependency_that_bit():
    """dedup must read push_filters — not reading it is the 1-3 s regression."""
    by_name = {r.name: r for r in declines.all_rules()}
    assert "push_filters" in by_name["dedup_chain"].reads
    # And the shape decision must read the stage that loads its statistics;
    # placed before it, the gate saw no number on any query.
    assert "semijoin" in by_name["traversal_shape"].reads
    # The frame_entity rewrite consumes the edge rewrite's output.
    assert "edge_rewrite" in by_name["frame_entity_rewrite"].reads
