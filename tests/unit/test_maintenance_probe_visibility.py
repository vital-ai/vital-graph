"""A drift probe that cannot answer must skip LOUDLY, and get the time to answer.

`issues/144`. All three derived-table integrity checks sat under:

    except Exception:
        continue  # space predates the table, or is not a KG space

Skipping is the right action — a probe that cannot answer must not trigger a
repair — but the comment asserts a benign cause, and the clause catches every
other one identically. What actually happened on prod: `entity_slot_sort_drift`
computes its expected count with the full unseeded `WITH RECURSIVE frame_walk`,
measured at 76s against the read path's 60s `statement_timeout`. So it timed out
every cycle, was read as "not a KG space", and the backfill never ran. The table
it should maintain is 0.6% populated, which is why the entity listing page sorts
its whole population to return 25 rows.

Two properties, and the fix needs both — raising the budget without reporting
failure would just move the silence, and reporting without raising the budget
would report every cycle forever.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import asyncpg
import pytest

from vitalgraph.process import maintenance_job as M


class _Conn:
    def __init__(self, statement_timeout="60s"):
        self.statements: list[str] = []
        self._st = statement_timeout

    async def fetchval(self, sql, *_a):
        self.statements.append(sql)
        if "lock_timeout" in sql:
            return "10s"
        return self._st if "statement_timeout" in sql else None

    async def execute(self, sql, *_a):
        self.statements.append(sql)
        return "SET"


@pytest.mark.asyncio
async def test_a_probe_gets_the_maintenance_budget_not_the_read_path_fence():
    conn = _Conn(statement_timeout="60s")
    async with M.maintenance_timeouts(conn):
        pass

    assert "SHOW statement_timeout" in conn.statements
    assert "SHOW lock_timeout" in conn.statements
    assert (f"SET statement_timeout = {M.MAINTENANCE_STATEMENT_TIMEOUT_MS}"
            in conn.statements)
    assert (f"SET lock_timeout = {M.MAINTENANCE_LOCK_TIMEOUT_MS}"
            in conn.statements), (
        "issues/149: raising only statement_timeout left the backfill losing "
        "43 lock races at the read path's 10s fence")
    assert M.MAINTENANCE_STATEMENT_TIMEOUT_MS > 76_000, (
        "the measured probe takes 76s on prod; a budget below that leaves "
        "issues/144 in place")


@pytest.mark.asyncio
async def test_the_budget_does_not_outlive_the_probe():
    """The connection goes back to a pool that also serves user queries."""
    conn = _Conn(statement_timeout="60s")
    async with M.maintenance_timeouts(conn):
        pass
    assert "SET statement_timeout = '60s'" in conn.statements[-2:]
    assert "SET lock_timeout = '10s'" in conn.statements[-2:]


@pytest.mark.asyncio
async def test_the_budget_is_restored_when_the_probe_raises():
    conn = _Conn(statement_timeout="60s")
    with pytest.raises(asyncpg.QueryCanceledError):
        async with M.maintenance_timeouts(conn):
            raise asyncpg.QueryCanceledError("canceling statement")
    assert "SET statement_timeout = '60s'" in conn.statements[-2:]


def test_a_timeout_is_reported_at_warning_with_its_consequence(caplog):
    """The message has to name what was skipped. "probe failed" alone reads as
    cosmetic; the reader needs to know a REPAIR did not happen."""
    with caplog.at_level("WARNING"):
        M.log_probe_failure(
            "entity_slot_sort_integrity", "sp_x",
            asyncpg.QueryCanceledError("canceling statement due to timeout"))

    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert "sp_x" in msg
    assert "QueryCanceledError" in msg
    assert "not be repaired" in msg.lower(), (
        "must name the consequence, not just the error")


def test_no_REPAIR_step_swallows_a_failure_silently():
    """`issues/144`: `except Exception: continue` with a comment asserting a
    benign cause. The clause caught statement timeouts too, so a total failure
    of the repair path looked identical to a non-KG space, for months.

    Scoped to the steps that REPAIR. A swallowed failure there means the repair
    silently did not happen, which is the defect. Elsewhere in this module there
    are handlers that are deliberately quiet and correct — a fail-safe that
    returns "do the work anyway", a best-effort timeout restore — and a guard
    that flags those teaches people to edit the guard.

    KNOWN AND NOT COVERED, found while writing this: `_run_value_stats_refresh`
    and one branch of the stats path still use `except Exception: continue` with
    a "non-KG space" comment. Same shape as issues/144. Worth narrowing, not
    done here.
    """
    import inspect
    import re
    for name in ("_run_edge_integrity", "_run_frame_entity_integrity",
                 "_run_entity_slot_sort_integrity", "_run_stats_recompute"):
        src = inspect.getsource(getattr(M.MaintenanceJob, name))
        lines = src.split("\n")
        for i, line in enumerate(lines):
            if not re.match(r"\s*except Exception(\s+as \w+)?\s*:\s*$", line):
                continue
            ind = len(line) - len(line.lstrip())
            body = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= ind:
                    break
                body.append(nxt)
            text = "\n".join(body)
            assert re.search(
                r"logger\.(warning|error|exception)|log_probe_failure|raise", text), (
                f"{name} swallows a failure without reporting it at WARNING or "
                f"above — production runs at INFO, so DEBUG is invisible, which "
                f"is exactly how issues/144 hid a dead repair path")

def test_the_stats_integrity_guard_is_not_a_debug_swallow():
    """`issues/148`. One `except` guards BOTH the coverage audit (141) and the
    oversized-pair repair (142). Logging it at DEBUG meant a total failure of
    both looked identical to a healthy cycle on a service that runs at INFO.

    Observed on production: every cycle skipped the check with "column p.pruned
    does not exist", while the column existed on every `*_rdf_pred_stats` table
    in the only schema of the only configured database, and the running image
    held the correct query. The cause is still open — what is not open is that
    nothing said so above DEBUG.
    """
    import inspect
    # `_run_stats_integrity` is gone with the accumulator (`issues/142`); the
    # step that inherited its "if this stops working nothing notices" role is
    # the recompute, which is now the ONLY thing keeping rdf_stats correct.
    src = inspect.getsource(M.MaintenanceJob._run_stats_recompute)
    tail = src[src.rindex("except"):]
    assert "logger.debug" not in tail, (
        "a swallowed recompute failure must not be invisible at INFO")
    assert "logger.warning" in tail
    assert "FAILED" in tail, (
        "the message must name the consequence — that the join reorder plans "
        "on whatever is in rdf_stats until the next cycle")
    assert "exc_info=True" in tail, (
        "the message alone was not enough to diagnose this; the failing "
        "statement is the useful part")


@pytest.mark.asyncio
async def test_the_repair_gets_the_same_budget_as_the_probe():
    """`issues/149`, second half. The probe was given the maintenance budget and
    the BACKFILL it gates was left on the read path's fences. So the probe
    completed, correctly reported a 2.7M-row gap, triggered the repair — and the
    repair died: 3 statement timeouts at 60s and 43 LockNotAvailableError at the
    10s lock fence. The table crept 26.5k -> 40k against a ~2.83M target.

    A gate that is fixed while the thing behind it is not looks exactly like a
    fixed gate, which is why this is asserted rather than assumed.
    """
    import inspect
    src = inspect.getsource(M.MaintenanceJob._run_entity_slot_sort_integrity)
    at_backfill = src.index("backfill_entity_slot_sort_batch(")
    before = src[:at_backfill]
    assert before.count("maintenance_timeouts(conn)") >= 2, (
        "the backfill call must be inside its own maintenance_timeouts block, "
        "not only the probe above it")
    tail = src[at_backfill:at_backfill + 200]
    assert "timeout=PROBE_CLIENT_TIMEOUT_S" in tail, (
        "and it needs the CLIENT-side bound too — command_timeout=60 fires in "
        "the driver regardless of any server-side SET")


def test_every_repair_runs_under_the_maintenance_budget():
    """`issues/149` was fixed three times before it was fixed everywhere.

    The defect is always the same shape: a PROBE is given the maintenance
    budget, the REPAIR it gates is left on the read path's 60s statement / 10s
    lock fences, and the result looks like a working check — it diagnoses
    correctly every cycle and never repairs anything.

    Found in `_run_entity_slot_sort_integrity` (measured: 3 statement timeouts,
    43 LockNotAvailableError, table stuck at 40k of ~2.83M), then found unfixed
    in `_run_edge_integrity`, `_run_frame_entity_integrity`, the orphan sweep,
    and `_run_stats_rebuild` — the last of which repairs corrupt rdf_stats, so
    it timing out means the stats stay corrupt forever (`issues/139`'s shape).

    Checks EVERY call site, not the first: an earlier version of this test used
    `src.index()` and passed while the orphan sweep was still unwrapped.

    The psycopg sync path is exempt — `_make_sync_connection` applies
    `maintenance_conn_options` at CONNECT time, which is the same fences by
    another route.
    """
    import inspect
    lines = inspect.getsource(M).split("\n")
    calls = ("backfill_entity_slot_sort_batch(", "backfill_edge_table(",
             "backfill_frame_entity_table(", "cleanup_orphan_edges(",
             "cleanup_stale_frame_entity(", "recompute_stats_tables(",
             "resync_value_stats(", "StatsRebuildOp(")
    unwrapped = []
    for i, line in enumerate(lines):
        code = line.split("#")[0]
        if "await " not in code and "StatsRebuildOp(" not in code:
            continue
        for c in calls:
            if c in code:
                ctx = "\n".join(lines[max(0, i - 25):i])
                if "maintenance_timeouts(" not in ctx:
                    unwrapped.append((i + 1, c))
    assert not unwrapped, (
        "repairs on the read path's fences — a repair that cannot finish is "
        f"issues/149: {unwrapped}")


def test_every_long_probe_and_repair_gets_a_CLIENT_side_timeout():
    """The OTHER half of `issues/149`, and the half that actually bit.

    `maintenance_timeouts` raises `statement_timeout` and `lock_timeout` with
    SET. Those are SERVER fences. The pool is built with `command_timeout=60`,
    which fires in the DRIVER and cannot be affected by any SET — so a call that
    runs past 60s is cancelled client-side no matter how generous the server
    budget is, and `test_every_repair_runs_under_the_maintenance_budget` above
    passes while the work still never completes.

    That is precisely how the slot-sort backfill "had never once run": the probe
    gating it took 97-133s, the driver gave up at 60s every cycle, and the
    diagnosis looked healthy.

    Found again 2026-09-04 in the EDGE path — `edge_table_drift`,
    `edge_table_orphan_rate` and `backfill_edge_table` all took no client
    timeout, so the repair for `issues/041`'s ~25% shortfall could not finish on
    a production-sized space either. Same defect, sibling module, four months
    later. Hence this test rather than another one-off fix.

    Scoped to calls that can run long. A fast indexed count does not need it.
    """
    import inspect
    lines = inspect.getsource(M).split("\n")
    # Anything that scans or writes proportional to the SPACE, not to a batch.
    long_calls = (
        "backfill_entity_slot_sort_batch(", "backfill_edge_table(",
        "backfill_frame_entity_table(", "entity_slot_sort_coverage(",
        "entity_slot_sort_all_types(", "edge_table_drift(",
        "edge_table_orphan_rate(", "frame_entity_drift(",
    )
    missing = []
    for i, line in enumerate(lines):
        code = line.split("#")[0]
        for c in long_calls:
            if c in code and "await " in code or (c in code and "await" in
                                                  "\n".join(lines[max(0, i - 2):i + 1])):
                # The call may wrap over several lines; read to its closing paren.
                window = "\n".join(lines[i:i + 6])
                if "timeout=" not in window:
                    missing.append((i + 1, c))
                break
    assert not missing, (
        "these run proportional to the space and would be cancelled by the "
        "pool's 60s command_timeout, in the driver, whatever the server fence "
        f"says — `issues/149`: {missing}")


def test_no_maintenance_helper_uses_a_timeout_it_does_not_accept():
    """The failure mode the call-site test above cannot see.

    Threading a client timeout is TWO edits — pass it at the call, accept it in
    the signature — and the call-site test only checks the first. Doing one
    without the other produces a NameError at runtime, on the repair path, which
    is the least observable place to put one.

    Caught exactly that on 2026-09-04: `frame_entity_drift` and
    `backfill_frame_entity_table` were given `timeout=timeout` in their queries
    while a failed edit left both signatures unchanged. Every test still passed.

    Scans the package rather than a list, because the next one will be in a
    module nobody thought to enumerate.
    """
    import ast
    import pathlib

    root = pathlib.Path(M.__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if node.args.kwarg:          # **kwargs can carry it
                continue
            names = ([a.arg for a in node.args.args]
                     + [a.arg for a in node.args.kwonlyargs])
            if "timeout" in names:
                continue
            loads = any(isinstance(x, ast.Name) and x.id == "timeout"
                        and isinstance(x.ctx, ast.Load) for x in ast.walk(node))
            stores = any(isinstance(x, ast.Name) and x.id == "timeout"
                         and isinstance(x.ctx, ast.Store) for x in ast.walk(node))
            if loads and not stores:
                offenders.append(f"{path.name}:{node.lineno} {node.name}")
    assert not offenders, (
        "these reference `timeout` without accepting or binding it — a "
        f"NameError the moment the branch runs: {offenders}")


def test_watches_are_not_given_the_maintenance_budget():
    """The inverse error. A watch on a 15-minute budget scans for 15 minutes."""
    import inspect
    for name in ("_run_grouping_self_link_check",
                 "_run_graph_registration_check"):
        body = inspect.getsource(getattr(M.MaintenanceJob, name))
        assert "maintenance_timeouts(" not in body, (
            f"{name} writes nothing; a longer budget only lets it scan more "
            f"(issues/143 measured it at 38.6s/pass evicting the read cache)")


def test_maintenance_queries_carry_a_CLIENT_side_timeout_too():
    """The blind spot that has now recurred four times.

    `maintenance_timeouts` raises the SERVER fences with SET. asyncpg's
    `command_timeout=60` is CLIENT-side and no SET can touch it, so a query
    inside that block is still abandoned at 60s with a bare `TimeoutError` —
    empty message, which is how it kept being misread as something else.

    History:
      issues/149  the slot-sort drift probe          — fixed, client timeout added
      issues/149  the backfill it gates              — missed, fixed later
      issues/150  (adjacent) the same for repairs    — audited
      issues/148  _run_stats_integrity               — MISSED BY THAT AUDIT

    The last one is why this test exists rather than another round of reading.
    The audit checked for `maintenance_timeouts` wrapping and never for
    `timeout=`, so six queries in the stats integrity check kept dying at 60s.
    Production consequence: the audit that rebuilds `rdf_stats` never ran, the
    table decayed to 5 rows, the anchor pair (77,479 rows) went ABSENT, and the
    semi-join gate fell back to a 10.4s runtime probe on every dedup query.
    """
    import inspect
    import re
    src = inspect.getsource(M)
    lines = src.split("\n")
    inblock, blockind, cur, bad = False, 0, "<module>", []
    for i, line in enumerate(lines):
        m = re.match(r"    (?:async )?def (\w+)", line)
        if m:
            cur = m.group(1)
        if "maintenance_timeouts(" in line:
            inblock, blockind = True, len(line) - len(line.lstrip())
            continue
        if inblock and line.strip():
            if (len(line) - len(line.lstrip())) <= blockind:
                inblock = False
        if inblock and re.search(
                r"await conn\.(fetchrow|fetchval|fetch|execute|executemany)\(", line):
            # generous window: these statements are long f-strings
            window = "\n".join(lines[i:i + 40])
            if "timeout=" not in window and cur != "<module>":
                bad.append((i + 1, cur, line.strip()[:60]))
    assert not bad, (
        "maintenance queries inside maintenance_timeouts without a CLIENT-side "
        "timeout — asyncpg abandons these at command_timeout=60 regardless of "
        f"any SET: {bad}")


def test_long_running_sync_helpers_accept_and_use_a_client_timeout():
    """The guard above only reads `maintenance_job`. That is not enough.

    Fixing the audit's client timeout moved the failure ONE LEVEL DOWN: the
    audit's response to a coverage gap was a full rebuild, whose own
    aggregate measured 19.6-49.0 s on production against the same 60 s
    `command_timeout`. Its nine queries had no `timeout=` at all, so the rebuild
    would die in the driver and roll back, leaving the stats as corrupt as
    before.

    So the helpers the maintenance loop CALLS have to be checked too, not just
    the loop itself.
    """
    import inspect
    from vitalgraph.db.sparql_sql import sync_stats_tables as S
    from vitalgraph.db.sparql_sql import sync_entity_slot_sort as E

    for fn in (S.recompute_stats_tables,
               E.entity_slot_sort_drift, E.entity_slot_sort_coverage,
               E.backfill_entity_slot_sort_batch):
        sig = inspect.signature(fn)
        assert "timeout" in sig.parameters, (
            f"{fn.__name__} runs for tens of seconds and cannot be bounded by "
            f"the caller without a timeout parameter")

    body = inspect.getsource(S.recompute_stats_tables)
    # `SET enable_hashagg` is excluded by name, not by loosening the count. The
    # claim is about statements that can RUN LONG and so must carry the client
    # timeout; a planner GUC assignment returns immediately and would never hit
    # `command_timeout` no matter what it was set to. Naming it keeps the check
    # exact — a new unbounded AGGREGATE still fails here.
    calls = body.count("await conn.execute(") - body.count("SET enable_hashagg")
    used = body.count("timeout=timeout")
    assert used >= calls, (
        f"{calls} long-running queries in the stats rebuild, only {used} pass "
        f"the client timeout — the unbounded ones die at command_timeout=60")


def test_tracker_calls_match_the_real_signature():
    """A mock that accepts **kwargs hides a TypeError until runtime.

    `_run_entity_slot_sort_integrity` called
    `create_process("...", space_id=...)`. `ProcessTracker.create_process` takes
    `process_subtype`, not `space_id`. Every unit test passed — the tracker is
    mocked — and the first real cycle on vg-test raised TypeError and ABORTED
    the whole run: "every later step was SKIPPED, not clean". So one wrong
    kwarg in one step silently disabled ANALYZE, VACUUM, every integrity check
    and the stats recompute.

    Checks the call sites against the actual signature by binding them.
    """
    import inspect
    import re
    from vitalgraph.process.process_tracker import ProcessTracker

    sig = inspect.signature(ProcessTracker.create_process)
    allowed = set(sig.parameters) - {"self"}
    src = inspect.getsource(M)
    bad = []
    for m in re.finditer(r"create_process\(\s*([^)]*)\)", src, re.S):
        for kw in re.findall(r"(\w+)\s*=", m.group(1)):
            if kw not in allowed:
                bad.append(kw)
    assert not bad, (
        f"create_process called with kwargs it does not accept: {sorted(set(bad))}; "
        f"accepted: {sorted(allowed)}")
