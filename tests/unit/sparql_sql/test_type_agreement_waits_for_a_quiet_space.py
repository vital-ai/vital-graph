"""A type-agreement rescan waits until the space has been quiet for a cycle.

`issues/344`. A stored verdict is usable only while nothing writes the space: its
token includes the space's write count. Production, one quiet hour on 2026-11-15:
the main KG space ran a 224 s edge scan as its one-hour born-stale back-off
expired, and was born stale again, as every attempt has been (`agrees IS NULL`).
That is 15 % of the database's time for a verdict it has never once been able to
keep. Spaces that do reach TRUE were rescanned right after each write, and the
next write made the new verdict unusable too.

So a space that already has a stored row rescans only once its token is the one
seen at the previous cycle. A space with no row yet still scans at once.
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
def token(monkeypatch):
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
async def test_a_moved_verdict_waits_one_quiet_cycle_then_rescans(token):
    conn = _Conn(_true_row())
    assert "quiet" in (await _why(conn) or ""), "written since last seen: wait"
    assert await _why(conn) is None, "same token a cycle later: quiet, so scan"


@pytest.mark.asyncio
async def test_a_space_written_every_cycle_is_never_rescanned(token):
    conn = _Conn(_true_row())
    for i in range(6):
        token["value"] = f"{100 + i}:7|w{5 + i}:9"
        assert "quiet" in (await _why(conn) or ""), f"cycle {i} rescanned a busy space"


@pytest.mark.asyncio
async def test_an_expired_born_stale_back_off_also_waits_for_quiet(token):
    """The production case: the back-off expires every hour, and the space is
    written throughout, so the 224 s scan was born stale again every time."""
    conn = _Conn(_stale_row(age_s=eta.BORN_STALE_BACKOFF_S + 1))
    assert "quiet" in (await _why(conn) or "")
    token["value"] = "101:7|w6:9"
    assert "quiet" in (await _why(conn) or "")
    assert await _why(conn) is None


@pytest.mark.asyncio
async def test_an_expired_timeout_back_off_also_waits_for_quiet(token):
    conn = _Conn({"agrees": None, "change_token": "OLD", "compute_ms": eta.REFRESH_TIMEOUT_MS,
                  "age_s": eta.TIMEOUT_BACKOFF_S + 1})
    assert "quiet" in (await _why(conn, "frame") or "")
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
