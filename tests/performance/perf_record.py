"""Result recording for the performance suite (P1 of
planning/planning_performance/performance_regression_tracking_plan.md).

The suite already *asserts* on plan shape and work counters; it just threw the
numbers away. This module captures each measurement as a structured record, so a
run can be compared against a promoted baseline (`scripts/perf_compare.py`).

Usage in a test — mark it with the bench id, then record:

    @pytest.mark.bench("query.fastpath.entity_page")
    async def test_fast_page_is_o_page(perf_conn, perf_record):
        plan = await assert_plan(perf_conn, sql, ..., max_shared_buffers=8_000)
        perf_record(plan=plan, dataset="wordnet_frames")

`perf_record` derives the metric dict from the plan via the harness extractors,
so adding tracking to an existing test is a one-line change and the assertion
semantics are untouched. Tests that skip (or fail) still emit a record with that
status — a bench present in the baseline but skipped in the run is a coverage
hole, not an implicit pass (see the plan's R5).

Recording is off unless ``VG_PERF_RECORD`` names an output path:

    VG_PERF_RECORD=tests/performance/results/run.json pytest -m performance
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import harness

# PG settings that move plan shape — recorded so runs from differently-tuned
# servers are never silently compared (plan R2).
PG_SETTINGS = [
    "server_version", "shared_buffers", "work_mem", "maintenance_work_mem",
    "effective_cache_size", "max_parallel_workers_per_gather", "random_page_cost",
    "jit", "default_statistics_target",
]


def _sh(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def git_stamp() -> Dict[str, Any]:
    dirty = _sh("git", "status", "--porcelain")
    return {
        "commit": _sh("git", "rev-parse", "HEAD"),
        "short": _sh("git", "rev-parse", "--short", "HEAD"),
        "branch": _sh("git", "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(dirty),
    }


def machine_stamp() -> Dict[str, Any]:
    return {
        "host": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
    }


def runner_stamp() -> Dict[str, Any]:
    """Which environment class this run measured in.

    The tracked environment is the ephemeral vg-test stack (clean PG per run,
    image rebuilt from the code under test). A host-PG run is a different class
    and must not be compared against a vg-test baseline.
    """
    host = os.environ.get("VG_TEST_PG_HOST", "localhost")
    port = os.environ.get("VG_TEST_PG_PORT", "5433")  # docker test stack (issues/099)
    is_vgtest = port == "5433"
    # A clean container DB and a persisted volume holding several loaded spaces
    # are NOT the same measurement environment, even though both are
    # "vg-test-docker": shared buffers, autovacuum load and on-disk layout all
    # differ. Measured: bulk-ingest copy_speedup 7.7x clean vs 5.4x persisted —
    # a 30% "regression" that is purely environmental. Recorded so the compare
    # tool refuses to read one as a regression of the other.
    persist = os.environ.get("VG_PERF_PERSIST", "").lower() in ("1", "true", "yes")
    seeded = os.environ.get("VG_PERF_SEEDED", "").lower() in ("1", "true", "yes")
    return {
        "class": ("vg-test-docker" if is_vgtest else "host-pg")
                 + ("-persist" if persist else "-clean"),
        "persist": persist,
        "seeded": seeded,
        "pg_host": host,
        "pg_port": port,
        "pg_database": os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
    }


# Spaces that exist ONLY on the seeded, persisted stack. Their presence WITH
# DATA is what distinguishes a resident run from a clean one — a clean run
# creates its own fixtures as it goes, so the existence of fixture tables proves
# nothing on its own. `issues/189` records twelve baseline cells reading
# `wordnet_frames` and `space_lead_dataset_test` under a stamp claiming clean.
SEED_ONLY_SPACES = ("wordnet_frames", "space_lead_dataset_test",
                    "lead_nurture_grouped")

# The tables whose STATISTICS decide the plans this suite measures. Prefix
# match, so every per-space table of a benchmark fixture is covered.
STATS_FIXTURE_PREFIXES = ("sp_lead_synth_", "sp_graph_synth_", "sp_graph_skew_",
                          "sp_graph_forms_", "sp_lead_types", "wordnet_frames",
                          "sp_sql_lead_dataset", "space_lead_dataset_test",
                          # The 74M production-shaped Nurture fixture. Must stay
                          # in step with VG_MAINTENANCE_EXCLUDE_SPACES in
                          # docker-compose.test.yml — a space stamped here but not
                          # excluded there reports "the fixtures were re-ANALYZEd"
                          # for something maintenance was free to touch.
                          #
                          # Replaced `lead_nurture_100k` (53.4M), which carried NO
                          # grouping URIs and so could not answer the query the KG
                          # endpoints use to open an entity — it returned 0 rows in
                          # 1ms, which passes any threshold while measuring nothing
                          # (`issues/171`).
                          "lead_nurture_grouped")


async def stats_stamp(conn) -> Dict[str, Any]:
    """When the benchmark fixtures were last ANALYZEd, and how big they are.

    `issues/112`. `PG_SETTINGS` above exists because a benchmark compared against
    an unrecorded CONFIGURATION is meaningless (`issues/081`). The STATISTICS
    STATE is exactly as load-bearing and was not recorded — and unlike the
    settings, THE APPLICATION MUTATES IT ON A SCHEDULE: `MaintenanceJob` scores
    each space and runs ANALYZE/VACUUM from inside the running container.

    That produced a 91% "regression" with identical code, identical settings and
    identical rows — `deep_paging.monotonic[100k]` went 174,345 -> 333,408
    buffers and 237 -> 474 ms because fresh statistics turned a `Gather Merge`
    into a `Sort` above a `Gather`. Attributing it took about forty minutes and
    began by suspecting the day's commits, because the comparison reports the
    delta against the last commit and offers no other candidate.

    Recorded as an aggregate rather than per-table: the question a comparison
    needs to answer is "were these two runs taken on the same statistics?", and
    a single latest-analyze timestamp plus a row total answers it without
    bloating the file with several hundred rows.
    """
    out: Dict[str, Any] = {}
    try:
        rows = await conn.fetch(
            """
            SELECT relname, n_live_tup,
                   greatest(coalesce(last_analyze, 'epoch'::timestamptz),
                            coalesce(last_autoanalyze, 'epoch'::timestamptz)) AS analyzed
            FROM pg_stat_user_tables
            """)
    except Exception:
        return out
    picked = [r for r in rows
              if any(r["relname"].startswith(p) for p in STATS_FIXTURE_PREFIXES)]
    if not picked:
        return out
    latest = max(r["analyzed"] for r in picked)
    out["fixture_tables"] = len(picked)
    out["fixture_live_tuples"] = sum(int(r["n_live_tup"] or 0) for r in picked)
    out["fixture_last_analyze"] = latest.isoformat() if latest else None
    return out


async def fixture_sizes(conn) -> Dict[str, Any]:
    """Bytes per SPACE — heap plus indexes — and the largest of them.

    `issues/189`. The aggregate `fixture_live_tuples` reads as reassuring and
    answers the wrong question: **a query touches ONE space.** 126,128,097 live
    tuples across 260 tables says nothing about whether the space a bench read
    was resident, and residency is what decides which plan wins.

    Grouped by `space_id` from the `space` table rather than by the prefixes in
    `STATS_FIXTURE_PREFIXES`, because `sp_lead_synth_` matches both
    `sp_lead_synth_100k` (35 GB, out of memory) and `sp_lead_synth_10k`
    (3.4 GB, resident) — merging them would hide the one property that matters.
    """
    out: Dict[str, Any] = {}
    try:
        spaces = [r["space_id"] for r in
                  await conn.fetch("SELECT space_id FROM space")]
        rows = await conn.fetch(
            "SELECT relname, pg_total_relation_size(c.oid) AS bytes "
            "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE c.relkind IN ('r','p') AND n.nspname = 'public'")
    except Exception:
        return out
    per: Dict[str, int] = {}
    for r in rows:
        name = r["relname"]
        # Longest match wins: `sp_lead_synth_10k` is a prefix of nothing here,
        # but a shorter space id could be a prefix of a longer one.
        owner = max((sp for sp in spaces if name.startswith(sp + "_")),
                    key=len, default=None)
        if owner:
            per[owner] = per.get(owner, 0) + int(r["bytes"] or 0)
    if not per:
        return out
    gated = {sp: b for sp, b in per.items()
             if any(sp.startswith(pre) for pre in STATS_FIXTURE_PREFIXES)}
    out["space_bytes"] = dict(sorted(per.items(), key=lambda kv: -kv[1]))
    if gated:
        biggest = max(gated.items(), key=lambda kv: kv[1])
        out["largest_gated_fixture"] = biggest[0]
        out["largest_gated_fixture_bytes"] = biggest[1]
    return out


def reconcile_runner(runner: Dict[str, Any], stats: Dict[str, Any],
                     sizes: Dict[str, Any],
                     shared_buffers_bytes: Optional[int]) -> Dict[str, Any]:
    """Re-derive the runner class from OBSERVED state; keep the flags as a check.

    `issues/189`. `runner.class` is what `compare_env` uses to decide whether two
    runs are comparable at all, and it was the one field taken on trust from an
    environment variable. The committed `query.json` is stamped
    `vg-test-docker-clean` while its own `stats` block records 126,128,097 live
    tuples across 260 tables — a clean container mounts no volume and holds
    none of that — and twelve of its cells read spaces that exist only on a
    seeded stack. Both facts were in the same file and nothing compared them.

    So the flags no longer decide. The DATABASE decides, the flags are recorded
    beside it, and a DISAGREEMENT BLOCKS PROMOTION rather than silently
    preferring either: a run that cannot say which environment it measured is
    not a baseline, whichever way the mismatch points.
    """
    out = dict(runner)
    tables = int(stats.get("fixture_tables") or 0)
    tuples = int(stats.get("fixture_live_tuples") or 0)

    # DERIVED FROM BYTES, NOT FROM `n_live_tup`.
    #
    # The obvious test is "are there fixture rows", and it is wrong: the first
    # version of this read `fixture_live_tuples > 0` and reported the live
    # 105 GB seeded stack as CLEAN. `n_live_tup` is a STATISTICS estimate and
    # reads 0 for a table that has never been ANALYZEd, which is the state 286
    # fixture tables on that stack are in — the same trap as `entity_slot_sort`
    # carrying 3,877,000 rows with `last_analyze` NULL (`issues/194`). A
    # detector for "was this seeded" must not depend on the thing the seeding
    # forgot to do.
    #
    # `pg_total_relation_size` is exact and needs no statistics. And the signal
    # is the SEED-ONLY spaces rather than total size, because a clean run
    # creates its own fixtures as it goes: presence of tables proves nothing,
    # presence of THESE spaces with data in them proves the volume persisted.
    seed_bytes = sum(b for sp, b in (sizes.get("space_bytes") or {}).items()
                     if any(sp.startswith(x) for x in SEED_ONLY_SPACES))
    observed_persist = seed_bytes > 0
    observed_seeded = observed_persist
    out["observed"] = {"persist": observed_persist, "seeded": observed_seeded,
                       "fixture_tables": tables, "fixture_live_tuples": tuples,
                       "seed_space_bytes": seed_bytes}
    flags = {"persist": bool(runner.get("persist")),
             "seeded": bool(runner.get("seeded"))}
    out["flags"] = flags

    base = "vg-test-docker" if runner.get("pg_port") == "5433" else "host-pg"
    out["class"] = base + ("-persist" if observed_persist else "-clean")
    out["persist"] = observed_persist
    out["seeded"] = observed_seeded

    if flags["persist"] != observed_persist or flags["seeded"] != observed_seeded:
        out["flags_disagree"] = (
            f"VG_PERF_PERSIST/VG_PERF_SEEDED say persist={flags['persist']} "
            f"seeded={flags['seeded']}, but the seed-only spaces hold "
            f"{seed_bytes:,} bytes across {tables} fixture table(s). Class "
            f"taken from the DATABASE. See issues/189.")
        out["promotion_blocked"] = out["flags_disagree"]

    # THE RESIDENCY PROPERTY, ASSERTED RATHER THAN INHERITED. Exactly one gated
    # fixture exceeds `shared_buffers`, and it does so by accident; if that stops
    # being true the suite measures only in-memory plans and nothing says so.
    big = sizes.get("largest_gated_fixture_bytes")
    if big is not None and shared_buffers_bytes:
        out["largest_gated_fixture"] = sizes.get("largest_gated_fixture")
        out["largest_gated_fixture_bytes"] = big
        out["shared_buffers_bytes"] = shared_buffers_bytes
        out["exceeds_shared_buffers"] = big > shared_buffers_bytes
    return out


def shared_buffers_bytes(pg: Dict[str, Any]) -> Optional[int]:
    """`shared_buffers` as bytes. It is reported in 8 kB blocks by default."""
    raw = (pg or {}).get("shared_buffers")
    if raw is None:
        return None
    try:
        return int(raw) * 8192
    except (TypeError, ValueError):
        pass
    import re as _re
    m = _re.match(r"^\s*(\d+)\s*([kKmMgGtT]?)B?\s*$", str(raw))
    if not m:
        return None
    mult = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}
    return int(m.group(1)) * mult[m.group(2).lower()]


async def pg_stamp(conn) -> Dict[str, Any]:
    settings: Dict[str, Any] = {}
    for name in PG_SETTINGS:
        try:
            settings[name] = await conn.fetchval("SELECT current_setting($1)", name)
        except Exception:
            settings[name] = None
    return settings


def metrics_from_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Derive the tracked metric set from an EXPLAIN (ANALYZE, BUFFERS) doc."""
    m = {
        "shared_buffers": harness.total_shared_buffers(plan),
        "shared_read": harness.shared_read_blocks(plan),
        "temp_written": harness.temp_written_blocks(plan),
        "actual_rows": harness.actual_rows(plan),
        "max_actual_rows": harness.max_actual_rows(plan),
        "estimated_rows": harness.estimated_rows(plan),
        "heap_fetches": harness.index_only_heap_fetches(plan),
    }
    # Wall-clock is context only — never the gate at L0-L2 (strategy doc §6).
    for key, out in (("Planning Time", "planning_ms"), ("Execution Time", "execution_ms")):
        if key in plan:
            m[out] = round(float(plan[key]), 3)
    return m


