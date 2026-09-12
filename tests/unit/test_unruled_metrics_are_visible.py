"""A recorded metric with no threshold rule must be reported, not dropped.

`perf_compare.rule_for` returns None when `thresholds.toml` has no entry for a
metric, and the comparison loop used to `continue` on that — no FAIL, no WARN,
no INFO. So "nobody wrote a rule" and "the rule passed" printed identically:
nothing at all.

Measured 2026-09-12 against the committed baselines: 106 of the 121 recorded
metric names were unruled, and they are mostly the claim each bench exists to
make — `underestimate_factor`, `deep_ratio`, `sort_ratio`, `advantage_ratio`,
`flips_within_range`. 37 of 108 query cells had no gating metric and no plan
shape, so nothing in the baseline could turn them red. The README describes the
baseline as the drift detector that catches "a 40% degradation that still clears
the floor"; for a third of the tier that was not true.

The reporting is AGGREGATED on purpose, and that is the second thing pinned
here. `ok_benches` counts a bench as within tolerance only when nothing WARNs
against it, so emitting one warning per unruled metric would have taken the
headline from 108/108 to roughly 30/108 and buried every real warning beneath
106 lines of bookkeeping — a warning nobody reads, manufactured deliberately.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Through the package — see the note in test_perf_baseline_stamping.py.
from scripts.perf_compare import (  # noqa: E402
    FAIL, INFO, UNRULED, WARN, benches_with_no_gate, compare_bench,
)

THRESHOLDS = {
    "metrics": {
        "shared_buffers": {"direction": "increase", "warn_pct": 5,
                           "fail_pct": 15, "min_abs_delta": 16},
        "execution_ms": {"direction": "increase", "report_only": True},
    }
}


def _bench(**metrics):
    return {"bench_id": "b", "status": "ok", "metrics": metrics}


def _levels(findings):
    return [f["level"] for f in findings]


class TestUnruledMetricsAreReported:

    def test_an_unruled_metric_produces_a_finding(self):
        out = compare_bench("b", _bench(deep_ratio=2.0), _bench(deep_ratio=9.0),
                            THRESHOLDS)
        unruled = [f for f in out if f["level"] == UNRULED]
        assert len(unruled) == 1, "the metric was dropped, not reported"
        assert unruled[0]["metric"] == "deep_ratio"
        assert "no rule" in unruled[0]["detail"]

    def test_the_finding_carries_both_values(self):
        """It is bookkeeping, but it should still show what moved."""
        out = compare_bench("b", _bench(deep_ratio=2.0), _bench(deep_ratio=9.0),
                            THRESHOLDS)
        detail = next(f["detail"] for f in out if f["level"] == UNRULED)
        assert "2" in detail and "9" in detail

    def test_unruled_is_not_a_severity(self):
        """It must not read as a regression, or the gate becomes noise."""
        out = compare_bench("b", _bench(deep_ratio=2.0), _bench(deep_ratio=9.0),
                            THRESHOLDS)
        assert FAIL not in _levels(out)
        assert WARN not in _levels(out)
        assert INFO not in _levels(out)

    def test_a_ruled_metric_is_unaffected(self):
        """The change must not disturb what already gated."""
        out = compare_bench("b", _bench(shared_buffers=100),
                            _bench(shared_buffers=1000), THRESHOLDS)
        assert FAIL in _levels(out)
        assert UNRULED not in _levels(out)

    def test_report_only_is_ruled(self):
        """`report_only` means CLASSIFIED-and-not-gating, which is the whole
        point of the distinction: it is expressible, and distinguishable from
        nobody having looked."""
        out = compare_bench("b", _bench(execution_ms=10.0),
                            _bench(execution_ms=90.0), THRESHOLDS)
        assert UNRULED not in _levels(out)


class TestBenchesWithNoGate:

    def test_a_bench_whose_metrics_are_all_unruled_has_no_gate(self):
        base = {"b": _bench(deep_ratio=2.0, page_size=25)}
        assert benches_with_no_gate(base, THRESHOLDS) == ["b"]

    def test_report_only_alone_is_not_a_gate(self):
        base = {"b": _bench(execution_ms=10.0)}
        assert benches_with_no_gate(base, THRESHOLDS) == ["b"]

    def test_one_gating_metric_is_enough(self):
        base = {"b": _bench(deep_ratio=2.0, shared_buffers=100)}
        assert benches_with_no_gate(base, THRESHOLDS) == []

    def test_a_plan_shape_counts_as_a_gate(self):
        """`shape.tree` FAILs on a mismatch, so a bench carrying one is not
        ungated even with no numeric rule."""
        b = _bench(deep_ratio=2.0)
        b["shape"] = {"tree": ["Index Only Scan", []], "node_types": [],
                      "indexes": [], "seq_scans": []}
        assert benches_with_no_gate({"b": b}, THRESHOLDS) == []

    def test_a_bench_that_did_not_run_is_not_counted(self):
        """A hole is already reported as a hole; do not double-count it here."""
        base = {"b": {"bench_id": "b", "status": "skipped", "metrics": {}}}
        assert benches_with_no_gate(base, THRESHOLDS) == []
