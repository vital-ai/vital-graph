"""The maintenance job honours VG_MAINTENANCE_EXCLUDE_SPACES.

issues/112 option 3. A maintenance cycle re-ANALYZEd the benchmark fixtures
mid-session and a bench then read +91% worse with identical code, because the
plan flipped on refreshed statistics. Excluding the fixtures keeps the ground
still.

Configured, not hardcoded: the fixture names belong to a dev machine rather
than to the product, and the exclusion is a real divergence from production —
the maintenance job is part of how a served space behaves — so a deployment
opts in visibly instead of inheriting a default that makes benchmarks unlike
production everywhere.
"""

from __future__ import annotations

import pytest

from vitalgraph.process.maintenance_job import MaintenanceJob

pytestmark = [pytest.mark.unit]

STATS = {"sp_lead_synth_100k": {"n": 1}, "wordnet_frames": {"n": 2},
         "sp_customer_live": {"n": 3}}


def _job(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("VG_MAINTENANCE_EXCLUDE_SPACES", raising=False)
    else:
        monkeypatch.setenv("VG_MAINTENANCE_EXCLUDE_SPACES", value)
    return MaintenanceJob(pool=None)


def test_unset_maintains_everything(monkeypatch):
    """The default must not change production behaviour."""
    job = _job(monkeypatch, None)
    assert job._excluded == set()
    assert job._drop_excluded(dict(STATS)) == STATS


def test_empty_string_is_not_a_space_named_empty(monkeypatch):
    job = _job(monkeypatch, "")
    assert job._excluded == set()
    assert job._drop_excluded(dict(STATS)) == STATS


def test_named_spaces_are_dropped(monkeypatch):
    job = _job(monkeypatch, "sp_lead_synth_100k,wordnet_frames")
    kept = job._drop_excluded(dict(STATS))
    assert set(kept) == {"sp_customer_live"}, kept


def test_whitespace_and_trailing_commas_are_tolerated(monkeypatch):
    """A hand-edited env var should not silently fail to match."""
    job = _job(monkeypatch, " sp_lead_synth_100k , wordnet_frames ,, ")
    assert job._excluded == {"sp_lead_synth_100k", "wordnet_frames"}
    assert set(job._drop_excluded(dict(STATS))) == {"sp_customer_live"}


def test_an_exempt_space_that_is_not_present_is_harmless(monkeypatch):
    job = _job(monkeypatch, "sp_does_not_exist")
    assert job._drop_excluded(dict(STATS)) == STATS


def test_every_stamped_fixture_is_also_exempt_from_maintenance():
    """The two lists answer the same question and must not drift.

    `VG_MAINTENANCE_EXCLUDE_SPACES` (docker-compose.test.yml) says which spaces
    maintenance must leave alone; `STATS_FIXTURE_PREFIXES`
    (tests/performance/perf_record.py) says which spaces the perf runner stamps
    as benchmark fixtures. A space in the second but not the first gets ANALYZEd
    by maintenance, and the stamp then reports

        NOTE stats.fixture_last_analyze: ... the fixtures were re-ANALYZEd

    on a run whose actual fixtures never moved — a false environment warning
    that makes a real one easy to ignore.

    Both files carry a comment saying to keep them in step. That comment already
    failed once: `sp_lead_types` and `space_lead_dataset_test` were stamped and
    not excluded (2026-08-23). A comment is not an invariant; this is.
    """
    import re
    from pathlib import Path

    from tests.performance.perf_record import STATS_FIXTURE_PREFIXES

    compose = (Path(__file__).resolve().parents[2]
               / "docker-compose.test.yml").read_text(encoding="utf-8")
    m = re.search(r"VG_MAINTENANCE_EXCLUDE_SPACES=\$\{VG_MAINTENANCE_EXCLUDE_SPACES:-([^}]*)\}",
                  compose)
    assert m, "could not find the exclusion list — has the compose var moved?"
    excluded = [s.strip() for s in m.group(1).split(",") if s.strip()]

    # A prefix covers an excluded space when that space starts with it; the
    # prefixes are deliberately prefixes (sp_lead_synth_ covers _10k and _100k).
    unmatched = [p for p in STATS_FIXTURE_PREFIXES
                 if not any(s.startswith(p) for s in excluded)]
    assert not unmatched, (
        f"stamped as benchmark fixtures but NOT exempt from maintenance: "
        f"{unmatched}. Add them to VG_MAINTENANCE_EXCLUDE_SPACES in "
        f"docker-compose.test.yml, or stop stamping them.")