def canonical_tree(node: Dict[str, Any]) -> List[Any]:
    """`[node_type, [children...]]`, children sorted so sibling order normalises.

    `issues/113`. A flat pre-order walk cannot tell a meaningless reordering from
    a real restructuring: PostgreSQL may emit a hash join's inputs either way
    round, and comparing the list elementwise failed a bench whose plan had 39
    identical nodes, identical rows and identical cost.

    Comparing the MULTISET fixed that and gave up something in exchange — a
    `Sort` above a `Gather` and a `Gather` above a `Sort` have the same counts
    and are different plans. This keeps both properties: children are sorted by
    their own canonical form, so a sibling swap is erased, while PARENT/CHILD
    relationships survive:

        Sort above Gather    ["Sort",   [["Gather", []]]]
        Gather above Sort    ["Gather", [["Sort",   []]]]

    Sorted by `repr` rather than by node type alone, so two children of the same
    type are ordered by their whole subtree and the result is stable.
    """
    kids = [canonical_tree(c) for c in (node.get("Plans") or [])]
    return [node.get("Node Type", ""), sorted(kids, key=repr)]


def tree_edges(tree: List[Any], parent: str = "") -> List[str]:
    """`parent>child` for every edge, for a difference a human can read.

    The tree itself is what gates; this is what the failure message says. Two
    nested lists printed side by side are unreadable at terminal width, which is
    the state the elementwise comparison left its messages in.
    """
    out = []
    node_type, kids = tree[0], tree[1]
    if parent:
        out.append(f"{parent}>{node_type}")
    for k in kids:
        out.extend(tree_edges(k, node_type))
    return out


