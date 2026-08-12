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
    port = os.environ.get("VG_TEST_PG_PORT", "5432")
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


def shape_from_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """The size-independent structural fingerprint — gated on exact match."""
    root = plan["Plan"] if "Plan" in plan else plan
    nodes = list(harness._walk(root))
    return {
        "node_types": [n.get("Node Type", "") for n in nodes],
        "indexes": sorted({n["Index Name"] for n in nodes if n.get("Index Name")}),
        "seq_scans": sorted({n.get("Relation Name", "") for n in nodes
                             if n.get("Node Type") == "Seq Scan"}),
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
