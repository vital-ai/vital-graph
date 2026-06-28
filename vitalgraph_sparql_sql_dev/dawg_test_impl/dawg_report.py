"""
Summarize DAWG test results across categories.

Produces a formatted console report and optional JSON output
for tracking pass rates over time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single DAWG test."""
    name: str
    category: str
    status: str  # PASS, FAIL, SKIP, ERROR, ACCEPTED
    expected_rows: int = 0
    actual_rows: int = 0
    time_ms: float = 0.0
    error_message: str = ""


@dataclass
class CategorySummary:
    """Aggregated results for a test category."""
    category: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    accepted: int = 0
    failures: List[TestResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        non_skipped = self.total - self.skipped
        if non_skipped == 0:
            return 0.0
        return (self.passed + self.accepted) / non_skipped * 100


@dataclass
class TestReport:
    """Complete test run report."""
    timestamp: str = ""
    engine: str = "pyoxigraph"
    categories: Dict[str, CategorySummary] = field(default_factory=dict)
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    accepted: int = 0

    @property
    def pass_rate(self) -> float:
        non_skipped = self.total - self.skipped
        if non_skipped == 0:
            return 0.0
        return (self.passed + self.accepted) / non_skipped * 100


def build_report(results: List[TestResult], engine: str = "pyoxigraph") -> TestReport:
    """Build a TestReport from a list of individual test results."""
    report = TestReport(
        timestamp=datetime.now().isoformat(),
        engine=engine,
    )

    for r in results:
        # Get or create category summary
        if r.category not in report.categories:
            report.categories[r.category] = CategorySummary(category=r.category)
        cat = report.categories[r.category]

        cat.total += 1
        report.total += 1

        if r.status == "PASS":
            cat.passed += 1
            report.passed += 1
        elif r.status == "ACCEPTED":
            cat.accepted += 1
            report.accepted += 1
        elif r.status == "FAIL":
            cat.failed += 1
            report.failed += 1
            cat.failures.append(r)
        elif r.status == "SKIP":
            cat.skipped += 1
            report.skipped += 1
        elif r.status == "ERROR":
            cat.errors += 1
            report.errors += 1
            cat.failures.append(r)

    return report


def print_report(report: TestReport, show_failures: bool = True, show_all: bool = False):
    """Print a formatted report to the console."""
    print()
    print("=" * 80)
    print(f"  DAWG SPARQL 1.1 Test Report  ({report.engine})")
    print(f"  {report.timestamp}")
    print("=" * 80)
    print()
    print(f"  {'Category':<25} {'Total':>6} {'Pass':>6} {'Fail':>6} {'Skip':>6} {'Error':>6} {'Acpt':>6} {'Rate':>7}")
    print("  " + "-" * 76)

    for cat_name in sorted(report.categories.keys()):
        cat = report.categories[cat_name]
        print(f"  {cat_name:<25} {cat.total:>6} {cat.passed:>6} {cat.failed:>6} "
              f"{cat.skipped:>6} {cat.errors:>6} {cat.accepted:>6} {cat.pass_rate:>6.1f}%")

    print("  " + "-" * 76)
    print(f"  {'TOTAL':<25} {report.total:>6} {report.passed:>6} {report.failed:>6} "
          f"{report.skipped:>6} {report.errors:>6} {report.accepted:>6} {report.pass_rate:>6.1f}%")
    print()

    if show_failures and (report.failed > 0 or report.errors > 0):
        print("  FAILURES / ERRORS:")
        print()
        for cat_name in sorted(report.categories.keys()):
            cat = report.categories[cat_name]
            for f in cat.failures:
                status_tag = f"[{f.status}]"
                msg = f.error_message[:60] if f.error_message else ""
                if f.status == "FAIL" and f.expected_rows != f.actual_rows:
                    msg = f"expected {f.expected_rows} rows, got {f.actual_rows}. {msg}"
                print(f"    {f.category}/{f.name:<30} {status_tag:<8} {msg}")
        print()



def save_report_json(report: TestReport, path: Path):
    """Save the report as JSON for historical tracking."""
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": report.timestamp,
        "engine": report.engine,
        "summary": {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "skipped": report.skipped,
            "errors": report.errors,
            "accepted": report.accepted,
            "pass_rate": round(report.pass_rate, 1),
        },
        "categories": {},
    }

    for cat_name, cat in report.categories.items():
        data["categories"][cat_name] = {
            "total": cat.total,
            "passed": cat.passed,
            "failed": cat.failed,
            "skipped": cat.skipped,
            "errors": cat.errors,
            "accepted": cat.accepted,
            "pass_rate": round(cat.pass_rate, 1),
            "failures": [
                {
                    "name": f.name,
                    "status": f.status,
                    "expected_rows": f.expected_rows,
                    "actual_rows": f.actual_rows,
                    "time_ms": round(f.time_ms, 1),
                    "error": f.error_message,
                }
                for f in cat.failures
            ],
        }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Report saved to %s", path)