def shape_from_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """The size-independent structural fingerprint — gated on exact match."""
    root = plan["Plan"] if "Plan" in plan else plan
    nodes = list(harness._walk(root))
    return {
        "node_types": [n.get("Node Type", "") for n in nodes],
        "indexes": sorted({n["Index Name"] for n in nodes if n.get("Index Name")}),
        "seq_scans": sorted({n.get("Relation Name", "") for n in nodes
                             if n.get("Node Type") == "Seq Scan"}),
        # The structural fingerprint proper. `node_types` is kept because it is
        # what the assertion helpers print and what a reader recognises.
        "tree": canonical_tree(root),
    }


class PerfRun:
    """Collects records for one pytest session and writes the run file."""

    def __init__(self, out_path: str):
        self.out_path = out_path
        self.records: Dict[str, Dict[str, Any]] = {}
        self.env: Dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "git": git_stamp(),
            "machine": machine_stamp(),
            "runner": runner_stamp(),
            "pg": {},
            "stats": {},
        }

    def add(self, bench_id: str, **fields: Any) -> None:
        rec = self.records.setdefault(bench_id, {"bench_id": bench_id})
        rec.update(fields)

    def set_status(self, bench_id: str, status: str, reason: str = "") -> None:
        """Status from the pytest report — never downgrade a real failure."""
        rec = self.records.setdefault(bench_id, {"bench_id": bench_id})
        if rec.get("status") == "failed":
            return
        rec["status"] = status
        if reason:
            rec["reason"] = reason

    def write(self) -> None:
        self.env["finished_at"] = datetime.now(timezone.utc).isoformat()

        # A run with no server configuration is not comparable to anything, and
        # SILENTLY producing one is worse than not trying: the empty `pg` slot
        # reads as "checked, nothing notable". The committed baseline
        # (promoted 2026-08-06) has exactly that, and every timing taken under
        # it was on shared_buffers=1GB against a fixture needing >3GB — which
        # made a sorted page 27x slower than it is on a correct configuration
        # and was not noticed for weeks (issues/081).
        if not self.env.get("pg"):
            self.env["pg_stamp_missing"] = (
                "no server settings recorded — timings in this run are NOT "
                "comparable across machines or configurations. See issues/081.")
            print("\n  WARNING: perf run recorded NO PostgreSQL settings. "
                  "Timings are not comparable. See issues/081.\n")

        doc = {
            "schema": 1,
            "env": self.env,
            "benches": [self.records[k] for k in sorted(self.records)],
        }
        os.makedirs(os.path.dirname(os.path.abspath(self.out_path)), exist_ok=True)
        with open(self.out_path, "w") as fh:
            json.dump(doc, fh, indent=2, sort_keys=False)
            fh.write("\n")

        # Append a one-line index entry for trend queries.
        index = os.path.join(os.path.dirname(os.path.abspath(self.out_path)),
                             "history.jsonl")
        summary = {
            "path": os.path.abspath(self.out_path),
            "at": self.env["finished_at"],
            "commit": self.env["git"].get("short"),
            "branch": self.env["git"].get("branch"),
            "dirty": self.env["git"].get("dirty"),
            "runner": self.env["runner"].get("class"),
            "n_ok": sum(1 for r in self.records.values() if r.get("status") == "ok"),
            "n_skipped": sum(1 for r in self.records.values() if r.get("status") == "skipped"),
            "n_failed": sum(1 for r in self.records.values() if r.get("status") == "failed"),
        }
        with open(index, "a") as fh:
            fh.write(json.dumps(summary) + "\n")


def bench_id_for(item) -> Optional[str]:
    """Bench id from the @pytest.mark.bench marker, suffixed with the param id."""
    marker = item.get_closest_marker("bench")
    if marker is None or not marker.args:
        return None
    base = marker.args[0]
    callspec = getattr(item, "callspec", None)
    return f"{base}[{callspec.id}]" if callspec is not None else base


def load_run(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def benches_by_id(run: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {b["bench_id"]: b for b in run.get("benches", [])}
