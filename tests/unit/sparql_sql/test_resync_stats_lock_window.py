"""The stats rebuild must not hold its exclusive lock across the aggregate.

`issues/145`. `TRUNCATE` takes an AccessExclusiveLock held until COMMIT, and
this function used to be:

    BEGIN; TRUNCATE t_stats; INSERT INTO t_stats SELECT ... GROUP BY ...; COMMIT

so the lock spanned an aggregate over the whole quad table — which the
function's own docstring describes as taking "minutes on a large space". Every
concurrent reader of the stats tables blocked on it. Sampling `pg_locks` on prod
during one rebuild caught the INSERT holding AccessExclusiveLock continuously
while 144 blocked-reader samples piled up behind it.

Locks are taken when a STATEMENT runs, not when its transaction opens, so
staging the aggregate into `ON COMMIT DROP` temp tables first keeps the rebuild
in one transaction — the atomicity `issues/103` is about, where a TRUNCATE
committed without its INSERT left 50M quads against a 136-row stats table —
while the exclusive lock covers only the TRUNCATE and a bulk insert from an
already-computed table.

The ordering IS the fix, so it is what these tests pin.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import sync_stats_tables as S


# **_kw because the real driver takes it: these queries now pass asyncpg's
# CLIENT-side `timeout=` (`issues/148` — command_timeout=60 fires in the driver
# and no server-side SET can raise it). A double narrower than the driver fails
# on a correct change.
class _Conn:
    def __init__(self):
        self.statements: list[str] = []

    def transaction(self):
        conn = self

        class _Txn:
            async def __aenter__(self):
                conn.statements.append("BEGIN")
                return self

            async def __aexit__(self, *_exc):
                conn.statements.append("COMMIT")
                return False

        return _Txn()

    async def execute(self, sql, *_args, **_kw):
        self.statements.append(" ".join(sql.split()))
        return "INSERT 0 7"

    async def fetchval(self, sql, *_args, **_kw):
        self.statements.append(" ".join(sql.split()))
        return 0


@pytest.fixture
async def rebuilt():
    conn = _Conn()
    await S._resync_stats_locked(
        conn, "sp_t", "sp_t_rdf_quad", "sp_t_rdf_pred_stats", "sp_t_rdf_stats")
    return conn.statements


def _index_of(stmts, *needles):
    for i, s in enumerate(stmts):
        if all(n in s for n in needles):
            return i
    raise AssertionError(f"no statement matching {needles} in:\n" +
                         "\n".join(f"  {s[:90]}" for s in stmts))


@pytest.mark.asyncio
async def test_the_aggregate_runs_before_any_truncate(rebuilt):
    """The property the whole fix consists of."""
    last_aggregate = max(
        _index_of(rebuilt, "CREATE TEMP TABLE _new_pred_stats"),
        _index_of(rebuilt, "CREATE TEMP TABLE _new_stats"),
    )
    first_truncate = min(
        _index_of(rebuilt, "TRUNCATE", "_rdf_pred_stats"),
        _index_of(rebuilt, "TRUNCATE", "_rdf_stats"),
    )
    assert last_aggregate < first_truncate, (
        "an aggregate after the TRUNCATE is inside the exclusive-lock window, "
        "which is exactly issues/145")


@pytest.mark.asyncio
async def test_no_scan_of_the_quad_table_after_the_first_truncate(rebuilt):
    """Stronger than the above: nothing touching the quad table may appear once
    the lock is held, however it is phrased."""
    first_truncate = min(
        _index_of(rebuilt, "TRUNCATE", "_rdf_pred_stats"),
        _index_of(rebuilt, "TRUNCATE", "_rdf_stats"),
    )
    inside = rebuilt[first_truncate:_index_of(rebuilt, "COMMIT")]
    offenders = [s for s in inside if "sp_t_rdf_quad" in s]
    assert not offenders, (
        "these run while holding AccessExclusiveLock:\n" +
        "\n".join(f"  {s[:100]}" for s in offenders))


@pytest.mark.asyncio
async def test_it_is_still_one_transaction(rebuilt):
    """issues/103: a TRUNCATE that commits without its INSERT leaves the table
    EMPTY, and absence means ZERO to every consumer — worse than stale."""
    assert rebuilt.count("BEGIN") == 1
    begin, commit = rebuilt.index("BEGIN"), rebuilt.index("COMMIT")
    for what in ("TRUNCATE sp_t_rdf_pred_stats", "TRUNCATE sp_t_rdf_stats"):
        assert begin < _index_of(rebuilt, what) < commit


@pytest.mark.asyncio
async def test_temp_tables_are_tied_to_the_transaction(rebuilt):
    """ON COMMIT DROP, so a failed rebuild cleans up after itself and a retry
    on the same pooled connection cannot meet a stale one."""
    for t in ("_new_pred_stats", "_new_stats"):
        stmt = rebuilt[_index_of(rebuilt, f"CREATE TEMP TABLE {t}")]
        assert "ON COMMIT DROP" in stmt, f"{t} outlives its transaction"


@pytest.mark.asyncio
async def test_the_row_count_cap_is_still_applied_once(rebuilt):
    """The cap must stay the shared constant and must still be in the staged
    aggregate — moving the SQL is where a threshold quietly goes missing, and
    the `pruned` update below has to agree with it exactly."""
    staged = rebuilt[_index_of(rebuilt, "CREATE TEMP TABLE _new_stats")]
    assert f"COUNT(*) <= {S.STATS_MAX_ROW_COUNT}" in staged
    pruned = rebuilt[_index_of(rebuilt, "SET pruned")]
    assert f"COUNT(*) > {S.STATS_MAX_ROW_COUNT}" in pruned
