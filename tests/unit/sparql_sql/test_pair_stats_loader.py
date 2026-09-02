"""The semi-join gate's pair-stats loader must not swallow its own bugs.

`_load_missing_pair_stats` wraps its whole body in `except Exception`. That is
deliberate — a statistics lookup failing should degrade the plan, not fail the
query — but it means any defect inside is invisible unless someone reads the
log, and until 2026-09-01 the handler logged at DEBUG while production runs at
INFO.

What hid there: `be8159c` made the pair-counting block conditional on
`if missing:` so range and text stats are still collected when the pair counts
are all cached, and left the trailing summary log referencing `still`, a name
that path never binds. Every query whose leaf pairs were fully cached raised
`UnboundLocalError` and had it swallowed — from 2026-08-14 until a test-stack
deploy surfaced it. Nothing was lost (the log is the last statement and the
handler only logs) but a genuine failure reported identically, so the two were
indistinguishable.

These tests pin the fully-cached path, which is the one that had no cover.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import logging

import pytest

from vitalgraph.db.sparql_sql import generator as G
from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_BGP


class _Aliases:
    def __init__(self, quad_stats):
        self.quad_stats = quad_stats


@pytest.fixture
def no_value_stats(monkeypatch):
    """The only DB call an empty BGP still makes."""
    async def _none(*_a, **_k):
        return {}
    monkeypatch.setattr(G, "_load_value_stats_cached", _none)


@pytest.mark.asyncio
async def test_fully_cached_pairs_do_not_raise_into_the_handler(
        no_value_stats, caplog):
    """`missing == []` must reach the summary log, not the except block.

    An empty BGP binds no constant pairs, so `needed_pairs` is empty and
    `missing` is empty — the exact shape that left `still` unbound.
    """
    plan = PlanV2(kind=KIND_BGP)
    aliases = _Aliases({})

    with caplog.at_level(logging.WARNING, logger=G.logger.name):
        await G._load_missing_pair_stats(
            plan, aliases, "sp_test", conn=object())

    assert "pair stats lookup failed" not in caplog.text, (
        "the loader swallowed an exception on the fully-cached path: "
        + caplog.text)


@pytest.mark.asyncio
async def test_the_loader_still_initialises_its_outputs(
        no_value_stats):
    """Whatever happens, the four attributes the gate reads must exist.

    `_selective_enough` and `_leaf_rows` read these unconditionally; leaving
    one unset turns a statistics miss into an AttributeError at plan time.
    """
    plan = PlanV2(kind=KIND_BGP)
    aliases = _Aliases({})

    await G._load_missing_pair_stats(plan, aliases, "sp_test", conn=object())

    assert aliases.extra_quad_stats == {}
    assert aliases.range_stats == {}
    assert aliases.text_stats == {}
    assert aliases.saturated_pairs == set()


@pytest.mark.asyncio
async def test_a_real_failure_is_reported_at_warning(monkeypatch, caplog):
    """A genuine fault must be loud, and must say what it costs.

    It was DEBUG, which is why the defect above survived two and a half weeks
    in a deployment that logs at INFO.
    """
    from vitalgraph.db.sparql_sql import semijoin as SJ

    def _boom(_plan, _aliases):
        raise RuntimeError("statistics table is gone")
    monkeypatch.setattr(SJ, "needed_pairs", _boom)

    plan = PlanV2(kind=KIND_BGP)
    aliases = _Aliases({})

    with caplog.at_level(logging.WARNING, logger=G.logger.name):
        await G._load_missing_pair_stats(
            plan, aliases, "sp_test", conn=object())

    assert "pair stats lookup failed" in caplog.text
    assert "without leaf statistics" in caplog.text, (
        "the warning should name the consequence, not just the exception")
    assert "statistics table is gone" in caplog.text


# ===========================================================================
# The semi-join gate's selectivity must be coherent before it is compared
# ===========================================================================

def _selectivity(matches, m_sat, candidates, c_sat, monkeypatch):
    """Drive `_selective_enough` with known leaf measurements."""
    from vitalgraph.db.sparql_sql import semijoin as SJ

    def fake(node, aliases, *, filter_derived=True):
        return {"L": (candidates, c_sat), "R": (matches, m_sat)}[node]
    monkeypatch.setattr(SJ, "_leaf_rows_detail", fake)
    return SJ._selective_enough("L", "R", object())


def test_ratio_above_one_is_refused_as_incoherent(monkeypatch):
    """A probe cannot match more rows than the anchor has candidates.

    `matches > candidates` means the two numbers came from different leaves —
    the signature of a selective leaf that could not be measured, so
    `_leaf_rows` returned the next one it could. Measured on production for a
    slot value absent from the term table: 50000/76 = 657.895, true matches 0.
    """
    assert _selectivity(50_000, True, 76, False, monkeypatch) is False


def test_a_coherent_ratio_above_the_threshold_still_probes(monkeypatch):
    """The guard must not swallow the case the rewrite exists for."""
    assert _selectivity(3_000, False, 10_000, False, monkeypatch) is True


def test_a_coherent_ratio_below_the_threshold_joins(monkeypatch):
    assert _selectivity(1, False, 76_827, False, monkeypatch) is False


def test_saturated_anchor_still_refused(monkeypatch):
    """The denominator guard is unchanged: a saturated anchor is a lower bound."""
    assert _selectivity(3_000, False, 50_000, True, monkeypatch) is False
