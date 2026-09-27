"""An O(graph) probe must not re-derive when nothing was written.

`issues/150`. `entity_slot_sort_drift` computes `expected` with the full
unseeded `WITH RECURSIVE frame_walk`. Measured on production 2026-09-03, AFTER
`478fa06` gave it the maintenance budget:

    durations: 216s, 216s, 122s, 303s, 252s, 59s, 256s
    DUTY CYCLE = 54% of wall-clock inside this ONE probe

Before that fix, asyncpg's `command_timeout=60` killed it at 60s. That was a bug
— the probe never completed, so the backfill it gates never ran — but it was
also accidentally bounding the damage. Raising the budget without gating the
cadence turned "fails fast every cycle" into "runs four minutes every cycle",
scanning the quad table and evicting the read path's cache. A user query
measured 1.5s with the probe idle and 58s with it running; a benchmark of that
query reported 58% of runs stalling, which matches the duty cycle.

The cheap probe stays ungated: `entity_slot_sort_coverage` measured 130ms and
answers the question that actually matters (is a type served at all).
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import inspect

import pytest

from vitalgraph.process import maintenance_job as M


class _Conn:
    def __init__(self, watermark):
        self.watermark = watermark

    async def fetchval(self, *_a):
        return self.watermark


@pytest.fixture(autouse=True)
def _clean():
    M.reset_probe_gate()
    yield
    M.reset_probe_gate()


@pytest.mark.asyncio
async def test_unchanged_data_skips_the_walk():
    assert await M.probe_data_changed(_Conn(100), "sp", "d") is True
    assert await M.probe_data_changed(_Conn(100), "sp", "d") is False


@pytest.mark.asyncio
async def test_a_write_reopens_it():
    await M.probe_data_changed(_Conn(100), "sp", "d")
    assert await M.probe_data_changed(_Conn(101), "sp", "d") is True


@pytest.mark.asyncio
async def test_unconverged_work_overrides_the_gate():
    """The trap in gating on writes alone.

    The backfill only ADDs, so a 2.7M-row gap takes many passes. On a quiet
    space, a write-only gate would skip every one of them and strand the table
    half-filled — the same "looks fixed, repairs nothing" outcome as issues/149.
    """
    await M.probe_data_changed(_Conn(100), "sp", "d")
    M.mark_probe_converged("sp", "d", False)
    assert await M.probe_data_changed(_Conn(100), "sp", "d") is True

    M.mark_probe_converged("sp", "d", True)
    assert await M.probe_data_changed(_Conn(100), "sp", "d") is False


@pytest.mark.asyncio
async def test_a_stats_reset_fails_toward_running():
    """`pg_stat_reset()` moves the counter DOWN. `!=` is the honest test; `>`
    would silently disable the probe forever after a reset."""
    await M.probe_data_changed(_Conn(500), "sp", "d")
    assert await M.probe_data_changed(_Conn(3), "sp", "d") is True


@pytest.mark.asyncio
async def test_an_unreadable_counter_does_the_work():
    class _Boom:
        async def fetchval(self, *_a):
            raise RuntimeError("no pg_stat")

    assert await M.probe_data_changed(_Boom(), "sp", "d") is True
    assert await M.probe_data_changed(_Conn(None), "sp", "d") is True


@pytest.mark.asyncio
async def test_spaces_and_probes_do_not_share_a_watermark():
    await M.probe_data_changed(_Conn(100), "a", "d")
    assert await M.probe_data_changed(_Conn(100), "b", "d") is True
    assert await M.probe_data_changed(_Conn(100), "a", "other") is True


def test_the_remaining_o_graph_probes_are_gated():
    """The slot-sort walk left this path entirely in `issues/151` — coverage
    replaced it. The gate still guards the sibling drift probes, which are the
    remaining full-table scans on the maintenance loop (edge_table_drift
    measured 17.7s over ~50M rows).

    `frame_slot_integrity` and `entity_slot_sort_coverage` joined the list in
    `issues/143` rec 1 — see the call-site test below for why naming them here
    was not enough.
    """
    src = inspect.getsource(M)
    for probe in ("edge_table_drift", "frame_entity_drift",
                  "frame_slot_integrity", "entity_slot_sort_coverage"):
        i = src.index(f'"{probe}")')
        window = src[max(0, i - 400):i]
        assert "probe_data_changed(" in window, f"{probe} is ungated"
    assert "mark_probe_converged(" in src, (
        "without recording convergence a repair strands half-done on a quiet "
        "space — the gate would skip the passes it still needs")


#: Probe functions whose cost is proportional to the SPACE, so every call site
#: needs a change gate. Measured on production over 57 days (`issues/143`):
#:   frame_slot_drift             34,979 calls  2,304 ms  22.4 h
#:   entity_slot_sort_coverage    30,833 calls  2,852 ms  24.4 h
#:   edge_table_drift              5,737 calls 18,161 ms  28.9 h
#: all three largely on `testspace`, whose quad write watermark is ZERO.
_EXPENSIVE_PROBES = (
    "edge_table_drift",
    "frame_slot_drift",
    "entity_slot_sort_coverage",
)


def _ungated_call_sites(src: str, probes=_EXPENSIVE_PROBES) -> list:
    """Call sites of *probes* whose ENCLOSING FUNCTION holds no gate.

    Scoped to the function, not to a character window. A window is the obvious
    implementation and it does not work: the real code carries ~1,200 characters
    of comment between the gate and the call, so any window wide enough to
    accept that also accepts a second, ungated call site sixty lines below the
    first — which is the exact defect this is meant to catch.
    """
    lines = src.split("\n")
    # (start_line_index, name) for every def, innermost-last
    defs = [(n, ln.strip().split("(")[0].replace("async def ", "").replace("def ", ""))
            for n, ln in enumerate(lines)
            if ln.lstrip().startswith(("def ", "async def "))]

    out = []
    for n, ln in enumerate(lines):
        for fn in probes:
            if f"await {fn}(" not in ln:
                continue
            owner = [(d, name) for d, name in defs if d < n]
            start = owner[-1][0] if owner else 0
            name = owner[-1][1] if owner else "<module>"
            body = "\n".join(lines[start:n])
            if "probe_data_changed(" not in body:
                out.append(f"{fn} at line {n + 1} in {name}()")
    return out


def test_every_call_site_of_an_expensive_probe_is_gated():
    """DERIVED PER CALL SITE, not from a list of probe names.

    `issues/143` rec 1 was recorded as done and was not: `frame_slot_drift` had
    TWO call sites, `_run_frame_entity_integrity` (gated since `issues/150`) and
    `_run_frame_slot_integrity` (never gated), so the same full scan ran twice a
    cycle — once gated, once not. The test above could not see that, because it
    asks "is this probe NAME gated somewhere" and the answer was yes.

    A second call site is the natural way this regresses: someone copies a step,
    and the copy loses the gate while the original keeps it.
    """
    ungated = _ungated_call_sites(inspect.getsource(M))
    assert not ungated, (
        "these call sites re-derive over the whole space on every cycle with no "
        "change gate:\n    " + "\n    ".join(ungated))


def test_the_detector_finds_an_ungated_call_site():
    """A derived test that cannot fail is worse than no test.

    The shape of the real defect: two call sites, the first gated, the second a
    copy that lost it.
    """
    gated_then_not = (
        "async def _run_frame_entity_integrity(self):\n"
        '    if not await probe_data_changed(conn, sid, "frame_entity_drift"):\n'
        "        continue\n"
        "    expected, actual = await frame_slot_drift(conn, sid)\n"
        "\n"
        "async def _run_frame_slot_integrity(self):\n"
        "    expected, actual = await frame_slot_drift(conn, sid)\n"
    )
    found = _ungated_call_sites(gated_then_not, ("frame_slot_drift",))
    assert len(found) == 1, found
    assert "_run_frame_slot_integrity" in found[0], found

    # and it does not cry wolf on a gated one
    assert _ungated_call_sites(
        "async def step(self):\n"
        '    if await probe_data_changed(c, s, "x"):\n'
        "        await edge_table_drift(c, s)\n", ("edge_table_drift",)) == []


def test_the_slot_sort_repair_no_longer_uses_the_o_graph_walk():
    """`issues/151`: coverage (130ms) decides, a bounded batch repairs."""
    src = inspect.getsource(M.MaintenanceJob._run_entity_slot_sort_integrity)
    assert "entity_slot_sort_drift(" not in src
    assert "backfill_entity_slot_sort_batch(" in src
