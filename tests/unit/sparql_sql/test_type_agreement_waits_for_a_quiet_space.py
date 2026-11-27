"""A type-agreement rescan waits until the space has been quiet for a cycle.

`issues/344`. A stored verdict is usable only while nothing writes the space: its
token includes the space's write count. Production, one quiet hour on 2026-11-15:
the main KG space ran a 224 s edge scan as its one-hour born-stale back-off
expired, and was born stale again, as every attempt has been (`agrees IS NULL`).
That is 15 % of the database's time for a verdict it has never once been able to
keep. Spaces that do reach TRUE were rescanned right after each write, and the
next write made the new verdict unusable too.

So a space that already has a stored row rescans only once its token has held
for `QUIET_S` (`issues/354`: it used to be "for one cycle", and `349` shrank a
cycle from ~12 min to ~5). A space with no row yet still scans at once.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import edge_type_agreement as eta


class _Conn:
    """A stored row, and the statements a scan would issue (counted)."""

    def __init__(self, row):
        self.row = row
        self.scans = 0

    async def fetchrow(self, sql, *args):
        return self.row

    async def fetchval(self, sql, *args, timeout=None):
        if sql.startswith("SELECT count(*)"):
            self.scans += 1                     # the scan starts with the count
            return 0                            # empty: stops there, stores nothing
        return None

    async def execute(self, sql, *args):
        return None


@pytest.fixture
def clock(monkeypatch):
    box = {"now": 1_000_000.0}
    monkeypatch.setattr(eta, "_quiet_clock", lambda: box["now"])
    return box


def _later(clock, s):
    clock["now"] += s


@pytest.fixture
def token(monkeypatch, clock):
    box = {"value": "100:7|w5:9"}

    async def change_token(conn, table, space_id=None):
        return box["value"]
    monkeypatch.setattr(eta, "change_token", change_token)
    eta.clear_cache()
    yield box
    eta.clear_cache()


def _true_row(stored_token="OLD"):
    return {"agrees": True, "change_token": stored_token, "compute_ms": 13_000, "age_s": 60}


def _stale_row(age_s):
    return {"agrees": None, "change_token": "OLD", "compute_ms": 224_517, "age_s": age_s}


async def _why(conn, kind="edge"):
    return await eta._refresh_not_needed(conn, "kg", kind, f"kg_{kind}")


@pytest.mark.asyncio
async def test_a_moved_verdict_waits_out_the_quiet_time_then_rescans(token, clock):
    conn = _Conn(_true_row())
    assert "quiet" in (await _why(conn) or ""), "written since last seen: wait"
    _later(clock, eta.QUIET_S)
    assert await _why(conn) is None, "token held for QUIET_S: quiet, so scan"


@pytest.mark.asyncio
async def test_a_space_written_every_cycle_is_never_rescanned(token):
    conn = _Conn(_true_row())
    for i in range(6):
        token["value"] = f"{100 + i}:7|w{5 + i}:9"
        assert "quiet" in (await _why(conn) or ""), f"cycle {i} rescanned a busy space"


@pytest.mark.asyncio
async def test_an_expired_born_stale_back_off_also_waits_for_quiet(token, clock):
    """The production case: the back-off expires every hour, and the space is
    written throughout, so the 224 s scan was born stale again every time."""
    conn = _Conn(_stale_row(age_s=eta.BORN_STALE_BACKOFF_S + 1))
    assert "quiet" in (await _why(conn) or "")
    token["value"] = "101:7|w6:9"
    assert "quiet" in (await _why(conn) or "")
    _later(clock, eta.QUIET_S)
    assert await _why(conn) is None


@pytest.mark.asyncio
async def test_an_expired_timeout_back_off_also_waits_for_quiet(token, clock):
    conn = _Conn({"agrees": None, "change_token": "OLD", "compute_ms": eta.REFRESH_TIMEOUT_MS,
                  "age_s": eta.TIMEOUT_BACKOFF_S + 1})
    assert "quiet" in (await _why(conn, "frame") or "")
    _later(clock, eta.QUIET_S)
    assert await _why(conn, "frame") is None


@pytest.mark.asyncio
async def test_a_current_verdict_is_still_skipped_as_current(token):
    conn = _Conn(_true_row(stored_token=token["value"]))
    assert await _why(conn) == "verdict still current"


@pytest.mark.asyncio
async def test_a_space_with_no_row_scans_at_once(token):
    assert await _why(_Conn(None)) is None


@pytest.mark.asyncio
async def test_an_unreadable_token_does_not_block(monkeypatch):
    async def none(conn, table, space_id=None):
        return None
    monkeypatch.setattr(eta, "change_token", none)
    eta.clear_cache()
    assert await _why(_Conn(_true_row())) is None


@pytest.mark.asyncio
async def test_spaces_and_kinds_keep_their_own_last_token(token):
    conn = _Conn(_true_row())
    await _why(conn, "edge")
    assert "quiet" in (await _why(conn, "frame") or ""), "frame inherited edge's sighting"
    assert "quiet" in (await eta._refresh_not_needed(conn, "other", "edge", "other_edge") or "")


@pytest.mark.asyncio
async def test_the_refresh_itself_does_not_scan_a_busy_space(token):
    conn = _Conn(_stale_row(age_s=eta.BORN_STALE_BACKOFF_S + 1))
    for i in range(4):
        token["value"] = f"{200 + i}:7|w{50 + i}:9"
        out = await eta.refresh_type_agreement(conn, "kg")
        assert all("quiet" in r.get("skipped", "") for r in out), out
    assert conn.scans == 0


@pytest.mark.asyncio
async def test_force_still_scans(token):
    conn = _Conn(_stale_row(age_s=10))
    await eta.refresh_type_agreement(conn, "kg", force=True)
    assert conn.scans == 2, "the manual trigger ignores every gate, as before"


# --- issues/354: quiet is measured in time, not in cycles ---------------------

@pytest.mark.asyncio
async def test_a_five_minute_pause_is_not_quiet(token, clock):
    """The production case after `349`: cycles ~5 min apart, and the main KG
    space pauses that long between writes. One cycle of quiet used to pass."""
    conn = _Conn(_stale_row(age_s=eta.BORN_STALE_BACKOFF_S + 1))
    assert "quiet" in (await _why(conn) or "")
    _later(clock, 300)
    assert "quiet" in (await _why(conn) or ""), "a 5-minute pause passed as quiet"


@pytest.mark.asyncio
async def test_a_write_during_the_wait_restarts_the_clock(token, clock):
    conn = _Conn(_true_row())
    await _why(conn)
    _later(clock, eta.QUIET_S - 60)
    token["value"] = "102:7|w7:9"                    # written just before it would pass
    assert "quiet" in (await _why(conn) or "")
    _later(clock, 120)
    assert "quiet" in (await _why(conn) or ""), "the old sighting's clock was kept"
    _later(clock, eta.QUIET_S)
    assert await _why(conn) is None


@pytest.mark.asyncio
async def test_a_space_paused_every_five_minutes_is_never_scanned_by_the_refresh(token, clock):
    """End to end through `refresh_type_agreement`, over a production day: a
    write burst, then a 5-minute pause, repeated."""
    conn = _Conn(_stale_row(age_s=eta.BORN_STALE_BACKOFF_S + 1))
    for i in range(288):                              # 24 h of 5-minute cycles
        if i % 2 == 0:
            token["value"] = f"{300 + i}:7|w{90 + i}:9"
        await eta.refresh_type_agreement(conn, "kg")
        _later(clock, 300)
    assert conn.scans == 0


@pytest.mark.asyncio
async def test_quiet_s_zero_is_the_old_one_cycle_test(token, clock, monkeypatch):
    monkeypatch.setattr(eta, "QUIET_S", 0.0)
    conn = _Conn(_true_row())
    assert "quiet" in (await _why(conn) or "")
    assert await _why(conn) is None


def test_the_default_is_thirty_minutes():
    import os
    if "VG_TYPE_AGREEMENT_QUIET_S" not in os.environ:
        assert eta.QUIET_S == 1800.0
