#!/usr/bin/env python3
"""Cheap checks that must pass BEFORE an expensive perf pass or a promotion.

WHY THIS EXISTS. A query-tier pass costs ~15 minutes and an ingest-tier pass
~39. Those are fine to spend once. They are not fine to spend, discover a
defect that was visible in the output, fix it, and spend again — which is
exactly what happened on 2026-09-13: the ingest tier was promoted, the
`test_partition_pruning` errors in that same output turned out to be a real
schema defect, and the tier had to be re-run. 78 minutes for one baseline.

Every check here is static or reads an already-recorded run. None of them needs
a database, and the whole thing finishes in seconds. Run it first, and run it
against the recorded run BEFORE promoting.

    python scripts/perf_preflight.py                  # static checks
    python scripts/perf_preflight.py --run run.json   # + is this run promotable

THE RULE IT ENCODES: a run missing a bench the tree DECLARES is not promotable.
A bench whose fixture errors is never stamped, so it leaves the run silently —
not failed, absent. Promote that and the absence is baked in, and `compare_bench`
can no longer warn, because the bench is missing from both sides.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PERF = ROOT / "tests" / "performance"

# Only `test_*.py`: `perf_record.py`'s docstring shows the mark in a usage
# example, and reading that as a declaration invents a bench that never runs.
_BENCH = re.compile(r'@pytest\.mark\.bench\(\s*["\']([^"\']+)')


def declared_benches() -> dict:
    out = {}
    for p in sorted(PERF.glob("test_*.py")):
        for m in _BENCH.finditer(p.read_text(encoding="utf-8")):
            out.setdefault(m.group(1), p.name)
    return out


def run_bench_ids(path: pathlib.Path) -> set:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {b["bench_id"].split("[")[0] for b in data.get("benches", [])}


def check_run_is_promotable(path: pathlib.Path, tier: str | None) -> list:
    """Declared-but-absent benches in a recorded run. Empty means promotable."""
    declared, present = declared_benches(), run_bench_ids(path)
    if not declared:
        return ["no bench declarations found — the scan is broken, not the tree"]
    if not present:
        return [f"{path} records no benches at all"]

    # A run of ONE tier legitimately lacks the other tier's benches, so only
    # complain about a declaration whose own file belongs to this pass.
    ingest = {p.name for p in PERF.glob("test_*.py")
              if "ingest_bench" in p.read_text(encoding="utf-8")}
    problems = []
    for bench, fname in sorted(declared.items()):
        if bench in present:
            continue
        if tier == "ingest" and fname not in ingest:
            continue
        if tier == "query" and fname in ingest:
            continue
        problems.append(
            f"{bench} ({fname}) is declared but ABSENT from the run — a bench "
            f"whose fixture errors is never stamped, so check that file for a "
            f"fixture that raises")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=pathlib.Path,
                    help="a recorded run file to check for promotability")
    ap.add_argument("--tier", choices=("query", "ingest"),
                    help="which tier produced the run, so the other tier's "
                         "benches are not reported as missing")
    args = ap.parse_args()

    failures = []
    declared = declared_benches()
    print(f"  bench ids declared in tests/performance: {len(declared)}")

    if args.run:
        if not args.run.exists():
            print(f"❌ no such run file: {args.run}")
            return 2
        problems = check_run_is_promotable(args.run, args.tier)
        present = len(run_bench_ids(args.run))
        print(f"  bench ids present in {args.run.name}: {present}")
        failures += problems

    if failures:
        print("\n❌ preflight FAILED — do not spend a tier pass on this:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("✅ preflight passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
