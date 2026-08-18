"""A performance baseline must record the server it was measured on (issues/081).

`shared_buffers` was 1 GB on a 64 GB machine while a single query on the 100k
fixture touched 400,000+ buffers (>3 GB). Every timing paid eviction, a sorted
page read 27x slower than it does on a correct configuration, and four
implementation attempts went into chasing a query-shape explanation for a memory
setting.

The machinery to catch that already existed. `perf_record.PG_SETTINGS` lists the
settings, `pg_stamp()` reads them, and the run document has an `env.pg` slot for
them. The committed baseline has `env.pg == {}`.

WHY NOTHING NOTICED, which is the part worth pinning. `compare_env` gated on:

    if a is not None and b is not None and a != b

Sensible-looking, and it means an ABSENT value can never disagree with anything.
So an empty baseline stamp did not fail the comparison gate — it disabled it,
silently, and a disabled gate reports the same "no problems" as a satisfied one.

Two changes, tested here: absence is reported rather than skipped, and a run
with no stamp cannot become a baseline without an explicit override.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# `scripts.perf_compare`, NOT a bare `perf_compare` off an inserted path.
#
# This line used to be `sys.path.insert(0, str(REPO / "scripts"))`, which bound
# the name `scripts` to a namespace package rooted INSIDE that directory. Every
# later `from scripts.X import ...` then looked for `scripts/scripts/X.py` and
# raised ModuleNotFoundError — five paging tests failed in full-suite runs and
# passed when their own files ran alone, and the failures were briefly blamed on
# an unrelated change (issues/088).
#
# Importing through the package also keeps ONE module object. With the path
# inserted, `perf_compare` and `scripts.perf_compare` are two distinct modules
# with separate module-level state, and a cache in one is invisible to the other.
from scripts.perf_compare import compare_env  # noqa: E402

STAMPED = {
    "server_version": "18.4",
    "shared_buffers": "16GB",
    "effective_cache_size": "48GB",
    "work_mem": "64MB",
    "random_page_cost": "1",
    "max_parallel_workers_per_gather": "2",
}


def _doc(pg):
    return {"env": {"pg": pg, "git": {}, "machine": {}, "runner": {}}}


class TestAbsenceIsReportedNotSkipped:

    def test_empty_baseline_stamp_is_a_problem(self):
        """The committed baseline's exact shape."""
        problems = compare_env(_doc(STAMPED), _doc({}))
        assert problems, "an unstamped baseline must not compare clean"
        assert any("baseline records NO PostgreSQL settings" in p for p in problems)

    def test_empty_run_stamp_is_a_problem(self):
        problems = compare_env(_doc({}), _doc(STAMPED))
        assert any("this run records NO PostgreSQL settings" in p for p in problems)

    def test_one_sided_key_is_reported(self):
        """The general case of the same bug, not just a wholly empty stamp."""
        partial = dict(STAMPED)
        del partial["shared_buffers"]
        problems = compare_env(_doc(STAMPED), _doc(partial))
        assert any("shared_buffers" in p and "did not record it" in p
                   for p in problems)

    def test_matching_stamps_compare_clean(self):
        """The fix must not make every comparison noisy."""
        assert compare_env(_doc(STAMPED), _doc(STAMPED)) == []

    def test_a_real_mismatch_is_still_reported(self):
        """The behaviour that already worked, kept."""
        other = dict(STAMPED, shared_buffers="1GB")
        problems = compare_env(_doc(STAMPED), _doc(other))
        assert any("shared_buffers" in p and "1GB" in p for p in problems)

    def test_both_sides_silent_on_a_key_is_not_invented_noise(self):
        """Neither side claiming a value is not a disagreement.

        Only the whole-stamp-missing case is reported then, not one line per
        setting — otherwise an old run pair produces six identical complaints.
        """
        minimal = {"server_version": "18.4"}
        problems = compare_env(_doc(minimal), _doc(minimal))
        assert problems == []


class TestPromotionRefusesAnUnstampedRun:
    """Promotion is when a run becomes what everything is compared against."""

    def _promote(self, tmp_path, pg, extra=()):
        run = {"schema": 1, "env": {"pg": pg, "git": {}, "machine": {}, "runner": {}},
               "benches": []}
        run_path = tmp_path / "run.json"
        run_path.write_text(json.dumps(run))
        name = "pytest_throwaway"
        out = REPO / "tests" / "performance" / "baselines" / f"{name}.json"
        try:
            result = subprocess.run(
                [sys.executable, "scripts/perf_compare.py", str(run_path),
                 "--promote", name, *extra],
                cwd=REPO, capture_output=True, text=True)
            written = json.loads(out.read_text()) if out.exists() else None
            return result, written
        finally:
            if out.exists():
                out.unlink()

    def test_unstamped_run_is_refused(self, tmp_path):
        result, written = self._promote(tmp_path, {})
        assert result.returncode != 0
        assert written is None, "a refused promotion must not write the baseline"
        assert "refusing to promote" in (result.stderr + result.stdout)

    def test_the_refusal_says_how_to_proceed(self, tmp_path):
        """A gate that blocks without naming the way through is a trap."""
        result, _ = self._promote(tmp_path, {})
        combined = result.stderr + result.stdout
        assert "--force-unstamped" in combined
        assert "issues/081" in combined

    def test_force_allows_it_and_records_that_it_was_unstamped(self, tmp_path):
        result, written = self._promote(tmp_path, {}, ("--force-unstamped",))
        assert result.returncode == 0
        assert written["baseline"]["pg_stamped"] is False, (
            "an override must leave a trace in the artifact, or the next "
            "reader cannot tell this baseline from a stamped one"
        )

    def test_a_stamped_run_promotes_normally(self, tmp_path):
        result, written = self._promote(tmp_path, STAMPED)
        assert result.returncode == 0
        assert written["baseline"]["pg_stamped"] is True


class TestTheCommittedBaseline:

    BASELINE = REPO / "tests" / "performance" / "baselines" / "main.json"

    @pytest.mark.skipif(not BASELINE.exists(), reason="no committed baseline")
    def test_it_is_flagged_rather_than_silently_trusted(self):
        """This currently FAILS the gate, and that is the point.

        The baseline in the tree was promoted from an unstamped run. Until it is
        re-promoted from a stamped one, any comparison against it must say so
        instead of reporting agreement.
        """
        base = json.loads(self.BASELINE.read_text())
        pg = base.get("env", {}).get("pg") or {}
        if pg:
            pytest.skip("baseline has been re-promoted with a stamp")
        assert compare_env(_doc(STAMPED), base), (
            "the unstamped committed baseline must be reported as a problem"
        )
