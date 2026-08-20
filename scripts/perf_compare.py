#!/usr/bin/env python
"""Compare a recorded performance run against a promoted baseline.

Implements P2 of planning/planning_performance/performance_regression_tracking_plan.md:
the suite records structured results (tests/performance/perf_record.py), this
tool diffs a run against a named baseline and exits non-zero on regression.

    # compare the run just recorded against a TIER baseline (query | slow)
    python scripts/perf_compare.py tests/performance/results/run.json --baseline query

    # promote a reviewed run to be the new baseline
    python scripts/perf_compare.py tests/performance/results/run.json --promote query

    # how has one bench moved over the recorded history?
    python scripts/perf_compare.py --trend query.fastpath.entity_page

Gating rules come from tests/performance/thresholds.toml. Plan shape is gated on
exact match; work counters on a percentage bound; wall-clock is report-only.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
import os
import sys
import tomllib
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_DIR = os.path.join(ROOT, "tests", "performance", "baselines")
RESULTS_DIR = os.path.join(ROOT, "tests", "performance", "results")
THRESHOLDS = os.path.join(ROOT, "tests", "performance", "thresholds.toml")

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"

# Env fields that must match for a comparison to be meaningful (plan R2).
ENV_GATES = [
    ("runner", "class"),
    ("runner", "persist"),
    ("runner", "seeded"),
    ("machine", "host"),
    ("pg", "server_version"),
    ("pg", "shared_buffers"),
    ("pg", "work_mem"),
    ("pg", "effective_cache_size"),
    ("pg", "random_page_cost"),
    ("pg", "max_parallel_workers_per_gather"),
]


def load_json(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def load_thresholds(path: str = THRESHOLDS) -> Dict[str, Any]:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def resolve_baseline(name_or_path: str) -> str:
    if os.path.exists(name_or_path):
        return name_or_path
    candidate = os.path.join(BASELINE_DIR, f"{name_or_path}.json")
    if os.path.exists(candidate):
        return candidate
    raise SystemExit(f"no baseline {name_or_path!r} (looked in {BASELINE_DIR})")


def benches(run: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {b["bench_id"]: b for b in run.get("benches", [])}


def rule_for(thresholds: Dict[str, Any], bench_id: str, metric: str) -> Optional[Dict[str, Any]]:
    override = (thresholds.get("bench", {}).get(bench_id, {}) or {}).get(metric)
    base = (thresholds.get("metrics", {}) or {}).get(metric)
    if base is None and override is None:
        return None
    merged = dict(base or {})
    merged.update(override or {})
    return merged


def pct_change(baseline: float, current: float) -> Optional[float]:
    if baseline == 0:
        return None if current == 0 else float("inf")
    return (current - baseline) / abs(baseline) * 100.0


# ---------------------------------------------------------------------------
# Environment comparability
# ---------------------------------------------------------------------------

def compare_env(run: Dict[str, Any], base: Dict[str, Any]) -> List[str]:
    """Return a list of environment mismatches that invalidate the comparison.

    A MISSING server stamp is reported, not skipped. The rule used to be
    `a is not None and b is not None and a != b`, which reads sensibly and has
    the effect that an absent value can never disagree with anything — so the
    committed baseline, whose `env.pg` is `{}`, silently disabled the entire
    configuration gate rather than failing it.

    That is how every timing in this repository came to be compared against a
    baseline taken on a 1 GB `shared_buffers` without anyone noticing
    (issues/081): the check existed, ran, and reported nothing, which reads
    exactly like agreement.

    Absence is not agreement. It is the absence of evidence, and for a
    comparison gate that is a problem to report.
    """
    problems = []
    base_pg = base.get("env", {}).get("pg") or {}
    run_pg = run.get("env", {}).get("pg") or {}
    if not base_pg:
        problems.append(
            "baseline records NO PostgreSQL settings — timings cannot be shown "
            "comparable to it. Promote a baseline from a stamped run "
            "(see issues/081)")
    if not run_pg:
        problems.append(
            "this run records NO PostgreSQL settings — see issues/081")

    for section, key in ENV_GATES:
        a = (base.get("env", {}).get(section, {}) or {}).get(key)
        b = (run.get("env", {}).get(section, {}) or {}).get(key)
        if a is None and b is None:
            continue          # neither side claims anything; nothing to compare
        if a is None or b is None:
            # One side knows and the other does not. Previously silent.
            known, unknown = ("run", "baseline") if a is None else ("baseline", "run")
            problems.append(
                f"{section}.{key}: {known}={b if a is None else a!r} but "
                f"{unknown} did not record it")
            continue
        if a != b:
            problems.append(f"{section}.{key}: baseline={a!r} run={b!r}")

    # The STATISTICS state, reported separately and as a NOTE rather than a
    # mismatch. A refreshed ANALYZE does not invalidate the run — it explains
    # it. Saying so is the whole point: `deep_paging.monotonic[100k]` moved 91%
    # with identical code, settings and rows, and the comparison offered no
    # candidate but "the last commit". Forty minutes went into excluding the
    # commits before anyone asked whether the statistics had changed
    # (issues/112).
    base_st = base.get("env", {}).get("stats") or {}
    run_st = run.get("env", {}).get("stats") or {}
    if base_st and run_st:
        b_at, r_at = base_st.get("fixture_last_analyze"), run_st.get("fixture_last_analyze")
        if b_at and r_at and b_at != r_at:
            problems.append(
                f"NOTE stats.fixture_last_analyze: baseline={b_at} run={r_at} — "
                f"the fixtures were re-ANALYZEd between these runs, so a plan "
                f"flip here is not necessarily a code change (issues/112)")
        b_n, r_n = base_st.get("fixture_live_tuples"), run_st.get("fixture_live_tuples")
        if b_n and r_n and b_n != r_n:
            problems.append(
                f"NOTE stats.fixture_live_tuples: baseline={b_n:,} run={r_n:,} — "
                f"the fixture data itself changed size")
    elif run_st and not base_st:
        problems.append(
            "NOTE the baseline records no fixture statistics state, so a plan "
            "flip caused by a background ANALYZE cannot be told apart from a "
            "code regression (issues/112)")
    return problems


# ---------------------------------------------------------------------------
# Per-bench comparison
# ---------------------------------------------------------------------------

def compare_bench(bench_id: str, base: Dict[str, Any], cur: Optional[Dict[str, Any]],
                                    thresholds: Dict[str, Any], partial: bool = False) -> List[Dict[str, Any]]:
    """Compare one bench; returns a list of finding dicts."""
    out: List[Dict[str, Any]] = []

    # Coverage: a bench that did not produce metrics this run is a hole, not a
    # pass (plan R5). But distinguish a *new* hole from a *known* one — a bench
    # the baseline also never measured (no dataset loaded, bench disabled) is a
    # standing gap to fix, not a regression this change introduced. Failing on
    # those forever would train everyone to ignore the gate.
    base_ok = base.get("status") == "ok"
    if cur is None:
        if partial:
            # A tier that deliberately excludes benches is not a hole. Saying
            # "REGRESSED to status=skipped" for every one of them is how a gate
            # gets ignored — the same failure mode as reporting nothing.
            return [{"bench": bench_id, "metric": "-", "level": INFO,
                     "detail": "not run in this tier (--partial)"}]
        return [{"bench": bench_id, "metric": "-",
                 "level": FAIL if base_ok else WARN,
                 "detail": "present in baseline, MISSING from run" if base_ok
                           else "not measured in baseline or run (known hole)"}]
    # Load benches carry their run parameters. A p99 from 20 users is not
    # comparable with a p99 from 5, and silently comparing them is worse than
    # not comparing at all.
    b_params, c_params = base.get("params"), cur.get("params")
    if b_params and c_params and b_params != c_params:
        diffs = [f"{k}: {b_params.get(k)}→{c_params.get(k)}"
                 for k in sorted(set(b_params) | set(c_params))
                 if b_params.get(k) != c_params.get(k)]
        return [{"bench": bench_id, "metric": "params", "level": WARN,
                 "detail": "run parameters differ, not comparable — "
                           + ", ".join(diffs)}]

    if cur.get("status") != "ok":
        reason = cur.get("reason", "")
        short = reason.split(".")[0][:90] if reason else ""
        if base_ok:
            return [{"bench": bench_id, "metric": "-", "level": FAIL,
                     "detail": f"REGRESSED to status={cur.get('status')}"
                               + (f" ({short})" if short else "")
                               + " — was measured in the baseline"}]
        return [{"bench": bench_id, "metric": "-", "level": WARN,
                 "detail": f"known hole, status={cur.get('status')}"
                           + (f" ({short})" if short else "")}]
    if not base_ok:
        return [{"bench": bench_id, "metric": "-", "level": INFO,
                 "detail": "now measured (was a hole in the baseline) — "
                           "promote a new baseline to gate it"}]

    # Plan shape. A flip index->seq scan is always a regression; a flip in the
    # ORDER of two siblings is not one at all.
    #
    # `issues/113`: this compared the flattened pre-order walk elementwise, so
    # `traversal.skew2k.dedup.depth3` failed with 39 nodes before and after, an
    # identical multiset of node types, identical rows, and cost within noise —
    # one `Index Only Scan` had moved position. Sibling order carries no meaning:
    # PostgreSQL may emit a hash join's inputs either way round.
    #
    # That matters because this metric is what catches REAL flips — `issues/112`
    # was diagnosed from `Gather Merge` becoming a `Sort` above a `Gather` — and
    # one that also fires on noise is one people skim past, taking the next real
    # flip with it.
    #
    # So the COUNTS gate and the ORDER reports. A multiset alone would miss a
    # genuine parent/child swap that preserves it (a `Sort` above a `Gather`
    # versus the reverse), which is why the order difference is still surfaced
    # rather than dropped — as information, at the level a reordering deserves.
    b_shape, c_shape = base.get("shape"), cur.get("shape")
    if b_shape and c_shape:
        for field in ("node_types", "indexes", "seq_scans"):
            b_val, c_val = b_shape.get(field), c_shape.get(field)
            if b_val == c_val:
                continue
            if isinstance(b_val, list) and isinstance(c_val, list):
                b_count, c_count = Counter(b_val), Counter(c_val)
                if b_count == c_count:
                    moved = sorted({n for i, n in enumerate(c_val)
                                    if i < len(b_val) and b_val[i] != n})
                    out.append({
                        "bench": bench_id, "metric": f"shape.{field}",
                        "level": INFO,
                        "detail": f"same {len(c_val)} entries, different order "
                                  f"({', '.join(moved[:3]) or 'positions shifted'}"
                                  f") — sibling order is not meaningful "
                                  f"(issues/113)"})
                    continue
                gained = sorted((c_count - b_count).elements())
                lost = sorted((b_count - c_count).elements())
                out.append({
                    "bench": bench_id, "metric": f"shape.{field}", "level": FAIL,
                    "detail": f"gained {gained or '-'}, lost {lost or '-'}"})
                continue
            out.append({"bench": bench_id, "metric": f"shape.{field}", "level": FAIL,
                        "detail": f"{b_val} → {c_val}"})

    b_metrics = base.get("metrics", {}) or {}
    c_metrics = cur.get("metrics", {}) or {}

    for metric, b_val in sorted(b_metrics.items()):
        if metric not in c_metrics:
            out.append({"bench": bench_id, "metric": metric, "level": WARN,
                        "detail": "not measured this run"})
            continue
        c_val = c_metrics[metric]
        if not isinstance(b_val, (int, float)) or not isinstance(c_val, (int, float)):
            if b_val != c_val:
                out.append({"bench": bench_id, "metric": metric, "level": WARN,
                            "detail": f"{b_val} → {c_val}"})
            continue

        rule = rule_for(thresholds, bench_id, metric)
        if rule is None:
            continue
        delta = pct_change(float(b_val), float(c_val))
        worse_dir = 1 if rule.get("direction", "increase") == "increase" else -1
        # Signed "how much worse" — positive means degraded.
        worse_pct = None if delta is None else delta * worse_dir

        if worse_pct in (None, 0):
            movement = ""
        else:
            # worse_pct is signed so that positive always means degraded,
            # whichever direction the metric improves in. Label it accordingly
            # rather than printing "-91% worse" at an improvement.
            movement = (f" ({worse_pct:+.1f}% "
                        f"{'worse' if worse_pct > 0 else 'better'})")
        entry = {"bench": bench_id, "metric": metric,
                 "detail": f"{_fmt(b_val)} → {_fmt(c_val)}{movement}"}

        # Percentage gates are meaningless on tiny counters — a 3→4 buffer change
        # is +33% but is noise, not a regression. Require an absolute movement too.
        min_abs = rule.get("min_abs_delta", 0)
        if min_abs and abs(float(c_val) - float(b_val)) < min_abs:
            continue

        if rule.get("report_only"):
            if worse_pct is not None and abs(worse_pct) >= 10:
                out.append({**entry, "level": INFO})
            continue
        if worse_pct is None:
            continue
        if worse_pct > rule.get("fail_pct", 15):
            out.append({**entry, "level": FAIL})
        elif worse_pct > rule.get("warn_pct", 5):
            out.append({**entry, "level": WARN})
        elif worse_pct < -25:
            # A large unexplained improvement usually means the bench stopped
            # doing its work (plan R5) — surface it for review.
            out.append({**entry, "level": INFO,
                        "detail": entry["detail"] + " — verify the bench still measures the work"})

    # Metrics new to this run are informational (a bench gained coverage).
    for metric in sorted(set(c_metrics) - set(b_metrics)):
        out.append({"bench": bench_id, "metric": metric, "level": INFO,
                    "detail": f"new metric = {_fmt(c_metrics[metric])}"})
    return out


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.3f}".rstrip("0").rstrip(".")
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

ICON = {OK: "✅", WARN: "⚠️ ", FAIL: "❌", INFO: "ℹ️ "}


def report(run: Dict[str, Any], base: Dict[str, Any],
           thresholds: Dict[str, Any],
           partial: bool = False) -> Tuple[int, List[Dict[str, Any]]]:
    cur_b, base_b = benches(run), benches(base)
    findings: List[Dict[str, Any]] = []

    env_problems = compare_env(run, base)
    for p in env_problems:
        findings.append({"bench": "-", "metric": "env", "level": WARN,
                         "detail": f"environment differs — {p}"})

    for bench_id in sorted(base_b):
        findings.extend(compare_bench(bench_id, base_b[bench_id],
                                      cur_b.get(bench_id), thresholds,
                                      partial=partial))

    new_benches = sorted(set(cur_b) - set(base_b))
    skipped_new = [b for b in new_benches if cur_b[b].get("status") != "ok"]
    for b in new_benches:
        findings.append({"bench": b, "metric": "-", "level": INFO,
                         "detail": "new bench, not in baseline"
                                   + ("" if b not in skipped_new
                                      else f" (status={cur_b[b].get('status')})")})

    # ---- print ----
    g_run = run.get("env", {}).get("git", {})
    g_base = base.get("env", {}).get("git", {})
    print(f"\nPERF vs baseline (env: {run.get('env', {}).get('runner', {}).get('class')}, "
          f"pg {run.get('env', {}).get('pg', {}).get('server_version')})")
    print(f"  baseline commit {g_base.get('short')} ({g_base.get('branch')})"
          f"  →  run commit {g_run.get('short')} ({g_run.get('branch')})"
          + ("  [DIRTY WORKING TREE]" if g_run.get("dirty") else ""))

    n_fail = sum(1 for f in findings if f["level"] == FAIL)
    n_warn = sum(1 for f in findings if f["level"] == WARN)
    ok_benches = [b for b in base_b
                  if not any(f["bench"] == b and f["level"] in (FAIL, WARN) for f in findings)]
    print(f"\n  ✅ {len(ok_benches)}/{len(base_b)} benches within tolerance")

    for level in (FAIL, WARN, INFO):
        for f in findings:
            if f["level"] != level:
                continue
            print(f"  {ICON[level]} {f['bench']:<44} {f['metric']:<20} {f['detail']}")

    print(f"\n  {n_fail} failing, {n_warn} warning, "
          f"{len(findings) - n_fail - n_warn} informational")
    return (1 if n_fail else 0), findings


# ---------------------------------------------------------------------------
# Promote / trend
# ---------------------------------------------------------------------------

def promote(run_path: str, name: str, reason: str = "", force: bool = False) -> str:
    run = load_json(run_path)

    # Promotion is the moment a run becomes the thing everything is compared
    # against, so it is the right place to be strict. The committed baseline was
    # promoted with `env.pg == {}` (issues/081), and because the comparison gate
    # skipped absent values, nothing downstream could notice: every subsequent
    # run was measured against a configuration nobody had recorded, which turned
    # out to be a 1 GB shared_buffers on a fixture needing more than 3 GB.
    if not (run.get("env", {}).get("pg") or {}):
        msg = (f"{run_path} records NO PostgreSQL settings (env.pg is empty). "
               f"A baseline without them cannot be shown comparable to anything "
               f"later. See issues/081.")
        if not force:
            print(f"❌ refusing to promote: {msg}", file=sys.stderr)
            print("   Re-run the benchmarks so the stamp is captured, or pass "
                  "--force-unstamped if you accept an uncomparable baseline.",
                  file=sys.stderr)
            raise SystemExit(2)
        print(f"⚠️  {msg}\n   Promoting anyway (--force-unstamped).")

    bad = [b["bench_id"] for b in run.get("benches", []) if b.get("status") != "ok"]
    if bad:
        print(f"⚠️  {len(bad)} bench(es) are not 'ok' and will be promoted as holes:")
        for b in bad[:10]:
            print(f"     - {b}")
    if run.get("env", {}).get("git", {}).get("dirty"):
        print("⚠️  run was recorded from a DIRTY working tree — the baseline commit "
              "will not reproduce it exactly.")
    run["baseline"] = {"name": name, "promoted_from": os.path.abspath(run_path),
                       "reason": reason,
                       "pg_stamped": bool(run.get("env", {}).get("pg") or {})}
    os.makedirs(BASELINE_DIR, exist_ok=True)
    out = os.path.join(BASELINE_DIR, f"{name}.json")
    with open(out, "w") as fh:
        json.dump(run, fh, indent=2)
        fh.write("\n")
    print(f"✅ promoted → {out}")
    return out


def trend(bench_id: str, metric: str, results_dir: str = RESULTS_DIR) -> None:
    index = os.path.join(results_dir, "history.jsonl")
    if not os.path.exists(index):
        raise SystemExit(f"no history at {index}")
    rows = []
    with open(index) as fh:
        for line in fh:
            try:
                entry = json.loads(line)
                run = load_json(entry["path"])
            except Exception:
                continue
            b = benches(run).get(bench_id)
            if b and b.get("status") == "ok" and metric in (b.get("metrics") or {}):
                rows.append((entry.get("at", ""), entry.get("commit", ""),
                             b["metrics"][metric]))
    if not rows:
        raise SystemExit(f"no recorded values for {bench_id}.{metric}")
    print(f"\ntrend — {bench_id}.{metric}\n")
    prev = None
    for at, commit, val in rows:
        delta = "" if prev is None else f"  ({pct_change(prev, val):+.1f}%)"
        print(f"  {at[:19]}  {commit:<10} {_fmt(val):>14}{delta}")
        prev = val


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", nargs="?", help="path to a recorded run JSON")
    ap.add_argument("--baseline", help="baseline name (tests/performance/baselines/<name>.json) or path")
    ap.add_argument("--promote", metavar="NAME", help="promote this run to a named baseline")
    ap.add_argument("--partial", action="store_true",
                    help="this run deliberately covers a SUBSET (e.g. "
                         "`-k something`), so a bench absent from it is "
                         "not-run rather than lost. Never promote a partial run: "
                         "it bakes the missing benches in as holes (issues/081)")
    ap.add_argument("--force-unstamped", action="store_true",
                    help="promote even if the run recorded no PostgreSQL "
                         "settings (issues/081 — the resulting baseline cannot "
                         "be shown comparable to anything)")
    ap.add_argument("--reason", default="", help="why this baseline was promoted")
    ap.add_argument("--json", metavar="PATH", help="write the findings as JSON")
    ap.add_argument("--trend", metavar="BENCH_ID", help="show a metric's history")
    ap.add_argument("--metric", default="shared_buffers", help="metric for --trend")
    ap.add_argument("--thresholds", default=THRESHOLDS)
    args = ap.parse_args()

    if args.trend:
        trend(args.trend, args.metric)
        return 0
    if not args.run:
        ap.error("a run path is required (or use --trend)")
    if args.promote and getattr(args, "partial", False):
        print("  refusing to promote a --partial run: the benches it did not "
              "run would be promoted as holes, which is exactly what issues/081 "
              "warns about. Record a full run first.")
        return 2

    if args.promote:
        promote(args.run, args.promote, args.reason,
                force=args.force_unstamped)
        return 0
    if not args.baseline:
        ap.error("--baseline is required when comparing")

    run = load_json(args.run)
    base = load_json(resolve_baseline(args.baseline))
    code, findings = report(run, base, load_thresholds(args.thresholds),
                            partial=args.partial)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"findings": findings}, fh, indent=2)
    return code


if __name__ == "__main__":
    sys.exit(main())
