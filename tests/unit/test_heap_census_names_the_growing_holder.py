"""The heap census names what grows, including a cache frozen at startup — issues/278.

Production's gen-2 GC pauses tripled (~160 ms to ~500 ms) after the
2026-10-17 releases, climbing for ~6 hours after each boot and then levelling
off. The census is how the growing structure is found.

The case that matters is the one the collector cannot see: a cache built
before the startup `gc.freeze()` is in the permanent generation, so
`gc.get_objects()` and `gc.get_referrers()` skip it — only the entries added
later are tracked. The census must still name it, by attribute path, with its
growth between passes.
"""

from __future__ import annotations

import asyncio
import collections
import gc
import sys
import types

import pytest

from vitalgraph.process import heap_census_job as H


class _Cache:
    def __init__(self):
        self._store = collections.OrderedDict()
        self._index = {}


class _Slotted:
    __slots__ = ("items",)

    def __init__(self):
        self.items = []


class _Entry:
    def __init__(self, i):
        self.payload = {"i": i}


@pytest.fixture
def fake_module():
    """A module under the `vitalgraph` prefix holding a cache instance."""
    m = types.ModuleType("vitalgraph._heap_census_fixture")
    m.cache = _Cache()
    m.slotted = _Slotted()
    m.small_registry = [_Cache()]          # a short list is descended into
    sys.modules[m.__name__] = m
    yield m
    del sys.modules[m.__name__]


def _run(job):
    return asyncio.run(job.run())


def test_a_frozen_cache_is_named_by_path_with_its_growth(fake_module):
    gc.collect()
    gc.freeze()
    try:
        job = H.HeapCensusJob(min_len=100)
        _run(job)
        for i in range(700):
            fake_module.cache._store[f"k{i}"] = _Entry(i)
        out = _run(job)
    finally:
        gc.unfreeze()

    holders = dict((p, ln) for p, (_t, ln) in out["holders"])
    path = "vitalgraph._heap_census_fixture.cache._store"
    assert holders.get(path) == 700, (
        f"the frozen cache is not named; holders: {list(holders)[:8]}")
    assert (path, 700) in out["holder_growth"]
    # The entries arrived after the freeze, so the TYPE half sees them.
    assert dict(out["type_growth"]).get(f"{__name__}._Entry") == 700


def test_slots_short_containers_and_lru_caches_are_reached(fake_module):
    import functools

    @functools.lru_cache(maxsize=None)
    def f(x):
        return x
    for i in range(150):
        f(i)
    fake_module.memo = f
    fake_module.slotted.items.extend(range(120))
    fake_module.small_registry[0]._index.update({i: i for i in range(130)})

    found = H.walk_holders(min_len=100)
    assert found["vitalgraph._heap_census_fixture.memo"] == ("lru_cache", 150)
    assert found["vitalgraph._heap_census_fixture.slotted.items"] == ("list", 120)
    assert found["vitalgraph._heap_census_fixture.small_registry[0]._index"] == ("dict", 130)


def test_a_big_container_is_measured_and_not_entered(fake_module):
    """Entering a cache's entries would make the walk as costly as the heap."""
    fake_module.cache._store.update({i: _Cache() for i in range(H._DESCEND_MAX_LEN + 1)})
    for v in fake_module.cache._store.values():
        v._index.update({j: j for j in range(200)})
    found = H.walk_holders(min_len=60)
    assert "vitalgraph._heap_census_fixture.cache._store" in found
    assert not any(p.startswith("vitalgraph._heap_census_fixture.cache._store[")
                   for p in found)


def test_the_first_pass_reports_no_growth_and_extra_roots_are_walked():
    holder = _Cache()
    holder._index.update({i: i for i in range(300)})
    job = H.HeapCensusJob(roots={"app": holder}, min_len=200)
    out = _run(job)
    assert out["type_growth"] == [] and out["holder_growth"] == []
    assert ("app._index", ("dict", 300)) in out["holders"]


def test_off_by_default_and_registered_on_one_task():
    from pathlib import Path
    import vitalgraph
    assert H.HEAP_CENSUS_INTERVAL_S == 0 or "VG_HEAP_CENSUS_INTERVAL_S" in __import__("os").environ
    src = (Path(vitalgraph.__file__).parent / "impl" / "vitalgraphapp_impl.py").read_text()
    block = src[src.index("HeapCensusJob, HEAP_CENSUS_INTERVAL_S"):]
    block = block[:block.index("except Exception")]
    assert "if HEAP_CENSUS_INTERVAL_S > 0" in block
    assert "single_runner=True" in block


def test_many_small_caches_add_up_by_kind(fake_module):
    """One cache per connection: none crosses the threshold, together they do."""
    conns = [_Cache() for _ in range(12)]
    for c in conns:
        c._index.update({i: i for i in range(50)})
    fake_module.pool = conns
    kinds = {}
    found = H.walk_holders(min_len=200, kinds=kinds)
    assert not any("pool[" in p for p in found)
    assert kinds[f"{__name__}._Cache._index"][1] >= 600
    assert kinds[f"{__name__}._Cache._index"][0] >= 12


def test_the_census_does_not_report_its_own_state(fake_module):
    job = H.HeapCensusJob(roots={"app": {"scheduler_jobs": [job_holder := []]}}, min_len=50)
    job_holder.append(job)                 # reachable, as the scheduler holds it
    fake_module.cache._store.update({i: i for i in range(400)})
    _run(job)
    out = _run(job)
    assert not any("_prev_" in p for p, _ in out["holders"]), out["holders"]
    assert not any("HeapCensusJob" in k for k, _c, _t in out["kinds"]), out["kinds"]
